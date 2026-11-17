## Intro

Radar (radar.naveenlabs.tech) follows releases of the libraries AI apps are built on and publishes a daily digest: releases, API changes and security advisories, clustered and ranked by code. It also checks a dependency file (requirements.txt, package.json or a lock file) against those changes, and its **upgrade agent** finds the lines in a public repository that break when you upgrade.

<!-- more -->

Radar is for teams building on fast-moving AI libraries who want to know what changed and whether it breaks them.

- **Daily digest** (`/`, `/archive`): releases, API changes and advisories of tracked AI libraries, clustered and ranked by code; a model writes short notes.
- **Upgrade report** (`/upgrade`): paste a dependency file; it is read in your browser and compared with Radar's recorded API changes. Nothing is sent to the server.
- **Upgrade agent** (`/agent`): point it at a public repository; it finds the code that breaks when the tracked libraries are upgraded and writes the fix.
- **Ask Radar** (`/ask`): "what broke in X" and "CVEs in X" are answered straight from data with no model; other questions search the archive and a local model answers with every sentence cited.
- **Feed and trends**: an RSS feed of the last 14 digests and weekly counts per library.

## Architecture

Two containers behind a TLS proxy: **radar-web** (FastAPI and Jinja, read-only filesystem) serves the published data, answers questions and runs the upgrade agent; **radar-batch** collects releases, API snapshots and advisories on a schedule and publishes the digest. Data lives in SQLite (WAL); published digests are immutable, hash-checked releases.

<!-- more -->

- **Collection** (radar-batch): releases every 3 hours, API surface snapshots and security advisories every 6 hours, and a daily backfill that snapshots about two years of minor releases per tracked package. `api_changes.json` holds every version step, so reports can chain changes across many versions.
- **The digest** (nightly): items are clustered and scored by code; a model writes notes that must match a schema and cite real items. If the model or its daily budget is unavailable, the digest still publishes with the computed facts and notes marked "unsynthesized"; if fewer than 80% of sources answered, it is marked "partial". Published digests are never rewritten; corrections are errata.
- **Publishing**: files plus a SHA-256 manifest, then a `CURRENT` pointer flips; web verifies the hashes before serving and keeps 10 releases.
- **The upgrade agent** is a LangGraph graph: fetch inputs, parse dependencies (requirements, pyproject, package.json, lock files), ground in Radar's API changes, index Python and TypeScript usage, then plan, investigate with read-only tools, verify in code, and write the report.
- **Shared agent runtime**: budget-checked model gateway with a backup model and real cost, a run store, and a live event stream that survives a reload. Recorded runs replay at no cost.
- **Durable jobs**: leases, cached stages, backoff and dead-letter, with heartbeats to an uptime monitor.

## Strengths

- **Models explain, code decides**: impact, signal and every number come from code; a model sentence is kept only when it cites real items.
- **Measured**: across 157 tracked version steps, 141 (90%) broke nothing, but 4 patch releases carried 21 breaking changes. That is the kind of surprise Radar exists to catch.
- **Tested**: about 860 tests; the agent's offline evaluation requires precision at least 0.9 and recall at least 0.8.

<!-- more -->

- **Grounded facts**: the digest's impact scores, clusters and counts are computed; the model only writes notes, and a note is dropped unless it cites real items.
- **A real finding**: of 157 version steps Radar tracked, 141 of 157 (90%) broke nothing, but 4 patch releases carried 21 breaking changes. Semantic versioning alone would have hidden them.
- **Private by default**: the upgrade report reads your dependency file in the browser and never uploads it; "my stack" lives in your browser only.
- **Degrades instead of failing**: a model outage or a spent budget still publishes the facts; a failing source marks the digest "partial" rather than stopping it.
- **Bounded spend**: digest notes run under a $0.03 daily cap; the agent has a per-run budget of $0.05, about 3 minutes, 8 candidates and 30 tool calls, plus a daily cap, a weekly brake and stop-all.
- **Tested**: about 860 tests in CI on every push, a diff evaluation, and an agent evaluation (precision at least 0.9, recall at least 0.8 offline; a live run with real models before a deploy).

## Intelligence

The upgrade agent uses models only where judgment is needed: a plan step and an investigation loop with read-only tools. Code fetches, parses, indexes and grounds the inputs, and code verifies every finding: a quoted line must really be on the cited line. A report step then writes the route, difficulty, security notes, patch and checklist.

<!-- more -->

- **The graph**: fetch inputs, parse dependencies, ground in Radar's API changes, index the code (Python and TypeScript), **plan** (model), **investigate** (model, read-only tools on the fetched snapshot), **verify** (code: the quote must be on the cited line), **report** (model: upgrade route, difficulty, security, patch and checklist). Everything except plan, investigate and the report text is plain Python.
- **The models**: a fast and a strong model on OpenRouter (DeepSeek and GLM) with data collection denied. A free model may be used only for public-repository runs, never for pasted files.
- **Untrusted input**: repository content is fenced in prompts, tools only read the fetched snapshot, and nothing from a repository is ever executed.
- **Ask Radar** uses a local model on the same server for archive questions, and every sentence must cite an item; the two most common questions ("what broke", "which CVEs") skip the model entirely and answer from data.
- **Guardrails**: the budget is checked before every call, a backup model takes over on failure, the real cost is recorded, and the agent stops at its call and time limits. Model-proposed patches are suggestions to check against the listed API changes.
