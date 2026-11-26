"""Stage 1A: Canonicalization & De-obfuscation Engine.

Normalizes untrusted input (user messages, documents, tool outputs) into an
InspectionBundle containing canonicalized text plus recursively unpacked payloads.
Never runs pattern matching on raw input.
"""
from __future__ import annotations

import base64
import html
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Control, Zero-Width, and Bidi (Trojan Source) Character Sets
# --------------------------------------------------------------------------- #
_INVISIBLE_CHARS = frozenset({
    "\u200b",  # Zero-width space
    "\u200c",  # Zero-width non-joiner
    "\u200d",  # Zero-width joiner
    "\u2060",  # Word joiner
    "\ufeff",  # Zero-width no-break space / BOM
    "\u00ad",  # Soft hyphen
    "\u200e",  # Left-to-right mark
    "\u200f",  # Right-to-left mark
    "\u2028",  # Line separator
    "\u2029",  # Paragraph separator
})

# ASCII control chars excluding standard whitespace (\t = 9, \n = 10, \r = 13)
_ASCII_CONTROL_CHARS = frozenset(
    chr(i) for i in list(range(0, 9)) + [11, 12] + list(range(14, 32)) + [127]
)

# Unicode Bidirectional (Bidi / Trojan Source) overrides
_BIDI_OVERRIDES = frozenset({
    "\u202a",  # Left-to-Right Embedding
    "\u202b",  # Right-to-Left Embedding
    "\u202c",  # Pop Directional Formatting
    "\u202d",  # Left-to-Right Override
    "\u202e",  # Right-to-Left Override
    "\u2066",  # Left-to-Right Isolate
    "\u2067",  # Right-to-Left Isolate
    "\u2068",  # First Strong Isolate
    "\u2069",  # Pop Directional Isolate
})

# --------------------------------------------------------------------------- #
# High-Frequency Homoglyph Translation Table (Cyrillic, Greek, Latin Lookalikes)
# --------------------------------------------------------------------------- #
_HOMOGLYPH_MAP: dict[str, str] = {
    # Cyrillic lowercase
    "а": "a", "с": "c", "е": "e", "о": "o", "р": "p", "х": "x",
    "і": "i", "ј": "j", "ѕ": "s", "у": "y", "в": "b", "к": "k",
    "м": "m", "н": "h", "т": "t", "ԁ": "d", "ԛ": "q", "ԝ": "w",
    "ї": "i", "г": "r", "з": "3", "б": "6",
    # Cyrillic uppercase
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "І": "I",
    "Ј": "J", "К": "K", "М": "M", "О": "O", "Р": "P", "Ѕ": "S",
    "Т": "T", "Х": "X", "У": "Y", "Ԃ": "D",
    # Greek lowercase
    "α": "a", "β": "b", "γ": "y", "δ": "d", "ε": "e", "η": "n",
    "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
    "υ": "u", "χ": "x", "ω": "w",
    # Greek uppercase
    "Α": "A", "Β": "B", "Γ": "G", "Δ": "D", "Ε": "E", "Ζ": "Z",
    "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    # Latin extended & other confusables
    "ı": "i", "ł": "l", "ø": "o", "đ": "d", "ƀ": "b", "ﬀ": "ff",
    "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
}
_HOMOGLYPH_TRANS = str.maketrans(_HOMOGLYPH_MAP)

# Base64 candidate regex: standard Base64 blocks of length >= 16 (multiple of 4)
_BASE64_PATTERN = re.compile(
    r"(?:[A-Za-z0-9+/]{4}){4,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?"
)

# Hex escape regex: \x69\x67...
_HEX_ESCAPE_PATTERN = re.compile(r"(?:\\[xX][0-9a-fA-F]{2})+")

# URL-encoded hex regex: %20, %3C...
_URL_ENCODED_PATTERN = re.compile(r"%[0-9a-fA-F]{2}")


@dataclass(frozen=True)
class InspectionBundle:
    """The canonicalized inspection bundle produced by Stage 1A."""

    original_text: str
    canonical_text: str
    decoded_payloads: list[str] = field(default_factory=list)
    all_spans: list[str] = field(default_factory=list)
    obfuscation_signals: list[str] = field(default_factory=list)
    invisible_chars_count: int = 0
    bidi_overrides_count: int = 0
    homoglyphs_count: int = 0
    decoding_depth: int = 0


class Normalizer:
    """Transforms raw text into an inspection bundle using a 5-step pipeline."""

    def __init__(
        self,
        max_depth: int = 3,
        max_buffer_size: int = 64_000,
        bidi_block_threshold: int = 1,
        invisible_block_threshold: int = 5,
    ):
        self.max_depth = max_depth
        self.max_buffer_size = max_buffer_size
        self.bidi_block_threshold = bidi_block_threshold
        self.invisible_block_threshold = invisible_block_threshold

    def canonicalize(self, text: str) -> InspectionBundle:
        """Execute Stage 1A normalization on the input text."""
        if not text:
            return InspectionBundle(
                original_text="",
                canonical_text="",
                decoded_payloads=[],
                all_spans=[""],
                obfuscation_signals=[],
            )

        signals: list[str] = []

        # 1. Unicode NFKC Normalization
        # Collapses mathematical bold/italic, fullwidth characters, circles, etc.
        nfkc_text = unicodedata.normalize("NFKC", text)

        # 2. Invisible, Control & Bidi Stripping
        invisible_count = 0
        bidi_count = 0
        cleaned_chars: list[str] = []

        for ch in nfkc_text:
            if ch in _BIDI_OVERRIDES:
                bidi_count += 1
            elif ch in _INVISIBLE_CHARS or ch in _ASCII_CONTROL_CHARS:
                invisible_count += 1
            else:
                cleaned_chars.append(ch)

        if invisible_count > 0:
            signals.append("zero_width_stripped")
        if bidi_count > 0:
            signals.append("bidi_override_stripped")
        if bidi_count >= self.bidi_block_threshold or invisible_count >= self.invisible_block_threshold:
            signals.append("obfuscation_detected")

        stripped_text = "".join(cleaned_chars)

        # 3. Homoglyph Resolution
        homoglyphs_count = sum(1 for c in stripped_text if c in _HOMOGLYPH_MAP)
        if homoglyphs_count > 0:
            homoglyphs_resolved = stripped_text.translate(_HOMOGLYPH_TRANS)
            signals.append("homoglyphs_normalized")
        else:
            homoglyphs_resolved = stripped_text

        # 4. Recursive Decoding (URL, Hex, HTML, Base64) with depth cap
        # We run unpacking on case-preserved text because Base64 is case-sensitive!
        decoded_payloads: list[str] = []
        depth_reached = self._unpack_payloads(
            homoglyphs_resolved,
            decoded_payloads,
            signals,
            current_depth=0,
        )

        # 5. Case Folding & Whitespace Normalization
        canonical_text = self._normalize_whitespace_and_case(homoglyphs_resolved)
        normalized_payloads = [
            self._normalize_whitespace_and_case(p) for p in decoded_payloads
        ]

        # Remove duplicate spans while preserving order
        all_spans: list[str] = []
        seen = set()
        for span in [canonical_text] + normalized_payloads:
            s_clean = span.strip()
            if s_clean and s_clean not in seen:
                seen.add(s_clean)
                all_spans.append(s_clean)

        if not all_spans:
            all_spans = [canonical_text]

        return InspectionBundle(
            original_text=text,
            canonical_text=canonical_text,
            decoded_payloads=normalized_payloads,
            all_spans=all_spans,
            obfuscation_signals=list(dict.fromkeys(signals)),
            invisible_chars_count=invisible_count,
            bidi_overrides_count=bidi_count,
            homoglyphs_count=homoglyphs_count,
            decoding_depth=depth_reached,
        )

    @staticmethod
    def _normalize_whitespace_and_case(s: str) -> str:
        """Lowercases and collapses excessive horizontal whitespace while preserving lines."""
        casefolded = s.lower()
        normalized_lines = [
            re.sub(r"[^\S\r\n]+", " ", line).strip()
            for line in casefolded.splitlines()
        ]
        return "\n".join(normalized_lines)

    def _unpack_payloads(
        self,
        text: str,
        results: list[str],
        signals: list[str],
        current_depth: int,
    ) -> int:
        """Recursively decode URL, hex, HTML entities, and base64 payloads."""
        if current_depth >= self.max_depth or len(text) > self.max_buffer_size:
            return current_depth

        max_depth_seen = current_depth
        new_payloads: list[str] = []

        # A. URL-encoded sequences (%20, %3c)
        if _URL_ENCODED_PATTERN.search(text):
            try:
                unquoted = urllib.parse.unquote(text)
                if unquoted != text and self._is_meaningful_text(unquoted):
                    new_payloads.append(unquoted)
                    signals.append("url_decoded")
            except Exception:
                pass

        # B. Hex escape sequences (\x69\x67...)
        if _HEX_ESCAPE_PATTERN.search(text):
            try:
                unhexed = _HEX_ESCAPE_PATTERN.sub(
                    lambda m: bytes.fromhex(
                        m.group(0).replace("\\x", "").replace("\\X", "")
                    ).decode("utf-8", errors="replace"),
                    text,
                )
                if unhexed != text and self._is_meaningful_text(unhexed):
                    new_payloads.append(unhexed)
                    signals.append("hex_decoded")
            except Exception:
                pass

        # C. HTML entities (&lt;system&gt;, &#x69;)
        if "&" in text and (";" in text or "&#" in text):
            try:
                unescaped = html.unescape(text)
                if unescaped != text and self._is_meaningful_text(unescaped):
                    new_payloads.append(unescaped)
                    signals.append("html_entity_decoded")
            except Exception:
                pass

        # D. Standalone Base64 candidate blocks
        for match in _BASE64_PATTERN.finditer(text):
            candidate = match.group(0)
            if len(candidate) < 16:
                continue
            try:
                decoded_bytes = base64.b64decode(candidate, validate=True)
                decoded_text = decoded_bytes.decode("utf-8", errors="strict")
                if self._is_meaningful_text(decoded_text):
                    new_payloads.append(decoded_text)
                    signals.append("base64_decoded")
            except Exception:
                pass

        # Recurse on newly uncovered payloads
        for payload in new_payloads:
            # Normalize NFKC and strip, but preserve case during recursion for Base64!
            clean_payload = unicodedata.normalize("NFKC", payload).strip()
            if clean_payload and clean_payload not in results and clean_payload != text:
                results.append(clean_payload)
                deeper = self._unpack_payloads(
                    clean_payload,
                    results,
                    signals,
                    current_depth + 1,
                )
                if deeper > max_depth_seen:
                    max_depth_seen = deeper

        return max_depth_seen

    @staticmethod
    def _is_meaningful_text(s: str) -> bool:
        """Check if decoded bytes form printable, non-trivial text."""
        stripped = s.strip()
        if len(stripped) < 3:
            return False
        # Ensure at least 80% printable characters
        printable_count = sum(1 for c in stripped if c.isprintable() or c in "\n\r\t")
        return (printable_count / len(stripped)) >= 0.8
