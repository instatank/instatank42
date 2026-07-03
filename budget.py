"""Spend tracking and hard caps. Costs are computed from the API's own usage
numbers after every call and accumulated per-day (IST) in a JSON file, so the
count survives restarts. Non-negotiable guard against runaway loops.
"""

import json
import os
from pathlib import Path

from memory import MEMORY_DIR, now

USAGE_DIR = MEMORY_DIR / "usage"

# USD per million tokens: (input, output). Full sticker prices — Sonnet 5 has
# cheaper intro pricing through 2026-08-31, so this over-estimates (safe side).
PRICES = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
}

DAILY_CAP_USD = float(os.environ.get("DAILY_CAP_USD", "0.50"))


def cost_of(model: str, usage) -> float:
    """Cost in USD of one API response, from its usage block.

    Cache writes bill at 1.25x input price, cache reads at 0.1x.
    """
    inp, out = PRICES[model]
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (
        usage.input_tokens * inp
        + cache_write * inp * 1.25
        + cache_read * inp * 0.10
        + usage.output_tokens * out
    ) / 1_000_000


def _usage_path() -> Path:
    return USAGE_DIR / f"{now().strftime('%Y-%m')}.json"


def _load() -> dict:
    path = _usage_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def add_spend(cost: float) -> None:
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    data = _load()
    key = now().strftime("%Y-%m-%d")
    data[key] = round(data.get(key, 0.0) + cost, 6)
    _usage_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def today_spend() -> float:
    return _load().get(now().strftime("%Y-%m-%d"), 0.0)


def month_spend() -> float:
    return round(sum(_load().values()), 4)


def over_daily_cap() -> bool:
    return today_spend() >= DAILY_CAP_USD
