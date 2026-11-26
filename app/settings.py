"""App settings, read from the environment with sensible demo defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from shared.envfile import load_env

load_env()  # gitignored .env (e.g. GEMINI_API_KEY for Layer 2 / chat)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "app" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    chat_model: str = os.environ.get("CHAT_MODEL", "claude-opus-5-5")
    helper_model: str = os.environ.get("HELPER_MODEL", "claude-haiku-5-5")
    anthropic_key: str | None = os.environ.get("ANTHROPIC_API_KEY") or None
    shield_url: str = os.environ.get("SHIELD_URL", "http://127.0.0.1:8090")
    admin_token: str = os.environ.get("ADMIN_TOKEN", "dev-admin-token")
    db_path: str = os.environ.get("APP_DB", str(DATA_DIR / "kavachpay.db"))
    parser: str = os.environ.get("PARSER", "pymupdf")
    min_relevance: float = float(os.environ.get("MIN_RELEVANCE", "0.3"))
    # Contextual Retrieval: situate each clean chunk with an LLM-written blurb
    # (embedded with the chunk) before indexing. Keyless via Ollama.
    enrich_context: bool = os.environ.get("ENRICH_CONTEXT", "false").lower() == "true"
    ollama_host: str = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    ollama_model: str | None = os.environ.get("OLLAMA_MODEL") or None
    # Chat model for the assistant: "auto" picks the best installed Ollama chat model;
    # "gemini" uses GEMINI_API_KEY (the hosted demo uses one key for chat and judge).
    chat_provider: str = os.environ.get("CHAT_PROVIDER", "auto")  # auto|ollama|gemini|stub
    chat_ollama_model: str = os.environ.get("CHAT_OLLAMA_MODEL", "auto")
    gemini_key: str | None = os.environ.get("GEMINI_API_KEY") or None
    gemini_chat_model: str = os.environ.get("GEMINI_CHAT_MODEL", "gemini-flash-lite-latest")
    layer2_provider: str = os.environ.get("LAYER2_PROVIDER", "auto")
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
    layer2_allow_heuristic: bool = os.environ.get("LAYER2_ALLOW_HEURISTIC_FALLBACK", "true").lower() in ("true", "1", "yes")
    session_secret: str = os.environ.get("SESSION_SECRET", "dev-session-secret-change-me")
    seed: int = int(os.environ.get("SEED", "1337"))

    # --- Public demo mode (the hosted live link) ---------------------------- #
    # Each visitor gets DEMO_REQUEST_LIMIT model-backed requests (chat messages +
    # uploads) in total, unless they attach their own Gemini key. DEMO_IP_LIMIT
    # and DEMO_DAILY_LIMIT are backstops for cookie clearing and abuse.
    public_demo: bool = os.environ.get("PUBLIC_DEMO", "0") == "1"
    demo_request_limit: int = int(os.environ.get("DEMO_REQUEST_LIMIT", "4"))
    demo_ip_limit: int = int(os.environ.get("DEMO_IP_LIMIT", "12"))
    demo_daily_limit: int = int(os.environ.get("DEMO_DAILY_LIMIT", "250"))
    # shared demo account data is reseeded when idle this long (minutes)
    demo_reset_minutes: int = int(os.environ.get("DEMO_RESET_MINUTES", "20"))
    upload_max_mb: float = float(os.environ.get("UPLOAD_MAX_MB", "10"))
    # read the client IP from X-Forwarded-For (only behind a proxy you trust)
    trust_proxy: bool = os.environ.get("TRUST_PROXY", "0") == "1"
    # serve the static dashboard build (dashboard/out) from the API itself
    dashboard_dir: str = os.environ.get("DASHBOARD_DIR", "")
    # split frontend/backend (e.g. Vercel + Render): comma-separated origins + SameSite=None cookies
    cors_origins: str = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    cors_origin_regex: str = os.environ.get("CORS_ORIGIN_REGEX", "")
    cross_site_cookies: bool = os.environ.get("CROSS_SITE_COOKIES", "0") == "1"

    def chat_enabled(self) -> bool:
        return bool(self.anthropic_key)


SETTINGS = Settings()
