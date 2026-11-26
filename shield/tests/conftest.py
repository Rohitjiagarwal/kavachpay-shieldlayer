"""Shield tests never call the real Gemini key (free-tier quota is precious)."""
import os

os.environ.setdefault("JUDGE_DISABLE_GEMINI", "1")
