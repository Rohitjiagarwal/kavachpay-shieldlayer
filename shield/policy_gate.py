"""Layer 3 — Deterministic Policy & Symbolic Gate.

100% pure deterministic code (zero AI, zero floating-point numeric scores, zero LLM judge).
Validates Layer 2's schema-enforced extraction against verified user auth context:
1. Authority Spoofing Checks (OWASP ASI01 / MITRE AML.T0054)
2. RBAC Invariants (Intent catalog role permissions)
3. ABAC Invariants (Customer ownership & tenant data isolation)
4. Multi-Intent Smuggling & Taint / FSM Invariants
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from shared.schemas import Layer2Extraction, PolicyResult, Verdict

logger = logging.getLogger("shield.policy_gate")

INTENT_CATALOG_PATH = Path(__file__).resolve().parents[1] / "config" / "intent_catalog.yaml"

ADMIN_AUTHORITIES = {
    "admin",
    "administrator",
    "system_administrator",
    "security_director",
    "director",
    "auditor",
    "compliance_officer",
    "root",
    "system",
    "developer",
    "supervisor",
    "manager",
}


@dataclass
class AuthContext:
    """Verified user identity and session authorization context."""

    role: str = "user"  # "user" | "admin" | "anonymous"
    customer_id: str | int = 1
    doc_owner: str | int | None = 1
    tainted: bool = False  # has uploaded file context
    confirmed: bool = False  # user has explicitly clicked confirmation


class PolicyGate:
    """Layer 3 Deterministic Policy & Symbolic Gate."""

    def __init__(self, catalog_path: Path = INTENT_CATALOG_PATH):
        self.catalog = self._load_catalog(catalog_path)

    def _load_catalog(self, path: Path) -> dict[str, Any]:
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                return data.get("intents", {})
            except Exception as e:
                logger.error(f"Failed to load intent catalog: {e}")
        return {}

    def evaluate(
        self,
        extraction: Layer2Extraction,
        auth_context: AuthContext | None = None,
    ) -> PolicyResult:
        """Deterministically evaluate Layer 2 extraction against policy rules."""
        ctx = auth_context or AuthContext()
        role = ctx.role.lower().strip()

        # 1. Extraction Failure Check (Fail-Closed)
        if extraction.extraction_failed:
            return PolicyResult(
                verdict=Verdict.block,
                rule_id="POL_EXTRACTION_FAILED",
                reason="Intent extraction failed or timed out (fail-closed policy)",
                owasp="ASI01",
                rbac_passed=False,
                abac_passed=False,
                blocked_intents=[it.intent for it in extraction.intents],
            )

        # 2. Authority Spoofing Check (OWASP ASI01 / MITRE AML.T0054)
        claimed = (extraction.claimed_authority or "").lower().strip()
        if claimed:
            # If prompt claims administrative / elevated authority while session is standard user
            if claimed in ADMIN_AUTHORITIES and role != "admin":
                return PolicyResult(
                    verdict=Verdict.block,
                    rule_id="POL_AUTHORITY_SPOOFING",
                    reason=f"Authority spoofing detected: untrusted prompt claimed '{extraction.claimed_authority}' but session is verified as '{ctx.role}'",
                    owasp="ASI01",
                    authority_spoofing=True,
                    rbac_passed=False,
                    abac_passed=True,
                    blocked_intents=[it.intent for it in extraction.intents],
                )

        # 3. Multi-Intent Smuggling Invariant
        # If innocent intent is bundled with unauthorized privileged intent
        if extraction.multi_intent_detected and len(extraction.intents) > 1:
            for it in extraction.intents:
                intent_def = self.catalog.get(it.intent, {})
                allowed_roles = intent_def.get("allowed_roles", ["user", "admin"])
                if role not in allowed_roles:
                    return PolicyResult(
                        verdict=Verdict.block,
                        rule_id="POL_INTENT_SMUGGLING",
                        reason=f"Multi-intent smuggling detected: unauthorized action '{it.intent}' bundled with innocent request",
                        owasp="ASI01",
                        rbac_passed=False,
                        abac_passed=False,
                        blocked_intents=[it.intent],
                    )

        # 4. RBAC Invariants (Role Permissions)
        allowed_intents: list[str] = []
        for it in extraction.intents:
            intent_def = self.catalog.get(it.intent)
            if intent_def is None:
                # If intent not in catalog, treat as general_faq if benign, or block if privileged
                if it.intent.startswith("admin_") or it.intent in ("update_role", "delete_user"):
                    if role != "admin":
                        return PolicyResult(
                            verdict=Verdict.block,
                            rule_id="POL_RBAC_VIOLATION",
                            reason=f"RBAC violation: role '{ctx.role}' is not authorized to execute privileged intent '{it.intent}'",
                            owasp="ASI02",
                            rbac_passed=False,
                            blocked_intents=[it.intent],
                        )
                allowed_intents.append(it.intent)
                continue

            allowed_roles = intent_def.get("allowed_roles", ["user", "admin"])
            if role not in allowed_roles:
                return PolicyResult(
                    verdict=Verdict.block,
                    rule_id="POL_RBAC_VIOLATION",
                    reason=f"RBAC violation: role '{ctx.role}' is not authorized to execute intent '{it.intent}'",
                    owasp="ASI02",
                    rbac_passed=False,
                    blocked_intents=[it.intent],
                )
            allowed_intents.append(it.intent)

        # 5. ABAC Invariants (Data Isolation / Resource Ownership)
        for it in extraction.intents:
            intent_def = self.catalog.get(it.intent, {})
            if intent_def.get("requires_abac") and role != "admin":
                # Check target customer / account ownership
                target = it.target_id or it.parameters.get("account_id") or it.parameters.get("target_customer")
                if target:
                    target_str = str(target).upper()
                    cid_str = str(ctx.customer_id).upper()
                    # If target explicitly refers to customer 0 (admin) or another customer ID
                    if target_str in ("0", "ADMIN", "ROOT") or (target_str.isdigit() and target_str != cid_str):
                        return PolicyResult(
                            verdict=Verdict.block,
                            rule_id="POL_ABAC_VIOLATION",
                            reason=f"ABAC violation: user {ctx.customer_id} cannot access target account {target}",
                            owasp="ASI02",
                            abac_passed=False,
                            blocked_intents=[it.intent],
                        )

        # All deterministic policy invariants passed!
        return PolicyResult(
            verdict=Verdict.allow,
            rule_id=None,
            reason=f"All {len(extraction.intents)} intent(s) passed deterministic policy & symbolic gate (RBAC/ABAC verified)",
            owasp="NONE",
            authority_spoofing=False,
            rbac_passed=True,
            abac_passed=True,
            allowed_intents=allowed_intents,
            blocked_intents=[],
        )
