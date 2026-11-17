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
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from briefs import find_project, load_briefs, model_context, prepared

MODEL = os.environ.get("CHAT_MODEL", "gemma3:4b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434/api/chat")
RATE_LIMIT = 10          # requests
RATE_WINDOW = 60         # seconds
MAX_MESSAGE_LEN = 1000
MAX_REPLY_TOKENS = 600
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

# Kept short: the server reads a prompt at roughly 50-85 tokens a second, so every line here delays the first word.
# The project facts live in briefs/ (one checked brief per project); a project question gets only that brief's
# relevant sections. Keep the one-line list in step with the Work list on naveenlabs.tech.
BASE_PROMPT = (
    "You are the chat assistant on naveenlabs.tech, a small AI model running locally on this personal site. Be clear "
    "and friendly. Refuse anything harmful, illegal, sexual, hateful or dangerous, and scams, spam or messages "
    "pretending to be a real company or person. Give no medical, legal or financial advice. Never claim to speak for "
    "any company. If you are not sure of a fact, say so.\n"
    "The site holds personal projects by Naveenkumar Dhamodharan, an Agentic AI Engineer: Trust "
    "(trust.naveenlabs.tech, MCP tool security), Radar (radar.naveenlabs.tech, AI library upgrades), Blueprints "
    "(blueprints.naveenlabs.tech, AI agent designs), TradFi (tradfi.naveenlabs.tech, stock trading, paper mode), Web3 "
    "(web3.naveenlabs.tech, crypto bots, paper mode) and Chat (chat.naveenlabs.tech, you). About these, use only the "
    "facts given; if they do not cover it, say you don't know and name the project's page. For every other topic, "
    "answer from your own knowledge and never send people to naveenlabs.tech."
)
GROUNDING = ("Answer only from this brief. If it does not cover the question, say you don't know and point to the "
             "project's page.\n")
BRIEFS = load_briefs(Path(__file__).parent / "briefs")

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
    project: Literal["trust", "radar", "blueprints", "tradfi", "web3", "chat"] | None = None   # the page's current project
    section: Literal["intro", "architecture", "strengths", "intelligence"] | None = None
    detail: bool = False


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


def _line(obj) -> str:
    return json.dumps(obj) + "\n"


def _answer(text: str, kind: str, project: str | None) -> Response:
    """A whole answer in the stream format: one text line, then the done line."""
    body = _line({"text": text}) + _line({"done": True, "kind": kind, "project": project})
    return Response(body, media_type="application/x-ndjson")


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(429, "Too many requests, slow down.")
    if _over_daily_cap(ip):
        raise HTTPException(429, "Daily limit reached, come back tomorrow.")
    if _SELF_HARM.search(req.message):
        return _answer(SUPPORT, "notice", None)
    if _BLOCKED.search(req.message):
        return _answer(REFUSAL, "notice", None)

    project = find_project(req.message, req.project)
    if req.section and project:
        return _answer(BRIEFS[project].section(req.section, req.detail), "brief", project)
    ready = prepared(req.message, project, BRIEFS)
    if ready is not None:
        return _answer(ready, "brief", find_project(req.message, None))

    if not _slots.acquire(blocking=False):
        raise HTTPException(503, "Busy, try again in a few seconds.", headers={"Retry-After": "5"})
    system = BASE_PROMPT + ("\n" + GROUNDING + model_context(project, req.message, BRIEFS) if project else "")
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": req.message}],
        "stream": True,
        "options": {"num_predict": MAX_REPLY_TOKENS, "num_thread": MODEL_THREADS},
    }
    http_req = urllib.request.Request(OLLAMA_URL, data=json.dumps(payload).encode(),
                                      headers={"Content-Type": "application/json"})
    try:
        upstream = urllib.request.urlopen(http_req, timeout=60)    # opened here so an unreachable model is still a 503
    except Exception as exc:
        _slots.release()
        raise HTTPException(503, "Model unavailable, try again shortly.") from exc
    return StreamingResponse(_relay(upstream, project), media_type="application/x-ndjson")


def _relay(upstream, project: str | None):
    """Pass the model's chunks on as they come, screening the text so far; the slot is freed however it ends."""
    text = ""
    try:
        with upstream:
            for raw in upstream:
                if not raw.strip():
                    continue
                data = json.loads(raw)
                chunk = (data.get("message") or {}).get("content", "")
                if chunk:
                    text += chunk
                    if _BLOCKED.search(text):
                        yield _line({"replace": REFUSAL})
                        break
                    yield _line({"text": chunk})
                if data.get("done"):
                    break
    except Exception:
        yield _line({"error": "The model stopped answering. Try again in a minute."})
    finally:
        _slots.release()
    yield _line({"done": True, "kind": "model", "project": project})


static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
