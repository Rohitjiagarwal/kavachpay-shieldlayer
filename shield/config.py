"""Build the 3-Layer Zero-Judge Security Funnel from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

from shared.envfile import load_env
from shield.funnel import Funnel, VerdictCache
from shield.intent_extractor import IntentExtractor
from shield.policy_gate import PolicyGate
from shield.regex_layer import RegexLayer

ROOT = Path(__file__).resolve().parents[1]
load_env()  # pick up GEMINI_API_KEY etc. from the gitignored .env


def build_funnel(env: dict | None = None) -> Funnel:
    """Build the 3-Layer Security Pipeline."""
    env = env or os.environ
    layer1 = RegexLayer()
    layer2 = IntentExtractor(env=env)
    layer3 = PolicyGate()

    return Funnel(
        layer1=layer1,
        layer2=layer2,
        layer3=layer3,
        chat_fail_mode=env.get("CHAT_FAIL_MODE", "open"),
        doc_fail_mode=env.get("DOC_FAIL_MODE", "closed"),
        cache=VerdictCache(),
    )


def layer2_provider_label(env: dict | None = None) -> str:
    """Return descriptive label for the active Layer 2 intent extractor provider."""
    env = env or os.environ
    mode = env.get("LAYER2_PROVIDER", "auto").lower()
    if mode == "gemini" or (mode == "auto" and env.get("GEMINI_API_KEY")):
        model = env.get("GEMINI_MODEL", "gemini-flash-lite-latest")
        return f"Gemini ({model})"
    if mode == "ollama":
        model = env.get("OLLAMA_MODEL", "qwen2.5:3b")
        return f"Ollama ({model})"
    return "Deterministic Heuristic Extractor"
