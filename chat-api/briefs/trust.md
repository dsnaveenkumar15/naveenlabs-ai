## Intro

Trust (trust.naveenlabs.tech) is a security checker for MCP servers, the plug-ins that give an AI agent its tools. You paste a server's tool list and Trust shows what those tools could do on your machine before you install them: hidden instructions, tool shadowing, shell access, reading credential files. Nothing you paste is stored. Its **Red Team** goes further: an agent attacks the tools in a sandbox and shows what got through.

<!-- more -->

Trust answers one question for anyone about to install an MCP server: what can these tools make my agent do?

- **Check a tool list** (`/check`): paste the JSON a server returns for `tools/list`. A rules engine reads every description and reports risky wording and capabilities, with the exact text that triggered each finding. No model is involved and nothing is stored.
- **Bring your own key**: a visitor can ask a model to review the list too. The browser calls the model provider with the visitor's own key; the key never reaches Trust's server.
- **Methodology** (`/methodology`): every rule, its severity and what it looks for, in public.
- **Red Team** (`/redteam`): an agent attacks a pasted tool list or a public GitHub repository with real models, shows a replay of what got through, and re-tests a suggested fix. Results are private links, deleted after seven days.
- **Benchmark** (`/benchmark`): published results of known attacks against named models, with and without defences.

## Architecture

Two containers behind a TLS proxy: **trust-web** (FastAPI and Jinja, read-only filesystem) serves pages and runs the Red Team on background threads; **trust-batch** runs a durable job worker for slow audits. Data lives in SQLite (WAL). Published results are immutable releases with a SHA-256 manifest that web checks before serving.

<!-- more -->

- **trust-web**: FastAPI with Jinja templates, non-root, read-only root filesystem. It serves `/check`, the methodology and the published audits, and runs Red Team agents on background threads with a live trace over server-sent events that survives a page reload.
- **trust-batch**: a durable job worker. Jobs are enqueued idempotently, claimed with leases, cached per stage, retried with backoff and dead-lettered after the attempt limit. A lease that expires counts as an attempt, so a poison job ends instead of looping.
- **Audit pipeline**: discover new servers every 6 hours, fetch a snapshot, extract the tools with tree-sitter (Python and TypeScript), score them with the rules engine, then a model review whose evidence is checked by code. A critical finding, a partial snapshot or a disagreement goes to an owner review before anything is published.
- **Publishing**: each publish writes an immutable release (files plus a SHA-256 manifest) and flips a `CURRENT` pointer. Web verifies the hashes before serving; the last 10 releases are kept, so rolling back is a pointer change.
- **Shared agent runtime**: a model gateway that checks the budget before every call, falls back to a backup model and records the real cost; a run store and runner; the event stream. Trust shares this core with Radar and Blueprints.
- **Owner controls**: every limit that may change without a deploy (switches, per-run and daily dollar caps, a weekly brake, stop-all) is stored in Trust's own database, with a note for every change.

## Strengths

- **Models explain, code decides**: grades and verdicts come from code; a model's statement is used only when its evidence checks out.
- **Proven defence**: in the published benchmark, 700 tries on 9 models, the code guard stopped 0 of 178 (0%) attacks getting through, against 33 of 195 (17%) with a prompt warning and 37 of 191 (19%) with no defence. The run cost $0.0919.
- **Tested**: 623 tests, plus a rules evaluation at precision and recall 1.00.

<!-- more -->

- **The benchmark result**: the 8 known-bad tool lists were run against 9 models under three conditions, 700 tries in total for $0.0919. With no defence, 37 of 191 (19%) tries leaked a fake secret or made a dangerous call; a prompt warning barely helped at 33 of 195 (17%); the code guard stopped every one, 0 of 178 (0%). The lesson: a warning in the prompt is not a control; code that checks the call is.
- **Launch gate**: before the Red Team went live it caught 8 of 8 planted problems with 0 of 4 false alarms, at about $0.02 in total.
- **Spend is bounded by design**: $0.10 and 10 minutes per run, $0.25 a day, runs per visitor, a queue, a weekly brake and a stop-all switch. A typical run costs well under one cent.
- **Safe by construction**: victims hold only fake secrets in a sandbox; untrusted tool text is fenced and labelled in prompts; output is schema-checked; nothing a scanned tool says can change a verdict.
- **Hardened container**: non-root, read-only filesystem, all capabilities dropped, `no-new-privileges`, CPU and memory limits, strict CSP with no inline code, HSTS, rate limits per visitor.
- **Tested**: 623 tests in CI on every push and a rules evaluation set (precision and recall on labelled cases; CI fails if either drops).

## Intelligence

The Red Team is an agent. An analyst model picks 3 to 6 of 8 catalogue attacks for the tools you pasted; two victim models, a careful one and a small one, are attacked with fake tools that hold planted fake secrets. Plain code decides every verdict and gives an A to F grade per model. All models run through OpenRouter with data collection denied.

<!-- more -->

- **The attack catalogue** (8 scenarios): hidden instructions, tool shadowing, output injection, impersonation, hiding actions from the user, encoded payloads, secret-file reads and dangerous escalation.
- **The models**: an analyst (GLM) plans the attacks; a careful victim (DeepSeek) and a small victim (Llama 3.1 8B) are attacked. All run on OpenRouter with data collection denied. The headline grade is the worst model's grade; each model is tried once, so results can vary between runs.
- **How the code guard works**: the guard is each attack's own fix, applied in code before any model sees the tools. For six of the eight attacks it strips the suspect text (its tag block, or else its sentence) from the tool's description; for impersonation it renames the copycat tool with an `ext_` prefix; for output injection it wraps the tool's output as untrusted content with a note to treat it as data and never follow instructions in it. Tests check that every fix removes the suspect text and itself passes Trust's own description rules.
- **Code decides**: plain-code checks give every verdict (did a fake secret leave the sandbox? was a dangerous call made?). Impersonation alone never forces an F.
- **Fix and re-test**: every attack that got through is run again with a suggested fix, so the report shows whether the fix holds. The result includes a regression pack to re-run later.
- **Guardrails on the agent itself**: the budget is checked before every model call, there is a backup model, the real cost is recorded from each response, and a restart marks runs in flight as failed with a clear message.
- **The audit reviews**: in the batch pipeline, one model writes a review of each audited server, but its claims are kept only when their evidence checks out, and anything critical waits for the owner.
