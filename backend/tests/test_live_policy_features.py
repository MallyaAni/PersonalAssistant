"""Pin exact-prefix feature reuse and actual nightly account equivalence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import event_risk
from backend.agents.trading.desk.grading import Graded
from backend.cli import market_daily
from backend.market.live_policy_features import FeatureCache
from backend.market.live_policy_replay import run_account
from backend.market.live_policy_report import NightlyReport
from backend.market.panel import Panel
from backend.tests.test_live_policy_replay import fixture


# Supply a long causal prefix with ties, a missing series and dividend adjustment.
def report(scale=1.0, columns=(0, 1, 2)):
    dates = np.busday_offset("2024-01-02", np.arange(300))
    growing = 100 * 1.01 ** np.arange(300)
    close = np.column_stack((growing, growing * 0.7, np.full(300, 100.0)))
    close[12, 1] = np.nan
    names = tuple(("AAA", "BBB", "SPY")[column] for column in columns)
    close = close[:, columns] * scale
    adjusted = close.copy()
    adjusted[:150] *= 0.99
    panel = Panel(
        dates,
        names,
        close.copy(),
        close * 1.01,
        close * 0.99,
        close.copy(),
        adjusted,
        np.ones_like(close),
        {name: ("synthetic",) for name in names},
        "SPY",
    )
    grades = np.tile([3, 2, 0], (300, 1))[:, columns]
    return NightlyReport(
        panel,
        Graded(grades, np.zeros_like(close), {}),
        {},
        grades.astype(float),
        (),
        {"basis": "entire_prefix_current_raw_share_units", "scale": scale},
    )


# Compare every cached verdict with the original current-basis arithmetic.
@pytest.mark.parametrize(
    ("scale", "columns"),
    [(1.0, (0, 1, 2)), (1.5, (0, 1, 2)), (0.1, (1, 0, 2)), (1.0, (0, 2))],
)
def test_cache_preserves_full_prefix_verdicts(scale, columns):
    value = report(scale, columns)
    cache = FeatureCache("a" * 64)
    expected = {
        "event": event_risk.decision(value.panel),
        "blocked": market_daily._band_blocked(value),
        "entries": market_daily._price_entries(value),
    }
    for kind, original in expected.items():
        assert cache(kind, value) == original
        assert cache(kind, value) == original
        assert cache.computations[kind] == 1
        assert cache.hits[kind] == 1


# Keep floating-point-sensitive share bases distinct instead of normalizing them.
def test_scale_equivalence_is_not_assumed_for_tied_widths():
    value = report()
    flat_adjustment = replace(value.panel, adj_close=value.panel.close.copy())
    value = replace(value, panel=flat_adjustment)
    scaled = replace(
        value,
        panel=replace(
            flat_adjustment,
            open=flat_adjustment.open / 1.5,
            high=flat_adjustment.high / 1.5,
            low=flat_adjustment.low / 1.5,
            close=flat_adjustment.close / 1.5,
            adj_close=flat_adjustment.adj_close / 1.5,
        ),
    )
    cache = FeatureCache("a" * 64)
    assert cache("blocked", value) == market_daily._band_blocked(value)
    assert cache("blocked", scaled) == market_daily._band_blocked(scaled)
    assert cache.computations["blocked"] == 2


# Invalidate a previous key for any changed consumed bytes or identity metadata.
@pytest.mark.parametrize(
    "change",
    ["past_price", "dates", "grades", "volume", "benchmark", "themes", "provenance"],
)
def test_changed_prefix_never_reuses_an_old_key(change):
    value = report()
    cache = FeatureCache("a" * 64)
    cache("blocked", value)
    if change in ("past_price", "volume"):
        field = "close" if change == "past_price" else "volume"
        array = getattr(value.panel, field).copy()
        array[0, 0] *= 2
        changed = replace(value, panel=replace(value.panel, **{field: array}))
    elif change == "dates":
        changed = replace(
            value,
            panel=replace(
                value.panel, dates=value.panel.dates - np.timedelta64(1, "D")
            ),
        )
    elif change == "grades":
        grades = value.graded.grades.copy()
        grades[-1, 0] = 0
        changed = replace(value, graded=replace(value.graded, grades=grades))
    elif change == "benchmark":
        changed = replace(value, panel=replace(value.panel, benchmark="BBB"))
    elif change == "themes":
        changed = replace(value, panel=replace(value.panel, themes={}))
    else:
        changed = replace(value, provenance={"basis": "different_source"})
    assert cache("blocked", changed) == market_daily._band_blocked(changed)
    assert cache.computations["blocked"] == 2


# Preserve earlier verdicts when a later source row outside the report changes.
def test_future_rows_do_not_enter_an_earlier_cache_key():
    value = report()
    original = value.panel.close.copy()
    earlier = replace(value, panel=replace(value.panel, close=original[:300].copy()))
    future = np.vstack((original, np.full((1, 3), 999999.0)))
    future[-1] *= 100
    same_prefix = replace(
        earlier, panel=replace(earlier.panel, close=future[:300].copy())
    )
    cache = FeatureCache("a" * 64)
    assert cache("blocked", earlier) == cache("blocked", same_prefix)
    assert cache.computations["blocked"] == 1


# Prevent account callers from mutating the cache's shared policy outputs or receipts.
def test_cached_outputs_are_detached():
    value = report()
    cache = FeatureCache("a" * 64)
    blocked, flags = cache("blocked", value)
    blocked.add("invented")
    flags["AAA"] = not flags["AAA"]
    policy = cache("event", value)
    policy["factor"] = -100
    receipt = cache.receipt()
    receipt["computations"]["event"] = 99
    assert cache("blocked", value) == market_daily._band_blocked(value)
    assert cache("event", value) == event_risk.decision(value.panel)
    assert cache.computations["event"] == 1


# Refuse unsupported sources, feature names and ambiguous prefix alignment.
def test_invalid_cache_dependencies_are_rejected():
    with pytest.raises(ValueError, match="source SHA256"):
        FeatureCache("not authenticated")
    cache = FeatureCache("a" * 64)
    with pytest.raises(ValueError, match="Unsupported"):
        cache("allocation", report())
    with pytest.raises(ValueError, match="nightly report"):
        cache("blocked", object())
    value = report()
    with pytest.raises(ValueError, match="Aligned"):
        cache(
            "blocked",
            replace(value, panel=replace(value.panel, dates=value.panel.dates[::-1])),
        )
    assert not cache.receipt()["entries"]


# Preserve real account decisions while allowing truthful runtime receipt timestamps.
def test_actual_account_is_unchanged_by_feature_reuse(tmp_path):
    started = datetime.now(UTC) - timedelta(seconds=1)
    panel, raw, cubes = fixture()
    cache = FeatureCache("a" * 64)
    original = run_account(panel, raw, cubes, tmp_path / "original", 1, 2, 10)
    first = run_account(
        panel, raw, cubes, tmp_path / "first", 1, 2, 10, feature_reader=cache
    )
    second = run_account(
        panel, raw, cubes, tmp_path / "second", 1, 2, 10, feature_reader=cache
    )
    ended = datetime.now(UTC)
    for result in (original, first, second):
        for row in result["paper_state"]["history"]:
            assert started <= datetime.fromisoformat(row.pop("written")) <= ended
    for key in (
        "sessions",
        "intents",
        "observations",
        "fills",
        "broker",
        "paper_state",
    ):
        assert original[key] == first[key] == second[key]
    assert cache.computations["blocked"] == 3
    assert cache.hits["blocked"] == 3
    assert first["sessions"][-1]["nav"] == 100225.25


# Refuse feature injection into ordinary live calls before touching state or a broker.
def test_feature_reader_requires_private_broker_and_clock(tmp_path):
    with pytest.raises(ValueError, match="explicit broker and clock"):
        market_daily.paper_trade(
            report(),
            tmp_path / "not_created",
            "2025-02-24",
            True,
            feature_reader=FeatureCache("a" * 64),
        )
    assert not (tmp_path / "not_created").exists()


# Keep event-only planning lazy so an unused entry feature is never evaluated.
def test_event_plan_does_not_read_ordinary_entries(tmp_path, monkeypatch):
    from backend.agents.trading.desk import nightly_plan

    panel, raw, cubes = fixture()
    monkeypatch.setattr(nightly_plan, "event_plan_required", lambda state, policy: True)
    cache = FeatureCache("a" * 64)
    run_account(panel, raw, cubes, tmp_path / "event", 1, 1, 10, feature_reader=cache)
    assert cache.computations["event"] == 2
    assert cache.computations["entries"] == 0
