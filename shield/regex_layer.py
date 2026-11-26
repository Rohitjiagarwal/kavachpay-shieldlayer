"""Layer 1 — Deterministic Security Funnel Interface.

Chains Stage 1A (Canonicalization) -> Stage 1B (Aho-Corasick) -> Stage 1C (Targeted Regex).
Preserves full backwards compatibility with existing callers, test suites, and funnels.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from shield.layer1_funnel import Layer1Filter, Layer1Result, RuleMatch

RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "regex_rules.yaml"
REGEX_RULES_PATH = RULES_PATH
AHO_CORASICK_PATH = Path(__file__).resolve().parents[1] / "rules" / "aho_corasick_signatures.yaml"

_FLAG_MAP = {
    "i": re.IGNORECASE,
    "s": re.DOTALL,
    "m": re.MULTILINE,
    "x": re.VERBOSE,
}


@dataclass
class Rule:
    """Legacy Rule dataclass preserved for backwards compatibility."""

    id: str
    pattern: re.Pattern
    owasp: str
    severity: str
    why: str


@dataclass
class RegexHit:
    """The hit object returned when Layer 1 blocks an input.

    Extended with Stage 1A-1C metadata while keeping rule_id, owasp, severity, why.
    """

    rule_id: str
    owasp: str
    severity: str
    why: str
    stage: str = "stage_1c"
    matched_span: str = ""
    obfuscation_signals: list[str] = field(default_factory=list)
    normalized_text: str = ""
    matches: list[RuleMatch] = field(default_factory=list)


def _compile_flags(flags: str) -> int:
    out = 0
    for ch in flags or "":
        out |= _FLAG_MAP.get(ch, 0)
    return out


class RegexLayer:
    """Layer 1 deterministic security funnel wrapper.

    Runs Stage 1A (Canonicalization & De-obfuscation) ->
         Stage 1B (Aho-Corasick Multi-Pattern Gate) ->
         Stage 1C (Targeted ReDoS-safe Regex Engine).
    """

    def __init__(
        self,
        rules_path: Path | str = RULES_PATH,
        mode: str = "fail_fast",
    ):
        self.rules_path = Path(rules_path)
        self.mode = mode
        self.rules: list[Rule] = []

        # Load legacy / configurable rules representation for introspection
        self.load()

        # Orchestrate the 3-stage funnel
        regex_path = self.rules_path if self.rules_path.exists() else REGEX_RULES_PATH
        self.funnel = Layer1Filter(
            mode="fail_fast" if mode == "fail_fast" else "audit",
            aho_corasick_path=AHO_CORASICK_PATH if AHO_CORASICK_PATH.exists() else None,
            regex_rules_path=regex_path,
        )

    def load(self) -> None:
        """Load rules into self.rules for backwards compatibility with tests/inspection."""
        if not self.rules_path.exists():
            return
        data = yaml.safe_load(self.rules_path.read_text(encoding="utf-8")) or {}
        rules = []
        for r in data.get("rules", []):
            rules.append(
                Rule(
                    id=r["id"],
                    pattern=re.compile(r["pattern"], _compile_flags(r.get("flags", ""))),
                    owasp=r.get("owasp") or r.get("owasp_ref", "NONE"),
                    severity=r.get("severity", "medium"),
                    why=r.get("why", r.get("description", "")),
                )
            )
        self.rules = rules

    def check(self, text: str) -> RegexHit | None:
        """Execute the 3-stage funnel and return the primary match as RegexHit, or None."""
        result: Layer1Result = self.funnel.scan(text)
        if not result.blocked or not result.matches:
            return None

        primary = result.primary_match
        assert primary is not None
        return RegexHit(
            rule_id=primary.rule_id,
            owasp=primary.owasp_ref,
            severity=primary.severity,
            why=primary.why,
            stage=primary.stage,
            matched_span=primary.matched_span,
            obfuscation_signals=result.obfuscation_signals,
            normalized_text=result.normalized_text,
            matches=result.matches,
        )

    def scan(self, text: str) -> Layer1Result:
        """Execute the 3-stage funnel and return the full Layer1Result object."""
        return self.funnel.scan(text)

    def __len__(self) -> int:
        return len(self.rules) if self.rules else len(self.funnel.targeted_regex)


# module-level singleton for convenience
_default: RegexLayer | None = None


def get_regex_layer() -> RegexLayer:
    global _default
    if _default is None:
        _default = RegexLayer()
    return _default
