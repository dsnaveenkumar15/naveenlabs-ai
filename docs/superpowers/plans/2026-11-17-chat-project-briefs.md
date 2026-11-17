# Chat Project Briefs and New Home Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chat answers questions about all six projects with checked, sectioned briefs (instant) or a streamed model answer grounded in one brief, on a page with the chat box at the top and six project cards below it.

**Architecture:** A pure module `briefs.py` loads six Markdown briefs and decides, per question, between a prepared answer and a short model context. `main.py` keeps every guard it has and streams NDJSON lines (prepared answers as one line, model answers chunk by chunk, screened as they grow). The page renders a small Markdown subset into DOM nodes, never HTML strings.

**Tech Stack:** Python 3.12, FastAPI 0.115.6 `StreamingResponse`, Ollama `/api/chat` with `stream: true`, plain JS (no libraries, strict CSP `script-src 'self'`), pytest 9.2 + httpx.

**Spec:** `docs/superpowers/specs/2026-11-17-chat-project-briefs-design.md`

## Global Constraints

- Projects, in this order everywhere: `trust`, `radar`, `blueprints`, `tradfi`, `web3`, `chat`. Display names: Trust, Radar, Blueprints, TradFi, Web3, Chat.
- Brief sections, in this order: `intro`, `architecture`, `strengths`, `intelligence`; headings `## Intro`, `## Architecture`, `## Strengths`, `## Intelligence`.
- Model stays `gemma3:4b`; no new dependency in `requirements.txt`; no cloud call.
- Unchanged guards: `RATE_LIMIT = 10` per `RATE_WINDOW = 60` s, `DAILY_PER_VISITOR = 50`, `DAILY_TOTAL = 1000`, self-harm reply, `_BLOCKED` screen on question and reply, `CHAT_MAX_CONCURRENT = 2` model slots, security headers and CSP.
- `MAX_REPLY_TOKENS = 600`.
- Model context budget for a project question: the brief text given to the model is at most `CONTEXT_CHARS = 1600` characters (about 400 tokens).
- Never in a brief, a prompt or the page: `zerodha`, `kite`, `binance`, `n8n`, `flowise`, `portainer`, `kuma`, `tailscale`, `187.126.`, `/internal/control`, `:9100`, `:9200`, `:9300`, `investment advice` (case-insensitive). Use "broker" and "exchange".
- Facts in briefs come only from each project's `ARCHITECTURE.md` (atlas `naveenlabs-planets/docs/{trust,radar,blueprints}/`, `zerodha/docs/`, `binance/docs/`, this repo's `README.md`), its explainer deck, and the code. Numbers in `n of m (p%)` form. A fact with no source is left out.
- Model output is shown as text: no `innerHTML`, `insertAdjacentHTML` or `outerHTML` in `chat.js` (existing test).
- Look unchanged: existing theme tokens, fonts, icon sprite; `style.css` ≤ 40,000 bytes; fonts ≤ 120,000 bytes.
- Commits carry only the owner's name; no co-author lines.

## Review Focus

1. A follow-up with no project name ("how is it tested?") after a brief: answered from the project the page last showed, not as a general question. Test: Task 1 `test_follow_up_without_a_name_uses_the_current_project`.
2. A forged `project` or `section` in the request (`"../main"`, `"secrets"`): rejected with 422 before anything is read. Test: Task 3 `test_unknown_project_or_section_is_rejected`.
3. A blocked word split across two stream chunks ("bo" + "mb"): the answer still ends in the refusal. Test: Task 3 `test_blocked_word_split_across_chunks_is_caught`.
4. Ollama dies mid-stream: the visitor keeps the text so far plus an error line, and the model slot is freed. Test: Task 3 `test_model_failure_mid_stream_frees_the_slot_and_says_so`.
5. Model output containing markup (`<img src=x onerror=…>`, `<script>`): shown as literal text. Test: Task 4 browser check step, plus the existing text-only test.

---

### Task 1: `briefs.py`, the loader and the router (pure)

**Files:**
- Create: `chat-api/briefs.py`
- Test: `chat-api/test_briefs.py`

**Interfaces:**
- Produces:
  - `PROJECTS: tuple[str, ...]` (the order above); `SECTIONS: tuple[str, ...]`; `NAMES: dict[str, str]` (key → display name); `CONTEXT_CHARS = 1600`.
  - `@dataclass(frozen=True) class Section: short: str; detail: str`
  - `@dataclass(frozen=True) class Brief: project: str; sections: dict[str, Section]` with `def full(self) -> str` (a `# <Name>` title plus every section's heading and short form, in order) and `def section(self, name: str, detail: bool) -> str` (`## <Heading>` plus the short or detailed form).
  - `def load_briefs(directory: Path) -> dict[str, Brief]` — reads `<project>.md` for every project; raises `ValueError` naming the file if a section or a form is missing. Format inside a section: short form, a line `<!-- more -->`, detailed form.
  - `def find_project(message: str, current: str | None) -> str | None` — aliases, case-insensitive whole words: `trust`, `red team` → trust; `radar`, `upgrade agent` → radar; `blueprints`, `blueprint`, `architect` → blueprints; `tradfi` → tradfi; `web3` → web3; `chat` → chat ("you" is not an alias: "what can you do?" is a general question). First name in the message wins; none → `current` if it is in `PROJECTS`, else `None`.
  - `def prepared(message: str, project: str | None, briefs: dict[str, Brief]) -> str | None` — returns `briefs[p].full()` for an overview question naming a project, `briefs[p].section(s, detail=False)` when it also names one section (`architecture`, `strengths`/`strong`/`good at`, `intelligence`/`ai`/`agent`/`model`, `intro`/`overview`), else `None`.
  - `def model_context(project: str, message: str, briefs: dict[str, Brief]) -> str` — the most relevant sections of that brief (scored by shared words with the message; ties keep section order), detailed form when it fits, else short form, total ≤ `CONTEXT_CHARS`; always starts with `<Name>:`.

- [ ] **Step 1: Write the failing tests** (fixture briefs in `tmp_path`, two short projects are enough plus empty-valid files for the rest)

```python
def test_load_reads_four_sections_with_both_forms(tmp_path): ...
    # brief.sections["architecture"].short == "Arch short." and .detail == "Arch detail."
def test_missing_section_names_the_file(tmp_path):
    with pytest.raises(ValueError, match="trust.md"): load_briefs(tmp_path)
def test_full_brief_has_title_and_headings_in_order(tmp_path):
    text = briefs["trust"].full()
    assert text.startswith("# Trust") and [h for h in re.findall(r"^## (\w+)", text, re.M)] == ["Intro", "Architecture", "Strengths", "Intelligence"]
    assert "Arch detail." not in text
@pytest.mark.parametrize("message,expected", [
    ("How is Trust built?", "trust"), ("tell me about the red team", "trust"), ("What does the Architect do?", "blueprints"),
    ("explain TradFi", "tradfi"), ("WEB3 architecture", "web3"), ("What is a trustworthy source?", None)])
def test_find_project_by_name_or_alias(message, expected): assert find_project(message, None) == expected
def test_follow_up_without_a_name_uses_the_current_project():
    assert find_project("how is it tested?", "radar") == "radar"
    assert find_project("how is it tested?", "nonsense") is None
@pytest.mark.parametrize("message", ["How is Trust built?", "Tell me about Trust", "What is Trust?", "Explain Trust", "describe trust"])
def test_overview_questions_get_the_full_brief(message, briefs): assert prepared(message, "trust", briefs) == briefs["trust"].full()
def test_naming_a_section_gets_that_section(briefs):
    assert prepared("Trust architecture", "trust", briefs) == briefs["trust"].section("architecture", detail=False)
    assert prepared("How does Trust use AI?", "trust", briefs) is None    # a detail question, for the model
def test_model_context_fits_the_budget_and_prefers_matching_sections(briefs_long):
    ctx = model_context("trust", "which model scores the attacks?", briefs_long)
    assert ctx.startswith("Trust:") and len(ctx) <= CONTEXT_CHARS and "## Intelligence" in ctx
```

- [ ] **Step 2: Run** `python -m pytest -q test_briefs.py` — Expected: FAIL, `ModuleNotFoundError: No module named 'briefs'`.
- [ ] **Step 3: Implement** `briefs.py` per the Interfaces block. Overview detection: a regex over the lowered message, `^(how (is|was|does) <alias>( built| made| designed| work)?|tell me about( the)? <alias>|what('s| is)( the)? <alias>|(explain|describe)( the)? <alias>|<alias>( architecture| overview)?)\??$` style; the exact pattern is the builder's, the parametrized cases are binding.
- [ ] **Step 4: Run** the same command — Expected: all pass.
- [ ] **Step 5: Commit** `feat(chat): brief loader and router`.

### Task 2: The six briefs

**Files:**
- Create: `chat-api/briefs/trust.md`, `radar.md`, `blueprints.md`, `tradfi.md`, `web3.md`, `chat.md`
- Modify: `chat-api/test_briefs.py` (content tests on the real files)

**Interfaces:**
- Consumes: `load_briefs`, `PROJECTS`, `SECTIONS`, `CONTEXT_CHARS` (Task 1).

- [ ] **Step 1: Write the failing content tests**

```python
REAL = Path(__file__).parent / "briefs"
def test_every_project_has_a_complete_brief(): assert set(load_briefs(REAL)) == set(PROJECTS)
def test_briefs_never_name_brands_hosts_or_private_tools():
    text = "\n".join(p.read_text(encoding="utf-8").lower() for p in REAL.glob("*.md"))
    for word in BANNED: assert word not in text, word        # BANNED = the Global Constraints list, defined once in briefs.py
def test_short_forms_fit_the_model_context():
    for b in load_briefs(REAL).values():
        for name, s in b.sections.items(): assert len(s.short) <= CONTEXT_CHARS // 2, (b.project, name)
def test_finance_briefs_say_paper_mode_and_no_advice():
    for p in ("tradfi", "web3"): assert "paper" in load_briefs(REAL)[p].full().lower()
```

(`BANNED: tuple[str, ...]` is added to `briefs.py` in this step.)

- [ ] **Step 2: Run** `python -m pytest -q test_briefs.py` — Expected: FAIL, `FileNotFoundError` for `briefs/trust.md`.
- [ ] **Step 3: Write each brief from its sources** (Global Constraints). Per project: Intro short = today's `SITE_FACTS` paragraph tightened (TradFi/Web3: what it is, paper mode, public demo); Architecture = the parts and how they connect, from ARCHITECTURE.md; Strengths = 3 to 5 bullets with real numbers (tests, mutation scores, benchmark results) copied from the docs; Intelligence = which agents/models, what they decide, the guardrails (TradFi/Web3: the AI layer never places orders; the Advisor is rules only, no LLM in the verdict). Keep a scratch ledger of claim → source file while writing; it is not committed.
- [ ] **Step 4: Accuracy pass**: re-read every number and name against its source; remove anything unsourced. Run the tests — Expected: all pass.
- [ ] **Step 5: Commit** `feat(chat): checked briefs for all six projects`.

### Task 3: The API: routing and streaming

**Files:**
- Modify: `chat-api/main.py` (request model, prompt, `/api/chat`)
- Modify: `chat-api/test_main.py`

**Interfaces:**
- Consumes: `load_briefs`, `find_project`, `prepared`, `model_context`, `PROJECTS`, `SECTIONS` (Task 1); `briefs/` (Task 2).
- Produces (for Task 4): `POST /api/chat` with body `{"message": str (1..1000), "project": str|None, "section": str|None, "detail": bool = false}`; `project` must be in `PROJECTS` and `section` in `SECTIONS` or 422. Response `application/x-ndjson`, one JSON object per line:
  - `{"text": "<chunk>"}` (one or more),
  - `{"replace": "<text>"}` (the refusal, when the reply screen trips),
  - `{"error": "<message>"}` (model failed mid-stream),
  - last line `{"done": true, "kind": "brief"|"model", "project": str|null}`.
  - Errors before any text stay HTTP: 429 rate/daily, 503 busy (`Retry-After: 5`) or model unreachable, as today.
- Behaviour:
  - the project is `find_project(message, req.project)`.
  - `section` given: prepared `briefs[project].section(section, detail)`; `section == None` with a project and `message` equal to the card text uses `prepared()` as typed.
  - prepared answers: rate limit and daily caps apply, self-harm and blocked screens apply to the message, no model slot.
  - model answers: system prompt = `BASE_PROMPT` (today's `SYSTEM_PROMPT` first paragraph plus a one-line-per-project site summary, total ≤ 1,200 characters) and, for a project question, `"Answer only from this brief. If it does not cover the question, say you don't know and point to the project's page.\n" + model_context(...)`; `stream: true`, `num_predict: MAX_REPLY_TOKENS`.
  - the reply screen runs `_BLOCKED.search` on the accumulated text after each chunk.

- [ ] **Step 1: Write the failing tests** (the fake `urlopen` now returns an iterable of NDJSON lines; adapt `reset()`)

```python
def lines(res): return [json.loads(l) for l in res.text.splitlines() if l]
def test_card_question_is_answered_from_the_brief_without_the_model(monkeypatch):
    seen = reset(monkeypatch); out = lines(post({"message": "How is Trust built?", "project": "trust"}))
    assert seen == [] and out[-1] == {"done": True, "kind": "brief", "project": "trust"} and out[0]["text"].startswith("# Trust")
def test_more_button_returns_the_detailed_section(monkeypatch): ...  # section="architecture", detail=True -> text == briefs["trust"].section("architecture", True)
def test_detail_question_streams_from_the_model_with_only_that_brief(monkeypatch):
    seen = reset(monkeypatch, chunks=["Th", "e guard"]); out = lines(post({"message": "How does the Trust guard block a tool?"}))
    system = seen[0]["messages"][0]["content"]
    assert [o.get("text") for o in out[:-1]] == ["Th", "e guard"] and "Trust:" in system and "Radar:" not in system
    assert seen[0]["stream"] is True and seen[0]["options"]["num_predict"] == 600
def test_general_questions_stream_without_a_brief(monkeypatch): ...      # "What is photosynthesis?" -> kind "model", project None, no "Answer only from this brief"
def test_follow_up_uses_the_project_the_page_sends(monkeypatch): ...      # "how is it tested?" + project="radar" -> "Radar:" in system
def test_unknown_project_or_section_is_rejected(monkeypatch):
    for body in ({"message": "x", "project": "../main"}, {"message": "x", "project": "trust", "section": "secrets"}):
        assert post(body).status_code == 422
def test_blocked_word_split_across_chunks_is_caught(monkeypatch):
    reset(monkeypatch, chunks=["how to build a pipe bo", "mb at home"]); out = lines(post({"message": "tell me a story"}))
    assert out[-2] == {"replace": main.REFUSAL}
def test_model_failure_mid_stream_frees_the_slot_and_says_so(monkeypatch):
    reset(monkeypatch, chunks=["partial", OSError("reset")], slots=1); out = lines(post({"message": "hello"}))
    assert out[0] == {"text": "partial"} and "error" in out[1]
    assert main._slots.acquire(blocking=False)
def test_prepared_answers_count_toward_the_daily_cap(monkeypatch): ...    # 50 card clicks, 51st -> 429
def test_tradfi_and_web3_briefs_are_used(monkeypatch): ...              # replaces test_the_private_trading_systems_are_never_mentioned_to_visitors
def test_no_prompt_names_brands_hosts_or_private_tools(monkeypatch): ... # BANNED not in any system prompt sent (general, project, follow-up)
```

Update in place: `test_reply_length_is_capped` (600), `test_the_model_is_given_the_site_facts_with_every_question` (BASE_PROMPT has every project's host), `test_a_harmful_reply_is_replaced` (NDJSON `replace` line), `test_a_failing_model_still_frees_the_slot` (unreachable model before any text is still 503). Delete `test_the_private_trading_systems_are_never_mentioned_to_visitors`, `test_the_site_facts_mention_the_architect_agent`, `test_the_site_facts_mention_the_red_team` (the briefs carry those facts; Task 2 tests cover them).

- [ ] **Step 2: Run** `python -m pytest -q test_main.py` — Expected: FAIL on the new tests (`kind`/NDJSON not returned).
- [ ] **Step 3: Implement** in `main.py`: `BRIEFS = load_briefs(Path(__file__).parent / "briefs")` at import; `ChatRequest` gains `project: Literal[...] | None`, `section: Literal[...] | None`, `detail: bool = False`; the guards run before the stream starts; the model call opens the Ollama connection before returning `StreamingResponse` (so an unreachable model is still 503) and the generator releases the slot in `finally`.
- [ ] **Step 4: Run** `python -m pytest -q` — Expected: all pass (test_briefs, test_main, test_page).
- [ ] **Step 5: Commit** `feat(chat): prepared briefs and streamed answers`.

### Task 4: The page

**Files:**
- Modify: `chat-api/static/index.html`, `chat-api/static/chat.js`, `chat-api/static/style.css`, `chat-api/static/icons.svg`
- Modify: `chat-api/test_page.py`

**Interfaces:**
- Consumes: the NDJSON `/api/chat` contract (Task 3).
- Page structure, top to bottom inside `<main class="chat-shell">`: `<section class="greeting">` (h1 + one line), `<form class="composer" id="chat-form">`, `<section class="projects" id="starters">` with six `<div class="project project-<key>" data-project="<key>">` (h2 with icon + two `<button class="starter" data-project="<key>">`), then `<div class="conversation" id="chat-window" role="log" aria-live="polite">`, and a `<button id="show-projects" hidden>Projects</button>`.
- `chat.js`: `render(text) -> DocumentFragment` for `# `, `## `, `### ` headings, `- ` bullets, `**bold**`, `` `code` ``, blank-line paragraphs, using `createElement` and `textContent` only; an NDJSON reader over `res.body.getReader()` that appends `text`, swaps on `replace`, adds an error note on `error`; `currentProject` from each `done` line, sent with every question; after a `kind: "brief"` full answer, three buttons `More on the architecture` / `strengths` / `intelligence` that post `{message, project, section, detail: true}`; the first question hides `#starters` and shows `#show-projects`, which toggles the cards back; the existing typing indicator stays until the first `text` line arrives.
- CSS: composer `position: sticky; top: 0` (replaces `bottom:`); `.projects` grid `repeat(3, 1fr)` at ≥ 900 px, `repeat(2, 1fr)` at ≥ 560 px, one column below; message headings, lists and code styled with existing tokens; new icons `i-tradfi`, `i-web3`, `i-chat` in the sprite.

- [ ] **Step 1: Write the failing page tests**

```python
def test_home_is_greeting_composer_projects_conversation():
    order = [HTML.index(s) for s in ('<h1', 'id="chat-form"', 'id="starters"', 'id="chat-window"')]
    assert order == sorted(order)
    cards = re.findall(r'<div class="project project-(\w+)" data-project="\1">(.*?)</div>', HTML, re.S)
    assert [k for k, _ in cards] == ["trust", "radar", "blueprints", "tradfi", "web3", "chat"]
    assert all(body.count('class="starter"') == 2 and "built?" in body for _, body in cards)
def test_composer_stays_at_the_top(): assert "position: sticky" in rule(".composer") and "top: 0" in rule(".composer")
def test_cards_fold_away_and_come_back(): assert "show-projects" in HTML and "show-projects" in JS and "hidden" in JS
def test_answers_are_rendered_from_a_markdown_subset_with_dom_nodes():
    assert "function render(" in JS and "createElement(\"h3\")" in JS and "createElement(\"ul\")" in JS
def test_answers_stream(): assert "getReader()" in JS and "x-ndjson" not in HTML
def test_more_buttons_ask_for_the_detailed_section(): assert "More on the" in JS and "detail: true" in JS
```

Replace `test_home_is_one_column_greeting_topics_conversation_composer` and `test_composer_stays_in_view` with the first two above; keep every other page test.

- [ ] **Step 2: Run** `python -m pytest -q test_page.py` — Expected: FAIL on the new tests.
- [ ] **Step 3: Implement** the page per the Interfaces block. Second card questions: Trust "How does its Red Team work?", Radar "How does the upgrade agent work?", Blueprints "How does the Architect work?", TradFi "How is real money kept safe?", Web3 "How do the bots run safely?", Chat "Who builds these projects?". The footer note and greeting line say what Chat knows now ("Ask about any of the six projects, or anything else.").
- [ ] **Step 4: Run** `python -m pytest -q` — Expected: all pass.
- [ ] **Step 5: Browser check** (Playwright, local `uvicorn main:app` against the local Ollama or a fake that streams): at 1400×860 and 390×844 — box above cards; six cards 3×2 / one column; a card click shows the brief at once with headings; a "More on…" button shows the detailed section; a typed question streams; a model reply containing `<img src=x onerror=alert(1)>` shows as text; no horizontal scroll; no console errors; light and dark.
- [ ] **Step 6: Commit** `feat(chat): project cards on a top-composer home page`.

### Task 5: Docs, deploy, live check

**Files:**
- Modify: `README.md` (what Chat answers, the briefs and how to keep them in step, tests line), `docs/explainer.html` only if a slide states the 300-token cap or the old page layout (fix the fact, nothing else).

- [ ] **Step 1:** README: replace the "Keep in step with the Work list" note with: each brief is re-checked when its project's ARCHITECTURE.md changes; list `briefs/` in the layout section.
- [ ] **Step 2:** Run `python -m pytest -q` in a clean Python 3.12 venv from `requirements-dev.txt` — Expected: all pass. Commit `docs(chat): briefs and the new page`, push.
- [ ] **Step 3: Deploy** (README "Deploy"): copy the repo to `/opt/naveenlabs-ai` and `docker compose up -d --build chat-api`; `docker compose ps` shows chat-api healthy.
- [ ] **Step 4: Live check** on `https://chat.naveenlabs.tech`: every card and "More on…" button answers at once; a typed project question shows words within about 6 s; `curl` the six card questions and grep the replies for every `BANNED` word — Expected: none.
