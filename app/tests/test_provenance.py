"""Layer 4: the Origin Gate decides from provenance tags only."""
from app.provenance import Origin, ToolRequest, authorize


def _req(tool, origin, args=None, arg_origins=None):
    return ToolRequest(tool=tool, args=args or {}, origin=origin, arg_origins=arg_origins or {})


def test_user_can_dispute_own_txn_from_their_message():
    d = authorize(_req("raise_dispute", Origin.user, {"txn_id": "KP1"}, {"txn_id": Origin.user}),
                  session_role="user")
    assert d.verdict == "allow"


def test_txn_id_from_document_is_denied():
    d = authorize(_req("raise_dispute", Origin.user, {"txn_id": "KP1"}, {"txn_id": Origin.document}),
                  session_role="user")
    assert d.verdict == "deny" and d.rule == "tainted-argument"


def test_document_cannot_request_actions():
    d = authorize(_req("raise_dispute", Origin.document, {"txn_id": "KP1"}), session_role="user")
    assert d.verdict == "deny" and d.rule == "untrusted-origin"


def test_user_claiming_admin_cannot_use_admin_tools():
    d = authorize(_req("admin_list_accounts", Origin.user), session_role="user")
    assert d.verdict == "deny" and d.rule == "wrong-principal"


def test_admin_can_use_admin_tools():
    assert authorize(_req("admin_list_accounts", Origin.admin), session_role="admin").allowed


def test_origin_must_match_session_role():
    d = authorize(_req("admin_list_accounts", Origin.admin), session_role="user")
    assert d.verdict == "deny" and d.rule == "role-mismatch"


def test_rule_of_two_requires_confirmation_after_upload():
    req = _req("raise_dispute", Origin.user, {"txn_id": "KP1"}, {"txn_id": Origin.user})
    assert authorize(req, session_role="user", tainted=True).verdict == "confirm"
    assert authorize(req, session_role="user", tainted=True, confirmed=True).allowed


def test_reads_are_not_slowed_by_rule_of_two():
    assert authorize(_req("get_account_summary", Origin.user), session_role="user", tainted=True).allowed
