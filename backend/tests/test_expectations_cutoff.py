"""Real desk/Parquet cutoff regressions, stopped before feature work or fitting.

These synthetic snapshots test input selection, not trading performance or
point-in-time completeness of the production market history.
"""

import inspect
import sys
from contextlib import ExitStack
from datetime import UTC, date, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from backend.agents.trading.desk import desk
from backend.cli import market_expectations as mx
from backend.cli.market_fomc import ResearchStore
from backend.market import challenger, edgar, levels_pit, universe
from backend.market.store import MarketStore
from backend.market.yahoo import DailyBar, TickerHistory

HISTORICAL = date(2024, 6, 28)
LATER = date(2025, 1, 2)
NEWEST = date(2025, 2, 3)
SESSIONS = (date(2024, 6, 27), HISTORICAL)
OMITTED = object()


class _BoundaryReached(BaseException):
    """Stop before computation without being hidden by the desk's fallback."""


# Give each synthetic extraction a stable, distinguishable source timestamp.
def _stamp(vintage):
    return datetime.combine(vintage, datetime.min.time(), UTC)


# Store real Parquet bars whose extraction vintage differs from their last session.
def _write_bars(store, vintage, ticker, value):
    closes = (100.0, 101.0) if ticker == "SPY" else (10.0 * value, 11.0 * value)
    bars = tuple(
        DailyBar(day, close, close, close, close, close, 1000)
        for day, close in zip(SESSIONS, closes, strict=True)
    )
    assert store.write(
        vintage,
        TickerHistory(ticker, bars, (), HISTORICAL, _stamp(vintage), "synthetic"),
    )


# Write a real EDGAR frame with distinguishable revised events or revenue values.
def _write_frame(store, vintage, kind, value):
    release = SESSIONS[0] if value == 1 else SESSIONS[1]
    record = edgar.CompanyRecord(
        "SYNTH",
        0,
        (
            edgar.EarningsEvent(
                datetime.combine(release, datetime.min.time(), UTC).replace(hour=12),
                release,
                f"synthetic-release-{value}",
                "2.02",
            ),
        ),
        (
            edgar.QuarterFact(
                "revenue",
                date(2024, 1, 1),
                date(2024, 3, 31),
                100.0 * value,
                release,
            ),
        ),
        _stamp(vintage),
    )
    events, facts = edgar.record_frames(record)
    assert store.write_frame(
        kind,
        vintage,
        "SYNTH",
        events if kind == "edgar_events" else facts,
        {"cik": "0", "source_time": record.source_time.isoformat()},
    )


# Append an immutable synthetic extraction, optionally leaving one input absent.
def _write_partition(store, vintage, value, missing=None):
    _write_bars(store, vintage, "SPY", value)
    if missing != "bars":
        _write_bars(store, vintage, "SYNTH", value)
    for kind in ("edgar_events", "edgar_facts"):
        if missing != kind:
            _write_frame(store, vintage, kind, value)


# Capture actual aligned panel values independently of NumPy array identity.
def _panel_snapshot(panel):
    return {
        "dates": tuple(str(day) for day in panel.dates),
        "close": {
            ticker: tuple(panel.close[:, panel.index(ticker)])
            for ticker in panel.tickers
        },
        "adjusted_close": {
            ticker: tuple(panel.adj_close[:, panel.index(ticker)])
            for ticker in panel.tickers
        },
    }


# Run the real desk, gap caller, panel builder and record loaders without fitting.
def _capture(store, asof=OMITTED):
    observed = {"reads": []}
    stage = "book"
    members = (
        universe.UniverseMember(
            ticker="SYNTH",
            role=universe.FOCUS,
            themes=(universe.SOFTWARE,),
            sector="Synthetic sector",
            sub_industry="Application Software",
        ),
    )
    actual_gap = challenger.expectations_gap
    actual_records = mx._records
    actual_read = store.read
    actual_frame = store.read_frame

    # Observe the real bar result and its selected extraction without replacing it.
    def observe_read(ticker, asof=None):
        result = actual_read(ticker, asof)
        observed["reads"].append(
            (stage, "bars", ticker, asof, result.source_time.date() if result else None)
        )
        return result

    # Observe generic frame reads while delegating all selection to the real store.
    def observe_frame(kind, ticker, asof=None):
        result = actual_frame(kind, ticker, asof)
        observed["reads"].append(
            (stage, kind, ticker, asof, store._latest_of_kind(kind, ticker, asof))
        )
        return result

    # Record the actual desk-to-gap argument and retain the production gap caller.
    def observe_gap(*args, **kwargs):
        nonlocal stage
        bound = inspect.signature(actual_gap).bind(*args, **kwargs)
        bound.apply_defaults()
        observed["gap_asof"] = bound.arguments.get("asof")
        observed["book"] = _panel_snapshot(args[1])
        stage = "gap"
        return actual_gap(*args, **kwargs)

    # Retain real deserialization and reaction conversion before observing results.
    def observe_records(*args, **kwargs):
        result = actual_records(*args, **kwargs)
        observed["records"], observed["quarters"], observed["reactions"] = result
        return result

    # Record real loader inputs and stop before features, datasets or model fitting.
    def stop_before_features(store_arg, panel, records, asof=None):
        assert store_arg is store
        assert records is observed["records"]
        observed["gap_panel"] = _panel_snapshot(panel)
        observed["features_asof"] = asof
        raise _BoundaryReached()

    fake_model = ModuleType("backend.market.model")
    fake_model.load_tone_features = Mock(return_value=None)
    forbidden = {
        name: Mock(side_effect=AssertionError(f"forbidden computation: {name}"))
        for name in ("_block", "_dataset", "_carried", "_fit_predict")
    }
    with ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, {fake_model.__name__: fake_model}))
        stack.enter_context(patch.object(store, "read", side_effect=observe_read))
        stack.enter_context(
            patch.object(store, "read_frame", side_effect=observe_frame)
        )
        stack.enter_context(patch.object(desk, "build_universe", return_value=members))
        stack.enter_context(patch.object(mx, "build_universe", return_value=members))
        stack.enter_context(
            patch.object(desk, "_fundamental_opinion", return_value=None)
        )
        stack.enter_context(patch.object(desk, "tightening_for", return_value=None))
        stack.enter_context(
            patch.object(
                desk.regime, "opine", return_value=SimpleNamespace(ai_trend=None)
            )
        )
        for analyst in (desk.technical, desk.sentiment, desk.value):
            stack.enter_context(patch.object(analyst, "opine", return_value=None))
        stack.enter_context(
            patch.object(levels_pit, "point_in_time_levels", return_value={})
        )
        stack.enter_context(
            patch.object(desk, "assemble", return_value=SimpleNamespace())
        )
        stack.enter_context(
            patch.object(challenger, "expectations_gap", side_effect=observe_gap)
        )
        stack.enter_context(patch.object(mx, "_records", side_effect=observe_records))
        boundary = stack.enter_context(
            patch.object(mx, "_features", side_effect=stop_before_features)
        )
        for name, guard in forbidden.items():
            stack.enter_context(patch.object(mx, name, guard))
        kwargs = {"inputs": (desk.EXPECTATIONS_GAP,)}
        if asof is not OMITTED:
            kwargs["asof"] = asof
        with pytest.raises(_BoundaryReached):
            desk.run(store, **kwargs)
        assert boundary.call_count == 1
        for guard in forbidden.values():
            guard.assert_not_called()
    return observed


# Future extraction revisions cannot change either historical gap input boundary.
@pytest.mark.parametrize("boundary", ["gap_panel", "records"])
def test_fixed_cutoff_is_invariant_after_future_partition_append(tmp_path, boundary):
    store = MarketStore(tmp_path)
    _write_partition(store, HISTORICAL, 1)
    before = _capture(store, HISTORICAL)
    _write_partition(store, LATER, 9)
    after = _capture(store, HISTORICAL)

    assert after["book"] == before["book"]
    assert before["book"]["close"]["SYNTH"] == (10.0, 11.0)
    assert after[boundary] == before[boundary]
    assert after["quarters"] == before["quarters"]
    assert after["reactions"] == before["reactions"]
    assert after["gap_asof"] == after["features_asof"] == HISTORICAL
    assert all(read[3] == HISTORICAL for read in after["reads"])
    assert all(read[4] == HISTORICAL for read in after["reads"])


# Omitted and explicit None cutoffs keep latest-vintage semantics, not last-bar time.
def test_default_and_none_select_latest_even_when_last_session_is_older(tmp_path):
    store = MarketStore(tmp_path)
    _write_partition(store, HISTORICAL, 1)
    _write_partition(store, LATER, 9)
    default = _capture(store)
    explicit = _capture(store, None)

    assert default == explicit
    assert explicit["book"]["dates"][-1] == HISTORICAL.isoformat()
    assert explicit["gap_panel"]["close"]["SYNTH"] == (90.0, 99.0)
    assert explicit["records"]["SYNTH"].facts[0].value == 900.0
    assert explicit["records"]["SYNTH"].source_time == _stamp(LATER)
    assert explicit["gap_asof"] is explicit["features_asof"] is None
    assert all(read[3] is None and read[4] == LATER for read in explicit["reads"])


# An explicit later cutoff selects its vintage, not the last session or newest data.
def test_later_cutoff_excludes_even_newer_partitions(tmp_path):
    store = MarketStore(tmp_path)
    for vintage, value in ((HISTORICAL, 1), (LATER, 5), (NEWEST, 9)):
        _write_partition(store, vintage, value)
    observed = _capture(store, LATER)

    assert observed["book"]["dates"][-1] == HISTORICAL.isoformat()
    assert observed["book"]["close"]["SYNTH"] == (50.0, 55.0)
    assert observed["gap_panel"] == observed["book"]
    assert observed["records"]["SYNTH"].facts[0].value == 500.0
    assert observed["records"]["SYNTH"].source_time == _stamp(LATER)
    assert observed["gap_asof"] == observed["features_asof"] == LATER
    assert all(read[3] == LATER and read[4] == LATER for read in observed["reads"])


# A previously missing input must stay absent when it first arrives after the cutoff.
@pytest.mark.parametrize("missing", ["bars", "edgar_events", "edgar_facts"])
def test_missing_historical_input_is_not_backfilled_from_future(tmp_path, missing):
    store = MarketStore(tmp_path)
    _write_partition(store, HISTORICAL, 1, missing=missing)
    before = _capture(store, HISTORICAL)
    _write_partition(store, LATER, 9)
    after = _capture(store, HISTORICAL)

    assert before["records"] == {}
    assert after["book"] == before["book"]
    assert after["gap_panel"] == before["gap_panel"]
    assert after["records"] == before["records"]
    assert after["quarters"] == after["reactions"] == {}
    if missing == "bars":
        assert "SYNTH" not in after["gap_panel"]["close"]
    assert ("gap", missing, "SYNTH", HISTORICAL, None) in after["reads"]
    latest = _capture(store)
    assert latest["gap_panel"]["close"]["SYNTH"] == (90.0, 99.0)
    assert latest["records"]["SYNTH"].facts[0].value == 900.0


# A research store's older cap survives explicit later requests through the desk.
@pytest.mark.parametrize("requested", [None, LATER])
def test_research_store_keeps_its_older_cap(tmp_path, requested):
    writer = MarketStore(tmp_path)
    _write_partition(writer, HISTORICAL, 1)
    pinned = ResearchStore(tmp_path, HISTORICAL)
    before = _capture(pinned, requested)
    _write_partition(writer, LATER, 9)
    after = _capture(pinned, requested)

    assert after["book"] == before["book"]
    assert after["gap_panel"] == before["gap_panel"] == before["book"]
    assert after["records"] == before["records"]
    assert after["records"]["SYNTH"].source_time == _stamp(HISTORICAL)
    assert after["records"]["SYNTH"].facts[0].value == 100.0
    assert all(read[4] == HISTORICAL for read in after["reads"])
