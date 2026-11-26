"""Decision recorder + in-process SSE broker for the live feed."""
from __future__ import annotations

import asyncio
from collections import deque

from app import db
from shared.schemas import Decision

_subscribers: list[asyncio.Queue] = []
_recent: deque = deque(maxlen=200)


def record(decision: Decision,
           session_id: str | None = None, customer_id: str | None = None) -> None:
    decision.session_id = session_id or decision.session_id
    decision.customer_id = customer_id or decision.customer_id
    with db.Session() as s:
        s.add(
            db.DecisionRow(
                id=decision.id, ts=decision.ts, source=decision.source.value,
                verdict=decision.verdict.value, layer=decision.layer.value,
                owasp=decision.owasp, score=decision.score, reason=decision.reason[:400],
                judge_provider=decision.judge_provider, judge_model=decision.judge_model,
                latency_ms=decision.latency_ms, cost_usd=decision.cost_usd,
                session_id=decision.session_id,
                customer_id=decision.customer_id, preview=decision.text_preview[:240],
            )
        )
        s.commit()
    payload = decision.model_dump(mode="json")
    _recent.append(payload)
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except Exception:  # noqa: BLE001
            pass


def activity(event: str, **fields) -> None:
    """Publish an agent-activity event (tool call, confirmation, output guard,
    turn summary) to the live feed. In-memory only; not counted in scan stats."""
    import time
    import uuid

    payload = {"kind": "agent", "id": uuid.uuid4().hex, "ts": time.time(), "event": event, **fields}
    _recent.append(payload)
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except Exception:  # noqa: BLE001
            pass


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    if q in _subscribers:
        _subscribers.remove(q)


def recent() -> list[dict]:
    return list(_recent)


def stats(since: float = 0.0) -> dict:

    with db.Session() as s:
        rows = s.query(db.DecisionRow).filter(db.DecisionRow.ts >= since).all()
    blocked_l1 = 0
    blocked_l2 = 0
    blocked_l3 = 0
    blocked_l4 = 0
    checked = len(rows)
    by_layer: dict[str, int] = {}
    by_source: dict[str, dict[str, int]] = {}
    by_owasp: dict[str, int] = {}
    for r in rows:
        if r.verdict == "block":
            if r.layer in ("layer1", "regex"):
                blocked_l1 += 1
            elif r.layer in ("layer2", "classifier"):
                blocked_l2 += 1
            elif r.layer in ("layer3", "judge"):
                blocked_l3 += 1
            elif r.layer == "provenance":
                blocked_l4 += 1
        by_layer[r.layer] = by_layer.get(r.layer, 0) + 1
        src = by_source.setdefault(r.source, {"allow": 0, "block": 0})
        src[r.verdict] = src.get(r.verdict, 0) + 1
        if r.verdict == "block" and r.owasp and r.owasp != "NONE":
            by_owasp[r.owasp] = by_owasp.get(r.owasp, 0) + 1
    total_blocked = blocked_l1 + blocked_l2 + blocked_l3 + blocked_l4
    return {
        "blocked": total_blocked,
        "by_layer": by_layer,
        "by_source": by_source,
        "by_owasp": by_owasp,
        "checked": checked,
        "blocked_layer1": blocked_l1,
        "blocked_layer2": blocked_l2,
        "blocked_layer3": blocked_l3,
        "blocked_provenance": blocked_l4,
        # legacy keys retained for UI/API compatibility
        "blocked_regex": blocked_l1,
        "blocked_classifier": blocked_l2,
        "blocked_judge": blocked_l3,
        "judge_calls": 0,
        "judge_calls_saved": checked,
        "judge_cost_usd": 0.0,
    }
