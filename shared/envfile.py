"""Minimal .env loader (no extra dependency).

Reads KEY=VALUE lines from the repo-root `.env` into os.environ **without
overriding** variables that are already set, so the shell/CI always wins.
`.env` is gitignored — secrets such as GEMINI_API_KEY live only there.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_loaded = False


def load_env(path: Path | None = None) -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    p = path or ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v
