"""Bedrock call cost, computed from committed rate tables (PLAN §6.1).

The Converse API response never carries a dollar figure -- only token counts
(``usage.inputTokens``/``outputTokens``/...). Cost has to be *computed*:
``usd = tokens / 1000 * rate``, where ``rate`` comes from a frozen JSON file
under ``prices/`` fetched once from the real AWS Pricing API
(``boto3 pricing.get_products``) and committed -- never a hand-typed number.
An unmapped ``(model_id, region)`` raises ``UnknownRate`` rather than
guessing; a wrong rate would silently misreport every cost figure downstream.

Ported from ``tasks/bm25_tune/bm25tune/pricing.py`` (``Rates``/``load_rates``/
``call_cost`` only -- the budget-ceiling/ledger machinery there is
task-scoped and not needed here).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PRICES_DIR = Path(__file__).resolve().parent / "prices"
EXPECTED_UNIT = "1K tokens"
COST_DP = 8


class PricingError(RuntimeError):
    """A rate table is missing, malformed, or priced in an unexpected unit."""


class UnknownRate(PricingError):
    """No committed rate for the requested (model, region, tier).

    Never falls back to a guessed number -- a wrong rate would silently
    corrupt every cost figure computed from it.
    """


@dataclass(frozen=True)
class Rates:
    """US$ per 1 000 tokens for one (model, region, tier), plus provenance."""

    input_per_1k: float
    output_per_1k: float
    tier: str
    table_id: str


def _model_slug(model_id: str) -> str:
    return model_id.replace(":", "-").replace(".", "-").replace("/", "-")


def _region_slug(region: str) -> str:
    return region.replace("-", "")


def rate_table_path(table_id: str, prices_dir: Path | None = None) -> Path:
    return (prices_dir or PRICES_DIR) / f"{table_id}.json"


def available_tables(prices_dir: Path | None = None) -> list[str]:
    directory = prices_dir or PRICES_DIR
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def load_rates(model_id: str, region: str, tier: str = "standard", *,
               prices_dir: Path | None = None) -> Rates:
    """Rates for one (model, region, tier), matched by table content.

    Every committed table is scanned (there is one file per model/region
    combo actually used, so this stays cheap) rather than requiring the
    caller to know the table's dated filename.
    """
    directory = prices_dir or PRICES_DIR
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            table = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if table.get("model_id") != model_id or table.get("region") != region:
            continue
        return _rates_from_table(table, tier, path)
    raise UnknownRate(
        f"no committed rate table for model={model_id!r} region={region!r} "
        f"under {directory}. Available: {available_tables(prices_dir) or '(none)'}. "
        "Fetch one via boto3 pricing.get_products(ServiceCode=AmazonBedrock) "
        "and commit it -- never hardcode a rate.")


def _rates_from_table(table: dict, tier: str, path: Path) -> Rates:
    rates = table.get("rates", {})
    entries: dict[str, dict] = {}
    for kind in ("input", "output"):
        suffix = f"-{kind}-tokens-{tier}"
        matches = [k for k in rates if k.endswith(suffix)]
        if len(matches) != 1:
            raise UnknownRate(
                f"{path} has {len(matches)} entries ending {suffix!r} "
                f"(expected exactly 1) for tier={tier!r}")
        entries[kind] = rates[matches[0]]
    for kind, entry in entries.items():
        if entry.get("unit") != EXPECTED_UNIT:
            raise PricingError(
                f"{kind} rate in {path} is priced per {entry.get('unit')!r}, "
                f"not {EXPECTED_UNIT!r} -- a per-token table would misreport "
                "cost by 1000x")
    return Rates(
        input_per_1k=float(entries["input"]["usd_per_unit"]),
        output_per_1k=float(entries["output"]["usd_per_unit"]),
        tier=tier,
        table_id=str(table.get("rate_table_id") or path.stem),
    )


def call_cost(tokens: dict[str, Any] | None, rates: Rates) -> dict[str, Any] | None:
    """Cost of one call from its normalized token stats (``usage_token_stats``
    shape: ``input_uncached``/``output``/``cache_read``/``cache_write``), or
    ``None`` when there is nothing to cost.

    Billed input = ``input_uncached + cache_write`` (a cache write is a normal
    input token plus a cache-creation surcharge Bedrock does not break out
    separately in this pricing tier, so it is billed at the plain input rate
    -- a documented undercount, not a guess).
    # ponytail: cache_read tokens are treated as free (no separate discounted
    # rate exists in the committed tables); add a cache-read rate column if a
    # heavily-cached system's report needs to account for it precisely.
    """
    if not tokens:
        return None
    input_billed = int(tokens.get("input_uncached", 0)) + int(tokens.get("cache_write", 0))
    output = int(tokens.get("output", 0))
    input_usd = round(input_billed / 1000.0 * rates.input_per_1k, COST_DP)
    output_usd = round(output / 1000.0 * rates.output_per_1k, COST_DP)
    return {
        "usd": round(input_usd + output_usd, COST_DP),
        "input_usd": input_usd,
        "output_usd": output_usd,
        "tier": rates.tier,
        "rate_table_id": rates.table_id,
    }


_missing_rate_warned: set[tuple[str, str]] = set()


def cost_for_provider(provider: Any, tokens: dict[str, Any] | None,
                      *, tier: str = "standard") -> dict[str, Any] | None:
    """``call_cost`` keyed off a live provider's ``model_id``/``region``.

    Returns ``None`` (and warns once per missing combo) rather than raising,
    so an unpriced model degrades a run's cost report to "unknown" instead of
    crashing the run -- opportunistic reporting, not a hard budget gate.
    """
    model_id = getattr(provider, "model_id", None)
    region = getattr(provider, "region", None)
    if not tokens or not model_id or not region:
        return None
    try:
        rates = load_rates(model_id, region, tier)
    except UnknownRate:
        key = (model_id, region)
        if key not in _missing_rate_warned:
            _missing_rate_warned.add(key)
            log.warning("[COST] no committed rate table for model=%s region=%s "
                       "-- cost will be omitted for these calls", model_id, region)
        return None
    return call_cost(tokens, rates)
