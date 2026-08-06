"""Bedrock call-cost arithmetic (``ragrun.pricing``, PLAN.md §6.1).

Bedrock's Converse response never carries a dollar figure (verified live
against ``bedrock-runtime.converse`` while building this: the response has
``output``/``stopReason``/``usage``/``metrics``/``ResponseMetadata`` and
nothing else) -- cost is always *computed* from token counts against a
committed rate table, never read off a response. So the one thing worth
pinning down here is that arithmetic, and that an unmapped model/region
raises rather than silently mispricing. Rate tables are built in a ``tmp_path``
fixture rather than pointed at the real committed ``prices/`` directory, so a
future re-vendored price file can't make this test flaky.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ragrun.pricing import (
    Rates,
    UnknownRate,
    call_cost,
    cost_for_provider,
    load_rates,
)

MODEL_ID = "openai.gpt-oss-120b-1:0"
REGION = "ap-southeast-2"


def _write_table(prices_dir: Path, *, input_usd: str = "0.0001545",
                 output_usd: str = "0.000618") -> None:
    prices_dir.mkdir(parents=True, exist_ok=True)
    table = {
        "rate_table_id": "test-table-2026-08-05",
        "region": REGION,
        "model_id": MODEL_ID,
        "rates": {
            "APS2-input-tokens-standard": {
                "usd_per_unit": input_usd, "unit": "1K tokens"},
            "APS2-output-tokens-standard": {
                "usd_per_unit": output_usd, "unit": "1K tokens"},
        },
    }
    import json
    (prices_dir / "test-table-2026-08-05.json").write_text(json.dumps(table))


def test_load_rates_matches_on_model_and_region(tmp_path: Path) -> None:
    """Matching is by table content (model_id/region fields), not filename --
    a caller never needs to know the dated table id to look one up."""
    _write_table(tmp_path)

    rates = load_rates(MODEL_ID, REGION, prices_dir=tmp_path)

    assert rates.input_per_1k == pytest.approx(0.0001545)
    assert rates.output_per_1k == pytest.approx(0.000618)
    assert rates.table_id == "test-table-2026-08-05"


def test_load_rates_unknown_combo_raises_rather_than_guessing(
        tmp_path: Path) -> None:
    """A wrong rate would silently corrupt every cost figure computed from
    it, so an unmapped (model, region) must be a hard error, not a 0 or a
    fallback to some other table's numbers."""
    _write_table(tmp_path)

    with pytest.raises(UnknownRate):
        load_rates("some-other-model", REGION, prices_dir=tmp_path)
    with pytest.raises(UnknownRate):
        load_rates(MODEL_ID, "us-east-1", prices_dir=tmp_path)


def test_load_rates_rejects_a_non_per_1k_unit(tmp_path: Path) -> None:
    """A per-token (not per-1K-token) table would misprice every call by
    1000x -- this must fail loudly at load time, not silently at call_cost
    time where the bug would look like a normal (if oddly small) cost."""
    import json
    tmp_path.mkdir(parents=True, exist_ok=True)
    table = {
        "rate_table_id": "bad-unit", "region": REGION, "model_id": MODEL_ID,
        "rates": {
            "APS2-input-tokens-standard": {
                "usd_per_unit": "0.0001", "unit": "1 token"},
            "APS2-output-tokens-standard": {
                "usd_per_unit": "0.0002", "unit": "1K tokens"},
        },
    }
    (tmp_path / "bad-unit.json").write_text(json.dumps(table))

    with pytest.raises(Exception, match="1000x"):
        load_rates(MODEL_ID, REGION, prices_dir=tmp_path)


def test_call_cost_bills_uncached_input_plus_cache_write_at_input_rate() -> None:
    """The exact arithmetic, worked out by hand: 1000 uncached + 500 cache-write
    input tokens billed at the input rate, 2000 output tokens at the output
    rate. cache_read tokens are a documented non-billed simplification (no
    separate discounted rate exists in the committed tables)."""
    rates = Rates(input_per_1k=0.0002, output_per_1k=0.0008,
                 tier="standard", table_id="t")
    tokens = {"input_uncached": 1000, "output": 2000,
              "cache_read": 5000, "cache_write": 500}

    cost = call_cost(tokens, rates)

    assert cost is not None
    assert cost["input_usd"] == pytest.approx(0.0002 + 0.0001)  # (1000+500)/1000 * 0.0002
    assert cost["output_usd"] == pytest.approx(0.0016)  # 2000/1000 * 0.0008
    assert cost["usd"] == pytest.approx(0.0002 + 0.0001 + 0.0016)
    assert cost["tier"] == "standard"
    assert cost["rate_table_id"] == "t"


def test_call_cost_returns_none_for_no_tokens() -> None:
    """A step that never reached the model (``tokens: None``) must carry
    ``cost: None`` too, not a fabricated $0."""
    rates = Rates(input_per_1k=0.0002, output_per_1k=0.0008,
                 tier="standard", table_id="t")

    assert call_cost(None, rates) is None
    assert call_cost({}, rates) is None


def test_cost_for_provider_reads_model_id_and_region_off_the_provider(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A helper other systems can use directly (facet_rag's own wiring
    precomputes ``Rates`` once via ``load_rates`` instead, since it needs the
    same rates repeatedly across many short-lived provider instances): cost
    keyed off a live provider object's ``model_id``/``region`` attributes."""
    import ragrun.pricing as pricing_module
    monkeypatch.setattr(pricing_module, "PRICES_DIR", tmp_path)
    _write_table(tmp_path)

    class FakeProvider:
        model_id = MODEL_ID
        region = REGION

    cost = cost_for_provider(FakeProvider(), {"input_uncached": 1000, "output": 500})

    assert cost is not None
    assert cost["usd"] == pytest.approx(
        1000 / 1000 * 0.0001545 + 500 / 1000 * 0.000618)


def test_cost_for_provider_returns_none_for_unpriced_model(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A model/region with no committed rate table degrades to "no cost
    reported" rather than crashing the run -- opportunistic reporting, not a
    hard budget gate (unlike bm25_tune's BudgetGuard, which this module does
    not port)."""
    import ragrun.pricing as pricing_module
    monkeypatch.setattr(pricing_module, "PRICES_DIR", tmp_path)

    class FakeProvider:
        model_id = "unpriced-model"
        region = "nowhere-1"

    cost = pricing_module.cost_for_provider(
        FakeProvider(), {"input_uncached": 1000, "output": 500})

    assert cost is None
