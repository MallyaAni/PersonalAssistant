"""OI-only arithmetic and the compatible legacy gamma wrapper.

These synthetic checks qualify field/algorithm boundaries, not OI freshness,
dealer positioning, execution or predictive value.
"""

import math
from dataclasses import asdict, fields
from datetime import date, timedelta

import pytest

from backend.market import live_technical, options

TODAY = date(2026, 9, 25)


# Supply one explicit OI observation without optional chain fields.
def _row(side="put", strike=95.0, oi=500, days=1):
    return options.OIRow(TODAY + timedelta(days=days), side, strike, oi)


# Make absence of fabricated gamma part of the public OI-only representation.
def test_oi_types_contain_only_the_declared_evidence():
    assert {field.name for field in fields(options.OIRow)} == {
        "expiry",
        "kind",
        "strike",
        "open_interest",
    }
    result = options.oi_levels([_row()], 100.0, TODAY)
    assert isinstance(result, options.OILevels)
    assert set(asdict(result)) == {
        "price",
        "expiry",
        "through",
        "put_wall",
        "put_wall_oi",
        "call_wall",
        "call_wall_oi",
    }


# Read only the four required fields into the OI-only row representation.
def test_live_parser_accepts_an_oi_only_frame():
    columns = {
        "expiry": ["2026-09-26"],
        "kind": ["put"],
        "strike": [95.0],
        "open_interest": [500],
    }
    assert live_technical._checked_option_rows(columns, {}) == [_row()]


# Required values cannot acquire usable defaults when they are null.
@pytest.mark.parametrize("field", ["expiry", "kind", "strike", "open_interest"])
def test_live_parser_rejects_null_required_values(field):
    columns = {
        "expiry": ["2026-09-26"],
        "kind": ["put"],
        "strike": [95.0],
        "open_interest": [500],
    }
    columns[field] = [None]
    with pytest.raises((TypeError, ValueError)):
        live_technical._checked_option_rows(columns, {})


# Retain inclusive expiry endpoints and exclude current, expired and far rows.
@pytest.mark.parametrize(("side", "strike"), [("put", 95.0), ("call", 105.0)])
@pytest.mark.parametrize("days", [-7, 0, 1, 60, 61, 90])
def test_oi_expiry_boundaries(side, strike, days):
    result = options.oi_levels([_row(side, strike, days=days)], 100.0, TODAY)
    eligible = 1 <= days <= 60
    assert (
        result.expiry
        == result.through
        == (TODAY + timedelta(days=days) if eligible else None)
    )
    assert getattr(result, f"{side}_wall") == (strike if eligible else None)
    assert getattr(result, f"{side}_wall_oi") == (500 if eligible else 0)


# Keep the raw price-space strike comparisons, including exact boundaries.
@pytest.mark.parametrize(
    ("side", "strike", "accepted"),
    [
        ("put", 75.0, True),
        ("put", 100.0, True),
        ("put", math.nextafter(75.0, 0.0), False),
        ("put", math.nextafter(100.0, math.inf), False),
        ("call", 100.0, True),
        ("call", 125.0, True),
        ("call", math.nextafter(100.0, 0.0), False),
        ("call", math.nextafter(125.0, math.inf), False),
    ],
)
def test_oi_strike_boundaries(side, strike, accepted):
    result = options.oi_levels([_row(side, strike)], 100.0, TODAY)
    assert getattr(result, f"{side}_wall") == (strike if accepted else None)
    assert getattr(result, f"{side}_wall_oi") == (500 if accepted else 0)


# Sum OI by strike across eligible expiries before applying the minimum.
@pytest.mark.parametrize(
    ("total", "accepted"), [(499, False), (500, True), (501, True)]
)
def test_oi_threshold_applies_after_aggregation(total, accepted):
    rows = [_row(oi=250, days=1), _row(oi=total - 250, days=60)]
    result = options.oi_levels(rows, 100.0, TODAY)
    assert result.expiry == TODAY + timedelta(days=1)
    assert result.through == TODAY + timedelta(days=60)
    assert result.put_wall == (95.0 if accepted else None)
    assert result.put_wall_oi == (total if accepted else 0)


# Equal OI still selects the nearer strike independently of row order.
@pytest.mark.parametrize("reverse", [False, True])
def test_oi_ties_choose_the_nearest_strike(reverse):
    rows = [
        _row("put", 90.0),
        _row("put", 95.0),
        _row("call", 110.0),
        _row("call", 105.0),
    ]
    result = options.oi_levels(list(reversed(rows)) if reverse else rows, 100.0, TODAY)
    assert (result.put_wall, result.call_wall) == (95.0, 105.0)
    assert (result.put_wall_oi, result.call_wall_oi) == (500, 500)


# Explicit legacy parameters retain their expiry and minimum-OI interpretation.
def test_oi_respects_explicit_horizon_and_threshold():
    rows = [
        _row(oi=10000, days=1),
        _row(oi=600, days=7),
        _row("call", 105.0, 599, days=14),
        _row(oi=20000, days=15),
    ]
    result = options.oi_levels(rows, 100.0, TODAY, min_days=7, max_days=14, min_oi=600)
    assert result.expiry == TODAY + timedelta(days=7)
    assert result.through == TODAY + timedelta(days=14)
    assert (result.put_wall, result.put_wall_oi) == (95.0, 600)
    assert (result.call_wall, result.call_wall_oi) == (None, 0)


# Empty and nonpositive-price inputs retain the old arithmetic's empty levels.
@pytest.mark.parametrize("price", [0.0, -1.0, 100.0])
@pytest.mark.parametrize("empty", [False, True])
def test_oi_empty_and_nonpositive_price_results(price, empty):
    result = options.oi_levels([] if empty else [_row()], price, TODAY)
    assert result.price == price
    assert result.put_wall == (95.0 if not empty and price > 0 else None)
    assert result.call_wall is None
    assert result.expiry == (None if empty else TODAY + timedelta(days=1))


# Compare shared OI fields while retaining the legacy all-stored-row gamma sum.
@pytest.mark.parametrize("gamma", [0.0, 0.02, math.nan, math.inf, 1e308])
def test_legacy_wrapper_preserves_gamma_and_shared_oi_fields(gamma):
    oi_rows = [
        _row(oi=3000, days=21),
        _row("call", 105.0, 3000, days=21),
        _row("call", 100.0, 1000, days=-7),
        _row("call", 100.0, 1000, days=90),
    ]
    rows = [
        options.ChainRow(
            row.expiry,
            row.kind,
            row.strike,
            row.open_interest,
            1,
            0.5,
            0.02 if i < 2 else gamma,
        )
        for i, row in enumerate(oi_rows)
    ]
    actual = options.walls(rows, 100.0, TODAY)
    expected = options.oi_levels(oi_rows, 100.0, TODAY)
    assert {
        key: value for key, value in asdict(actual).items() if key != "net_gamma"
    } == asdict(expected)
    if math.isnan(gamma):
        assert math.isnan(actual.net_gamma)
    elif math.isinf(gamma) or gamma == 1e308:
        assert actual.net_gamma == math.inf
    else:
        assert actual.net_gamma == pytest.approx(gamma * 200000.0)


# Prove the legacy wrapper delegates OI selection instead of duplicating its math.
def test_legacy_wrapper_calls_the_shared_oi_core(monkeypatch):
    rows = [options.ChainRow(TODAY, "call", 100.0, 500, 1, 0.5, 0.02)]
    sentinel = options.OILevels(100.0, TODAY, 95.0, 600, 105.0, 700, TODAY)
    calls = []

    # Return a distinctive OI result while recording the forwarded policy inputs.
    def shared(found, price, today, min_days, max_days, min_oi):
        calls.append((found, price, today, min_days, max_days, min_oi))
        return sentinel

    monkeypatch.setattr(options, "oi_levels", shared)
    actual = options.walls(rows, 100.0, TODAY, min_days=2, max_days=30, min_oi=600)
    assert calls == [(rows, 100.0, TODAY, 2, 30, 600)]
    assert {
        key: value for key, value in asdict(actual).items() if key != "net_gamma"
    } == asdict(sentinel)
    assert actual.net_gamma == 1000.0


# The full legacy parser must not silently acquire OI-only defaults.
def test_legacy_parser_still_requires_gamma():
    columns = options.frame([options.ChainRow(TODAY, "call", 100.0, 500, 1, 0.5, 0.02)])
    del columns["gamma"]
    with pytest.raises(KeyError, match="gamma"):
        options.rows_from_frame(columns)
