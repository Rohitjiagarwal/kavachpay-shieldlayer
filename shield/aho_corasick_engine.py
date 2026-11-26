"""Stage 1B: Aho-Corasick Multi-Pattern Gate.

Pre-compiles an O(n) exact-match automaton from static threat signatures
at startup (never rebuilt per request). Scans all spans from the Stage 1A
inspection bundle across categorized LLM & agentic signatures.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import ahocorasick
import yaml

SIGNATURES_PATH = Path(__file__).resolve().parents[1] / "rules" / "aho_corasick_signatures.yaml"


@dataclass(frozen=True)
class AhoCorasickMatch:
    """An exact signature match detected by Stage 1B."""

    id: str
    phrase: str
    category: str
    severity: Literal["critical", "high", "medium", "low"]
    owasp_ref: str
    mitre_ref: str
    description: str
    matched_span: str = ""
    start_idx: int = 0
    end_idx: int = 0


class AhoCorasickEngine:
    """Pre-compiled Aho-Corasick multi-pattern scanner."""

    def __init__(
        self,
        signatures_path: Path | str = SIGNATURES_PATH,
        mode: Literal["fail_fast", "audit"] = "fail_fast",
    ):
        self.signatures_path = Path(signatures_path)
        self.mode = mode
        self.automaton = ahocorasick.Automaton()
        self.signatures_count = 0
        self._load_and_compile()

    def _load_and_compile(self) -> None:
        """Load signatures and compile the Aho-Corasick trie with failure transitions."""
        if not self.signatures_path.exists():
            raise FileNotFoundError(f"Signatures file not found: {self.signatures_path}")

        data = yaml.safe_load(self.signatures_path.read_text(encoding="utf-8")) or {}
        entries = data.get("signatures", [])

        for sig in entries:
            phrase = sig["phrase"].lower()
            meta = {
                "id": sig["id"],
                "phrase": phrase,
                "category": sig.get("category", "threat"),
                "severity": sig.get("severity", "high"),
                "owasp_ref": sig.get("owasp_ref", "LLM01"),
                "mitre_ref": sig.get("mitre_ref", "AML.T0051"),
                "description": sig.get("description", ""),
            }
            # Associate phrase with its metadata payload in the automaton trie
            self.automaton.add_word(phrase, meta)
            self.signatures_count += 1

        self.automaton.make_automaton()

    def scan_span(self, text: str) -> list[AhoCorasickMatch]:
        """Scan a single string span against the automaton."""
        if not text:
            return []

        text_lower = text.lower()
        matches: list[AhoCorasickMatch] = []

        for end_idx, meta in self.automaton.iter(text_lower):
            phrase_len = len(meta["phrase"])
            start_idx = end_idx - phrase_len + 1
            matched_span = text[start_idx : end_idx + 1]

            match = AhoCorasickMatch(
                id=meta["id"],
                phrase=meta["phrase"],
                category=meta["category"],
                severity=meta["severity"],
                owasp_ref=meta["owasp_ref"],
                mitre_ref=meta["mitre_ref"],
                description=meta["description"],
                matched_span=matched_span,
                start_idx=start_idx,
                end_idx=end_idx,
            )
            matches.append(match)

            # In fail-fast mode, immediately short-circuit on high or critical severity
            if self.mode == "fail_fast" and match.severity in ("critical", "high"):
                return matches

        return matches

    def scan_spans(self, spans: list[str]) -> list[AhoCorasickMatch]:
        """Scan all normalized and unpacked spans from Stage 1A."""
        all_matches: list[AhoCorasickMatch] = []

        for span in spans:
            span_matches = self.scan_span(span)
            if span_matches:
                all_matches.extend(span_matches)
                if self.mode == "fail_fast" and any(
                    m.severity in ("critical", "high") for m in span_matches
                ):
                    return all_matches

        return all_matches

    def __len__(self) -> int:
        return self.signatures_count
