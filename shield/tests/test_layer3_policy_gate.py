"""Tests for Layer 3: Deterministic Policy & Symbolic Gate."""
from __future__ import annotations

import pytest

from shared.schemas import ExtractedIntent, Layer2Extraction, Verdict
from shield.policy_gate import AuthContext, PolicyGate


@pytest.fixture
def gate() -> PolicyGate:
    return PolicyGate()


def test_benign_user_faq_allowed(gate: PolicyGate):
    extraction = Layer2Extraction(
        intents=[ExtractedIntent(intent="general_faq", neutral_summary="Question about refund timing.")],
        claimed_authority=None,
    )
    res = gate.evaluate(extraction, AuthContext(role="user", customer_id=1))
    assert res.verdict == Verdict.allow
    assert res.rbac_passed
    assert res.abac_passed


def test_authority_spoofing_blocked(gate: PolicyGate):
    # Untrusted prompt claims to be security director, but session is ordinary user
    extraction = Layer2Extraction(
        intents=[ExtractedIntent(intent="admin_security_summary", neutral_summary="Security report.")],
        claimed_authority="security_director",
    )
    res = gate.evaluate(extraction, AuthContext(role="user", customer_id=1))
    assert res.verdict == Verdict.block
    assert res.rule_id == "POL_AUTHORITY_SPOOFING"
    assert res.authority_spoofing is True
    assert res.owasp == "ASI01"


def test_verified_admin_authority_allowed(gate: PolicyGate):
    # When session is legitimately verified as admin, admin claimed authority does not trigger spoofing block
    extraction = Layer2Extraction(
        intents=[ExtractedIntent(intent="admin_security_summary", neutral_summary="Security report.")],
        claimed_authority="admin",
    )
    res = gate.evaluate(extraction, AuthContext(role="admin", customer_id=0))
    assert res.verdict == Verdict.allow
    assert res.authority_spoofing is False


def test_rbac_violation_blocked(gate: PolicyGate):
    # Standard user attempting to invoke an admin intent without claiming authority
    extraction = Layer2Extraction(
        intents=[ExtractedIntent(intent="update_role", neutral_summary="Elevate user permissions.")],
        claimed_authority=None,
    )
    res = gate.evaluate(extraction, AuthContext(role="user", customer_id=1))
    assert res.verdict == Verdict.block
    assert res.rule_id == "POL_RBAC_VIOLATION"
    assert res.owasp == "ASI02"


def test_abac_cross_tenant_access_blocked(gate: PolicyGate):
    # User 1 attempting to view/modify Customer 0 (Admin) or Customer 2
    extraction = Layer2Extraction(
        intents=[ExtractedIntent(intent="check_balance", target_id="2", neutral_summary="Check user 2 balance.")],
        claimed_authority=None,
    )
    res = gate.evaluate(extraction, AuthContext(role="user", customer_id=1))
    assert res.verdict == Verdict.block
    assert res.rule_id == "POL_ABAC_VIOLATION"
    assert res.owasp == "ASI02"


def test_abac_own_account_allowed(gate: PolicyGate):
    extraction = Layer2Extraction(
        intents=[ExtractedIntent(intent="check_balance", target_id="1", neutral_summary="Check balance.")],
        claimed_authority=None,
    )
    res = gate.evaluate(extraction, AuthContext(role="user", customer_id=1))
    assert res.verdict == Verdict.allow


def test_multi_intent_smuggling_blocked(gate: PolicyGate):
    # Innocent check_balance combined with unauthorized delete_user
    extraction = Layer2Extraction(
        intents=[
            ExtractedIntent(intent="check_balance", neutral_summary="Check balance."),
            ExtractedIntent(intent="delete_user", target_id="2", neutral_summary="Delete customer 2."),
        ],
        multi_intent_detected=True,
    )
    res = gate.evaluate(extraction, AuthContext(role="user", customer_id=1))
    assert res.verdict == Verdict.block
    assert res.rule_id in ("POL_INTENT_SMUGGLING", "POL_RBAC_VIOLATION")


def test_fail_closed_on_extraction_failure(gate: PolicyGate):
    extraction = Layer2Extraction(
        extraction_failed=True,
    )
    res = gate.evaluate(extraction, AuthContext(role="user", customer_id=1))
    assert res.verdict == Verdict.block
    assert res.rule_id == "POL_EXTRACTION_FAILED"
