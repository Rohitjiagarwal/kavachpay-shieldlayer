"""Stage 1C: Targeted Regex Engine.

Runs a lean, pre-compiled, ReDoS-safe set of structural and contextual regex
rules on inputs that survive Stage 1B (or all spans in audit mode).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "regex_rules.yaml"

_FLAG_MAP = {
    "i": re.IGNORECASE,
    "s": re.DOTALL,
    "m": re.MULTILINE,
    "x": re.VERBOSE,
}


def compile_flags(flags: str) -> int:
    out = 0
    for ch in flags or "":
        out |= _FLAG_MAP.get(ch, 0)
    return out


@dataclass(frozen=True)
class TargetedRegexRule:
    id: str
    name: str
    pattern: re.Pattern
    category: str
    severity: Literal["critical", "high", "medium", "low"]
    owasp_ref: str
    description: str
    false_positive_notes: str


@dataclass(frozen=True)
class RegexMatch:
    rule_id: str
    name: str
    category: str
    severity: Literal["critical", "high", "medium", "low"]
    owasp_ref: str
    description: str
    matched_span: str = ""
    start_idx: int = 0
    end_idx: int = 0


class TargetedRegexEngine:
    """Pre-compiled ReDoS-safe targeted regex engine."""

    def __init__(
        self,
        rules_path: Path | str = RULES_PATH,
        mode: Literal["fail_fast", "audit"] = "fail_fast",
    ):
        self.rules_path = Path(rules_path)
        self.mode = mode
        self.rules: list[TargetedRegexRule] = []
        self._load_and_compile()

    def _load_and_compile(self) -> None:
        if not self.rules_path.exists():
            raise FileNotFoundError(f"Regex rules file not found: {self.rules_path}")

        data = yaml.safe_load(self.rules_path.read_text(encoding="utf-8")) or {}
        entries = data.get("rules", [])

        compiled_rules: list[TargetedRegexRule] = []
        for r in entries:
            flags = compile_flags(r.get("flags", ""))
            compiled_rules.append(
                TargetedRegexRule(
                    id=r["id"],
                    name=r.get("name", r["id"]),
                    pattern=re.compile(r["pattern"], flags),
                    category=r.get("category", "regex_rule"),
                    severity=r.get("severity", "medium"),
                    owasp_ref=r.get("owasp_ref", "LLM01"),
                    description=r.get("description", ""),
                    false_positive_notes=r.get("false_positive_notes", ""),
                )
            )
        self.rules = compiled_rules

    def scan_span(self, text: str) -> list[RegexMatch]:
        """Scan a single text span across all regex rules."""
        if not text:
            return []

        matches: list[RegexMatch] = []
        for rule in self.rules:
            m = rule.pattern.search(text)
            if m:
                match = RegexMatch(
                    rule_id=rule.id,
                    name=rule.name,
                    category=rule.category,
                    severity=rule.severity,
                    owasp_ref=rule.owasp_ref,
                    description=rule.description,
                    matched_span=m.group(0),
                    start_idx=m.start(),
                    end_idx=m.end(),
                )
                matches.append(match)
                if self.mode == "fail_fast":
                    return matches

        return matches

    def scan_spans(self, spans: list[str]) -> list[RegexMatch]:
        """Scan all spans from the inspection bundle."""
        all_matches: list[RegexMatch] = []
        for span in spans:
            matches = self.scan_span(span)
            if matches:
                all_matches.extend(matches)
                if self.mode == "fail_fast":
                    return all_matches
        return all_matches

    def __len__(self) -> int:
        return len(self.rules)
