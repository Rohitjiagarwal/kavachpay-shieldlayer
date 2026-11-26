"""Layer 1 Orchestrator — 3-Stage Deterministic Security Funnel.

Executes sequentially:
  Stage 1A: Canonicalization & De-obfuscation (Unicode NFKC, invisible/bidi stripping, homoglyph mapping, recursive decoding)
  Stage 1B: Aho-Corasick Multi-Pattern Scan (O(n) static threat signatures across OWASP LLM / Agentic / MITRE)
  Stage 1C: Targeted Regex Engine (lean, pre-compiled, ReDoS-safe structural rules)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from shield.aho_corasick_engine import AhoCorasickEngine, AhoCorasickMatch
from shield.normalizer import InspectionBundle, Normalizer
from shield.targeted_regex_engine import RegexMatch, TargetedRegexEngine


@dataclass(frozen=True)
class RuleMatch:
    """A unified detection hit across any sub-stage."""

    rule_id: str
    stage: Literal["stage_1a", "stage_1b", "stage_1c"]
    category: str
    severity: Literal["critical", "high", "medium", "low"]
    owasp_ref: str
    why: str
    matched_span: str = ""


@dataclass
class Layer1Result:
    """The structured result object returned by the Layer 1 Orchestrator."""

    blocked: bool
    stage_triggered: Literal["stage_1a", "stage_1b", "stage_1c"] | None
    matches: list[RuleMatch]
    obfuscation_signals: list[str]
    normalized_text: str
    latency_ms: float
    inspection_bundle: InspectionBundle | None = None

    @property
    def primary_match(self) -> RuleMatch | None:
        return self.matches[0] if self.matches else None


class Layer1Filter:
    """The 3-stage deterministic security funnel orchestrator."""

    def __init__(
        self,
        mode: Literal["fail_fast", "audit"] = "fail_fast",
        aho_corasick_path: Path | str | None = None,
        regex_rules_path: Path | str | None = None,
        block_on_bidi_override: bool = True,
    ):
        self.mode = mode
        self.block_on_bidi_override = block_on_bidi_override

        # Initialize sub-stages
        self.normalizer = Normalizer()
        self.aho_corasick = (
            AhoCorasickEngine(signatures_path=aho_corasick_path, mode=mode)
            if aho_corasick_path
            else AhoCorasickEngine(mode=mode)
        )
        self.targeted_regex = (
            TargetedRegexEngine(rules_path=regex_rules_path, mode=mode)
            if regex_rules_path
            else TargetedRegexEngine(mode=mode)
        )

    def scan(self, text: str) -> Layer1Result:
        """Run untrusted input through Stage 1A -> Stage 1B -> Stage 1C."""
        t0 = time.perf_counter()

        # ------------------------------------------------------------------ #
        # Stage 1A: Canonicalization & De-obfuscation
        # ------------------------------------------------------------------ #
        bundle = self.normalizer.canonicalize(text)
        matches: list[RuleMatch] = []
        stage_triggered: Literal["stage_1a", "stage_1b", "stage_1c"] | None = None

        # Check for active Trojan Source / severe Bidi override injection
        if self.block_on_bidi_override and "bidi_override_stripped" in bundle.obfuscation_signals:
            match = RuleMatch(
                rule_id="obfuscation_bidi_trojan_source",
                stage="stage_1a",
                category="obfuscation",
                severity="high",
                owasp_ref="LLM01",
                why="Unicode Bidirectional (Bidi / Trojan Source) override character detected",
                matched_span="[bidi_override]",
            )
            matches.append(match)
            stage_triggered = "stage_1a"
            if self.mode == "fail_fast":
                return Layer1Result(
                    blocked=True,
                    stage_triggered=stage_triggered,
                    matches=matches,
                    obfuscation_signals=bundle.obfuscation_signals,
                    normalized_text=bundle.canonical_text,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    inspection_bundle=bundle,
                )

        # ------------------------------------------------------------------ #
        # Stage 1B: Aho-Corasick Multi-Pattern Scan on all spans
        # ------------------------------------------------------------------ #
        ac_matches: list[AhoCorasickMatch] = self.aho_corasick.scan_spans(bundle.all_spans)
        if ac_matches:
            for ac_m in ac_matches:
                matches.append(
                    RuleMatch(
                        rule_id=ac_m.id,
                        stage="stage_1b",
                        category=ac_m.category,
                        severity=ac_m.severity,
                        owasp_ref=ac_m.owasp_ref,
                        why=ac_m.description,
                        matched_span=ac_m.matched_span,
                    )
                )
            if not stage_triggered:
                stage_triggered = "stage_1b"

            if self.mode == "fail_fast":
                return Layer1Result(
                    blocked=True,
                    stage_triggered=stage_triggered,
                    matches=matches,
                    obfuscation_signals=bundle.obfuscation_signals,
                    normalized_text=bundle.canonical_text,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    inspection_bundle=bundle,
                )

        # ------------------------------------------------------------------ #
        # Stage 1C: Targeted Regex Engine on surviving input (or all in audit)
        # ------------------------------------------------------------------ #
        # Only inputs that survive Stage 1B reach Stage 1C (or audit mode collects all)
        if not matches or self.mode == "audit":
            rx_matches: list[RegexMatch] = self.targeted_regex.scan_spans(bundle.all_spans)
            if rx_matches:
                for rx_m in rx_matches:
                    matches.append(
                        RuleMatch(
                            rule_id=rx_m.rule_id,
                            stage="stage_1c",
                            category=rx_m.category,
                            severity=rx_m.severity,
                            owasp_ref=rx_m.owasp_ref,
                            why=rx_m.description,
                            matched_span=rx_m.matched_span,
                        )
                    )
                if not stage_triggered:
                    stage_triggered = "stage_1c"

        blocked = len(matches) > 0
        latency_ms = (time.perf_counter() - t0) * 1000

        return Layer1Result(
            blocked=blocked,
            stage_triggered=stage_triggered if blocked else None,
            matches=matches,
            obfuscation_signals=bundle.obfuscation_signals,
            normalized_text=bundle.canonical_text,
            latency_ms=latency_ms,
            inspection_bundle=bundle,
        )
