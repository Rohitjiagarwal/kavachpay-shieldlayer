"""Tool rules are enforced in code, not in the prompt. These prove it."""
from __future__ import annotations

from sqlalchemy import select

from app import db
from app.tools import ToolContext, call_tool


def _ctx(customer_id: int):
    return ToolContext(session_id="t", customer_id=customer_id, confirmed_tokens=set())


def _order_for(customer_id: int, status: str | None = None):
    with db.Session() as s:
        q = select(db.Order).where(db.Order.customer_id == customer_id)
        for o in s.scalars(q).all():
            if status is None or o.status == status:
                return o.id, o.customer_id
    return None, None


def test_get_order_of_another_customer_is_not_found():
    # find an order NOT owned by customer 1
    with db.Session() as s:
        other = s.scalars(select(db.Order).where(db.Order.customer_id != 1)).first()
    res = call_tool(_ctx(1), "get_order", {"order_id": other.id})
    assert res.ok is False
    assert "not found" in res.data["error"]


def test_refund_over_limit_is_not_auto_approved():
    oid, cust = _order_for_delivered()
    res = call_tool(_ctx(cust), "request_refund",
                    {"order_id": oid, "amount_usd": 200.01, "reason": "x"})
    assert res.data["result"] == "pending"  # 1 cent over the $200 limit


def test_refund_within_limit_is_approved():
    oid, cust = _order_for_delivered()
    res = call_tool(_ctx(cust), "request_refund",
                    {"order_id": oid, "amount_usd": 50.0, "reason": "x"})
    assert res.data["result"] == "approved"


def test_refund_ignores_model_supplied_customer_id():
    # even if the model passes a customer_id, it is stripped; ownership stands
    with db.Session() as s:
        other = s.scalars(select(db.Order).where(db.Order.customer_id != 1)).first()
    res = call_tool(_ctx(1), "request_refund",
                    {"order_id": other.id, "amount_usd": 10, "reason": "x",
                     "customer_id": other.customer_id})
    assert res.ok is False  # order 'not found' because ctx customer != owner


def test_address_change_requires_confirmation_and_processing():
    oid, cust = _order_for(1, "processing") if _order_for(1, "processing")[0] else _any_processing()
    res = call_tool(_ctx(cust), "update_shipping_address",
                    {"order_id": oid, "address": "New St 1"})
    assert res.ok is False
    assert res.confirm_required is not None  # confirmation token issued


def test_escalation_is_rate_limited():
    ctx = _ctx(3)
    for _ in range(3):
        assert call_tool(ctx, "escalate_to_human", {"summary": "help"}).ok
    assert call_tool(ctx, "escalate_to_human", {"summary": "help"}).ok is False


# helpers ------------------------------------------------------------------- #
def _order_for_delivered():
    """A delivered order within the 30-day auto-refund window."""
    from app.tools import _days_since

    with db.Session() as s:
        for o in s.scalars(select(db.Order).where(db.Order.status == "delivered")).all():
            if _days_since(o.delivered_at) <= 30:
                return o.id, o.customer_id
    raise AssertionError("no delivered order within 30 days in seed data")


def _any_processing():
    with db.Session() as s:
        o = s.scalars(select(db.Order).where(db.Order.status == "processing")).first()
        return o.id, o.customer_id
