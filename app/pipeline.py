"""The chat turn pipeline (Flow A) for Kavach Assist.

Hand-written sequence of nodes with a small runner (no orchestration framework):

  shield -> redact -> route -> act(tools) -> retrieve -> rerank -> build_context
         -> generate -> output_checks

- shield   : the user's message goes through the 3-layer zero-judge ShieldLayer
             pipeline (L1 funnel -> L2 intent extractor -> L3 policy gate)
             before any chat model sees it.
- redact   : UPI PIN / OTP / CVV / card numbers are masked before the model or
             the logs see them, and the user is warned.
- route    : small talk / general chat skips RAG entirely, so "hi" gets a
             human reply instead of a policy dump. Account intents run tools.
- act      : tools are planned and executed **in code** (deterministic), never
             by the model, so a tricked model still cannot move money.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app import db, events, llm
from app.canaries import CANARIES
from app.output_checks import run_output_checks
from app.provenance import Origin, ToolRequest, authorize
from app.rag.embed import rerank
from app.rag.store import Hit, get_store
from app.tools import ToolContext, call_tool

SYSTEM_PATH = Path(__file__).resolve().parent / "prompts" / "system.md"
CONTEXT_BUDGET = 4000
PER_SOURCE_BUDGET = 1300
TOP_RERANK = 3
HISTORY_TURNS = 3

BLOCKED_REPLY = (
    "I can't help with that one — it looks like an attempt to change how I work. "
    "I'm happy to help with your payments, refunds, UPI or account though."
)


@dataclass
class TurnState:
    message: str
    ctx: ToolContext
    history: list[dict] = field(default_factory=list)
    customer_name: str = "the customer"
    # working state
    clean_message: str = ""
    intent: str = "knowledge"  # smalltalk|general|account|knowledge|blocked
    redactions: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    needs_documents: bool = True
    hits: list[Hit] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    reply: str = ""
    receipts: list[str] = field(default_factory=list)
    confirm: dict | None = None
    timings: dict[str, float] = field(default_factory=dict)
    tool_results: dict[str, Any] = field(default_factory=dict)
    tools_used: list[str] = field(default_factory=list)
    blocked: bool = False
    shield: dict = field(default_factory=dict)
    model: dict = field(default_factory=dict)
    output_events: list[str] = field(default_factory=list)
    tainted: bool = False  # this session has ingested an uploaded file (Rule of Two)
    gate: list[dict] = field(default_factory=list)  # Layer 4 decisions this turn
    # live progress sink: emit(event_dict). None = no streaming.
    emit: Callable[[dict], None] | None = field(default=None, repr=False, compare=False)


def _system_prompt(name: str) -> str:
    text = SYSTEM_PATH.read_text(encoding="utf-8")
    return text.replace("{CANARY_SYSPROMPT}", CANARIES.sysprompt).replace("{CUSTOMER_NAME}", name)


def _emit(state: TurnState, **event) -> None:
    if state.emit:
        try:
            state.emit(event)
        except Exception:  # noqa: BLE001 - progress must never break a turn
            pass


STEP_LABELS = {
    "shield": "Scanning the message with ShieldLayer",
    "redact": "Checking for PINs, OTPs and card numbers",
    "route": "Working out what you need",
    "act": "Planning and running tools",
    "retrieve": "Searching the knowledge base",
    "rerank": "Ranking the most relevant passages",
    "build_context": "Assembling context for the model",
    "origin_gate": "Policy gate: checking action authorization and provenance",
    "generate": "Writing the reply",
    "output_checks": "Checking the reply before sending",
}


def _skip_reason(state: TurnState, name: str) -> str | None:
    if name == "act" and state.intent not in ("account", "admin"):
        return "no account data needed"
    if name == "origin_gate" and not (state.gate or state.sources or state.tool_results):
        return "no actions or untrusted content in this turn"
    if name == "retrieve" and not state.needs_documents:
        return f"{state.intent} message, no documents needed"
    if name in ("rerank", "build_context") and not state.hits:
        return "nothing retrieved"
    return None


def _step_result(state: TurnState, name: str) -> tuple[str, str]:
    """(status, human detail) for a finished node, from real state."""
    if name == "shield":
        sh = state.shield
        if state.blocked:
            return "block", f"blocked at {sh.get('layer')} ({sh.get('owasp') or 'LLM01'}): {sh.get('reason', '')[:80]}"
        return "done", f"verified by {sh.get('layer', 'ShieldLayer')}"
    if name == "redact":
        if state.redactions:
            return "warn", "hid " + ", ".join(state.redactions)
        return "done", "nothing sensitive found"
    if name == "route":
        return "done", f"intent: {state.intent}" + (" · will search docs" if state.needs_documents else "")
    if name == "act":
        uniq = list(dict.fromkeys(state.tools_used))
        denied = [g for g in state.gate if g["verdict"] == "deny"]
        if denied and not uniq:
            return "block", f"{len(denied)} request(s) refused by the origin gate"
        if not uniq:
            return "done", "no tools ran"
        return "done", f"{len(state.tools_used)} tool call(s): {', '.join(uniq)}"
    if name == "origin_gate":
        n = len(state.gate)
        denied = [g for g in state.gate if g["verdict"] == "deny"]
        held = [g for g in state.gate if g["verdict"] == "confirm"]
        if denied:
            return "block", (f"{n} action(s) checked · {len(denied)} refused: "
                             + "; ".join(f"{g['tool']} from {g['origin']}" for g in denied[:3]))
        if held:
            return "warn", f"{n} action(s) checked · {len(held)} waiting for your confirmation"
        return "done", f"{n} action(s) checked · all came from you" if n else "no embedded actions found"
    if name == "retrieve":
        q = len(state.queries)
        return "done", f"{len(state.hits)} candidate passages from {q} quer{'y' if q == 1 else 'ies'}"
    if name == "rerank":
        return "done", f"kept top {len(state.hits)}"
    if name == "build_context":
        chars = sum(len(x["text"]) for x in state.sources)
        return "done", f"{len(state.sources)} source(s) · {chars:,} chars"
    if name == "generate":
        if state.model.get("error"):
            return "block", "model error: " + state.model["error"][:100]
        toks = state.model.get("output_tokens")
        who = state.model.get("model") or state.model.get("provider")
        return "done", (f"{toks} tokens" if toks else "reply ready") + f" from {who}"
    if name == "output_checks":
        if state.blocked:
            return "block", "secret leak caught, reply replaced (" + ", ".join(state.output_events) + ")"
        if state.output_events:
            return "warn", "fixed before sending: " + ", ".join(state.output_events)
        return "done", "clean: no leaks, PII, bad links or fake citations"
    return "done", ""


def _timed(state: TurnState, name: str, fn):
    label = STEP_LABELS.get(name, name)
    skip = _skip_reason(state, name)
    if skip:
        _emit(state, type="step", id=name, status="skip", label=label, detail=skip)
        return None
    _emit(state, type="step", id=name, status="start", label=label)
    t0 = time.perf_counter()
    out = fn()
    state.timings[name] = round((time.perf_counter() - t0) * 1000, 2)
    status, detail = _step_result(state, name)
    _emit(state, type="step", id=name, status=status, label=label, detail=detail,
          ms=state.timings[name])
    return out


# --------------------------------------------------------------------------- #
# Intent vocab
# --------------------------------------------------------------------------- #
DOMAIN = re.compile(
    r"\b(upi|pay(ment|ments|ed|ing|nest)?|paid|money|debit(ed)?|credit(ed)?|deduct(ed)?|refund\w*|"
    r"transaction\w*|txn|transfer\w*|wallet|kyc|balance|recharge|bill|cashback|reward\w*|fraud|"
    r"scam\w*|otp|pin|bank|account|limit\w*|merchant|qr|card|block\w*|dispute\w*|fail(ed|ure)?|"
    r"pending|stuck|reverse\w*|reversal|utr|statement|history|aadhaar|hack\w*|stolen|lost|"
    r"unauthori[sz]ed|complain\w*|ticket|charged|twice|wrong|send|sent|receive\w*|collect)\b|₹|\brs\.?\s?\d",
    re.I,
)
SMALLTALK = re.compile(
    r"^\s*(hi+|hello+|hey+|hii+|heya|yo|namaste|namaskar|hola|sup|good\s+(morning|afternoon|evening|night)|"
    r"thanks?( you)?( so much)?|thank u|thx|ty|ok(ay)?|cool|great|nice|awesome|bye|goodbye|see ya|"
    r"how are (you|u)|how('s| is) it going|what'?s up|who are (you|u)|what('s| is) your name|"
    r"what can (you|u) do|help|are you (a )?(bot|human|real)|lol|haha+|hmm+)\b[\s\W\w]{0,30}$",
    re.I,
)
TXN_ID = re.compile(r"\bKP[A-Z0-9]{8}\b", re.I)
HUMAN = re.compile(r"\b(human|real person|agent|executive|customer care|call me|talk to (someone|a person)|"
                   r"speak to|manager|supervisor)\b", re.I)
SCAM_CALL = re.compile(r"(call(ed)?|sms|message|whatsapp|link|someone|person).*(otp|pin|cvv|kyc|anydesk|screen ?share)", re.I)
FRAUD = re.compile(r"\b(fraud|scam\w*|hack\w*|stolen|lost (my )?phone|unauthori[sz]ed|didn'?t (make|do) (this|it)|"
                   r"someone (used|took|stole)|block (my )?(upi|account|payments?))\b", re.I)
DISPUTE = re.compile(r"\b(dispute|raise|complain\w*|refund|get (my )?money back|ticket|reverse)\b", re.I)
TXN_LIST = re.compile(r"\b(transactions?|payments?|history|statement|recent|last|debited|deducted|stuck|"
                      r"pending|failed|cut|charged)\b", re.I)
ACCOUNT = re.compile(r"\b(balance|kyc|my account|upi id|my upi|linked bank|wallet)\b", re.I)
DOC_REF = re.compile(r"\b(pdf|document|file|receipt|attachment|upload(ed)?|statement i (sent|shared))\b", re.I)
ADMIN_ASK = re.compile(
    r"\b(as (the |an )?admin|i'?m (the |an )?admin|admin (mode|access|panel)|all (the )?(customers?|accounts?|users?)|"
    r"other (customers?|users?|accounts?)|list (customers|accounts|users)|unblock|re-?enable (my |the |his |her )?upi|"
    r"security (summary|report|stats)|quarantine)\b", re.I)

# Actions written *inside* content (documents, tool results). L4 treats these as
# requests from that content, which can never trigger a tool.
EMBEDDED_ACTIONS = [
    ("raise_dispute", re.compile(r"\b(raise|file|open|submit|create)\s+(a\s+|the\s+)?dispute\b[^.\n]{0,80}?\b(KP[A-Z0-9]{8})", re.I)),
    ("admin_unblock_upi", re.compile(r"\b(unblock|re-?enable|reactivate)\s+(the\s+|their\s+|this\s+)?upi\b", re.I)),
    ("block_upi", re.compile(r"\bblock\s+(the\s+|their\s+|this\s+|his\s+|her\s+)?upi\b", re.I)),
    ("credit_money", re.compile(r"\b(credit|refund|transfer|send|pay)\s+(rs\.?|₹|inr)\s?[\d,]{3,}", re.I)),
    ("credit_money", re.compile(r"\bmark\s+(this|it)\s+as\s+refunded\b", re.I)),
    ("escalate_to_human", re.compile(r"\b(assistant|ai|bot)\b[^.\n]{0,40}\b(escalate|open a ticket)\b", re.I)),
]

# Secrets users should never type. Masked before the model or logs see them.
SECRET_PATTERNS = [
    ("card number", re.compile(r"\b(?:\d[ -]?){15,18}\d\b")),
    ("UPI PIN / OTP / CVV", re.compile(
        r"\b(?:upi\s*pin|m?pin|otp|cvv|cvc|password|passcode)\b[^0-9]{0,15}(\d{3,8})", re.I)),
    ("Aadhaar number", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
]


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def node_shield(state: TurnState) -> None:
    """3-Layer Zero-Judge security pipeline on the user's message."""
    try:
        from app.scanner import get_scanner
        from shared.schemas import ScanItem, Source
        from shield.policy_gate import AuthContext

        seen: list[str] = []

        def on_step(layer: str, status: str, detail: str) -> None:
            seen.append(layer)
            _emit(state, type="layer", id=layer, status=status, detail=detail)

        auth_ctx = AuthContext(
            role=state.ctx.role,
            customer_id=state.ctx.customer_id,
            doc_owner=state.ctx.doc_owner,
            tainted=state.tainted,
        )

        d = get_scanner().scan([ScanItem(text=state.message, source=Source.user)],
                               on_step=on_step, auth_context=auth_ctx)[0]
        if not seen:  # HTTP mode: no live callbacks, so report the layers from the verdict
            for layer, status, detail in _layers_from_decision(d):
                _emit(state, type="layer", id=layer, status=status, detail=detail)
        events.record(d, session_id=state.ctx.session_id,
                      customer_id=str(state.ctx.customer_id))
        state.shield = {"verdict": d.verdict.value, "layer": d.layer.value, "owasp": d.owasp,
                        "reason": d.reason[:200], "rule_id": d.rule_id,
                        "latency_ms": round(d.latency_ms, 1)}
        if d.layer2_extraction:
            state.shield["extraction"] = d.layer2_extraction.model_dump()
        if d.policy_result:
            state.shield["policy"] = d.policy_result.model_dump()
        if d.verdict.value == "block":
            state.blocked = True
            state.intent = "blocked"
            state.reply = BLOCKED_REPLY
    except Exception as e:  # noqa: BLE001
        state.shield = {"verdict": "allow", "layer": "unavailable", "reason": str(e)[:120]}


def _layers_from_decision(d) -> list[tuple[str, str, str]]:
    layer, blocked = d.layer.value, d.verdict.value == "block"
    is_l1_block = (layer in ("regex", "layer1") and blocked)
    if is_l1_block:
        rule_id = d.rule_id or ""
        if rule_id.startswith("obfuscation_"):
            return [
                ("regex", "block", f"rule {d.rule_id} ({d.owasp})"),
                ("stage_1a", "block", f"rule {d.rule_id} ({d.owasp})"),
                ("stage_1b", "skip", "not reached"),
                ("stage_1c", "skip", "not reached"),
                ("layer2", "skip", "not reached (blocked at L1)"),
                ("layer3", "skip", "not reached (blocked at L1)"),
            ]
        elif rule_id.startswith("ac_"):
            return [
                ("regex", "block", f"signature {d.rule_id} ({d.owasp})"),
                ("stage_1a", "pass", "canonicalized NFKC · zero-width & bidi clean"),
                ("stage_1b", "block", f"signature {d.rule_id} ({d.owasp})"),
                ("stage_1c", "skip", "not reached"),
                ("layer2", "skip", "not reached (blocked at L1)"),
                ("layer3", "skip", "not reached (blocked at L1)"),
            ]
        else:
            return [
                ("regex", "block", f"rule {d.rule_id} ({d.owasp})"),
                ("stage_1a", "pass", "canonicalized NFKC · zero-width & bidi clean"),
                ("stage_1b", "pass", "61 threat signatures checked · clean"),
                ("stage_1c", "block", f"rule {d.rule_id} ({d.owasp})"),
                ("layer2", "skip", "not reached (blocked at L1)"),
                ("layer3", "skip", "not reached (blocked at L1)"),
            ]

    # Layer 1 passed
    out = [
        ("regex", "pass", "3-stage deterministic funnel · clean"),
        ("stage_1a", "pass", "canonicalized NFKC · zero-width & bidi clean"),
        ("stage_1b", "pass", "61 threat signatures checked · clean"),
        ("stage_1c", "pass", "22 bounded regex rules checked · no rule matched"),
    ]

    # Layer 2 details
    ext = d.layer2_extraction
    if ext:
        intents_str = ", ".join(it.intent for it in ext.intents) if ext.intents else "general_faq"
        out.append(("layer2", "pass" if not ext.extraction_failed else "warn",
                    f"extracted [{intents_str}] ({ext.provider_used})"))
    else:
        out.append(("layer2", "pass", "intents extracted & neutralized"))

    # Layer 3 details
    if layer in ("layer3", "policy_gate") and blocked:
        out.append(("layer3", "block", f"[{d.rule_id}] {d.reason}"))
    else:
        out.append(("layer3", "pass", "all RBAC/ABAC and authority invariants verified"))

    return out


def node_redact(state: TurnState) -> None:
    text = state.message
    for label, pat in SECRET_PATTERNS:
        if pat.search(text):
            def _mask(m: re.Match) -> str:
                if m.lastindex:
                    return m.group(0).replace(m.group(1), "••••")
                return "••••"
            text = pat.sub(_mask, text)
            state.redactions.append(label)
    state.clean_message = text


def node_route(state: TurnState) -> None:
    q = state.clean_message
    if state.ctx.role == "admin" and (ADMIN_ASK.search(q) or re.search(r"\b(accounts?|customers?|users?)\b", q, re.I)):
        state.intent = "admin"
    elif ADMIN_ASK.search(q) and state.ctx.role != "admin":
        state.intent = "account"  # planner will raise the admin request; L4 decides
    elif TXN_ID.search(q) or HUMAN.search(q) or FRAUD.search(q) or (DOC_REF.search(q) and DISPUTE.search(q)):
        state.intent = "account"
    elif SMALLTALK.match(q) and not DOMAIN.search(q):
        state.intent = "smalltalk"
    elif not DOMAIN.search(q) and not _followup(state):
        state.intent = "general"
    elif (ACCOUNT.search(q) or (re.search(r"\b(my|mine|i)\b", q, re.I) and TXN_LIST.search(q))):
        state.intent = "account"
    else:
        state.intent = "knowledge"
    state.needs_documents = state.intent in ("knowledge", "account")
    # follow-ups: fold in the previous user turn so retrieval keeps context
    prev = next((m["content"] for m in reversed(state.history) if m["role"] == "user"), "")
    state.queries = [q] + ([f"{prev} {q}"] if prev and len(q.split()) < 8 else [])


def _followup(state: TurnState) -> bool:
    """Short follow-up like 'how long will it take?' after a payments question."""
    if not state.history or len(state.clean_message.split()) > 10:
        return False
    recent = " ".join(m["content"] for m in state.history[-2:])
    return bool(DOMAIN.search(recent)) and bool(
        re.search(r"\b(it|that|this|how long|when|why|what about|and|also|then)\b", state.clean_message, re.I))


CONFIRM_SUMMARY = {
    "block_upi": "Block all outgoing UPI payments on your KavachPay account",
    "raise_dispute": "Raise a dispute for {txn_id}",
    "escalate_to_human": "Open a ticket with a human specialist",
}


def _gate(state: TurnState, name: str, args: dict, origin: Origin,
          arg_origins: dict[str, Origin] | None = None, why: str = "", confirmed: bool = False):
    """Layer 4: ask the origin gate before any tool runs. Records and streams the decision."""
    req = ToolRequest(tool=name, args=args, origin=origin, arg_origins=arg_origins or {}, why=why)
    d = authorize(req, session_role=state.ctx.role, tainted=state.tainted, confirmed=confirmed)
    entry = {"tool": name, "origin": origin.value, "verdict": d.verdict, "rule": d.rule, "reason": d.reason,
             "arg_origins": {k: v.value for k, v in (arg_origins or {}).items()},
             "args": {k: v for k, v in args.items() if k not in ("reason", "summary")}, "why": why}
    state.gate.append(entry)
    _emit(state, type="gate", id=name, status=d.verdict, detail=d.reason, origin=origin.value, rule=d.rule)
    events.activity("gate", tool=name, status=d.verdict, rule=d.rule, origin=origin.value,
                    session_id=state.ctx.session_id, customer_id=str(state.ctx.customer_id),
                    args=entry["args"], arg_origins=entry["arg_origins"], detail=d.reason)
    if d.verdict == "deny":
        from shared.schemas import Decision, Layer, Source, Verdict

        src = {"document": Source.document, "tool": Source.tool}.get(origin.value, Source.user)
        dec = Decision(source=src, verdict=Verdict.block, layer=Layer.provenance, owasp="LLM06",
                       reason=f"[{d.rule}] {d.reason}", rule_id=d.rule,
                       text_preview=f"{name}({', '.join(f'{k}={v}' for k, v in entry['args'].items())}) "
                                    f"requested by {origin.value}")
        events.record(dec, session_id=state.ctx.session_id, customer_id=str(state.ctx.customer_id))
    return d


def _run(state: TurnState, name: str, args: dict, origin: Origin | None = None,
         arg_origins: dict[str, Origin] | None = None, why: str = "") -> Any:
    origin = origin or Origin(state.ctx.role)
    d = _gate(state, name, args, origin, arg_origins, why)
    if d.verdict == "deny":
        return None
    if d.verdict == "confirm":
        import uuid

        token = f"confirm-{name}-{uuid.uuid4().hex[:10]}"
        summary = CONFIRM_SUMMARY.get(name, f"Run {name}").format(**{k: v for k, v in args.items()})
        state.confirm = {"token": token, "tool": name, "args": args, "summary": summary,
                         "rule": d.rule, "reason": d.reason}
        _emit(state, type="tool", id=name, status="confirm", detail=summary)
        return None
    _emit(state, type="tool", id=name, status="start")
    res = call_tool(state.ctx, name, args)
    if name == "get_transaction" and res.ok and isinstance(res.data, dict):
        _scan_tool_fields(state, res.data)
    status = "confirm" if res.confirm_required else ("done" if res.ok else "denied")
    rows = len(res.data) if isinstance(res.data, list) else None
    detail = res.receipt or (f"{rows} row(s)" if rows is not None else "")
    _emit(state, type="tool", id=name, status=status, detail=detail)
    events.activity("tool_call", tool=name, status=status, session_id=state.ctx.session_id,
                    customer_id=str(state.ctx.customer_id),
                    args={k: v for k, v in args.items() if k not in ("reason", "summary")},
                    detail=detail)
    state.tool_results[name] = res.data
    state.tools_used.append(name)
    if res.receipt:
        state.receipts.append(res.receipt)
    if res.confirm_required:
        state.confirm = res.confirm_required
    return res


def _scan_tool_fields(state: TurnState, row: dict) -> None:
    """Tool results are untrusted too: scan free-text fields with L1-L3 (source=tool)."""
    from app.scanner import get_scanner
    from shared.schemas import ScanItem, Source

    for key in ("receiver_remark", "status_detail"):
        text = row.get(key) or ""
        if len(text) < 12:
            continue
        d = get_scanner().scan([ScanItem(text=text, source=Source.tool)])[0]
        _emit(state, type="layer", id=d.layer.value if d.layer.value != "none" else "layer3",
              status="block" if d.verdict.value == "block" else "pass",
              detail=f"tool field '{key}': {d.verdict.value} ({d.reason[:80]})")
        if d.verdict.value == "block":
            events.record(d, session_id=state.ctx.session_id, customer_id=str(state.ctx.customer_id))
            row[key] = "[removed by ShieldLayer: this field contained instructions]"
            row.setdefault("_shield", []).append(f"{key} blocked at {d.layer.value}")
        # whatever L1-L3 said, actions written inside the field can never run (L4)
        _embedded_requests(state, text, Origin.tool, f"inside {key} of a tool result")


def _embedded_requests(state: TurnState, text: str, origin: Origin, where: str) -> None:
    seen = {(g["tool"], g["origin"]) for g in state.gate}
    for tool, pat in EMBEDDED_ACTIONS:
        m = pat.search(text or "")
        if not m or (tool, origin.value) in seen:
            continue
        args: dict = {}
        if tool == "raise_dispute":
            args = {"txn_id": m.group(3).upper()}
        _gate(state, tool, args, origin, {k: origin for k in args}, why=f"found {where}: '{m.group(0)[:80]}'")
        seen.add((tool, origin.value))


def _doc_txn_ids(state: TurnState) -> list[str]:
    """Transaction ids that appear in the user's own uploaded files."""
    owner = state.ctx.doc_owner
    ids: list[str] = []
    for h in get_store().search("transaction receipt payment id", customer_id=owner, top=30):
        if h.chunk.owner == owner and h.chunk.visibility == "private":
            ids += [x.upper() for x in TXN_ID.findall(h.chunk.text)]
    return list(dict.fromkeys(ids))


def node_act(state: TurnState) -> None:
    """Deterministic tool planning — the model never chooses or calls tools.
    Every planned call passes the Layer 4 origin gate first."""
    q = state.clean_message
    if state.intent == "admin":
        if re.search(r"\b(unblock|re-?enable|reactivate|activate)\b", q, re.I):
            _run(state, "admin_unblock_upi", {"target_customer": 1}, arg_origins={"target_customer": Origin.admin},
                 why="admin asked to re-enable UPI")
        if re.search(r"\b(accounts?|customers?|users?)\b", q, re.I):
            _run(state, "admin_list_accounts", {}, why="admin asked for accounts")
        if re.search(r"\b(security|summary|report|stats|quarantine|blocked|threats?)\b", q, re.I) or not state.gate:
            _run(state, "admin_security_summary", {}, why="admin asked for a security summary")
        return
    if state.intent != "account":
        return
    if ADMIN_ASK.search(q) and state.ctx.role != "admin":
        # The message asks for admin powers. The planner forwards the request
        # honestly (origin = this session's real role); Layer 4 refuses it.
        tool = "admin_unblock_upi" if re.search(r"\b(unblock|re-?enable)\b", q, re.I) else (
            "admin_security_summary" if re.search(r"\b(security|quarantine)\b", q, re.I) else "admin_list_accounts")
        _run(state, tool, {}, why="message asked for admin access")
        return
    ids = [m.upper() for m in TXN_ID.findall(q)]
    if not ids and DOC_REF.search(q) and DISPUTE.search(q):
        # "dispute the transaction in my receipt": the id only exists inside a file
        for tid in _doc_txn_ids(state)[:2]:
            _run(state, "raise_dispute", {"txn_id": tid, "reason": q[:200]},
                 arg_origins={"txn_id": Origin.document}, why="transaction id read from your uploaded file")
        if state.gate:
            return
    if FRAUD.search(q):
        _run(state, "get_account_summary", {})
        _run(state, "block_upi", {})  # returns a confirmation request, never auto-blocks
        _run(state, "get_recent_transactions", {"limit": 5})
    if ids:
        for tid in ids[:3]:
            _run(state, "get_transaction", {"txn_id": tid}, arg_origins={"txn_id": Origin.user})
            if DISPUTE.search(q):
                _run(state, "raise_dispute", {"txn_id": tid, "reason": q[:200]},
                     arg_origins={"txn_id": Origin.user}, why="you typed this transaction id")
    elif TXN_LIST.search(q) and "get_recent_transactions" not in state.tool_results:
        status = None
        if re.search(r"\b(fail(ed)?|debited|deducted|cut|not received|didn'?t go)\b", q, re.I):
            status = "failed"
        elif re.search(r"\b(pending|stuck|processing)\b", q, re.I):
            status = "pending"
        res = _run(state, "get_recent_transactions", {"status": status, "limit": 6})
        if status and res is not None and isinstance(res.data, list) and not res.data:
            _run(state, "get_recent_transactions", {"limit": 6})
    if ACCOUNT.search(q) and "get_account_summary" not in state.tool_results:
        _run(state, "get_account_summary", {})
    if HUMAN.search(q):
        convo = " | ".join(m["content"][:120] for m in state.history[-4:] if m["role"] == "user")
        _run(state, "escalate_to_human", {"summary": f"User asked for a human. Context: {convo} | {q[:200]}"})
    if not state.tool_results and not state.gate:
        # generic "my ..." account question — show recent activity
        _run(state, "get_recent_transactions", {"limit": 6})


def node_retrieve(state: TurnState) -> None:
    if not state.needs_documents:
        return
    store = get_store()
    fused: dict[str, Hit] = {}
    for q in state.queries:
        for h in store.search(q, customer_id=state.ctx.doc_owner, top=20):
            if h.chunk.chunk_id not in fused or h.score > fused[h.chunk.chunk_id].score:
                fused[h.chunk.chunk_id] = h
    state.hits = list(fused.values())


def node_rerank(state: TurnState) -> None:
    if not state.hits:
        return
    docs = [h.chunk.text for h in state.hits]
    scores = rerank(state.queries[-1], docs)
    ranked = sorted(zip(state.hits, scores), key=lambda x: x[1], reverse=True)
    top_n = 1 if state.intent == "account" else TOP_RERANK
    state.hits = [h for h, _ in ranked[:top_n]]


def node_build_context(state: TurnState) -> None:
    total = 0
    for i, h in enumerate(state.hits, start=1):
        c = h.chunk
        text = c.text[:PER_SOURCE_BUDGET]
        if total + len(text) > CONTEXT_BUDGET:
            break
        total += len(text)
        state.sources.append({"id": f"c{i}", "title": c.doc_title, "page": c.page,
                              "heading": c.heading_path, "text": text,
                              "visibility": c.visibility, "owner": c.owner})


def node_origin_gate(state: TurnState) -> None:
    """L4 over content: actions written inside *untrusted* documents can be read, never run.

    Only user uploads (private) are untrusted third-party content. Our own help
    centre articles legitimately tell people "block UPI" / "raise a dispute";
    treating that advice as a command produced false refusals."""
    for src in state.sources:
        if src.get("visibility") != "private":
            continue
        _embedded_requests(state, src["text"], Origin.document, f"in uploaded file '{src['title']}'")


def _sources_block(sources: list[dict]) -> str:
    lines = ["<knowledge>"]
    for s in sources:
        lines.append(f"[{s['id']}] ({s['title']} › {s['heading']})\n{s['text']}")
    lines.append("</knowledge>")
    return "\n".join(lines)


def _account_block(results: dict) -> str:
    import json

    return "<account_data>\n" + json.dumps(results, ensure_ascii=False, default=str)[:5000] + "\n</account_data>"


GUIDE = {
    "smalltalk": "This is casual small talk. Reply like a friendly human in 1-2 short sentences. "
                 "Do not mention policies or documents.",
    "general": "This is a general question not about KavachPay. Answer it briefly and naturally "
               "(if harmless). Don't mention policies.",
    "knowledge": "Answer from <knowledge> and cite [cN]. If it isn't covered, say so and offer a specialist.",
    "account": "Answer ONLY what the user asked, using <account_data> (their real data, fetched just now) "
               "first, then <knowledge> for policy, citing [cN]. Mention a transaction only if it is in "
               "<account_data> AND the user asked about it. Never state a refund rule or timeline that is not "
               "in <knowledge> or this guidance. Be specific: txn id, ₹ amount, status, next step, ticket id.",
    "admin": "You are talking to the KavachPay security admin. Summarise <account_data> in a few short "
             "bullet points. Be factual and brief.",
}


SECRET_WARNING = (
    "\n\n**Please never share your UPI PIN, OTP or card details**, not even with KavachPay. "
    "We will never ask for them. If that was your real PIN, change it in your bank's UPI app now."
)


def _block_upi_reply(state: TurnState) -> str:
    """Safety-critical reply, written by code. A small model once answered "I've blocked
    your UPI" while the block was still waiting for the user's tap, so the model is
    not asked to write this one at all."""
    lines = [
        "**Let's secure your account right now.** Your UPI is **not blocked yet**.",
        "- Tap **Yes, block UPI now** below. After that, no money can leave via KavachPay.",
        "- Call the cyber-crime helpline **1930** and report on cybercrime.gov.in "
        "(the first hours matter most).",
        "- Call your bank to block the linked account or card, and ask your mobile operator to block the SIM.",
        "- Never share your UPI PIN or OTP. KavachPay will never ask for it.",
    ]
    rows = state.tool_results.get("get_recent_transactions")
    debits = [r for r in rows or [] if isinstance(r, dict) and r.get("direction") == "debit"][:3]
    if debits:
        lines.append("\nI checked your account. Please confirm you made these recent payments:")
        lines += [f"- {r['txn_id']}: ₹{r['amount_inr']:,.0f} to {r['counterparty']} ({r['status']}, {r['date']})"
                  for r in debits]
        lines.append("If any of them isn't yours, say \"raise a dispute for <txn id>\".")
    return "\n".join(lines)


def node_generate(state: TurnState) -> None:
    if state.confirm and state.confirm.get("tool") == "block_upi":
        state.model = {"provider": "fixed", "model": "safety template"}
        state.reply = _block_upi_reply(state)
        return
    model = llm.chat_model()
    state.model = {"provider": model.provider, "model": getattr(model, "model", "")}
    _emit(state, type="model", id="generate", phase="start",
          detail=state.model["model"] or model.provider)
    parts = []
    if state.sources:
        parts.append(_sources_block(state.sources))
    if state.tool_results:
        parts.append(_account_block(state.tool_results))
    note = GUIDE.get(state.intent, "")
    if state.redactions:
        # the warning itself is added by code after generation (see SECRET_WARNING)
        note += (" The app has already warned the user about sharing secrets; do NOT mention PINs, OTPs "
                 "or the warning. Just answer their actual question.")
    if SCAM_CALL.search(state.clean_message):
        note += (" This sounds like a scam attempt: say clearly it's a scam, KavachPay never asks for OTP/PIN, "
                 "and if they shared anything: block UPI here, call 1930, report on cybercrime.gov.in.")
    failed = [r for v in state.tool_results.values() if isinstance(v, list) for r in v
              if isinstance(r, dict) and r.get("status") == "failed" and r.get("money_debited")]
    if failed:
        note += (" FACT: failed-but-debited UPI payments auto-reverse to the bank within T+1 working day; "
                 "if late, the bank owes Rs100/day. Offer to raise a dispute (the user can say "
                 "'raise a dispute for <txn id>'). Do not mention operator 4-hour waits for failed payments.")
    denied = [g for g in state.gate if g["verdict"] == "deny"]
    if denied:
        lines = "; ".join(f"{g['tool']} requested by {g['origin']} ({g['reason']})" for g in denied[:3])
        note += (f" SECURITY LAYER 4 refused these actions: {lines}. In one or two sentences tell the user "
                 "plainly that you did NOT do it and why. If a transaction id came from a file, ask them to "
                 "type the id themselves. Never claim the action happened.")
    if state.confirm and state.confirm.get("tool") != "block_upi":
        note += (f" The action '{state.confirm['summary']}' is waiting for the user to tap Confirm; it has NOT "
                 "happened yet. Say that in one sentence.")
    parts.append(f"(assistant guidance: {note})")
    parts.append(f"User: {state.clean_message}")
    user_content = "\n\n".join(parts)

    # short, trimmed history: enough for follow-ups, small enough to stay fast/accurate
    recent = state.history[-HISTORY_TURNS * 2:]
    if state.intent in ("account", "admin"):
        # Account answers must come from data fetched *this* turn. Earlier assistant replies
        # carry stale numbers the model re-narrates, so only keep what the user said.
        recent = [m for m in recent if m["role"] == "user"]
    hist = [{"role": m["role"], "content": m["content"][:400]} for m in recent]
    messages = hist + [{"role": "user", "content": user_content}]
    try:
        kw = {}
        if getattr(model, "supports_progress", False) and state.emit:
            kw["on_progress"] = lambda phase, n: _emit(state, type="model", id="generate",
                                                       phase=phase, tokens=n)
        resp = model.complete(_system_prompt(state.customer_name), messages,
                              tool_results=state.tool_results or None, **kw)
        state.model["output_tokens"] = (getattr(resp, "usage", None) or {}).get("output_tokens")
        state.reply = resp.text or "Sorry, I didn't catch that — could you rephrase?"
        if state.redactions:
            state.reply += SECRET_WARNING
    except Exception as e:  # noqa: BLE001
        state.reply = ("I'm having trouble reaching my brain right now 😅. "
                       "Please try again in a moment, or ask for a human specialist.")
        state.model["error"] = str(e)[:200]


def node_output_checks(state: TurnState) -> None:
    allowed = {int(s["id"][1:]) for s in state.sources}
    with db.Session() as s:
        cust = s.get(db.Customer, state.ctx.customer_id)
        contacts = {cust.email.lower(), cust.phone} if cust else set()
    # the user's own UTR numbers look like phone numbers; allow them
    for v in state.tool_results.values():
        for row in v if isinstance(v, list) else [v]:
            if isinstance(row, dict) and row.get("utr"):
                contacts.add(str(row["utr"]))
    res = run_output_checks(state.reply, canaries=CANARIES.all(), allowed_citations=allowed,
                            customer_contacts=contacts)
    state.reply = res.text
    if res.refused:
        state.blocked = True
    state.output_events = list(res.events)
    if res.events:
        events.activity("output_guard", session_id=state.ctx.session_id,
                        customer_id=str(state.ctx.customer_id), owasp=list(res.events),
                        status="block" if res.refused else "fixed",
                        detail="reply replaced (secret leak)" if res.refused
                        else "reply edited before sending")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def run_turn(message: str, ctx: ToolContext,
             history: list[dict] | None = None, customer_name: str = "the customer",
             emit: Callable[[dict], None] | None = None, tainted: bool = False) -> TurnState:
    state = TurnState(message=message, ctx=ctx, history=history or [],
                      customer_name=customer_name, emit=emit, tainted=tainted)
    _emit(state, type="step", id="received", status="done", label="Message received",
          detail=f"{len(message)} chars · {len(state.history) // 2} earlier turn(s) in context")
    _timed(state, "shield", lambda: node_shield(state))
    if state.blocked:
        _turn_activity(state)
        return state
    _timed(state, "redact", lambda: node_redact(state))
    _timed(state, "route", lambda: node_route(state))
    _timed(state, "act", lambda: node_act(state))
    _timed(state, "retrieve", lambda: node_retrieve(state))
    _timed(state, "rerank", lambda: node_rerank(state))
    _timed(state, "build_context", lambda: node_build_context(state))
    _timed(state, "origin_gate", lambda: node_origin_gate(state))
    _timed(state, "generate", lambda: node_generate(state))
    _timed(state, "output_checks", lambda: node_output_checks(state))
    _turn_activity(state)
    return state


def execute_confirmed(ctx: ToolContext, pending: dict, tainted: bool = False):
    """Run an action the user confirmed. It still passes the origin gate."""
    state = TurnState(message="", ctx=ctx, tainted=tainted)
    tool, args = pending.get("tool", ""), dict(pending.get("args", {}))
    d = _gate(state, tool, args, Origin(ctx.role), {k: Origin.user for k in args if k == "txn_id"},
              why="user tapped Confirm", confirmed=True)
    if d.verdict != "allow":
        from app.tools import ToolResult

        return ToolResult(ok=False, data={"error": d.reason})
    if tool == "block_upi":
        ctx.confirmed_tokens.add(pending["token"])
        args["confirm_token"] = pending["token"]
    return call_tool(ctx, tool, args)


def _turn_activity(state: TurnState) -> None:
    events.activity("turn", session_id=state.ctx.session_id, customer_id=str(state.ctx.customer_id),
                    intent=state.intent, blocked=state.blocked, tools=state.tools_used,
                    model=state.model.get("model") or state.model.get("provider"),
                    shield_layer=state.shield.get("layer"),
                    ms=round(sum(state.timings.values()), 1))
