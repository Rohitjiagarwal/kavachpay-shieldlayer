"""The chatbot's tools. Every rule is enforced in code, never in the prompt, so
a tricked model still cannot do damage. This is the main defence against
excessive agency (LLM06) and identity abuse (ASI03).

The customer id always comes from the session, never from an argument the model
supplies. Each call is logged to `tool_calls` for the audit trail (ASI10).
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app import db


@dataclass
class ToolContext:
    session_id: str
    customer_id: int
    # one-time confirmation tokens the UI has issued (ASI09)
    confirmed_tokens: set[str]
    escalations: int = 0
    role: str = "user"  # from the signed session: "user" or "admin"
    visitor_id: str = ""  # the browser (kp_vid cookie); scopes uploaded files

    @property
    def doc_owner(self) -> str:
        """Owner key for uploaded files. Every public-demo visitor signs in as the
        same demo customer, so files are scoped to customer + visitor: one
        visitor's upload can never be retrieved in another visitor's chat."""
        return f"{self.customer_id}:{self.visitor_id}" if self.visitor_id else str(self.customer_id)


@dataclass
class ToolResult:
    ok: bool
    data: Any
    receipt: str | None = None  # human-readable action receipt for the UI
    confirm_required: dict | None = None  # {token, summary} when confirmation needed


REFUND_AUTO_LIMIT = 200.0
REFUND_WINDOW_DAYS = 30
ESCALATION_LIMIT = 3


def _log(ctx: ToolContext, tool: str, args: dict, allowed: bool, result: str) -> None:
    with db.Session() as s:
        s.add(
            db.ToolCall(
                ts=time.time(),
                session_id=ctx.session_id,
                customer_id=str(ctx.customer_id),
                tool=tool,
                args_json=json.dumps(args)[:2000],
                allowed=1 if allowed else 0,
                result=result[:400],
            )
        )
        s.commit()


def _days_since(dt: datetime | None) -> float:
    if not dt:
        return 1e9
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (datetime.now(UTC) - dt).days


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def get_my_orders(ctx: ToolContext) -> ToolResult:
    with db.Session() as s:
        rows = s.scalars(
            select(db.Order).where(db.Order.customer_id == ctx.customer_id)
        ).all()
        data = [
            {"order_id": o.id, "status": o.status, "amount_usd": o.amount_usd}
            for o in rows
        ]
    _log(ctx, "get_my_orders", {}, True, f"{len(data)} orders")
    return ToolResult(ok=True, data=data)


def get_order(ctx: ToolContext, order_id: int) -> ToolResult:
    with db.Session() as s:
        o = s.get(db.Order, int(order_id))
        # Ownership check: another customer's order is "not found" (ASI03/LLM02).
        if o is None or o.customer_id != ctx.customer_id:
            _log(ctx, "get_order", {"order_id": order_id}, False, "not found / not owner")
            return ToolResult(ok=False, data={"error": "order not found"})
        data = {
            "order_id": o.id,
            "status": o.status,
            "amount_usd": o.amount_usd,
            "address": o.address,
            "notes": o.notes,
            "ordered_at": o.ordered_at.isoformat(),
            "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
        }
    _log(ctx, "get_order", {"order_id": order_id}, True, "ok")
    return ToolResult(ok=True, data=data)


def request_refund(ctx: ToolContext, order_id: int, amount_usd: float, reason: str) -> ToolResult:
    amount_usd = float(amount_usd)
    with db.Session() as s:
        o = s.get(db.Order, int(order_id))
        if o is None or o.customer_id != ctx.customer_id:
            _log(ctx, "request_refund", {"order_id": order_id}, False, "not owner")
            return ToolResult(ok=False, data={"error": "order not found"})

        auto_ok = (
            amount_usd <= REFUND_AUTO_LIMIT
            and o.status == "delivered"
            and _days_since(o.delivered_at) <= REFUND_WINDOW_DAYS
        )
        if auto_ok:
            o.status = "refunded"
            s.commit()
            _log(ctx, "request_refund", {"order_id": order_id, "amount_usd": amount_usd}, True, "approved")
            return ToolResult(
                ok=True,
                data={"result": "approved", "order_id": o.id, "amount_usd": amount_usd},
                receipt=f"Refunded ${amount_usd:.2f} on order {o.id}.",
            )
        # otherwise a pending ticket for a human — never auto-approved
        s.add(db.Ticket(session_id=ctx.session_id, customer_id=str(ctx.customer_id),
                        summary=f"Refund ${amount_usd:.2f} on order {order_id}: {reason}"))
        s.commit()
    _log(ctx, "request_refund", {"order_id": order_id, "amount_usd": amount_usd}, False, "pending_human")
    return ToolResult(
        ok=True,
        data={"result": "pending", "reason": "exceeds auto-approve policy"},
        receipt=f"Refund of ${amount_usd:.2f} on order {order_id} sent to a human for review.",
    )


def update_shipping_address(
    ctx: ToolContext, order_id: int, address: str, confirm_token: str | None = None
) -> ToolResult:
    with db.Session() as s:
        o = s.get(db.Order, int(order_id))
        if o is None or o.customer_id != ctx.customer_id:
            _log(ctx, "update_shipping_address", {"order_id": order_id}, False, "not owner")
            return ToolResult(ok=False, data={"error": "order not found"})
        if o.status != "processing":
            _log(ctx, "update_shipping_address", {"order_id": order_id}, False, "not processing")
            return ToolResult(ok=False, data={"error": "address can only change while processing"})
        # Human confirmation required (ASI09).
        if not confirm_token or confirm_token not in ctx.confirmed_tokens:
            token = f"confirm-{order_id}-{int(time.time())}"
            return ToolResult(
                ok=False,
                data={"error": "confirmation required"},
                confirm_required={
                    "token": token,
                    "summary": f"Change address of order {order_id} to: {address}",
                },
            )
        o.address = address
        s.commit()
    _log(ctx, "update_shipping_address", {"order_id": order_id, "address": address}, True, "updated")
    return ToolResult(ok=True, data={"result": "updated"}, receipt=f"Address of order {order_id} updated.")


def escalate_to_human(ctx: ToolContext, summary: str) -> ToolResult:
    if ctx.escalations >= ESCALATION_LIMIT:
        _log(ctx, "escalate_to_human", {}, False, "rate limited")
        return ToolResult(ok=False, data={"error": "too many escalations this session"})
    ctx.escalations += 1
    with db.Session() as s:
        s.add(db.Ticket(session_id=ctx.session_id, customer_id=str(ctx.customer_id), summary=summary))
        s.commit()
    _log(ctx, "escalate_to_human", {"summary": summary}, True, "ticket opened")
    return ToolResult(ok=True, data={"result": "ticket_opened"}, receipt="A support ticket was opened for you.")


def get_my_documents(ctx: ToolContext) -> ToolResult:
    with db.Session() as s:
        rows = s.scalars(
            select(db.Document).where(db.Document.owner == ctx.doc_owner)
        ).all()
        data = [{"doc_id": d.id, "filename": d.filename, "status": d.status} for d in rows]
    _log(ctx, "get_my_documents", {}, True, f"{len(data)} docs")
    return ToolResult(ok=True, data=data)


# --------------------------------------------------------------------------- #
# KavachPay payment tools
# --------------------------------------------------------------------------- #
AUTO_DISPUTE_LIMIT_INR = 2000.0
DISPUTE_WINDOW_DAYS = 30


def _txn_dict(t, full: bool = False) -> dict:
    d = {
        "txn_id": t.id, "direction": t.direction, "type": t.kind,
        "counterparty": t.counterparty, "amount_inr": t.amount_inr,
        "status": t.status, "money_debited": bool(t.debited),
        "date": t.created_at.strftime("%d %b %Y, %I:%M %p"),
    }
    if t.dispute_ticket:
        d["dispute_ticket"] = t.dispute_ticket
    if full:
        d.update({"utr": t.utr, "status_detail": t.failure_reason, "receiver_remark": t.notes})
    return d


def _ticket_id() -> str:
    return "TKT-" + uuid.uuid4().hex[:6].upper()


def get_account_summary(ctx: ToolContext) -> ToolResult:
    with db.Session() as s:
        c = s.get(db.Customer, ctx.customer_id)
        if c is None:
            return ToolResult(ok=False, data={"error": "account not found"})
        data = {
            "name": c.name, "upi_id": c.upi_id, "linked_bank": f"{c.bank_name} {c.bank_masked}",
            "wallet_balance_inr": c.wallet_balance_inr, "kyc": c.kyc_level,
            "upi_status": c.upi_status,
        }
    _log(ctx, "get_account_summary", {}, True, "ok")
    return ToolResult(ok=True, data=data)


def get_recent_transactions(ctx: ToolContext, status: str | None = None, limit: int = 8) -> ToolResult:
    with db.Session() as s:
        q = select(db.Transaction).where(db.Transaction.customer_id == ctx.customer_id)
        if status in ("failed", "pending", "success", "reversed"):
            q = q.where(db.Transaction.status == status)
        rows = s.scalars(q.order_by(db.Transaction.created_at.desc()).limit(int(limit))).all()
        data = [_txn_dict(t) for t in rows]
    _log(ctx, "get_recent_transactions", {"status": status}, True, f"{len(data)} txns")
    return ToolResult(ok=True, data=data)


def get_transaction(ctx: ToolContext, txn_id: str) -> ToolResult:
    txn_id = str(txn_id).upper().strip()
    with db.Session() as s:
        t = s.get(db.Transaction, txn_id)
        # Ownership check: another customer's transaction is simply "not found".
        if t is None or t.customer_id != ctx.customer_id:
            _log(ctx, "get_transaction", {"txn_id": txn_id}, False, "not found / not owner")
            return ToolResult(ok=False, data={"error": f"no transaction {txn_id} on your account"})
        data = _txn_dict(t, full=True)
    _log(ctx, "get_transaction", {"txn_id": txn_id}, True, "ok")
    return ToolResult(ok=True, data=data)


def raise_dispute(ctx: ToolContext, txn_id: str, reason: str = "") -> ToolResult:
    """File a dispute. The bot never moves money: it only opens tracked tickets."""
    txn_id = str(txn_id).upper().strip()
    with db.Session() as s:
        t = s.get(db.Transaction, txn_id)
        if t is None or t.customer_id != ctx.customer_id:
            _log(ctx, "raise_dispute", {"txn_id": txn_id}, False, "not owner")
            return ToolResult(ok=False, data={"error": f"no transaction {txn_id} on your account"})
        if t.dispute_ticket:
            return ToolResult(ok=True, data={"result": "already_open", "ticket": t.dispute_ticket})
        if t.status == "reversed":
            return ToolResult(ok=True, data={"result": "not_needed",
                                             "detail": "this amount was already reversed to your bank"})
        if _days_since(t.created_at) > DISPUTE_WINDOW_DAYS:
            return ToolResult(ok=False, data={"error": "older than the 30-day dispute window"})
        ticket = _ticket_id()
        auto = (t.status in ("failed", "pending") and bool(t.debited)
                and t.amount_inr <= AUTO_DISPUTE_LIMIT_INR)
        t.dispute_ticket = ticket
        s.add(db.Ticket(session_id=ctx.session_id, customer_id=str(ctx.customer_id),
                        summary=f"[{ticket}] Dispute {txn_id} Rs{t.amount_inr:.0f} ({t.status}): {reason}"))
        s.commit()
        amount = t.amount_inr
    if auto:
        _log(ctx, "raise_dispute", {"txn_id": txn_id}, True, "auto-filed")
        return ToolResult(
            ok=True,
            data={"result": "filed", "ticket": ticket, "track": "auto-reversal tracking",
                  "expected": "within T+1 working day; Rs100/day compensation from bank if late"},
            receipt=f"Dispute {ticket} filed for \u20b9{amount:,.0f} ({txn_id}).",
        )
    _log(ctx, "raise_dispute", {"txn_id": txn_id}, True, "human review")
    return ToolResult(
        ok=True,
        data={"result": "human_review", "ticket": ticket,
              "why": "amount above Rs2,000 or not a failed/pending payment",
              "expected": "specialist update within 48 hours"},
        receipt=f"Dispute {ticket} sent to a specialist for \u20b9{amount:,.0f} ({txn_id}).",
    )


def block_upi(ctx: ToolContext, confirm_token: str | None = None) -> ToolResult:
    """Emergency block of outgoing UPI. Needs explicit user confirmation (ASI09)."""
    with db.Session() as s:
        c = s.get(db.Customer, ctx.customer_id)
        if c is None:
            return ToolResult(ok=False, data={"error": "account not found"})
        if c.upi_status == "blocked":
            return ToolResult(ok=True, data={"result": "already_blocked"})
        if not confirm_token or confirm_token not in ctx.confirmed_tokens:
            token = f"confirm-blockupi-{ctx.customer_id}-{int(time.time())}"
            return ToolResult(
                ok=False, data={"result": "awaiting_confirmation"},
                confirm_required={"token": token, "tool": "block_upi", "args": {},
                                  "summary": "Block all outgoing UPI payments on your KavachPay account"},
            )
        c.upi_status = "blocked"
        s.commit()
    _log(ctx, "block_upi", {}, True, "blocked")
    return ToolResult(ok=True, data={"result": "blocked"},
                      receipt="UPI blocked. No money can leave your account via KavachPay.")


# --------------------------------------------------------------------------- #
# Admin tools (Layer 4 lets only an admin-signed session run these)
# --------------------------------------------------------------------------- #
def admin_list_accounts(ctx: ToolContext) -> ToolResult:
    with db.Session() as s:
        rows = s.scalars(select(db.Customer).order_by(db.Customer.id)).all()
        data = {"total_accounts": len(rows),
                "blocked": [c.upi_id for c in rows if c.upi_status == "blocked"],
                "kyc_issues": sum(1 for c in rows if c.kyc_level != "full"),
                "sample": [{"id": c.id, "name": c.name, "upi_id": c.upi_id, "upi_status": c.upi_status,
                            "kyc": c.kyc_level} for c in rows[:5]]}
    _log(ctx, "admin_list_accounts", {}, True, f"{len(rows)} accounts")
    return ToolResult(ok=True, data=data)


def admin_unblock_upi(ctx: ToolContext, target_customer: int = 1) -> ToolResult:
    with db.Session() as s:
        c = s.get(db.Customer, int(target_customer))
        if c is None:
            return ToolResult(ok=False, data={"error": "account not found"})
        was = c.upi_status
        c.upi_status = "active"
        s.commit()
        name = c.name
    _log(ctx, "admin_unblock_upi", {"target_customer": target_customer}, True, f"{was}->active")
    return ToolResult(ok=True, data={"result": "active", "was": was, "customer": name},
                      receipt=f"UPI re-enabled for {name} (was {was}).")


def admin_security_summary(ctx: ToolContext) -> ToolResult:
    from app import events

    st = events.stats()
    with db.Session() as s:
        q = s.query(db.Quarantine).count()
    data = {"decisions": st["checked"], "blocked": st["blocked"], "by_layer": st["by_layer"],
            "quarantined_chunks": q, "by_owasp": st["by_owasp"]}
    _log(ctx, "admin_security_summary", {}, True, "ok")
    return ToolResult(ok=True, data=data)


# Registry used by the LLM tool loop. Note: customer id is NOT a parameter.
LEGACY_TOOL_SPECS = [
    {
        "name": "get_my_orders",
        "description": "List the signed-in customer's orders.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_order",
        "description": "Get one order's details by id. Only the signed-in customer's own orders.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "integer"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "request_refund",
        "description": "Request a refund. Auto-approved only if <= $200, delivered and within 30 days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer"},
                "amount_usd": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["order_id", "amount_usd", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_shipping_address",
        "description": "Change an order's shipping address (only while processing, needs confirmation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer"},
                "address": {"type": "string"},
                "confirm_token": {"type": "string"},
            },
            "required": ["order_id", "address"],
            "additionalProperties": False,
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Open a support ticket for a human agent.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_my_documents",
        "description": "List the signed-in customer's uploaded files.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

TOOL_SPECS = [
    {"name": "get_account_summary",
     "description": "Signed-in user's UPI ID, bank, wallet balance, KYC and UPI status.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_recent_transactions",
     "description": "Signed-in user's recent transactions, optionally filtered by status.",
     "input_schema": {"type": "object", "additionalProperties": False,
                      "properties": {"status": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "get_transaction", "description": "One transaction by id (KP...). Only the user's own.",
     "input_schema": {"type": "object", "properties": {"txn_id": {"type": "string"}},
                      "required": ["txn_id"], "additionalProperties": False}},
    {"name": "raise_dispute",
     "description": "Open a dispute ticket on the user's own transaction. Never moves money.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["txn_id"],
                      "properties": {"txn_id": {"type": "string"}, "reason": {"type": "string"}}}},
    {"name": "block_upi", "description": "Emergency block of outgoing UPI (needs user confirmation).",
     "input_schema": {"type": "object", "properties": {"confirm_token": {"type": "string"}},
                      "additionalProperties": False}},
    {"name": "escalate_to_human", "description": "Open a support ticket for a human specialist.",
     "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}},
                      "required": ["summary"], "additionalProperties": False}},
]

DISPATCH = {
    "get_account_summary": get_account_summary,
    "get_recent_transactions": get_recent_transactions,
    "get_transaction": get_transaction,
    "raise_dispute": raise_dispute,
    "block_upi": block_upi,
    "get_my_orders": get_my_orders,
    "get_order": get_order,
    "request_refund": request_refund,
    "update_shipping_address": update_shipping_address,
    "escalate_to_human": escalate_to_human,
    "get_my_documents": get_my_documents,
    "admin_list_accounts": admin_list_accounts,
    "admin_unblock_upi": admin_unblock_upi,
    "admin_security_summary": admin_security_summary,
}


def call_tool(ctx: ToolContext, name: str, args: dict) -> ToolResult:
    fn = DISPATCH.get(name)
    if fn is None:
        return ToolResult(ok=False, data={"error": f"unknown tool {name}"})
    # Never let the model pass customer_id; strip anything suspicious.
    args = {k: v for k, v in args.items() if k not in ("customer_id", "session_id")}
    return fn(ctx, **args)
