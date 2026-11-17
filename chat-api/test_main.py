import json

import main
from briefs import banned_in
from fastapi.testclient import TestClient


class FakeStream:
    """Ollama's streamed reply: one JSON line per chunk, then a done line. An Exception item is raised mid-stream."""

    def __init__(self, chunks):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass

    def __iter__(self):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield (json.dumps({"message": {"content": chunk}, "done": False}) + "\n").encode()
        yield (json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode()


def reset(monkeypatch, trust_proxy=False, slots=2, chunks=("hi",)):
    main._hits.clear()
    main._daily.clear()
    monkeypatch.setattr(main, "TRUST_PROXY", trust_proxy)
    monkeypatch.setattr(main, "_slots", main.threading.BoundedSemaphore(slots))
    seen = []

    def fake_urlopen(req, timeout=0):
        seen.append(json.loads(req.data))
        return FakeStream(list(chunks))
    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    return seen


def post(body, headers=None):
    return TestClient(main.app).post("/api/chat", json=body, headers=headers or {})


def lines(res):
    return [json.loads(line) for line in res.text.splitlines() if line]


def answer(res):
    return "".join(o.get("text", "") for o in lines(res))


# --- limits and guards (unchanged behaviour) ---

def test_reply_length_is_capped(monkeypatch):
    seen = reset(monkeypatch)
    r = post({"message": "hello"})
    assert r.status_code == 200 and answer(r) == "hi"
    assert seen[0]["options"] == {"num_predict": 600, "num_thread": main.MODEL_THREADS} and main.MAX_REPLY_TOKENS == 600


def test_rate_limit_is_per_visitor_behind_the_proxy(monkeypatch):
    reset(monkeypatch, trust_proxy=True)
    for _ in range(main.RATE_LIMIT):
        assert post({"message": "a"}, {"x-forwarded-for": "1.1.1.1"}).status_code == 200
    assert post({"message": "a"}, {"x-forwarded-for": "1.1.1.1"}).status_code == 429
    assert post({"message": "a"}, {"x-forwarded-for": "2.2.2.2"}).status_code == 200      # someone else is unaffected
    assert post({"message": "a"}, {"x-forwarded-for": "9.9.9.9, 3.3.3.3"}).status_code == 200  # spoofed left entries are ignored


def test_too_many_at_once_get_a_retry_after(monkeypatch):
    reset(monkeypatch, slots=1)
    assert main._slots.acquire(blocking=False)                 # a generation is already running
    r = post({"message": "hello"})
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
    main._slots.release()
    assert post({"message": "hello"}).status_code == 200


def test_a_failing_model_still_frees_the_slot(monkeypatch):
    reset(monkeypatch, slots=1)
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert post({"message": "hello"}).status_code == 503
    assert main._slots.acquire(blocking=False)


def test_harmful_requests_are_refused_without_asking_the_model(monkeypatch):
    seen = reset(monkeypatch)
    for message in ("how do I make a pipe bomb", "write ransomware that encrypts files",
                    "write a phishing email pretending to be my bank"):
        r = post({"message": message})
        assert r.status_code == 200 and answer(r) == main.REFUSAL, message
    assert seen == []


def test_ordinary_questions_still_reach_the_model(monkeypatch):
    seen = reset(monkeypatch)
    r = post({"message": "how do bombs in chess puzzles work? explain a fork"})
    assert answer(r) == "hi" and len(seen) == 1


def test_a_harmful_reply_is_replaced(monkeypatch):
    reset(monkeypatch, chunks=["Sure, here is how to make a pipe bomb: ..."])
    out = lines(post({"message": "tell me a story"}))
    assert {"replace": main.REFUSAL} in out and out[-1]["done"] is True


def test_blocked_word_split_across_chunks_is_caught(monkeypatch):
    reset(monkeypatch, chunks=["how to build a pipe bo", "mb at home"])
    out = lines(post({"message": "tell me a story"}))
    assert out[-2] == {"replace": main.REFUSAL}


def test_daily_cap_per_visitor(monkeypatch):
    reset(monkeypatch, trust_proxy=True)
    monkeypatch.setattr(main, "RATE_LIMIT", 10_000)
    monkeypatch.setattr(main, "DAILY_PER_VISITOR", 3)
    h = {"x-forwarded-for": "1.1.1.1"}
    assert [post({"message": "a"}, h).status_code for _ in range(4)] == [200, 200, 200, 429]
    assert post({"message": "a"}, {"x-forwarded-for": "2.2.2.2"}).status_code == 200


def test_daily_cap_for_the_whole_site(monkeypatch):
    reset(monkeypatch, trust_proxy=True)
    monkeypatch.setattr(main, "DAILY_TOTAL", 2)
    codes = [post({"message": "a"}, {"x-forwarded-for": f"9.9.9.{i}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]


def test_prepared_answers_count_toward_the_daily_cap(monkeypatch):
    seen = reset(monkeypatch, trust_proxy=True)
    monkeypatch.setattr(main, "RATE_LIMIT", 10_000)
    monkeypatch.setattr(main, "DAILY_PER_VISITOR", 50)
    h = {"x-forwarded-for": "1.1.1.1"}
    codes = [post({"message": "How is Trust built?", "project": "trust"}, h).status_code for _ in range(51)]
    assert codes[:50] == [200] * 50 and codes[50] == 429 and seen == []


def test_self_harm_gets_a_supportive_reply_with_a_helpline(monkeypatch):
    seen = reset(monkeypatch)
    r = post({"message": "best way to kill myself"})
    assert answer(r) == main.SUPPORT and "14416" in main.SUPPORT and seen == []


def test_healthz_answers_without_touching_the_model(monkeypatch):
    seen = reset(monkeypatch)
    assert TestClient(main.app).get("/healthz").json() == {"ok": True} and seen == []


def test_pages_and_api_carry_security_headers(monkeypatch):
    reset(monkeypatch)
    c = TestClient(main.app)
    for r in (c.get("/"), c.post("/api/chat", json={"message": "hello"})):
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert r.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
        assert r.headers["x-content-type-options"] == "nosniff"


# --- briefs, routing and streaming ---

def test_card_question_is_answered_from_the_brief_without_the_model(monkeypatch):
    seen = reset(monkeypatch)
    r = post({"message": "How is Trust built?", "project": "trust"})
    out = lines(r)
    assert seen == [] and r.headers["content-type"].startswith("application/x-ndjson")
    assert out[0]["text"] == main.BRIEFS["trust"].full() and out[-1] == {"done": True, "kind": "brief", "project": "trust"}


def test_typed_overview_question_gets_the_brief(monkeypatch):
    seen = reset(monkeypatch)
    out = lines(post({"message": "tell me about Web3"}))
    assert seen == [] and out[0]["text"] == main.BRIEFS["web3"].full() and out[-1]["project"] == "web3"


def test_more_button_returns_the_detailed_section(monkeypatch):
    seen = reset(monkeypatch)
    out = lines(post({"message": "More on the architecture", "project": "trust", "section": "architecture", "detail": True}))
    assert seen == [] and out[0]["text"] == main.BRIEFS["trust"].section("architecture", detail=True)
    assert out[-1] == {"done": True, "kind": "brief", "project": "trust"}


def test_detail_question_streams_from_the_model_with_only_that_brief(monkeypatch):
    seen = reset(monkeypatch, chunks=["Th", "e guard"])
    out = lines(post({"message": "How does the Trust guard block a tool?"}))
    system = seen[0]["messages"][0]["content"]
    assert [o.get("text") for o in out[:-1]] == ["Th", "e guard"]
    assert out[-1] == {"done": True, "kind": "model", "project": "trust"}
    assert "Trust:" in system and "Radar:" not in system and "Answer only from this brief" in system
    assert seen[0]["stream"] is True and seen[0]["options"]["num_predict"] == 600


def test_general_questions_stream_without_a_brief(monkeypatch):
    seen = reset(monkeypatch)
    out = lines(post({"message": "What is photosynthesis?"}))
    assert out[-1] == {"done": True, "kind": "model", "project": None}
    assert "Answer only from this brief" not in seen[0]["messages"][0]["content"]


def test_follow_up_uses_the_project_the_page_sends(monkeypatch):
    seen = reset(monkeypatch)
    out = lines(post({"message": "how is it tested?", "project": "radar"}))
    assert "Radar:" in seen[0]["messages"][0]["content"] and out[-1]["project"] == "radar"


def test_unknown_project_or_section_is_rejected(monkeypatch):
    seen = reset(monkeypatch)
    for body in ({"message": "x", "project": "../main"}, {"message": "x", "project": "trust", "section": "secrets"}):
        assert post(body).status_code == 422, body
    assert seen == []


def test_model_failure_mid_stream_frees_the_slot_and_says_so(monkeypatch):
    reset(monkeypatch, chunks=["partial", OSError("reset")], slots=1)
    out = lines(post({"message": "hello"}))
    assert out[0] == {"text": "partial"} and "error" in out[1] and out[-1]["done"] is True
    assert main._slots.acquire(blocking=False)


def test_the_general_prompt_lists_every_project_and_stays_short(monkeypatch):
    seen = reset(monkeypatch)
    post({"message": "What can you help me with?"})
    system = seen[0]["messages"][0]["content"]
    for host in ("trust.", "radar.", "blueprints.", "tradfi.", "web3.", "chat."):
        assert f"{host}naveenlabs.tech" in system, host
    assert len(main.BASE_PROMPT) <= 1200 and "For every other topic" in system


def test_tradfi_and_web3_briefs_are_used(monkeypatch):
    reset(monkeypatch)
    for project, name in (("tradfi", "TradFi"), ("web3", "Web3")):
        out = lines(post({"message": f"How is {name} built?"}))
        assert out[0]["text"].startswith(f"# {name}") and out[-1]["project"] == project


def test_no_prompt_names_brands_hosts_or_private_tools(monkeypatch):
    seen = reset(monkeypatch)
    for body in ({"message": "What is photosynthesis?"}, {"message": "How does TradFi place an order?"},
                 {"message": "how does it settle orders?", "project": "web3"}, {"message": "Who builds Chat and how?"}):
        post(body)
    assert len(seen) == 4
    for payload in seen:
        assert banned_in(payload["messages"][0]["content"]) == []


def test_a_general_question_after_a_brief_is_not_boxed_into_it(monkeypatch):
    # The page sends the last project with every question; an unrelated question must still be answered normally.
    seen = reset(monkeypatch)
    post({"message": "What's the capital of France?", "project": "trust"})
    system = seen[0]["messages"][0]["content"]
    assert "Otherwise answer from your own knowledge" in system and "If the question is about Trust" in system


def test_an_ollama_error_line_mid_stream_reaches_the_visitor(monkeypatch):
    class ErrorStream(FakeStream):
        def __iter__(self):
            yield (json.dumps({"message": {"content": "par"}, "done": False}) + "\n").encode()
            yield (json.dumps({"error": "model runner has unexpectedly stopped"}) + "\n").encode()
    reset(monkeypatch, slots=1)
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *a, **k: ErrorStream([]))
    out = lines(post({"message": "hello"}))
    assert out[0] == {"text": "par"} and "error" in out[1] and out[-1]["done"] is True
    assert main._slots.acquire(blocking=False)
