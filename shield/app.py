"""Shield HTTP service: POST /scan, GET /health, GET /model.

3-Layer Zero-Judge Security Pipeline:
  Layer 1: 3-Stage Deterministic Funnel (1A -> 1B -> 1C)
  Layer 2: Quarantined Intent Extractor & Neutralizer
  Layer 3: Deterministic Policy & Symbolic Gate
"""
from __future__ import annotations

import os

from fastapi import FastAPI

from shared.schemas import Decision, ScanRequest, ScanResponse
from shield.config import build_funnel, layer2_provider_label

app = FastAPI(title="ShieldLayer Shield", version="2.0.0")

_funnel = None


def funnel():
    global _funnel
    if _funnel is None:
        _funnel = build_funnel()
    return _funnel


@app.on_event("startup")
def _startup() -> None:
    funnel()
    provider = layer2_provider_label()
    print(
        f"[shield] 3-Layer Zero-Judge Pipeline initialized. "
        f"L1=3-stage-funnel L2={provider} L3=deterministic-policy-gate"
    )


@app.post("/scan", response_model=ScanResponse)
def scan(req: ScanRequest) -> ScanResponse:
    f = funnel()
    results: list[Decision] = []
    for item in req.items:
        d = f.check(
            text=item.text,
            source=item.source,
            context=item.context,
            layers=req.layers,
            fail_mode=req.fail_mode,
        )
        if item.id:
            d.chunk_id = item.id
        results.append(d)
    return ScanResponse(results=results)


@app.get("/health")
def health() -> dict:
    f = funnel()
    return {
        "status": "ok",
        "pipeline": "3-layer-zero-judge",
        "layer1": "3-stage-deterministic-funnel",
        "layer2": layer2_provider_label(),
        "layer3": "deterministic-policy-gate",
        "cache": {"hits": f.cache.hits, "misses": f.cache.misses},
    }


@app.get("/model")
def model() -> dict:
    return {
        "pipeline": "3-layer-zero-judge",
        "layer1": "3-stage-deterministic-funnel",
        "layer2": layer2_provider_label(),
        "layer3": "deterministic-policy-gate",
        "zero_judge": True,
        "zero_classifier": True,
    }


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("SHIELD_PORT", 8090)))
