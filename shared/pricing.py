"""One place for model prices, so cost numbers on the dashboard stay honest.

Prices are USD per 1,000,000 tokens. Update this table when prices change; the
dashboard and scorecard read `cost_usd` which is computed here.

A local Ollama model is free ($0). An Ollama *cloud* model with no price listed
reports ``None`` (shown as "n/a"), never a guessed number.
"""
from __future__ import annotations

# USD per 1e6 tokens: (input, output)
PRICES: dict[str, tuple[float, float]] = {
    # Claude (illustrative placeholder values; verify against current pricing)
    "claude-haiku-5-5": (1.00, 5.00),
    "claude-opus-5-5": (15.00, 75.00),
    "claude-sonnet-5-5": (3.00, 15.00),
    # Local Ollama models are free to run.
    "ollama:local": (0.0, 0.0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Cost of one call, or None when the model has no known price."""
    if model.startswith("ollama/local") or model == "ollama:local":
        return 0.0
    price = PRICES.get(model)
    if price is None:
        return None
    pin, pout = price
    return round((input_tokens * pin + output_tokens * pout) / 1_000_000, 8)
