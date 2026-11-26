"""KavachPay backend (FastAPI), guarded by ShieldLayer."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Cookie,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app import db, events, seed, sessions
from app.pipeline import execute_confirmed, run_turn
from app.quota import Quota
from app.rag.ingest import ingest_file
from app.settings import SETTINGS
from app.tools import ToolContext
from shared import byok

app = FastAPI(title="KavachPay", version="0.3.0")
_origins = [o.strip() for o in SETTINGS.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=SETTINGS.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(SETTINGS.db_path).parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# per-session confirm tokens + escalation counts (in-memory; demo scope)
_confirm_tokens: dict[str, set[str]] = {}
_escalations: dict[str, int] = {}
_history: dict[str, list[dict]] = {}
_pending: dict[str, dict] = {}  # session -> {token, tool, args}
_tainted: dict[str, list[str]] = {}  # session -> uploaded file names (Rule of Two)
_sid_vid: dict[str, str] = {}  # session -> visitor (scopes the live feed)

QUOTA = Quota(SETTINGS.demo_request_limit, SETTINGS.demo_ip_limit, SETTINGS.demo_daily_limit)
_last_turn = 0.0
_last_reset = time.time()

# The two demo profiles. The role is written into the signed session cookie,
# so it can never be changed by what a message says.
ADMIN_ID = 0
DEMO_USER_ID = 1


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    seed.seed_all()  # idempotent
    # The vector store is in-memory, so (re)index the KB on every start.
    seed.ingest_kb()


# --------------------------------------------------------------------------- #
# auth, visitor and budget helpers
# --------------------------------------------------------------------------- #
def current(session: str | None) -> dict:
    data = sessions.read_cookie(session) if session else None
    if not data:
        raise HTTPException(401, "not signed in")
    data.setdefault("role", "user")
    data.setdefault("vid", data["session_id"])
    _sid_vid[data["session_id"]] = data["vid"]
    return data


def require_admin(x_admin_token: str | None) -> None:
    if x_admin_token != SETTINGS.admin_token:
        raise HTTPException(403, "admin token required")


def _ctx(data: dict) -> ToolContext:
    sid = data["session_id"]
    return ToolContext(
        session_id=sid, customer_id=data["customer_id"],
        confirmed_tokens=_confirm_tokens.setdefault(sid, set()),
        escalations=_escalations.get(sid, 0), role=data.get("role", "user"),
        visitor_id=data.get("vid", ""),
    )


def _client_ip(request: Request) -> str:
    if SETTINGS.trust_proxy:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _visitor_key(x_gemini_key: str | None) -> str | None:
    """The visitor's own Gemini key, if they attached one. Never stored or logged."""
    if not x_gemini_key:
        return None
    if not byok.valid(x_gemini_key):
        raise HTTPException(400, "That does not look like a Gemini API key.")
    return x_gemini_key


def _spend(request: Request, data: dict, key: str | None) -> None:
    """Use one free request (public demo only; visitor keys are not counted)."""
    if not SETTINGS.public_demo or key:
        return
    st = QUOTA.spend(data["vid"], _client_ip(request))
    if st.remaining < 0:
        msg = {
            "visitor": f"You've used your {st.limit} free requests.",
            "network": "Your network has used its free requests.",
            "daily": "The live demo's daily budget is used up. It resets at midnight UTC.",
        }.get(st.reason, "Free requests used up.")
        raise HTTPException(429, {"code": "quota", "reason": st.reason, "message": msg})


def _maybe_reset_shared_data() -> None:
    """Every public visitor shares one demo account, so mutations (a blocked UPI,
    a raised dispute) are reseeded once the demo has been idle for a while."""
    global _last_reset
    if not SETTINGS.public_demo:
        return
    now = time.time()
    if now - _last_reset > SETTINGS.demo_reset_minutes * 60 and now - _last_turn > 180:
        _last_reset = now
        seed.reset_data()


# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #
class LoginBody(BaseModel):
    customer_id: int


class ChatBody(BaseModel):
    message: str


class ConfirmBody(BaseModel):
    confirm_token: str


MAX_MESSAGE_CHARS = 2000


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    from app import llm

    return {"status": "ok", "chat_enabled": SETTINGS.chat_enabled(), "parser": SETTINGS.parser,
            "chat_model": llm.describe_chat_model(), "public_demo": SETTINGS.public_demo}


@app.get("/api/demo/status")
def demo_status(request: Request, session: str | None = Cookie(default=None),
                kp_vid: str | None = Cookie(default=None)) -> dict:
    """How many free requests this visitor has left (public demo only)."""
    data = sessions.read_cookie(session) if session else None
    vid = (data or {}).get("vid") or sessions.read_visitor(kp_vid) or "anonymous"
    st = QUOTA.status(vid, _client_ip(request))
    return {"public": SETTINGS.public_demo, "limit": st.limit, "used": st.used,
            "remaining": st.remaining if SETTINGS.public_demo else None, "reason": st.reason,
            "visitor_key_model": SETTINGS.gemini_chat_model}


@app.post("/api/byok/check")
def byok_check(x_gemini_key: str | None = Header(default=None)) -> dict:
    """Check a visitor's key with a metadata call (no tokens are generated).
    Only runs when the visitor presses "Check key" in the UI."""
    import os

    import httpx

    from app.llm import GEMINI_BASE

    key = _visitor_key(x_gemini_key)
    if not key:
        raise HTTPException(400, "no key sent")
    base = (os.environ.get("GEMINI_BASE_URL") or GEMINI_BASE).rstrip("/")
    try:
        r = httpx.get(f"{base}/models/{SETTINGS.gemini_chat_model}",
                      headers={"x-goog-api-key": key}, timeout=8.0)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"could not reach Google: {type(e).__name__}"}
    if r.status_code == 200:
        return {"ok": True, "message": f"Key works with {SETTINGS.gemini_chat_model}."}
    try:
        msg = r.json().get("error", {}).get("message", "")[:160]
    except Exception:  # noqa: BLE001
        msg = ""
    return {"ok": False, "message": f"Google said {r.status_code}: {msg}"}


@app.get("/api/customers")
def customers() -> list[dict]:
    """The two sign-in profiles: one customer and one security admin."""
    with db.Session() as s:
        c = s.get(db.Customer, DEMO_USER_ID)
        user = {"id": DEMO_USER_ID, "role": "user", "name": c.name if c else "Demo customer",
                "email": c.email if c else "", "title": "Customer",
                "blurb": "Chat with Kavi about payments, refunds and fraud. Try the missions."}
    admin = {"id": ADMIN_ID, "role": "admin", "name": "Security Admin", "email": "secops@kavachpay.example",
             "title": "Security admin", "blurb": "Watch every verdict live and use admin-only tools."}
    return [user, admin]


@app.post("/api/login")
def login(body: LoginBody, response: Response, kp_vid: str | None = Cookie(default=None)) -> dict:
    if body.customer_id == ADMIN_ID:
        role, name = "admin", "Security Admin"
    elif body.customer_id == DEMO_USER_ID:
        role = "user"
        _maybe_reset_shared_data()
        with db.Session() as s:
            c = s.get(db.Customer, DEMO_USER_ID)
            name = c.name if c else "Demo customer"
    else:
        raise HTTPException(404, "unknown profile")
    vid = sessions.read_visitor(kp_vid) or uuid.uuid4().hex
    sid = uuid.uuid4().hex
    _sid_vid[sid] = vid
    samesite = "none" if SETTINGS.cross_site_cookies else "lax"
    secure = SETTINGS.cross_site_cookies
    response.set_cookie("kp_vid", sessions.make_visitor(vid), httponly=True,
                        samesite=samesite, secure=secure, max_age=60 * 60 * 24 * 30)
    response.set_cookie("session", sessions.make_cookie(body.customer_id, sid, role, vid),
                        httponly=True, samesite=samesite, secure=secure)
    return {"customer_id": body.customer_id, "name": name, "role": role, "session_id": sid}


def _turn(data: dict, message: str, emit=None) -> dict:
    """Run one chat turn and update the session; returns the API response."""
    global _last_turn
    _last_turn = time.time()
    sid = data["session_id"]
    ctx = _ctx(data)
    with db.Session() as s:
        c = s.get(db.Customer, data["customer_id"])
        name = c.name.split()[0] if c else ("Admin" if ctx.role == "admin" else "there")
    hist = _history.setdefault(sid, [])
    state = run_turn(message[:MAX_MESSAGE_CHARS], ctx, history=hist, customer_name=name, emit=emit,
                     tainted=bool(_tainted.get(sid)))
    _escalations[sid] = ctx.escalations
    if state.confirm:
        # The token is only honoured once the *user* taps Confirm in the UI.
        _pending[sid] = state.confirm
    hist.append({"role": "user", "content": state.clean_message or "[blocked message]"})
    hist.append({"role": "assistant", "content": state.reply})
    del hist[:-12]
    sources = [
        {"id": s_["id"], "title": s_["title"], "page": s_["page"], "heading": s_["heading"]}
        for s_ in state.sources
    ]
    return {
        "reply": state.reply,
        "sources": sources,
        "actions": state.receipts,
        "confirm": state.confirm,
        "blocked": state.blocked,
        "timings": state.timings,
        "intent": state.intent,
        "shield": state.shield,
        "redactions": state.redactions,
        "tools": state.tools_used,
        "model": state.model,
        "output_events": state.output_events,
        "gate": state.gate,
        "tainted": bool(_tainted.get(sid)),
    }


@app.post("/api/chat")
def chat(body: ChatBody, request: Request, session: str | None = Cookie(default=None),
         x_gemini_key: str | None = Header(default=None)) -> dict:
    data = current(session)
    key = _visitor_key(x_gemini_key)
    _spend(request, data, key)
    with byok.use(key):
        return _turn(data, body.message)


@app.post("/api/chat/stream")
def chat_stream(body: ChatBody, request: Request, session: str | None = Cookie(default=None),
                x_gemini_key: str | None = Header(default=None)):
    """Same turn as /api/chat, streamed as NDJSON progress events.

    Each line is one event as it really happens in the pipeline (step start/done,
    funnel layer, tool call, model progress), then {"type": "final", ...} with the
    full response. The reply text is sent only in "final", after output checks ran.
    """
    import queue
    import threading

    data = current(session)
    key = _visitor_key(x_gemini_key)
    _spend(request, data, key)
    q: queue.Queue = queue.Queue()
    t_start = time.perf_counter()

    def emit(ev: dict) -> None:
        q.put({**ev, "t": round((time.perf_counter() - t_start) * 1000, 1)})

    def work() -> None:
        try:
            with byok.use(key):  # context variables do not cross threads by themselves
                q.put({"type": "final", **_turn(data, body.message, emit=emit)})
        except Exception as e:  # noqa: BLE001
            q.put({"type": "error", "message": str(e)[:200]})
        finally:
            q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def gen():
        while True:
            item = q.get()
            if item is None:
                return
            yield json.dumps(item, default=str) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/shield/info")
def shield_info() -> dict:
    """What is guarding the app right now: 3-Layer Zero-Judge security pipeline."""
    from app.scanner import get_scanner
    from shield.config import layer2_provider_label

    sc = get_scanner()
    l2_label = layer2_provider_label()
    try:
        f = sc._inprocess()
        cache = {"hits": f.cache.hits, "misses": f.cache.misses}
        fail = {"chat": f.chat_fail_mode, "document": f.doc_fail_mode}
    except Exception:  # noqa: BLE001
        cache, fail = {}, {}
    return {
        "pipeline": "3-layer-zero-judge",
        "scanner_mode": sc.mode,
        "layer1": "3-stage-deterministic-funnel",
        "layer2": l2_label,
        "layer3": "deterministic-policy-gate",
        "cache": cache,
        "fail_modes": fail,
    }


@app.post("/api/chat/confirm")
def chat_confirm(body: ConfirmBody, session: str | None = Cookie(default=None)) -> dict:
    data = current(session)
    sid = data["session_id"]
    pend = _pending.get(sid)
    if not pend or pend.get("token") != body.confirm_token:
        raise HTTPException(400, "nothing to confirm")
    res = execute_confirmed(_ctx(data), pend, tainted=bool(_tainted.get(sid)))
    _pending.pop(sid, None)
    msg = res.receipt or ("Done." if res.ok else f"Couldn't complete: {res.data}")
    _history.setdefault(sid, []).append({"role": "assistant", "content": f"(action confirmed) {msg}"})
    return {"ok": res.ok, "message": msg}


@app.post("/api/chat/reset")
def chat_reset(session: str | None = Cookie(default=None)) -> dict:
    data = current(session)
    _history.pop(data["session_id"], None)
    _tainted.pop(data["session_id"], None)
    _pending.pop(data["session_id"], None)
    return {"ok": True}


@app.get("/api/me")
def me(session: str | None = Cookie(default=None)) -> dict:
    data = current(session)
    if data.get("role") == "admin":
        return {"role": "admin", "name": "Security Admin", "account": None, "transactions": [],
                "tainted": bool(_tainted.get(data["session_id"]))}
    from app.tools import get_account_summary, get_recent_transactions

    ctx = _ctx(data)
    acct = get_account_summary(ctx).data
    txns = get_recent_transactions(ctx, limit=6).data
    return {"role": "user", "account": acct, "transactions": txns,
            "tainted": bool(_tainted.get(data["session_id"]))}


def _max_upload_bytes() -> int:
    return int(SETTINGS.upload_max_mb * 1024 * 1024)


def _process_upload(path: str, owner: str, title: str, doc_id: str, customer_id: str,
                    key: str | None = None) -> None:
    with byok.use(key):
        res = ingest_file(path, owner=owner, doc_title=title, doc_id=doc_id)
    for d in res.decisions:
        events.record(d, customer_id=customer_id)


@app.post("/api/documents")
async def upload(background: BackgroundTasks, file: UploadFile, request: Request,
                 session: str | None = Cookie(default=None),
                 x_gemini_key: str | None = Header(default=None)) -> dict:
    data = current(session)
    key = _visitor_key(x_gemini_key)
    _spend(request, data, key)
    raw = await file.read()
    if len(raw) > _max_upload_bytes():
        raise HTTPException(413, f"file too large ({SETTINGS.upload_max_mb:g} MB limit)")
    doc_id = uuid.uuid4().hex[:16]
    name = Path(file.filename or "upload").name
    dest = UPLOAD_DIR / f"{doc_id}_{name}"
    dest.write_bytes(raw)
    owner = _ctx(data).doc_owner
    with db.Session() as s:
        s.add(db.Document(id=doc_id, owner=owner, filename=name,
                          sha256="", status="processing", visibility="private", progress="queued"))
        s.commit()
    background.add_task(_process_upload, str(dest), owner, name, doc_id, str(data["customer_id"]), key)
    return Response(
        content=json.dumps({"doc_id": doc_id, "status": "processing"}),
        media_type="application/json", status_code=202,
    )


ALLOWED_UPLOADS = {".pdf", ".docx", ".txt", ".md"}


@app.post("/api/chat/upload")
async def chat_upload(file: UploadFile, request: Request, session: str | None = Cookie(default=None),
                      x_gemini_key: str | None = Header(default=None)):
    """Attach a file in chat. Streams the scan as NDJSON: every chunk goes through
    L1-L3 before it can reach the knowledge base; flagged chunks are quarantined.
    Afterwards the session is marked as having read untrusted content (Rule of Two)."""
    import queue
    import threading

    data = current(session)
    if data.get("role") == "admin":
        raise HTTPException(403, "uploads are for the customer profile")
    name = Path(file.filename or "upload").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_UPLOADS:
        raise HTTPException(415, f"allowed: {', '.join(sorted(ALLOWED_UPLOADS))}")
    raw = await file.read()
    if len(raw) > _max_upload_bytes():
        raise HTTPException(413, f"file too large ({SETTINGS.upload_max_mb:g} MB limit)")
    key = _visitor_key(x_gemini_key)
    _spend(request, data, key)
    doc_id = uuid.uuid4().hex[:16]
    dest = UPLOAD_DIR / f"{doc_id}_{name}"
    dest.write_bytes(raw)
    owner, sid = _ctx(data).doc_owner, data["session_id"]
    customer = str(data["customer_id"])
    q: queue.Queue = queue.Queue()
    t0 = time.perf_counter()

    def emit(ev: dict) -> None:
        q.put({"type": "upload", **ev, "t": round((time.perf_counter() - t0) * 1000, 1)})

    def work() -> None:
        try:
            emit({"stage": "received", "filename": name, "bytes": len(raw)})
            with byok.use(key):
                res = ingest_file(str(dest), owner=owner, doc_title=name, doc_id=doc_id,
                                  on_event=emit, dedupe=False)
            for d in res.decisions:
                events.record(d, session_id=sid, customer_id=customer)
            _tainted.setdefault(sid, []).append(name)
            _history.setdefault(sid, []).append({
                "role": "assistant",
                "content": f"(the user attached '{name}': {res.chunks_indexed} of {res.chunks_total} sections "
                           f"passed the security scan, {res.chunks_quarantined} quarantined)"})
            events.activity("upload", session_id=sid, customer_id=customer, filename=name,
                            status=res.status, detail=f"{res.chunks_indexed}/{res.chunks_total} indexed, "
                                                      f"{res.chunks_quarantined} quarantined")
            q.put({"type": "final", "doc_id": doc_id, "filename": name, "status": res.status,
                   "chunks_total": res.chunks_total, "chunks_indexed": res.chunks_indexed,
                   "chunks_quarantined": res.chunks_quarantined, "tainted": True})
        except Exception as e:  # noqa: BLE001
            q.put({"type": "error", "message": f"could not read this file: {str(e)[:160]}"})
        finally:
            q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def gen():
        while (item := q.get()) is not None:
            yield json.dumps(item, default=str) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/samples")
def list_samples() -> list[dict]:
    from app.samples import SAMPLES

    return [{"name": k, "description": v, "url": f"/api/samples/{k}"} for k, v in SAMPLES.items()]


@app.get("/api/samples/{name}")
def get_sample(name: str) -> Response:
    from app.samples import SAMPLES, build

    if name not in SAMPLES:
        raise HTTPException(404, "no such sample")
    return Response(content=build(name), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/documents")
def list_documents(session: str | None = Cookie(default=None)) -> list[dict]:
    data = current(session)
    with db.Session() as s:
        rows = s.scalars(select(db.Document).where(db.Document.owner == _ctx(data).doc_owner)).all()
        return [{"doc_id": d.id, "filename": d.filename, "status": d.status,
                 "chunks_indexed": d.chunks_indexed, "chunks_total": d.chunks_total,
                 "progress": d.progress, "parsed_by": d.parsed_by} for d in rows]


@app.get("/api/documents/{doc_id}")
def document_status(doc_id: str, session: str | None = Cookie(default=None)) -> dict:
    data = current(session)
    with db.Session() as s:
        d = s.get(db.Document, doc_id)
        if not d or d.owner != _ctx(data).doc_owner:
            raise HTTPException(404, "not found")
        return {"doc_id": d.id, "status": d.status, "progress": d.progress,
                "parsed_by": d.parsed_by, "chunks_indexed": d.chunks_indexed,
                "chunks_total": d.chunks_total}


def _feed_filter(session: str | None):
    """Public demo: a visitor sees their own events plus system events (KB
    indexing), never another visitor's messages. Locally: everything."""
    if not SETTINGS.public_demo:
        return lambda item: True
    data = sessions.read_cookie(session) if session else None
    vid = (data or {}).get("vid")

    def ok(item: dict) -> bool:
        sid = item.get("session_id")
        return sid is None or (vid is not None and _sid_vid.get(sid) == vid)
    return ok


@app.get("/api/events")
async def event_stream(session: str | None = Cookie(default=None)):
    ok = _feed_filter(session)

    async def gen():
        q = events.subscribe()
        try:
            for item in events.recent():
                if ok(item):
                    yield f"data: {json.dumps(item)}\n\n"
            while True:
                item = await q.get()
                if ok(item):
                    yield f"data: {json.dumps(item)}\n\n"
        finally:
            events.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/quarantine")
def quarantine(x_admin_token: str | None = Header(default=None),
               session: str | None = Cookie(default=None)) -> list[dict]:
    """Quarantined chunks. The admin token sees everything. A signed-in session
    sees its own visitor's uploads (public demo), or everything when it is the
    admin profile on a local install."""
    owner_suffix: str | None = None
    if not (x_admin_token and x_admin_token == SETTINGS.admin_token):
        data = current(session)
        if SETTINGS.public_demo or data.get("role") != "admin":
            owner_suffix = f":{data['vid']}"
    with db.Session() as s:
        rows = s.scalars(select(db.Quarantine)).all()
        if owner_suffix is not None:
            mine = {d.id for d in s.scalars(select(db.Document)).all() if d.owner.endswith(owner_suffix)}
            rows = [q for q in rows if q.doc_id in mine]
        return [{"id": q.id, "doc_id": q.doc_id, "chunk_id": q.chunk_id,
                 "text": q.text[:600], "score": q.score, "layer": q.layer,
                 "owasp": q.owasp, "reason": q.reason, "hidden_text": bool(q.hidden_text)}
                for q in rows]


class PlaygroundBody(BaseModel):
    text: str
    source: str = "user"


@app.post("/api/playground")
def playground(body: PlaygroundBody, request: Request, session: str | None = Cookie(default=None),
               x_gemini_key: str | None = Header(default=None)) -> dict:
    """Run one text through the 3-layer zero-judge pipeline (L1 funnel -> L2 intent extractor -> L3 policy gate)."""
    from contextlib import nullcontext

    from app.scanner import get_scanner
    from shared.schemas import ScanItem, Source
    from shield.policy_gate import AuthContext

    data = current(session)
    key = _visitor_key(x_gemini_key)
    layers = None
    if SETTINGS.public_demo and not key:
        if not QUOTA.throttle(f"lab:{data['vid']}", 20, 60):
            raise HTTPException(429, {"code": "throttle", "message": "Slow down: 20 scans per minute."})
    scanner = get_scanner()
    src = Source(body.source) if body.source in ("user", "document", "tool") else Source.user
    actx = AuthContext(customer_id=str(data.get("customer_id", "0")), role=data.get("role", "user"))
    ctx_mgr = byok.use(key) if key else (byok.disable_server_key() if SETTINGS.public_demo else nullcontext())
    with ctx_mgr:
        d = scanner.scan([ScanItem(text=body.text[:MAX_MESSAGE_CHARS], source=src)], auth_context=actx, layers=layers)[0]
    events.record(d, session_id=data["session_id"], customer_id=str(data["customer_id"]))
    return {
        "verdict": d.verdict.value, "layer": d.layer.value, "owasp": d.owasp,
        "score": d.score, "raw_score": d.raw_score, "reason": d.reason,
        "rule_id": d.rule_id, "latency_ms": d.latency_ms,
        "layer2_extraction": d.layer2_extraction.model_dump() if d.layer2_extraction else None,
        "policy_result": d.policy_result.model_dump() if d.policy_result else None,
    }


@app.get("/api/scorecard")
def scorecard() -> dict:
    p = Path(__file__).resolve().parents[1] / "attacks" / "results" / "latest.json"
    if not p.exists():
        return {"available": False}
    return {"available": True, **json.loads(p.read_text(encoding="utf-8"))}


@app.get("/api/stats")
def stats(since: float = 0.0) -> dict:
    return events.stats(since)


@app.post("/api/admin/reset")
def admin_reset(x_admin_token: str | None = Header(default=None)) -> dict:
    require_admin(x_admin_token)
    seed.reset_data()
    seed.ingest_kb()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Static dashboard (single-container deploy). Mounted last so /api wins.
# --------------------------------------------------------------------------- #
if SETTINGS.dashboard_dir and Path(SETTINGS.dashboard_dir).is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=SETTINGS.dashboard_dir, html=True), name="dashboard")
else:
    @app.api_route("/", methods=["GET", "HEAD"])
    def root_health() -> dict:
        return {"status": "ok", "service": "kavachpay-api"}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
