import json

import main
from fastapi.testclient import TestClient


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self.body).encode()


def reset(monkeypatch, trust_proxy=False, slots=2):
    main._hits.clear()
    monkeypatch.setattr(main, "TRUST_PROXY", trust_proxy)
    monkeypatch.setattr(main, "_slots", main.threading.BoundedSemaphore(slots))
    seen = []

    def fake_urlopen(req, timeout=0):
        seen.append(json.loads(req.data))
        return FakeResponse({"message": {"content": "hi"}})
    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_reply_length_is_capped(monkeypatch):
    seen = reset(monkeypatch)
    r = TestClient(main.app).post("/api/chat", json={"message": "hello"})
    assert r.status_code == 200 and r.json() == {"reply": "hi"} and seen[0]["options"] == {"num_predict": main.MAX_REPLY_TOKENS}


def test_rate_limit_is_per_visitor_behind_the_proxy(monkeypatch):
    reset(monkeypatch, trust_proxy=True)
    c = TestClient(main.app)
    for _ in range(main.RATE_LIMIT):
        assert c.post("/api/chat", json={"message": "a"}, headers={"x-forwarded-for": "1.1.1.1"}).status_code == 200
    assert c.post("/api/chat", json={"message": "a"}, headers={"x-forwarded-for": "1.1.1.1"}).status_code == 429
    assert c.post("/api/chat", json={"message": "a"}, headers={"x-forwarded-for": "2.2.2.2"}).status_code == 200      # someone else is unaffected
    assert c.post("/api/chat", json={"message": "a"}, headers={"x-forwarded-for": "9.9.9.9, 3.3.3.3"}).status_code == 200  # spoofed left entries are ignored


def test_too_many_at_once_get_a_retry_after(monkeypatch):
    reset(monkeypatch, slots=1)
    assert main._slots.acquire(blocking=False)                 # a generation is already running
    r = TestClient(main.app).post("/api/chat", json={"message": "hello"})
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
    main._slots.release()
    assert TestClient(main.app).post("/api/chat", json={"message": "hello"}).status_code == 200


def test_a_failing_model_still_frees_the_slot(monkeypatch):
    reset(monkeypatch, slots=1)
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert TestClient(main.app).post("/api/chat", json={"message": "hello"}).status_code == 503
    assert main._slots.acquire(blocking=False)
