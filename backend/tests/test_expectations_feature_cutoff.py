"""Partition-cutoff noninterference through real expectations feature loaders.

Synthetic Parquet partitions exercise storage, filing/tone conversion and split
adjustment, never a fit or prediction. When Torch is unavailable, the tone
loader's exact function AST is compiled from model.py; this proves that loader's
deterministic behavior, not importability of the complete Torch model module.
Partition identity is not proof of historical publication availability.
"""

import ast
import hashlib
import importlib.util
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from backend.agents.trading.desk import desk
from backend.cli import market_expectations as mx
from backend.market import edgar, language, levels_pit, universe, valuation
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.yahoo import CorporateAction, DailyBar, TickerHistory

CUTOFF = date(2024, 6, 28)
FUTURE = date(2025, 1, 2)
BAR_VINTAGE = date(2024, 6, 20)
EVENT_VINTAGE = date(2024, 6, 21)
FACT_VINTAGE = date(2024, 6, 24)
TONE_VINTAGE = date(2024, 6, 26)
TICKER = "SYNTH"


class FeaturesReached(BaseException):
    """Stop before labels/fits without being swallowed by desk.run's fallback."""


# Use the real module where available, otherwise compile its exact pure loader.
@pytest.fixture(autouse=True)
def tone_loader(monkeypatch, record_property):
    source = Path(mx.__file__).parents[1] / "market" / "model.py"
    content = source.read_bytes()
    record_property("tone_loader_source_sha256", hashlib.sha256(content).hexdigest())
    if importlib.util.find_spec("torch") is not None:
        from backend.market.model import load_tone_features

        record_property("tone_loader_mode", "complete-module-import")
        return load_tone_features
    tree = ast.parse(content, filename=str(source))
    definitions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "load_tone_features"
    ]
    assert len(definitions) == 1
    module = ModuleType("backend.market.model")
    module.__file__ = str(source)
    exact_function = ast.Module(body=definitions, type_ignores=[])
    exec(compile(exact_function, str(source), "exec"), module.__dict__)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    record_property("tone_loader_mode", "exact-function-AST-without-Torch-import")
    return module.load_tone_features


# Make every downstream dataset, fit and inference attempt a hard test failure.
@pytest.fixture(autouse=True)
def forbid_learning(monkeypatch):
    forbidden = []
    for name in ("_block", "_dataset", "_carried", "_fit_predict"):
        sentinel = Mock(side_effect=AssertionError(f"forbidden computation: {name}"))
        monkeypatch.setattr(mx, name, sentinel)
        forbidden.append(sentinel)
    yield
    for sentinel in forbidden:
        sentinel.assert_not_called()


# Provide a fixed weekday calendar ending before every eligible partition vintage.
def _days():
    days = np.arange("2023-12-01", "2024-06-15", dtype="datetime64[D]")
    return days[np.is_busday(days)].astype(object)


# Store the same bars in every vintage, changing only reconstructed split evidence.
def _write_history(store, vintage, ticker=TICKER, split=2.0):
    days = _days()
    bars = tuple(
        DailyBar(
            day,
            20.0 + i / 10,
            21.0 + i / 10,
            19.0 + i / 10,
            20.0 + i / 10,
            20.0 + i / 10,
            1000,
        )
        for i, day in enumerate(days)
    )
    actions = (CorporateAction(date(2024, 5, 20), "split", split),) if split else ()
    history = TickerHistory(
        ticker,
        bars,
        actions,
        days[-1],
        datetime.combine(vintage, datetime.min.time(), UTC),
        "synthetic-feature-cutoff",
    )
    assert store.write(vintage, history)


# Create dated historical fundamentals whose later reconstruction is observable.
def _record(revenue=100.0):
    event = edgar.EarningsEvent(
        datetime(2024, 5, 1, 12, tzinfo=UTC), date(2024, 5, 1), "synthetic-2024", "2.02"
    )
    facts = [
        edgar.QuarterFact(
            "revenue", date(2023, 1, 1), date(2023, 3, 31), 50.0, date(2023, 5, 1)
        )
    ]
    for name, value in (
        ("revenue", revenue),
        ("net_income", 20.0),
        ("equity", 500.0),
        ("shares", 10.0),
    ):
        facts.append(
            edgar.QuarterFact(
                name, date(2024, 1, 1), date(2024, 3, 31), value, date(2024, 5, 1)
            )
        )
    return edgar.CompanyRecord(
        TICKER, 0, (event,), tuple(facts), datetime(2024, 6, 1, tzinfo=UTC)
    )


# Write one actual EDGAR frame independently so each kind can have its own vintage.
def _write_filing(store, kind, vintage, revenue=100.0):
    record = _record(revenue)
    events, facts = edgar.record_frames(record)
    assert store.write_frame(
        kind,
        vintage,
        TICKER,
        events if kind == "edgar_events" else facts,
        {"cik": "0", "source_time": record.source_time.isoformat()},
    )


# Persist a revised score for the same historical release, not a new future event.
def _write_tone(store, vintage, guidance=0.25):
    record = language.ToneRecord(
        "synthetic-2024",
        date(2024, 5, 1),
        guidance,
        0.5,
        0.0,
        0.0,
        0.0,
        "Synthetic fixture; no model call",
        "fixture",
        "fixture",
        False,
    )
    assert store.write_frame(
        language.TONE_KIND, vintage, TICKER, language.tone_frame((record,))
    )


# Seed deliberately staggered eligible vintages in an isolated real Parquet store.
@pytest.fixture
def stored(tmp_path):
    store = MarketStore(tmp_path / "market")
    _write_history(store, BAR_VINTAGE)
    _write_history(store, BAR_VINTAGE, ticker="SPY", split=0.0)
    _write_filing(store, "edgar_events", EVENT_VINTAGE)
    _write_filing(store, "edgar_facts", FACT_VINTAGE)
    _write_tone(store, TONE_VINTAGE)
    panel = build_panel(store, (TICKER,), "SPY", {}, CUTOFF)
    assert panel.dates[-1] < np.datetime64(BAR_VINTAGE)
    return store, panel


# Change one future data family while keeping every historical partition untouched.
def _append_future(store, component):
    if component == "tone":
        _write_tone(store, FUTURE, guidance=-0.75)
    elif component == "filings":
        _write_filing(store, "edgar_facts", FUTURE, revenue=400.0)
    elif component == "splits":
        _write_history(store, FUTURE, split=4.0)
    else:
        raise AssertionError(component)


# Capture real feature outputs after the actual desk/challenger call, before labels.
def _desk_features(store, asof, monkeypatch):
    captured = []
    actual_features = mx._features
    members = (
        universe.UniverseMember(
            ticker=TICKER,
            role=universe.FOCUS,
            themes=(universe.SOFTWARE,),
            sector="Synthetic",
        ),
    )

    # Preserve all loader calculations, then stop the production pipeline immediately.
    def capture(*args, **kwargs):
        result = actual_features(*args, **kwargs)
        captured.append((args[1], result))
        raise FeaturesReached()

    with monkeypatch.context() as patch:
        patch.setattr(desk, "build_universe", Mock(return_value=members))
        patch.setattr(mx, "build_universe", Mock(return_value=members))
        patch.setattr(desk, "_fundamental_opinion", Mock(return_value=None))
        patch.setattr(desk, "tightening_for", Mock(return_value=None))
        patch.setattr(
            desk.regime, "opine", Mock(return_value=SimpleNamespace(ai_trend=None))
        )
        for analyst in (desk.technical, desk.sentiment, desk.value):
            patch.setattr(analyst, "opine", Mock(return_value=None))
        patch.setattr(desk, "assemble", Mock(return_value=SimpleNamespace()))
        patch.setattr(mx, "_features", capture)
        with pytest.raises(FeaturesReached):
            desk.run(store, asof=asof, inputs=(desk.EXPECTATIONS_GAP,))
    assert len(captured) == 1
    return captured[0]


# Compare every deterministic feature output, preserving NaN locations exactly.
def _assert_same_features(first, second):
    for index in (0, 4):
        np.testing.assert_array_equal(first[index], second[index])
    assert first[1] == second[1]
    assert first[3] == second[3]
    if first[2] is None:
        assert second[2] is None
    else:
        np.testing.assert_array_equal(first[2], second[2])
    assert first[5].keys() == second[5].keys()
    for horizon in first[5]:
        np.testing.assert_array_equal(first[5][horizon], second[5][horizon])
    for name in (*valuation.MULTIPLES, "market_cap"):
        np.testing.assert_array_equal(getattr(first[6], name), getattr(second[6], name))


# A changed latest-path value demonstrates that each appended fixture is meaningful.
def _changed_value(panel, features, component):
    column = panel.index(TICKER)
    if component == "tone":
        return float(features[2][-1, column, features[3]["tone_guidance"]])
    if component == "filings":
        return float(features[6].price_sales[-1, column])
    return float(features[6].market_cap[-1, column])


# The historical desk must not change deterministic gap inputs after future appends.
@pytest.mark.parametrize("component", ["tone", "filings", "splits"])
def test_desk_feature_outputs_ignore_future_partitions(
    stored, monkeypatch, component, record_property
):
    store, _ = stored
    panel, before = _desk_features(store, CUTOFF, monkeypatch)
    _append_future(store, component)
    later_panel, latest = _desk_features(store, None, monkeypatch)
    pinned_panel, after = _desk_features(store, CUTOFF, monkeypatch)
    original = _changed_value(panel, before, component)
    changed = _changed_value(later_panel, latest, component)
    pinned = _changed_value(pinned_panel, after, component)
    record_property("before", original)
    record_property("latest_after_append", changed)
    record_property("pinned_after_append", pinned)
    assert (
        original != changed
    ), "future fixture must affect real latest-path calculations"
    np.testing.assert_array_equal(panel.close, pinned_panel.close)
    np.testing.assert_array_equal(panel.dates, pinned_panel.dates)
    _assert_same_features(before, after)


# The feature helper itself must retain an explicit vintage and latest-data behavior.
@pytest.mark.parametrize("component", ["tone", "filings", "splits"])
def test_feature_helper_cutoff_and_none_semantics(stored, component):
    store, panel = stored
    records = {TICKER: _record()}
    before = mx._features(store, panel, records, asof=CUTOFF)
    _append_future(store, component)
    pinned = mx._features(store, panel, records, asof=CUTOFF)
    omitted = mx._features(store, panel, records)
    explicit_none = mx._features(store, panel, records, asof=None)
    later = mx._features(store, panel, records, asof=FUTURE)
    _assert_same_features(before, pinned)
    _assert_same_features(omitted, explicit_none)
    _assert_same_features(omitted, later)
    assert _changed_value(panel, before, component) != _changed_value(
        panel, omitted, component
    )


# Real tone/filing/split readers independently select their newest eligible partition.
def test_actual_loaders_honor_staggered_vintages(stored, tone_loader):
    store, panel = stored
    expected = {
        "bars": BAR_VINTAGE,
        "edgar_events": EVENT_VINTAGE,
        "edgar_facts": FACT_VINTAGE,
        language.TONE_KIND: TONE_VINTAGE,
    }
    for kind, vintage in expected.items():
        assert store._latest_of_kind(kind, TICKER, CUTOFF) == vintage
        assert store.read_frame(kind, TICKER, vintage) is not None
    for component in ("tone", "filings", "splits"):
        _append_future(store, component)
    column = panel.index(TICKER)
    tone = tone_loader(store, panel, CUTOFF)
    levels = levels_pit.point_in_time_levels(store, panel, CUTOFF)
    assert tone[-1, column, language.FEATURE_NAMES.index("tone_guidance")] == 0.25
    assert levels["revenue"][-1, column] == 400.0
    assert levels["shares"][-1, column] == 20.0
    assert store.latest_asof(TICKER, CUTOFF) == BAR_VINTAGE
    assert levels_pit.point_in_time_levels(store, panel)["shares"][-1, column] == 40.0
    assert tone_loader(store, panel)[-1, column, 0] == -0.75


# Future-only tone and fundamentals cannot fill an earlier missing partition.
@pytest.mark.parametrize("missing", ["tone", "events", "facts", "splits"])
def test_feature_helper_keeps_missing_eligible_inputs_missing(
    tmp_path, stored, missing
):
    _, panel = stored
    store = MarketStore(tmp_path / "missing")
    _write_history(store, FUTURE if missing == "splits" else BAR_VINTAGE)
    _write_filing(
        store, "edgar_events", FUTURE if missing == "events" else EVENT_VINTAGE
    )
    _write_filing(store, "edgar_facts", FUTURE if missing == "facts" else FACT_VINTAGE)
    _write_tone(store, FUTURE if missing == "tone" else TONE_VINTAGE)
    features = mx._features(store, panel, {}, asof=CUTOFF)
    latest = mx._features(store, panel, {})
    column = panel.index(TICKER)
    if missing == "tone":
        assert features[2] is None
        assert latest[2] is not None
    elif missing in ("events", "facts"):
        for name in (*valuation.MULTIPLES, "market_cap"):
            assert np.isnan(getattr(features[6], name)[:, column]).all()
        assert np.isfinite(latest[6].market_cap[-1, column])
    else:
        assert store.read(TICKER, CUTOFF) is None
        assert features[6].market_cap[-1, column] == 10.0 * panel.close[-1, column]
        assert latest[6].market_cap[-1, column] == 20.0 * panel.close[-1, column]
