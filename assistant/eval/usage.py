"""Token usage and what it cost.

Prices are USD per million tokens, first-party API list prices as of
2026-06. Cache writes are the 5-minute TTL (the agent loop's
`cache_control: ephemeral` default): 1.25x input. Cache reads: 0.1x input.
A model missing from this table is reported with cost None, never as free.
"""

from __future__ import annotations

from typing import Any

USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

PRICE_PER_MTOK = {
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def usage_dict(usage: Any) -> dict[str, int]:
    """The four fields, with the SDK's optional cache fields as 0."""
    if usage is None:
        return {name: 0 for name in USAGE_FIELDS}
    if isinstance(usage, dict):
        return {name: int(usage.get(name) or 0) for name in USAGE_FIELDS}
    return {name: int(getattr(usage, name, 0) or 0) for name in USAGE_FIELDS}


def add(total: dict[str, int], usage: dict[str, int]) -> dict[str, int]:
    return {name: total.get(name, 0) + usage.get(name, 0) for name in USAGE_FIELDS}


def zero() -> dict[str, int]:
    return {name: 0 for name in USAGE_FIELDS}


def cost_usd(model: str, usage: dict[str, int]) -> float | None:
    price = PRICE_PER_MTOK.get(model)
    if price is None:
        return None
    per_token_in = price["input"] / 1_000_000
    return (
        usage["input_tokens"] * per_token_in
        + usage["cache_creation_input_tokens"] * per_token_in * CACHE_WRITE_MULTIPLIER
        + usage["cache_read_input_tokens"] * per_token_in * CACHE_READ_MULTIPLIER
        + usage["output_tokens"] * price["output"] / 1_000_000
    )


class BudgetGuard:
    """Decides whether one more episode or judgement fits in a budget.

    A call cannot be stopped halfway without corrupting the record, so the
    check happens before each one, against the most expensive one seen so far
    times a margin (or `first_estimate` before anything has run)."""

    MARGIN = 1.5

    def __init__(self, first_estimate: float) -> None:
        self.first_estimate = first_estimate
        self.most_expensive = 0.0

    def observe(self, cost: float) -> None:
        self.most_expensive = max(self.most_expensive, cost)

    def next_estimate(self) -> float:
        return max(self.first_estimate, self.most_expensive * self.MARGIN)
