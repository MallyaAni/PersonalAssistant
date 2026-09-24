"""Realized learner labels never turn split mechanics into stock alpha."""

import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from backend.market import learned_archive
from backend.market.store import MarketStore
from backend.market.yahoo import DailyBar, TickerHistory


# Use twelve consecutive exchange sessions and a pure stock split at day six.
def _sessions() -> tuple[date, ...]:
    dates = np.arange("2026-01-05", "2026-01-23", dtype="datetime64[D]")
    return tuple(value.astype(date) for value in dates[np.is_busday(dates)][:12])


# Keep each label's entry and exit on a single frozen bar partition.
def _write_history(store, ticker, sessions, asof, split=False):
    bars = []
    for index, day in enumerate(sessions):
        raw = 10.0 if split and index >= 6 else 100.0
        adjusted = 10.0 if split else 100.0
        bars.append(DailyBar(day, raw, raw, raw, raw, adjusted, 1000))
    store.write(
        asof,
        TickerHistory(
            ticker,
            tuple(bars),
            (),
            sessions[-1],
            datetime.combine(asof, datetime.min.time(), UTC).replace(hour=22),
            "fixture",
        ),
    )


# A stock with only a 10:1 split has zero SPY-relative return, and its label
# is unavailable before the exit vintage was actually fetched.
def test_label_uses_one_mature_adjusted_vintage(tmp_path):
    days = _sessions()
    store = MarketStore(tmp_path)
    _write_history(store, "SPY", days, days[-1])
    _write_history(store, "AAA", days, days[-1], split=True)
    early = datetime.combine(days[-2], datetime.min.time(), UTC).replace(hour=23)
    early_label = learned_archive.realize_label(store, "AAA", "SPY", days, 0, early)
    assert early_label.reason == "immature"
    now = datetime.combine(days[-1], datetime.min.time(), UTC).replace(hour=23)
    outcome = learned_archive.realize_label(store, "AAA", "SPY", days, 0, now)
    assert outcome.value == pytest.approx(0.0)
    assert outcome.vintage == days[-1]
    assert outcome.recorded_on == days[-1]


# The brake outcome waits for all twenty QQQ sessions and reads one adjusted
# vintage, so a late ten-percent loss is visible only after that close.
def test_brake_label_waits_for_full_qqq_drawdown_window(tmp_path):
    dates = np.arange("2026-01-05", "2026-02-10", dtype="datetime64[D]")
    days = tuple(value.astype(date) for value in dates[np.is_busday(dates)][:21])
    store = MarketStore(tmp_path)
    bars = tuple(
        DailyBar(day, 100, 100, 100, 90 if i == 20 else 100,
                 90 if i == 20 else 100, 1000)
        for i, day in enumerate(days)
    )
    source = datetime.combine(days[-1], datetime.min.time(), UTC).replace(hour=22)
    store.write(days[-1], TickerHistory("QQQ", bars, (), days[-1], source, "fixture"))
    early = source - timedelta(days=1)
    early_label = learned_archive.realize_brake_label(store, days, 0, early)
    assert early_label.reason == "immature"
    outcome = learned_archive.realize_brake_label(
        store, days, 0, source + timedelta(hours=1)
    )
    assert outcome.value == 1.0
    assert outcome.recorded_on == days[-1]


# Do not search later vintages until a missing name happens to reappear.
def test_missing_first_mature_vintage_stays_missing(tmp_path):
    days = _sessions()
    store = MarketStore(tmp_path)
    _write_history(store, "SPY", days, days[-1])
    _write_history(store, "AAA", days, days[-1] + timedelta(days=1), split=True)
    now = datetime.combine(days[-1] + timedelta(days=1), datetime.min.time(), UTC)
    now = now.replace(hour=23)
    outcome = learned_archive.realize_label(store, "AAA", "SPY", days, 0, now)
    assert outcome.value is None
    assert outcome.reason == "missing_same_vintage"
    assert outcome.vintage == days[-1]


# An archived row is a candidate only if captured on its decision session;
# missing sessions remain explicit and never borrow tomorrow's features.
def test_load_keeps_late_and_missing_observations_out_of_training(tmp_path):
    days = _sessions()
    store = MarketStore(tmp_path)
    _write_history(store, "SPY", days, days[-1])
    _write_history(store, "AAA", days, days[-1], split=True)
    path = tmp_path / "learned_inputs" / f"asof={days[0]}.json"
    path.parent.mkdir()
    row = {
        "schema": "desk-learned-inputs/1",
        "session": days[0].isoformat(),
        "captured_at": f"{days[0]}T23:00:00+00:00",
        "benchmark": "SPY",
        "record_sha256": "0" * 64,
        "market_features": {name: 0.5 for name in learned_archive.MARKET_COLUMNS},
        "regime": {name: 0.5 for name in learned_archive.REGIME_COLUMNS},
        "stocks": {
            "AAA": {
                "desk_grade": "A",
                "current_bar_complete": True,
                "price_features": {name: 1.0 for name in learned_archive.PRICE_COLUMNS},
                "fundamental_features": {},
                "tone_features": {},
                "desk_fundamental_rank": 0.75,
            }
        },
    }
    path.write_text(json.dumps(row), encoding="utf-8")
    now = datetime.combine(days[-1], datetime.min.time(), UTC).replace(hour=23)
    result = learned_archive.load(tmp_path, store, days, now)
    stock = result.inputs.tickers.index("AAA")
    assert result.audit["captured"] == 1
    assert result.audit["mature"] == 1
    assert result.inputs.membership[0, stock] == 1
    assert result.labels[0, stock] == pytest.approx(0.0)
    assert np.isnan(result.inputs.features[1:, stock]).all()
    row["captured_at"] = f"{days[1]}T15:00:00+00:00"
    path.write_text(json.dumps(row), encoding="utf-8")
    late = learned_archive.load(tmp_path, store, days, now)
    assert late.audit["late_capture"] == 1
    assert np.all(late.inputs.membership == -1)


# A caller cannot shorten the exchange calendar to turn an immature label
# into a conveniently earlier ten-session outcome.
def test_load_rejects_omitted_exchange_session(tmp_path):
    days = _sessions()
    store = MarketStore(tmp_path)
    _write_history(store, "SPY", days, days[-1])
    now = datetime.combine(days[-1], datetime.min.time(), UTC).replace(hour=23)
    with pytest.raises(ValueError, match="omits or invents"):
        learned_archive.load(tmp_path, store, days[:4] + days[5:], now)
    before_fetch = now.replace(hour=21)
    with pytest.raises(ValueError, match="complete SPY calendar"):
        learned_archive.load(tmp_path, store, days, before_fetch)


# A tiny valid archive cannot manufacture a monthly fit or a crash forecast.
def test_shadow_fit_fails_closed_without_training_history(tmp_path):
    days = _sessions()
    store = MarketStore(tmp_path)
    _write_history(store, "SPY", days, days[-1])
    _write_history(store, "AAA", days, days[-1])
    now = datetime.combine(days[-1], datetime.min.time(), UTC).replace(hour=23)
    archive = learned_archive.load(tmp_path, store, days, now)
    forecasts = learned_archive.fit_shadow(archive)
    assert forecasts.rank_scored == 0
    assert forecasts.brake_scored == 0
    assert np.isnan(forecasts.rank.values).all()
    assert np.isnan(forecasts.brake.values).all()
    assert not forecasts.rank.model_hash
    assert not forecasts.brake.model_hash
