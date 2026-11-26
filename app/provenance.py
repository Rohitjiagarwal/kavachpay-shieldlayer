"""Layer 4 - the Origin Gate (provenance-based authorization for agent actions).

Layers 1-3 *detect* attacks by reading text, and a clever enough wording can
slip past any detector. Layer 4 does not read text at all. Every tool request
the agent wants to make carries tags saying **where it came from**:

    origin       who is asking for the action        (user | admin | document | tool | model)
    arg_origins  where each argument value came from (user | admin | database | document | tool | model)

Fixed rules in code then decide allow / confirm / deny. The role comes from the
signed-in session, never from what the text claims ("I am the admin" typed by a
customer is still origin=user). Data that arrived inside a document, a tool
result or the model's own output can be *read*, but can never *cause* an action.

Rule of Two (Meta, 2025): once a session has taken in untrusted content (an
uploaded file), state-changing tools need an explicit user confirmation for the
rest of that session, so untrusted input + private data + actions never combine
unattended.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Origin(str, Enum):
    user = "user"          # the signed-in customer typed it
    admin = "admin"        # the signed-in security admin typed it
    database = "database"  # read from the customer's own records by our code
    document = "document"  # inside a KB article or an uploaded file
    tool = "tool"          # inside a tool result (e.g. a payment remark)
    model = "model"        # written by the LLM


PRINCIPALS = {Origin.user, Origin.admin}  # the only origins that can ever ask for an action


@dataclass(frozen=True)
class Policy:
    kind: str                       # read | write | admin
    principals: frozenset[Origin]   # who may invoke it
    arg_sources: dict[str, frozenset[Origin]] = field(default_factory=dict)
    always_confirm: bool = False


_SELF = frozenset({Origin.user, Origin.database})
POLICIES: dict[str, Policy] = {
    "get_account_summary": Policy("read", frozenset({Origin.user})),
    "get_recent_transactions": Policy("read", frozenset({Origin.user})),
    "get_transaction": Policy("read", frozenset({Origin.user}), {"txn_id": _SELF}),
    "raise_dispute": Policy("write", frozenset({Origin.user}), {"txn_id": _SELF}),
    "block_upi": Policy("write", frozenset({Origin.user}), always_confirm=True),
    "escalate_to_human": Policy("write", frozenset({Origin.user})),
    "admin_list_accounts": Policy("admin", frozenset({Origin.admin})),
    "admin_unblock_upi": Policy("admin", frozenset({Origin.admin}),
                                {"target_customer": frozenset({Origin.admin})}),
    "admin_security_summary": Policy("admin", frozenset({Origin.admin})),
}


@dataclass
class ToolRequest:
    tool: str
    args: dict
    origin: Origin
    arg_origins: dict[str, Origin] = field(default_factory=dict)
    why: str = ""  # what made the agent propose this (for the audit trail)


@dataclass
class GateDecision:
    verdict: str  # allow | confirm | deny
    rule: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"


def authorize(req: ToolRequest, *, session_role: str, tainted: bool = False,
              confirmed: bool = False) -> GateDecision:
    """Decide from provenance tags only. Pure function: no text, no model."""
    pol = POLICIES.get(req.tool)
    if pol is None:
        return GateDecision("deny", "unknown-tool", f"'{req.tool}' is not an allowed tool")

    # 1) the requester must be a principal, and must match the session's real role
    if req.origin not in PRINCIPALS:
        return GateDecision(
            "deny", "untrusted-origin",
            f"requested by {req.origin.value} content; only a signed-in person can trigger actions")
    if req.origin.value != session_role:
        return GateDecision(
            "deny", "role-mismatch",
            f"request claims {req.origin.value} but this session is signed in as {session_role}")
    if req.origin not in pol.principals:
        who = " or ".join(sorted(p.value for p in pol.principals))
        return GateDecision(
            "deny", "wrong-principal",
            f"{req.tool} is {pol.kind}-only for {who}; this session is {session_role} "
            "(the role comes from sign-in, not from what the message says)")

    # 2) every argument must come from a source allowed to steer this tool
    for arg, allowed in pol.arg_sources.items():
        src = req.arg_origins.get(arg)
        if arg in req.args and src is not None and src not in allowed:
            ok = " / ".join(sorted(a.value for a in allowed))
            return GateDecision(
                "deny", "tainted-argument",
                f"{arg}={req.args[arg]} came from {src.value}; {req.tool} only accepts it from {ok}")

    # 3) Rule of Two + always-confirm tools
    if pol.kind == "write" and not confirmed:
        if pol.always_confirm:
            return GateDecision("confirm", "needs-confirmation", "irreversible action, user must confirm")
        if tainted:
            return GateDecision(
                "confirm", "rule-of-two",
                "this chat has read an uploaded file, so actions need your confirmation")

    return GateDecision("allow", "ok", f"{req.origin.value} may run {req.tool}"
                        + (" with arguments from " + ", ".join(sorted({o.value for o in req.arg_origins.values()}))
                           if req.arg_origins else ""))
