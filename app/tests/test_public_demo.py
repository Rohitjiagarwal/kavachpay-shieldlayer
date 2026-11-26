"""Public-demo protections: request budget, visitor keys, per-visitor isolation.

No test here talks to Google: the Gemini clients are replaced with fakes, and
conftest points GEMINI_BASE_URL at a dead local port as a second guard.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import llm, main
from app.llm import GeminiChatModel, LLMResponse
from app.quota import Quota
from app.settings import SETTINGS
from app.tools import ToolContext
from shared import byok

FAKE_KEY = "AIza" + "x" * 35


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setattr(SETTINGS, "public_demo", True)
    monkeypatch.setattr(main, "QUOTA", Quota(per_visitor=4, per_ip=12, per_day=250))
    yield


def _user() -> TestClient:
    c = TestClient(main.app)
    c.post("/api/login", json={"customer_id": 1})
    return c


def _chat(c: TestClient, msg: str, **headers):
    return c.post("/api/chat", json={"message": msg}, headers=headers)


# --------------------------------------------------------------------------- #
# budget
# --------------------------------------------------------------------------- #
def test_four_requests_then_refused(public):
    with _user() as c:
        for i in range(4):
            assert _chat(c, "hi").status_code == 200, i
        r = _chat(c, "hi")
        assert r.status_code == 429
        assert r.json()["detail"]["code"] == "quota"
        st = c.get("/api/demo/status").json()
        assert st["public"] and st["remaining"] == 0 and st["used"] == 4


def test_budget_follows_the_visitor_across_profile_switches(public):
    with _user() as c:
        for _ in range(4):
            _chat(c, "hi")
        c.post("/api/login", json={"customer_id": 0})  # switch to admin, same browser
        assert _chat(c, "hi").status_code == 429


def test_uploads_count_toward_the_budget(public):
    with _user() as c:
        pdf = c.get("/api/samples/payment_receipt.pdf").content
        for _ in range(3):
            _chat(c, "hi")
        with c.stream("POST", "/api/chat/upload",
                      files={"file": ("r.pdf", pdf, "application/pdf")}) as r:
            assert r.status_code == 200
            list(r.iter_lines())
        assert _chat(c, "hi").status_code == 429


def test_local_mode_is_unlimited():
    with _user() as c:
        for _ in range(6):
            assert _chat(c, "hi").status_code == 200
        assert c.get("/api/demo/status").json()["public"] is False


def test_quota_network_and_daily_backstops():
    q = Quota(per_visitor=4, per_ip=2, per_day=100)
    assert q.spend("a", "1.1.1.1").remaining >= 0
    assert q.spend("b", "1.1.1.1").remaining >= 0
    st = q.spend("c", "1.1.1.1")  # new visitor, same network
    assert st.remaining == -1 and st.reason == "network"
    d = Quota(per_visitor=4, per_ip=10, per_day=1)
    d.spend("a", "1")
    assert d.spend("b", "2").reason == "daily"


# --------------------------------------------------------------------------- #
# bring your own key
# --------------------------------------------------------------------------- #
def test_visitor_key_is_not_counted_and_reaches_gemini(public, monkeypatch):
    seen = []

    def fake_complete(self, system, messages, tools=None, tool_results=None, on_progress=None):
        seen.append((self.provider, self._key))
        return LLMResponse(text="Hello from Gemini")

    monkeypatch.setattr(GeminiChatModel, "complete", fake_complete)
    with _user() as c:
        for _ in range(6):  # more than the free budget
            r = _chat(c, "Where is my refund for a failed UPI payment?", **{"X-Gemini-Key": FAKE_KEY})
            assert r.status_code == 200
            assert r.json()["model"]["provider"] == "gemini"
    assert seen and all(k == FAKE_KEY for _, k in seen)
    assert byok.current() is None  # nothing leaks out of the request


def test_malformed_visitor_key_is_rejected(public):
    with _user() as c:
        r = _chat(c, "hi", **{"X-Gemini-Key": "not a key"})
        assert r.status_code == 400


def test_server_uses_stub_without_visitor_key():
    assert llm.chat_model().provider != "gemini"


def test_byok_context_switches_per_request():
    assert byok.current() is None
    with byok.use(FAKE_KEY):
        assert byok.current() == FAKE_KEY
        assert llm.chat_model().provider == "gemini"
    assert byok.current() is None


def test_playground_in_public_demo_never_spends_server_key(public, monkeypatch):
    from shield.layer2_providers import GeminiProvider

    monkeypatch.setattr(
        GeminiProvider,
        "_call_gemini",
        lambda self, m, t, k: pytest.fail("server Gemini key must not be called from /api/playground in public demo"),
    )
    with _user() as c:
        r = c.post("/api/playground", json={"text": "What is my balance?", "source": "user"})
        assert r.status_code == 200
        assert r.json()["verdict"] == "allow"


def test_cross_site_cookies_flag(monkeypatch):
    monkeypatch.setattr(SETTINGS, "cross_site_cookies", True)
    with TestClient(main.app) as c:
        r = c.post("/api/login", json={"customer_id": 1})
        assert r.status_code == 200
        cookies = "\n".join(r.headers.get_list("set-cookie"))
        assert "SameSite=none" in cookies and "Secure" in cookies


def test_gemini_chat_client_request_shape(monkeypatch):
    sent = {}

    class R:
        status_code = 200

        @staticmethod
        def json():
            return {"candidates": [{"content": {"parts": [{"text": "Hi there"}]}}],
                    "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3}}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, body=json, headers=headers)
        return R()

    monkeypatch.setattr("httpx.post", fake_post)
    m = GeminiChatModel("gemini-flash-lite-latest", FAKE_KEY)
    out = m.complete("system", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                                {"role": "user", "content": "c"}, {"role": "user", "content": "d"}])
    assert out.text == "Hi there" and out.usage["output_tokens"] == 3
    assert FAKE_KEY not in sent["url"] and sent["headers"]["x-goog-api-key"] == FAKE_KEY
    roles = [c["role"] for c in sent["body"]["contents"]]
    assert roles == ["user", "model", "user"]  # consecutive user turns merged


# --------------------------------------------------------------------------- #
# isolation between visitors
# --------------------------------------------------------------------------- #
def test_uploads_are_private_to_the_visitor():
    from app.rag.store import get_store

    a, b = _user(), _user()
    with a, b:
        pdf = a.get("/api/samples/payment_receipt.pdf").content
        with a.stream("POST", "/api/chat/upload",
                      files={"file": ("receipt.pdf", pdf, "application/pdf")}) as r:
            final = [json.loads(x) for x in r.iter_lines() if x][-1]
        assert final["chunks_indexed"] >= 1
        docs_a = a.get("/api/documents").json()
        docs_b = b.get("/api/documents").json()
        assert any(d["doc_id"] == final["doc_id"] for d in docs_a)
        assert not any(d["doc_id"] == final["doc_id"] for d in docs_b)
        vid_b = main.sessions.read_cookie(b.cookies.get("session"))["vid"]
        ctx_b = ToolContext(session_id="x", customer_id=1, confirmed_tokens=set(), visitor_id=vid_b)
        hits = get_store().search("payment receipt transaction", customer_id=ctx_b.doc_owner, top=30)
        assert not any(h.chunk.doc_id == final["doc_id"] for h in hits)


def test_live_feed_hides_other_visitors(public):
    a, b = _user(), _user()
    with a, b:
        sid_a = main.sessions.read_cookie(a.cookies.get("session"))["session_id"]
        ok_for_b = main._feed_filter(b.cookies.get("session"))
        ok_for_a = main._feed_filter(a.cookies.get("session"))
        item = {"session_id": sid_a, "text_preview": "a's message"}
        assert ok_for_a(item) and not ok_for_b(item)
        assert ok_for_b({"session_id": None})  # system events (KB indexing) are shared


def test_quarantine_needs_a_session_or_token():
    with TestClient(main.app) as c:
        assert c.get("/api/quarantine").status_code == 401
        assert c.get("/api/quarantine", headers={"X-Admin-Token": SETTINGS.admin_token}).status_code == 200
