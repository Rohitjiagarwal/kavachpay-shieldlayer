"""Shared contracts used by every ShieldLayer service.

The `Decision` record is the single source of truth for a funnel check. It is
produced by Layer 1 (regex), Layer 2 (classifier) or Layer 3 (judge) and is
written to SQLite, streamed to the dashboard and aggregated into the scorecard.

Nothing in here imports a service-specific dependency, so both the `shield`
service and the `app` backend can share it.
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Verdict(str, Enum):
    allow = "allow"
    block = "block"


class Layer(str, Enum):
    # 3-Layer Zero-Judge Architecture
    layer1 = "layer1"
    layer2 = "layer2"
    layer3 = "layer3"
    # Legacy / alias references for backward compatibility
    regex = "regex"
    classifier = "classifier"
    judge = "judge"
    provenance = "provenance"
    none = "none"


class Source(str, Enum):
    user = "user"
    document = "document"
    tool = "tool"


# OWASP categories. Kept as plain strings so new items are easy to add.
OWASP_LLM = [f"LLM{n:02d}" for n in range(1, 11)]
OWASP_ASI = [f"ASI{n:02d}" for n in range(1, 11)]
OWASP_ALL = OWASP_LLM + OWASP_ASI + ["NONE"]
OwaspId = str


# --------------------------------------------------------------------------- #
# Layer 2: Quarantined Intent Extractor Contracts
# --------------------------------------------------------------------------- #
class ExtractedIntent(BaseModel):
    """A single isolated intent extracted from normalized user text."""
    intent: str
    target_id: str | None = None
    parameters: dict = Field(default_factory=dict)
    neutral_summary: str = ""


class Layer2Extraction(BaseModel):
    """Strict schema-enforced output from Layer 2 (no allow/block decision)."""
    intents: list[ExtractedIntent] = Field(default_factory=list)
    claimed_authority: str | None = None
    urgency_or_override_tone: bool = False
    multi_intent_detected: bool = False
    extraction_failed: bool = False
    provider_used: str = ""
    latency_ms: float = 0.0


# --------------------------------------------------------------------------- #
# Layer 3: Deterministic Policy & Symbolic Gate Contracts
# --------------------------------------------------------------------------- #
class PolicyResult(BaseModel):
    """Deterministic verdict produced by Layer 3 (zero AI, zero numeric scores)."""
    verdict: Verdict = Verdict.allow
    rule_id: str | None = None
    reason: str = ""
    owasp: OwaspId = "NONE"
    authority_spoofing: bool = False
    rbac_passed: bool = True
    abac_passed: bool = True
    allowed_intents: list[str] = Field(default_factory=list)
    blocked_intents: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Legacy Judge contracts (preserved for backwards compatibility during migration)
# --------------------------------------------------------------------------- #
class JudgeInput(BaseModel):
    """What the funnel hands to a judge backend."""

    text: str
    source: Source = Source.user
    # Up to the last 3 turns for chat, so multi-turn set-ups are visible.
    context: list[str] = Field(default_factory=list)


class JudgeVerdict(BaseModel):
    """The strict shape every judge backend (Claude / Ollama) must return."""

    verdict: Verdict
    owasp: OwaspId = "NONE"
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    reason: str = Field(default="", max_length=400)


# --------------------------------------------------------------------------- #
# The Decision record
# --------------------------------------------------------------------------- #
class Decision(BaseModel):
    """One funnel decision, from any layer."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    ts: float = Field(default_factory=time.time)

    source: Source = Source.user
    text_preview: str = ""  # first ~200 chars, never the full secret-bearing text
    text_sha256: str = ""

    verdict: Verdict = Verdict.allow
    layer: Layer = Layer.none
    owasp: OwaspId = "NONE"

    # New 3-Layer Zero-Judge metadata
    layer2_extraction: Layer2Extraction | None = None
    policy_result: PolicyResult | None = None

    # Legacy scores & judge metadata preserved as optional
    raw_score: float | None = None
    score: float | None = None
    confidence: float | None = None

    reason: str = ""
    rule_id: str | None = None  # which regex rule fired, if any

    # provenance / cost
    judge_provider: str | None = None  # "anthropic" | "ollama" | None
    judge_model: str | None = None
    latency_ms: float = 0.0
    cost_usd: float | None = 0.0

    # context
    doc_id: str | None = None
    chunk_id: str | None = None
    session_id: str | None = None
    customer_id: str | None = None

    def blocked(self) -> bool:
        return self.verdict == Verdict.block


class ScanItem(BaseModel):
    """One item in a POST /scan request."""

    id: str | None = None
    text: str
    source: Source = Source.user
    context: list[str] = Field(default_factory=list)


class ScanRequest(BaseModel):
    items: list[ScanItem]
    # Restrict which layers run. None = full funnel. Used by the attack runner
    # to measure each setup (e.g. ["regex"], ["regex","classifier"]).
    layers: list[Layer] | None = None
    fail_mode: Literal["open", "closed"] | None = None


class ScanResponse(BaseModel):
    results: list[Decision]
