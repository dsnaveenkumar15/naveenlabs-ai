# Chat: project briefs and a new home page

| | |
|---|---|
| Date | 2026-11-17 |
| Status | Agreed in chat with the owner; awaiting the owner's read of this document |
| App | Chat, `chat.naveenlabs.tech` (this repo, `chat-api/`) |

## Why

Recruiters, interviewers, architects and the owner's current colleagues open Chat to learn about his projects. Today
Chat knows one paragraph per project, says nothing about TradFi or Web3, caps every reply at 300 tokens, and shows the
chat box at the bottom of the page. A deep question gets a thin answer or "I don't know". The owner wants detailed,
well-structured answers about every project that are **both fast and right**.

What matters most: a wrong fact about a project in front of an interviewer or an architect, and a long blank wait.
Both are failures.

## Goals

1. Chat explains all six projects in detail: **Trust, Radar, Blueprints, Chat, TradFi, Web3**.
2. A project answer has four headed sections: **Intro** (short, like today's paragraph), **Architecture** (the parts
   and how they connect), **Strengths** (what is good about it, with real numbers), **Intelligence** (how it uses AI:
   which agents and models, what they decide, the guardrails around them).
3. Fast: the prepared answers appear at once; a model answer shows its first words within about 4 to 6 seconds and
   streams from there.
4. Right: every fact in a prepared answer comes from that project's own docs and code; the model answers project
   questions only from the prepared text.
5. A new home page: the chat box at the top, the example questions as six project cards below it (layout B, chosen by
   the owner in the mockup).

## Non-goals

- No vector database or retrieval pipeline: six short documents do not need one.
- No cloud model and no new cost: the model stays `gemma3:4b` on the owner's server.
- No accounts, no saved conversations, no long chat memory.
- No change to the general-knowledge behaviour (history, coding, maths and so on) beyond streaming and formatting.

## Anti-goals (a failure even if it works)

- An invented number, feature or claim about a project.
- Broker or exchange brand names in any answer (the sites say "broker" and "exchange").
- Secrets, server addresses, ports, private tools (n8n, Flowise, consoles, Kuma, Portainer) or anything that reads as
  investment advice.
- A page that sits blank for many seconds after a click.

## Measured constraint (2026-11-17, on the VPS, today's prompt)

| | |
|---|---|
| Prompt read (prefill) | about 50 to 85 tokens/s: today's 702-token prompt took 8 to 13 s before the first word |
| Generation | about 12 to 18 tokens/s |

So the model must get a **short** context (about 400 tokens or fewer) and must **stream**. Everything that can be
prepared is prepared.

## What gets built

### 1. Project briefs (the knowledge)

- One Markdown file per project in `chat-api/briefs/`: `trust.md`, `radar.md`, `blueprints.md`, `chat.md`,
  `tradfi.md`, `web3.md`.
- Each file has exactly four sections, `## Intro`, `## Architecture`, `## Strengths`, `## Intelligence`. Each section has
  a short form (shown in the full brief) and a detailed form (shown by the "More on…" buttons), marked in a way the
  builder chooses.
- Sources, per project: its own `docs/ARCHITECTURE.md` (Trust, Radar, Blueprints in atlas
  `naveenlabs-planets/docs/<app>/`; TradFi `zerodha/docs/`; Web3 `binance/docs/`; Chat this repo's README) and its
  explainer deck, re-checked against the code like the decks were. A fact with no source is left out.
- Written for a technical reader in plain English: short sentences, real numbers in `n of m (p%)` form, no marketing.
- Each section's short form stays small enough to be the model's whole context (see 3).

### 2. Answering

Three paths, decided on the server:

| The visitor | Chat answers with | Model? |
|---|---|---|
| clicks a card question or a "More on…" button | the prepared brief, section or detailed section | no, instant |
| types an overview question naming a project ("tell me about Trust", "how is Radar built", "what is Web3", "Blueprints architecture") | the prepared brief, or the named section | no, instant |
| types any other question about a project ("how does Trust stop a tool from reading credentials?") | the model, with a short system prompt plus the one or two most relevant sections of that project's brief, streamed | yes |
| asks anything else | the model as today, streamed | yes |

- **Which project:** a name or alias in the message (Trust, Red Team → Trust; Radar, Upgrade Agent → Radar;
  Blueprints, Architect → Blueprints; Chat; TradFi; Web3). With none, the project of the last brief shown in this
  conversation, which the page sends with the question.
- **If the brief does not cover it:** the model says it does not know and names the project's page.
- **Reply length:** model replies may run to about 600 tokens (today 300).
- **Unchanged:** rate limit (10 a minute), daily caps (50 per visitor, 1,000 in total), the self-harm reply, the blocked
  topics screen on the question, at most 2 model answers at once. Prepared answers count toward the rate limit and the
  daily caps but take no model slot.
- **The reply screen while streaming:** the blocked-topics screen runs on the text so far as it streams; on a match the
  stream stops and the answer is replaced by the refusal.

### 3. The page

- Greeting, then the chat box directly under it; the box stays at the top during the conversation.
- Below the box before the first question: six project cards in a 3 × 2 grid (one column on phones): name, icon, and two
  questions. The first is always "How is X built?" (the full brief); the second is specific to the project (for
  example Trust "How does its Red Team work?", TradFi "How is real money kept safe?").
- After the first question the cards fold away and the conversation takes their place under the box; a small
  "Projects" control brings them back.
- Under a brief answer: three buttons, "More on the architecture", "More on the strengths", "More on the
  intelligence", each showing that section's detailed form.
- Answers show headings, bullet lists, bold and inline code. Rendering builds DOM nodes from a small Markdown subset;
  model output is never inserted as HTML.
- A typing indicator until the first words; then the text grows as it streams.
- The look stays: today's lavender theme, fonts and icons (new icons for TradFi and Web3 in the same sprite).

### 4. Tests (beside today's 32)

- Every brief has the four sections with both forms; no brand names, server addresses, ports or private tool names in
  any brief.
- Routing: each card question, each "More on…" button and a set of typed overview questions return the prepared text
  without calling the model; a typed detail question calls the model with only that project's sections, within the
  context budget.
- Streaming: the reply arrives in pieces; a blocked word mid-stream ends in the refusal.
- Today's test that forbids TradFi and Web3 is replaced by one that checks their briefs are used.
- Page tests: box above the cards, six cards, cards fold away after the first question, budgets still met.

## Amendment 2026-11-17 (owner decision after the live check)

The live check showed gemma3:4b getting project facts wrong even with the relevant brief sections in its prompt
(it described Trust's code guard as agents probing the system). The owner chose: a typed project question gets the
brief section that matches it best, in detail, with no model; the model answers only general questions. A question
that names no project and shares no meaningful word with the last brief shown is a general question.

## Amendment 2, 2026-11-17 (owner: "use the model for all the replies, slower is fine, make the answers correct")

Replaces amendment 1. Every reply is written by the model. A project question gets that project's whole brief in
detailed form, strict faithfulness rules and temperature 0 (a spike on the server showed this faithful where part of
the brief was not). Code checks every number in a finished project answer against the brief; a number it does not
hold replaces the answer with the checked brief section. Each project answer offers "Show the checked brief". The
first words come after about 15 to 20 s.

## Decided by the owner

- Detailed answers about all six projects, including TradFi and Web3.
- The four sections: intro, architecture, strengths, intelligence.
- Speed and correctness both matter.
- Prepared briefs for project answers, the model only on the brief for other project questions.
- Layout B: chat box on top, project cards below that fold away once a chat starts.

## My calls (the owner can overrule)

- The "More on…" buttons show prepared detailed text, not model text, because a model answer takes 30 to 40 s to finish
  on this server.
- No brand names, no private tools or addresses in answers; "broker" and "exchange" instead.
- The answer stream format, the alias list wording, how short and detailed forms are marked in a brief.
- The site look is unchanged.
- Briefs are kept in step by hand: when a project's ARCHITECTURE.md changes, its brief is re-checked (a line in that
  section of the README, like today's "Keep in step with the Work list" note).

## Left to the builder

- The Markdown subset and its renderer; the stream format (NDJSON or text lines); how the page sends the current
  project; exact card questions beyond the two named examples.
- Section choice for the model context (keywords or a simple score), within about 400 tokens.

## After the build

- Deploy: copy the repo to `/opt/naveenlabs-ai` and `docker compose up -d --build chat-api` (README, "Deploy").
- Check on the live site: every card and button instant; a typed project question shows words within about 6 s;
  nothing in any answer names a broker or exchange brand.
