"""How the app reaches the Shield's funnel.

Preferred: HTTP POST to the Shield service's /scan. Fallback: if the Shield
service is not reachable, build the funnel in-process so ingestion and tests run
without a separate service. The mode is reported to the caller.
"""
from __future__ import annotations

import time

import httpx

from app.settings import SETTINGS
from shared.schemas import Decision, ScanItem, ScanRequest, ScanResponse


class ScanClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or SETTINGS.shield_url
        self._inproc = None
        self.mode = "unknown"
        self._http_down_until = 0.0  # skip HTTP for a while after a failure

    def _inprocess(self):
        if self._inproc is None:
            from shield.config import build_funnel

            self._inproc = build_funnel()
        return self._inproc

    def scan(self, items: list[ScanItem], layers=None, fail_mode=None,
             on_step=None, auth_context=None) -> list[Decision]:
        """`on_step` gets live per-layer progress (in-process mode only)."""
        from shared import byok

        # try HTTP first (unless it failed recently). In-process only when no
        # Shield URL is configured (the single-container deploy), or when the
        # visitor brought their own key: that key lives in this process only.
        try:
            if not self.base_url or byok.current():
                raise RuntimeError("in-process scan")
            if time.time() < self._http_down_until:
                raise RuntimeError("shield http recently unavailable")
            req = ScanRequest(items=items, layers=layers, fail_mode=fail_mode)
            r = httpx.post(f"{self.base_url}/scan", json=req.model_dump(mode="json"), timeout=4.0)
            r.raise_for_status()
            self.mode = "http"
            return ScanResponse(**r.json()).results
        except Exception:  # noqa: BLE001
            if self.mode != "in-process":
                self._http_down_until = time.time() + 60
            self.mode = "in-process"
            f = self._inprocess()
            out = []
            for it in items:
                d = f.check(it.text, it.source, it.context, layers=layers, fail_mode=fail_mode,
                            on_step=on_step, auth_context=auth_context)
                if it.id:
                    d.chunk_id = it.id
                out.append(d)
            return out


_client: ScanClient | None = None


def get_scanner() -> ScanClient:
    global _client
    if _client is None:
        _client = ScanClient()
    return _client
