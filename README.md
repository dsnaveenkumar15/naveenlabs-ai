# naveenlabs-ai

Self-hosted AI stack for the VPS: local models (Ollama), a public chat page
(feeds the "AI galaxy" planet on naveenlabs.tech), and private automation
tools (n8n, Flowise).

## Services

| Service | Domain | Access | What it is |
|---|---|---|---|
| chat-api (Comet) | `comet.naveenlabs.tech` | **public** | Static chat UI + thin rate-limited proxy to Ollama. Visitors can chat with a small local model, nothing else. |
| ollama | (internal only) | none — no Traefik label, unreachable from outside the Docker network | Model runtime. Only `chat-api`/`n8n`/`flowise` can reach it, via `http://ollama:11434`. |
| n8n | `127.0.0.1:5678` on the VPS (SSH tunnel) | **private**, Basic Auth | Workflow automation. Never expose without auth — nodes can execute arbitrary code/shell commands. |
| flowise | `127.0.0.1:3000` on the VPS (SSH tunnel) | **private**, Basic Auth | Low-code LLM app/agent builder, points at the same local Ollama. |

## Why chat-api is a separate thin service instead of exposing Ollama directly

Ollama's own API has no auth and no rate limiting — exposing it straight to
the internet means anyone can hammer the model for free, unbounded. `chat-api`
(FastAPI, `chat-api/main.py`) adds a per-IP in-memory rate limit (10 req/min)
and a fixed system prompt, and is the only thing with a public Traefik label.
# ponytail: in-memory limiter, not shared across replicas or restarts --
# fine for one container on a personal site, revisit if this ever needs to
# scale out.

## Local testing (done, works)

`chat-api` was run locally against the laptop's existing Ollama instance
(see [[completed_work_about_me_bot]] for how that got installed) before
packaging into Docker — confirmed request/response and rate-limit-429 paths
both work. n8n/Flowise weren't tested locally (Docker isn't installed on this
laptop) — first real run will be on the VPS, which is the actual target
environment anyway.

## Deploy (VPS, not done yet — see reference_vps_access memory for the full checklist)

```bash
# on the VPS
mkdir -p /opt/naveenlabs-ai && cd /opt/naveenlabs-ai
# scp this whole repo here, or git clone if a remote gets set up later
cp .env.example .env
# edit .env: set real N8N_PASSWORD / FLOWISE_PASSWORD (not the placeholder)
docker compose up -d --build
docker compose exec ollama ollama pull qwen2.5:1.5b
```

Add a DNS A record for the `comet.` subdomain only (n8n and Flowise are other companies' product names and admin logins: never give them public hostnames; open them with `ssh -L 5678:127.0.0.1:5678 -L 3000:127.0.0.1:3000 root@VPS`) → VPS IP before
starting (Traefik cert issuance needs them resolvable). See
[[reference_vps_access]] for the existing Traefik setup this plugs into (no
Traefik-side config changes needed, same pattern as the other 2 apps already
on that VPS).

## Landing page wiring (do after this is deployed and confirmed working)

Add an entry to naveenlabs-home's `script.js` `galaxies.ai.planets` array
pointing at `https://comet.naveenlabs.tech` — that's the first real planet in
the AI galaxy (currently empty/placeholder). Don't wire it before the chat
page is actually live, or the planet links to a 404.
