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
import threading
import time
import json
import urllib.request
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

MODEL = os.environ.get("CHAT_MODEL", "qwen2.5:1.5b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434/api/chat")
RATE_LIMIT = 10          # requests
RATE_WINDOW = 60         # seconds
MAX_MESSAGE_LEN = 1000
MAX_REPLY_TOKENS = 300
# Behind Traefik the socket peer is the proxy, so the real visitor is the rightmost X-Forwarded-For entry.
TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"
# The model shares a small box with real apps: at most this many generations run at once, the rest are told to retry.
_slots = threading.BoundedSemaphore(int(os.environ.get("CHAT_MAX_CONCURRENT", "2")))

SYSTEM_PROMPT = (
    "You are a small AI model running locally on naveenlabs.tech, a personal "
    "site. Be concise and friendly. If asked who runs this site, mention it's "
    "Naveenkumar Dhamodharan's personal AI playground."
)

app = FastAPI()
_hits: dict[str, deque] = defaultdict(deque)


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


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    if _rate_limited(_client_ip(request)):
        raise HTTPException(429, "Too many requests, slow down.")
    if not _slots.acquire(blocking=False):
        raise HTTPException(503, "Busy, try again in a few seconds.", headers={"Retry-After": "5"})

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": req.message},
        ],
        "stream": False,
        "options": {"num_predict": MAX_REPLY_TOKENS},
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

    return {"reply": data["message"]["content"]}


static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
