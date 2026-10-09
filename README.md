# naveenlabs-ai

Self-hosted AI stack on the VPS: a local model runtime (Ollama), the public **Chat** page
(`https://chat.naveenlabs.tech`, the Chat planet on naveenlabs.tech), and private automation tools (n8n, Flowise).

Status (2026-10-09): Chat and Ollama are deployed and healthy. n8n and Flowise are configured but not running.
The whole server: `docs/ARCHITECTURE.md` in the `naveenlabs-ops` repository; the AI apps that share Ollama:
`docs/ARCHITECTURE.md` in the `atlas` repository.

## Services

| Service | Address | Access | What it is |
|---|---|---|---|
| chat-api (Chat) | `chat.naveenlabs.tech` | public | Static chat page plus a thin, guarded API in front of the model |
| ollama | internal only | none | Model runtime (`ollama/ollama:0.35.0`, capped at 3 of 4 CPU cores and 6 GB, model never unloaded: a cold load can outlast chat-api's 60 s timeout). No Traefik route; only chat-api, n8n, Flowise and Radar reach it at `http://ollama:11434` |
| n8n | `127.0.0.1:5678` (SSH tunnel) | private, Basic Auth | Workflow automation. Never public: its nodes can run shell commands |
| flowise | `127.0.0.1:3000` (SSH tunnel) | private, Basic Auth | Low-code LLM app builder on the same Ollama |

Open the private tools with `ssh -L 5678:127.0.0.1:5678 -L 3000:127.0.0.1:3000 root@VPS`. They must never get a
public hostname (other products' names and admin logins; see the hosting-policy rules).

**Chat's look:** its own "soft conversational" theme in `chat-api/static/` (lavender, DM Sans, speech-bubble mark,
soft filled icons in `icons.svg`), light by default with the shared light/dark toggle. One column: greeting, question
cards by topic, the conversation, a pill composer that stays in view, a three-dot typing indicator.
`chat-api/test_page.py` checks tokens, contrast, budgets and markup.

## Why Chat is a separate service instead of exposing Ollama

Ollama's API has no authentication and no limits. `chat-api/main.py` is the only public piece and adds:

- **Limits:** 10 requests per minute per visitor, 50 per visitor per day, 1,000 per day for the whole site
  (`CHAT_DAILY_PER_VISITOR`, `CHAT_DAILY_TOTAL`), at most 2 generations at once (`CHAT_MAX_CONCURRENT`, others get
  503 with `Retry-After`), replies capped at 300 tokens, questions at 1,000 characters.
- **Guardrails:** a topic screen on the question and on the reply (weapons, malware, phishing and scams, drugs,
  sexual content); self-harm questions get a supportive reply with the Tele-MANAS helpline (14416); a system prompt
  that refuses harmful requests, gives no medical, legal or financial advice and never claims to speak for a company.
  The screen is a keyword list, not a classifier; the system prompt is the second layer.
- **Security headers** on every response: strict CSP, HSTS, `nosniff`, `frame-ancestors 'none'`, permissions policy.
  API docs are turned off.
- **Visitor identity behind the proxy:** the rightmost `X-Forwarded-For` entry (`TRUST_PROXY=1`).
- **`/healthz`** for the Docker health check and the external uptime probe.

The limiter and counters are in memory: one container on a personal site, so a restart resetting them is acceptable.

## Model

Chat runs **gemma3:4b** (Google, open weights, ~3.3 GB). Chosen on 2026-10-04 by benchmarking on this server
(4 vCPU AMD EPYC, no GPU) with the live prompt and reply cap:

| Model | Avg reply | Quality on the test questions |
|---|---|---|
| qwen2.5:1.5b (before) | 1.8 s | invented facts |
| llama3.2:3b | 4.2 s | mixed |
| **gemma3:4b** | 4.7 s | all correct |

- **Site facts:** a small model knows nothing about naveenlabs.tech and invents answers about it, so `SITE_FACTS` in
  `chat-api/main.py` is sent with every question (projects, owner, and the rule: site questions only from these
  facts, general questions answered normally). **Update it whenever the landing page's Work list changes.**
- **CPU:** a reply used all 4 cores, starving the trading apps, so Ollama is capped at `cpus: "3.0"` and the model
  runs with `num_thread: 3` (`CHAT_MODEL_THREADS`). Typical replies take 7-10 s, long ones about 15 s.
- **Memory:** 6 GB cap (gemma ~3.6 GB loaded plus Radar's `nomic-embed-text`; at 4 GB, two loaded models were killed).
- To change models: `docker compose exec ollama ollama pull <model>`, set `CHAT_MODEL`, check speed and quality first.

## Container hardening

chat-api runs as a non-root user with a read-only filesystem, all Linux capabilities dropped,
`no-new-privileges`, 0.5 CPU and 256 MB, and a health check. Python dependencies and the Ollama image are pinned.

## Tests

```powershell
cd chat-api
python -m pytest -q        # limits, guardrails, daily caps, self-harm reply, headers, health check, page theme and markup
```

## Deploy (VPS)

The repository has no git remote; it is copied to the server:

```bash
# from the laptop, in this directory
tar --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache -cf - . \
  | ssh root@VPS "tar -xf - -C /opt/naveenlabs-ai"
# on the VPS
cd /opt/naveenlabs-ai && docker compose up -d --build ollama chat-api
docker inspect -f '{{.State.Health.Status}}' naveenlabs-ai-chat-api-1      # wait for "healthy"
docker compose exec ollama ollama pull gemma3:4b                         # first deploy only
docker compose exec ollama ollama run gemma3:4b "Say ok."                # after any ollama restart: load the model once
```

The warm-up matters: a cold load can take longer than chat-api's 60 s timeout, and a timed-out request aborts the
load, so without it every visitor gets "Model unavailable". `OLLAMA_KEEP_ALIVE=-1` then keeps the model loaded.

DNS: an A record `chat` pointing at the VPS. Only `chat` is public.

## Architecture

```mermaid
flowchart LR
    visitor(["Visitor"]) --> traefik["Traefik<br/>TLS, Host: chat.naveenlabs.tech"]
    traefik --> api["chat-api (FastAPI)"]
    subgraph api_inside["chat-api, per question"]
        direction TB
        limits["rate limits, daily caps,<br/>2 at once"] --> screen["topic screen<br/>on the question"]
        screen --> prompt["system prompt +<br/>SITE_FACTS"]
        prompt --> reply_screen["topic screen<br/>on the reply"]
    end
    api --> api_inside
    prompt --> ollama["ollama (internal only)<br/>gemma3:4b, 3 cores, 6 GB"]
    radar["Radar /ask"] --> ollama
```

The browser loads the static page from chat-api and posts each question to `/api/chat`. Ollama has no route from
outside the Docker network; chat-api is the only public piece and adds every limit and guardrail. Radar's `/ask`
uses the same Ollama for embeddings (`nomic-embed-text`).

## Completed work

| Date | Work |
|---|---|
| 2026-09-25 | Stack defined: Ollama, chat-api, n8n, Flowise |
| 2026-10-02 | n8n and Flowise private; per-visitor rate limit behind the proxy, concurrency and reply caps; guardrails (topic screen, self-harm helpline reply); Chat named and given its hostname |
| 2026-10-03 | Shared product design with dark mode; hardened container (health endpoint, security headers, non-root, read-only); light/dark toggle shared across sites |
| 2026-10-04 | Model benchmarked on the server and switched to gemma3:4b; answers about the site come from a fact sheet; Ollama capped at 3 cores and 6 GB |
| 2026-10-07 | "Soft conversational" theme, one-column home with topic cards, typing indicator; model never unloaded (cold load outlasted the timeout); facts mention the Architect and Red Team |
| 2026-10-08 | Facts no longer describe the private trading systems (a test forbids it) |

Open item: this repository has no GitHub remote yet; it exists on the laptop and, as copied files, on the server.
