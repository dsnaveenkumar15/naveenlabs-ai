## Intro

Chat (chat.naveenlabs.tech) is this assistant: a small open model running on the owner's own server, with no account and nothing saved. It answers questions about the six projects on naveenlabs.tech from checked briefs, and general questions from its own knowledge, behind rate limits and guardrails.

<!-- more -->

Chat is a public front door to the projects and a demonstration of running a model safely on modest hardware.

- **Project answers**: Trust, Radar, Blueprints, TradFi, Web3 and Chat each have a checked brief (intro, architecture, strengths, intelligence). The model answers every project question from that project's whole brief, and code checks the answer; "Show the checked brief" shows the source.
- **General questions**: history, science, coding, writing and the like are answered from the model's own knowledge.
- **Private**: no account, no cookies for tracking, and no conversation is stored.
- **Who builds it**: Naveenkumar Dhamodharan, an Agentic AI Engineer, as independent personal projects not affiliated with any company.

## Architecture

A thin, guarded FastAPI service (chat-api) in front of a local Ollama model runtime, both in Docker on one server. Ollama has no public route; chat-api is the only public piece. Project briefs are Markdown files shipped with the app; a project question gets the model with that project's whole brief, a general question gets it with a short site prompt, and every answer streams to the page as it is written.

<!-- more -->

- **chat-api**: FastAPI, non-root, read-only filesystem, all capabilities dropped, CPU and memory limits, and a health check. It serves the static page and one API endpoint.
- **Ollama**: runs the model with a CPU cap so the other apps on the server keep their share; it has no public address.
- **Routing a question**: a question naming a project, or a follow-up sharing words with the last brief shown, goes to the model with that project's whole brief in its detailed form; anything else is a general question. "Show the checked brief" returns the brief itself without the model.
- **Checking the answer**: when a project answer is complete, code compares every number in it with the brief; if one is not in the brief, the answer is replaced by the checked brief section.
- **Streaming**: model answers arrive word by word, and the reply screen checks the text as it grows.
- **The page**: plain HTML, CSS and JavaScript with a strict content security policy and no inline code; answers are rendered from a small Markdown subset into page elements, never as raw HTML.

## Strengths

- **Correct before fast**: project answers take longer (about 15 to 20 seconds before the first words) because the model reads the whole brief; they stream as they are written.
- **Right**: project facts come only from briefs checked against each project's own documentation and code.
- **Guarded**: per-visitor rate limits, daily caps, at most 2 answers generated at once, and a topic screen on questions and replies.

<!-- more -->

- **Limits**: 10 questions a minute per visitor, 50 per visitor per day, 1,000 per day for the whole site, at most 2 model answers at once (others are asked to retry), questions up to 1,000 characters.
- **Guardrails**: a topic screen on the question and the reply (weapons, malware, phishing and scams, drugs, sexual content); a supportive reply with the Tele-MANAS helpline (14416) for self-harm; a system prompt that refuses harmful requests and gives no medical, legal or financial advice.
- **Security headers** on every response: strict CSP, HSTS, `nosniff`, `frame-ancestors 'none'` and a permissions policy; API docs are turned off.
- **Model chosen by measurement**: gemma3:4b was picked after benchmarking three models on this server with the live prompt; the smaller one invented facts, gemma answered the test questions correctly.
- **Tested**: unit tests cover the limits, the guardrails, the routing to briefs, streaming and the page's theme, contrast and markup.

## Intelligence

Chat runs gemma3:4b, an open-weights model from Google, on the server's CPU with no GPU. For a project question it gets that project's whole checked brief, strict rules (use only these facts, keep numbers with their words, add no conclusions) and temperature 0, and code checks every number in its answer against the brief.

<!-- more -->

- **The model**: gemma3:4b (open weights, about 3.3 GB), run by Ollama on 3 of the server's 4 CPU cores, so the other apps keep working while it answers.
- **Measured, then decided**: given only part of a brief, the model mixed up facts (it described Trust's code guard as agents probing the system). Given the whole brief, the strict rules and temperature 0, five test questions came back faithful with no invented numbers, at the cost of a slower start.
- **Models explain, code decides**: a number in an answer that the brief does not hold replaces the answer with the checked brief section, and every project answer offers the brief it was written from.
- **Safety around the model**: the question is screened before the model sees it, and the answer is screened as it streams; a match replaces the answer with a refusal.
