# naveenlabs-ai

Self-hosted AI stack on the VPS: a local model runtime (Ollama), the public **Chat** page
(`https://chat.naveenlabs.tech`, the Chat planet on naveenlabs.tech), and private automation tools (n8n, Flowise).

Status (2026-10-03): Chat and Ollama are deployed and healthy. n8n and Flowise are configured but not running.
Shared architecture, security and operations: see `docs/ARCHITECTURE.md` in the `atlas` repository.

## Services

| Service | Address | Access | What it is |
|---|---|---|---|
| chat-api (Chat) | `chat.naveenlabs.tech` | public | Static chat page plus a thin, guarded API in front of the model |
| ollama | internal only | none | Model runtime (`ollama/ollama:0.35.0`, capped at 3 of 4 CPU cores and 6 GB, model kept loaded for 24 h). No Traefik route; only chat-api, n8n, Flowise and Radar reach it at `http://ollama:11434` |
| n8n | `127.0.0.1:5678` (SSH tunnel) | private, Basic Auth | Workflow automation. Never public: its nodes can run shell commands |
| flowise | `127.0.0.1:3000` (SSH tunnel) | private, Basic Auth | Low-code LLM app builder on the same Ollama |

Open the private tools with `ssh -L 5678:127.0.0.1:5678 -L 3000:127.0.0.1:3000 root@VPS`. They must never get a
public hostname (other products' names and admin logins; see the hosting-policy rules).

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
python -m pytest -q        # limits, guardrails, daily caps, self-harm reply, headers, health check
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
```

DNS: an A record `chat` pointing at the VPS. Only `chat` is public.
