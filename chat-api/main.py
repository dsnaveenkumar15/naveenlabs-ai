"""
Public chat API for the AI galaxy page. Thin proxy in front of Ollama --
never expose Ollama's raw API publicly (no auth, no rate limit on its own).

Rate limiting is a bare in-memory per-IP token bucket, good enough for a
personal site on a single container.
# ponytail: in-memory rate limiter resets on restart and isn't shared across
# replicas -- fine for a single-instance personal site, revisit with Redis if
# this ever needs to scale past one container.
"""
import os
import re
import threading
import time
import json
import urllib.request
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

MODEL = os.environ.get("CHAT_MODEL", "gemma3:4b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434/api/chat")
RATE_LIMIT = 10          # requests
RATE_WINDOW = 60         # seconds
MAX_MESSAGE_LEN = 1000
MAX_REPLY_TOKENS = 300
# Matches Ollama's CPU cap (docker-compose cpus: 3): more threads than cores only gets throttled.
MODEL_THREADS = int(os.environ.get("CHAT_MODEL_THREADS", "3"))
# Behind Traefik the socket peer is the proxy, so the real visitor is the rightmost X-Forwarded-For entry.
TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"
# The model shares a small box with real apps: at most this many generations run at once, the rest are told to retry.
_slots = threading.BoundedSemaphore(int(os.environ.get("CHAT_MAX_CONCURRENT", "2")))
# Daily ceilings so the public demo can't be farmed: per visitor and for the whole site (UTC day).
DAILY_PER_VISITOR = int(os.environ.get("CHAT_DAILY_PER_VISITOR", "50"))
DAILY_TOTAL = int(os.environ.get("CHAT_DAILY_TOTAL", "1000"))

REFUSAL = "I can't help with that. I'm a small demo model for friendly, everyday questions."
SUPPORT = ("I'm sorry you're going through this. Please talk to someone now: in India call Tele-MANAS "
           "on 14416 (free, 24x7), or your local emergency number. You don't have to face this alone.")
_SELF_HARM = re.compile(r"(?i)\b(kill|hurt|harm)\s+(myself|me)\b|\bsuicid|\bself.?harm\b|\bend\s+my\s+life\b")
# Topics this public demo refuses outright, checked on the question and on the reply.
# ponytail: keyword screen, not a classifier; a small local model can't run a safety model alongside it.
_BLOCKED = re.compile(r"""(?ix)
    \b(pipe|nail|car|fertili[sz]er|homemade|make\s+a|build\s+a)\s*bombs?\b | \bexplosives?\b | \bdetonat
  | \b(make|build|3d.?print)\w*\s+(a\s+)?(gun|firearm|silencer)\b | \bnerve\s+agent | \bsarin\b | \bricin\b | \banthrax\b
  | \b(ransomware|keylogger|malware|botnet|rootkit|trojan|credential\s+stealer)\b | \bddos\b | \bsql\s*injection\s+payload
  | \bphishing\b | \bscam\s+(email|message|script)\b | \bpretending\s+to\s+be\s+(my|a|the)\s+bank\b
  | \b(kill|hurt|harm)\s+(myself|yourself|himself|herself)\b | \bsuicide\s+method | \bself.?harm\b
  | \b(cook|synthesi[sz]e|make)\w*\s+(meth|cocaine|heroin|fentanyl|lsd)\b
  | \b(child|minor|underage)\w*\s+(porn|sex|nude)\w* | \bcsam\b
  | \b(porn|nsfw|explicit\s+sex)\w*
""")

SYSTEM_PROMPT = (
    "You are the chat assistant on naveenlabs.tech, a small AI model running locally on this personal "
    "site. Be concise and friendly. Only if the user asks who runs or built this site, say it was "
    "built by Naveenkumar Dhamodharan as his personal AI playground; otherwise do not mention him. "
    "Politely refuse anything harmful, illegal, sexual, hateful or dangerous, and anything that "
    "writes scams, spam or messages pretending to be a real company or person. Do not give "
    "medical, legal or financial advice. Never claim to be made by, or speak for, any company. "
    "If you are not sure of a fact, say so instead of guessing."
)

# A small local model knows nothing about this site, so without these facts it invents answers about it.
# Keep in step with the Work list on naveenlabs.tech.
SITE_FACTS = """
How to answer:
- General questions (history, literature, science, geography, coding, writing, maths): answer normally from your own knowledge.
- Questions about naveenlabs.tech, its projects (Trust, Radar, Blueprints, Chat, TradFi, Web3) or its owner: answer only from these facts.
  If such a site question is not covered below, say you don't know and suggest visiting naveenlabs.tech.
  For every other topic, never send people to naveenlabs.tech.
Facts about naveenlabs.tech:
- Owner: Naveenkumar Dhamodharan, an Agentic AI Engineer. He builds agentic AI systems (LangGraph orchestration, RAG,
  MCP/A2A protocols) with production reliability. Contact and links: naveenlabs.tech.
- Trust (trust.naveenlabs.tech): a security checker for MCP servers (the plug-ins that give an AI agent tools). You
  paste a server's tool list and Trust shows what those tools could do on your machine before you install it, such as
  hidden instructions, shell access and reading credential files. Nothing pasted is stored.
- Radar (radar.naveenlabs.tech): follows releases of the libraries AI apps are built on, publishes a digest, and checks
  a dependency file (requirements.txt, package.json or a lock file) for breaking changes, deprecations and security
  advisories between your versions and the latest.
- Blueprints (blueprints.naveenlabs.tech): reference architectures for AI agents, each checked by a linter, priced per
  month and kept current; you can compare two or draft a custom one.
- Chat (chat.naveenlabs.tech): you, a small open model running on the owner's own server, with rate limits and
  guardrails. No account, nothing saved.
- TradFi: the owner's personal stock-trading system for his own brokerage account, through the broker's public API.
- Web3: the owner's personal crypto-trading system for his own exchange account.
  (Outside this site, "TradFi" also means traditional finance and "Web3" the blockchain-based web; mention that briefly
  if the question is about the general terms.)
- All projects are independent personal projects, not affiliated with any company. Nothing here is investment advice.
"""
SYSTEM_PROMPT = SYSTEM_PROMPT + "\n" + SITE_FACTS.strip()

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@app.get("/healthz")
def healthz():
    return {"ok": True}
_hits: dict[str, deque] = defaultdict(deque)
_daily: dict[str, int] = {}        # "YYYY-MM-DD|ip" and "YYYY-MM-DD|*" -> count


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LEN)


def _client_ip(request: Request) -> str:
    if TRUST_PROXY:
        parts = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.time()
    hits = _hits[ip]
    while hits and now - hits[0] > RATE_WINDOW:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        return True
    hits.append(now)
    return False


def _over_daily_cap(ip: str) -> bool:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if any(not k.startswith(day) for k in _daily):
        for k in [k for k in _daily if not k.startswith(day)]:
            del _daily[k]
    mine, total = f"{day}|{ip}", f"{day}|*"
    if _daily.get(mine, 0) >= DAILY_PER_VISITOR or _daily.get(total, 0) >= DAILY_TOTAL:
        return True
    _daily[mine] = _daily.get(mine, 0) + 1
    _daily[total] = _daily.get(total, 0) + 1
    return False


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(429, "Too many requests, slow down.")
    if _over_daily_cap(ip):
        raise HTTPException(429, "Daily limit reached, come back tomorrow.")
    if _SELF_HARM.search(req.message):
        return {"reply": SUPPORT}
    if _BLOCKED.search(req.message):
        return {"reply": REFUSAL}
    if not _slots.acquire(blocking=False):
        raise HTTPException(503, "Busy, try again in a few seconds.", headers={"Retry-After": "5"})

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": req.message},
        ],
        "stream": False,
        "options": {"num_predict": MAX_REPLY_TOKENS, "num_thread": MODEL_THREADS},
    }
    http_req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(http_req, timeout=60) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        raise HTTPException(503, "Model unavailable, try again shortly.") from exc
    finally:
        _slots.release()

    reply = data["message"]["content"]
    return {"reply": REFUSAL if _BLOCKED.search(reply) else reply}


static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
