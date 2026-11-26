"""Layer 2 — Quarantined Intent Extractor & Neutralizer.

Strictly isolated module placed directly after Layer 1:
- Accepts ONLY normalized text from Layer 1 (never user role, JWT, session, or tool schemas).
- Operates in a zero-privilege sandbox with no allow/block decision power.
- Emits schema-enforced JSON: intents[], claimed_authority, urgency_or_override_tone, multi_intent.
"""
from __future__ import annotations

import logging

from shared.schemas import Layer2Extraction
from shield.layer2_providers import BaseLayer2Provider, HeuristicProvider, build_layer2_provider

logger = logging.getLogger("shield.intent_extractor")


class IntentExtractor:
    """Layer 2 Quarantined Intent Extractor."""

    def __init__(
        self,
        provider: BaseLayer2Provider | None = None,
        env: dict | None = None,
    ):
        self.provider = provider or build_layer2_provider(env)
        self.heuristic_fallback = HeuristicProvider()

    def extract(self, normalized_text: str) -> Layer2Extraction:
        """Extract schema-enforced intent bundle from normalized text.

        Guarantees isolation: this method takes only a text string.
        """
        if not normalized_text or not normalized_text.strip():
            return Layer2Extraction(
                intents=[],
                claimed_authority=None,
                urgency_or_override_tone=False,
                multi_intent_detected=False,
                extraction_failed=False,
                provider_used="empty_input",
                latency_ms=0.0,
            )

        try:
            res = self.provider.extract(normalized_text)
            if res.extraction_failed:
                # Check if we should fall back to heuristic for demo mode
                import os
                if os.environ.get("LAYER2_ALLOW_HEURISTIC_FALLBACK", "true").lower() in ("true", "1", "yes"):
                    logger.info("Primary Layer 2 provider failed; invoking heuristic live fallback")
                    fallback_res = self.heuristic_fallback.extract(normalized_text)
                    fallback_res.provider_used = f"{fallback_res.provider_used}_fallback"
                    return fallback_res
            return res
        except Exception as e:
            logger.error(f"Unexpected error in Layer 2 extraction: {e}")
            import os
            if os.environ.get("LAYER2_ALLOW_HEURISTIC_FALLBACK", "true").lower() in ("true", "1", "yes"):
                fallback_res = self.heuristic_fallback.extract(normalized_text)
                fallback_res.provider_used = "heuristic_exception_fallback"
                return fallback_res

            return Layer2Extraction(
                extraction_failed=True,
                provider_used="error",
                latency_ms=0.0,
            )
