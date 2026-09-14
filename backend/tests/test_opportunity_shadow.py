"""Prospective inference, delayed funded fills and immutable isolated account proof."""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from backend.market import opportunity_learning as ol
from backend.market import opportunity_shadow as shadow
from backend.market.store import MarketStore
from backend.market.yahoo import DailyBar, TickerHistory


# Build a tiny deterministic frozen network with the same production feature schema.
def bundle(tmp_path):
    path = tmp_path / "model.npz"
    np.savez(
        path,
        **{
            "0.weight": np.zeros((32, 36), dtype=np.float32),
            "0.bias": np.zeros(32, dtype=np.float32),
            "2.weight": np.zeros((16, 32), dtype=np.float32),
            "2.bias": np.zeros(16, dtype=np.float32),
            "4.weight": np.zeros((1, 16), dtype=np.float32),
            "4.bias": np.ones(1, dtype=np.float32),
            "medians": np.zeros(18),
            "scale": np.ones(18),
            "tickers": np.array(["ABC", "SPY"]),
            "feature_names": np.array(
                [*shadow.gp.FEATURE_NAMES, *ol.FUNDAMENTAL_NAMES]
            ),
        },
    )
    return path


# Persist real daily store partitions ending on the requested completed session.
def history(root, day, tail):
    dates = np.busday_offset("2026-02-02", np.arange(180))
    dates = dates[dates <= np.datetime64(day)]
    store = MarketStore(root)
    for ticker in ("ABC", "SPY"):
        bars = []
        for session in dates:
            d = session.astype(object)
            price = tail.get(d.isoformat(), 100.0) if ticker == "ABC" else 100.0
            bars.append(DailyBar(d, price, price, price, price, price, 1000))
        store.write(
            day,
            TickerHistory(
                ticker,
                tuple(bars),
                (),
                day,
                datetime.combine(day, datetime.min.time(), UTC),
            ),
        )


# Run a funded prospective journey and prove entry gaps do not become earned returns.
def test_three_day_journey_is_delayed_persisted_and_idempotent(tmp_path):
    path = bundle(tmp_path)
    root = tmp_path / "market"
    day = date(2026, 9, 14)
    now = datetime(2026, 9, 14, 21, tzinfo=UTC)
    history(root, day, {})
    first = shadow.observe(root, now, path)
    assert first["accounts"]["neural@10bps"]["equity"] == 100000
    assert first["accounts"]["neural@10bps"]["pending"] == [0.1, 0]
    history(root, day + timedelta(days=1), {"2026-09-15": 200})
    second = shadow.observe(root, now + timedelta(days=1), path)
    expected = 100000 / 1.0001
    assert second["accounts"]["neural@10bps"]["equity"] == pytest.approx(expected)
    assert second["accounts"]["neural@10bps"]["cash"] >= 0
    history(root, day + timedelta(days=2), {"2026-09-15": 200, "2026-09-16": 220})
    third = shadow.observe(root, now + timedelta(days=2), path)
    assert third["accounts"]["neural@10bps"]["equity"] == pytest.approx(expected * 1.01)
    assert third["accounts"]["USD@10bps"]["equity"] == 100000
    folder = root / "desk/ml-forward"
    before = {p.name: p.read_bytes() for p in folder.glob("*.json")}
    assert shadow.observe(root, now + timedelta(days=2), path) == third
    assert {p.name: p.read_bytes() for p in folder.glob("*.json")} == before
    assert shadow.latest(folder) == third


# Missing a run cancels its old intent instead of manufacturing a hindsight fill.
def test_missed_session_cancels_pending_fill(tmp_path):
    state = shadow.initialize(tmp_path, ("ABC", "SPY"), "fixed", datetime.now(UTC))
    targets = {name: np.array([0.1, 0]) for name in shadow.POLICIES}
    first = shadow.advance(
        state, "2026-09-14", datetime.now(UTC), np.ones(2), np.ones(2), targets
    )
    missed = shadow.advance(
        first, "2026-09-16", datetime.now(UTC), np.ones(2), np.ones(2) * 10, targets
    )
    assert missed["accounts"]["neural@10bps"]["equity"] == 100000
    assert missed["accounts"]["neural@10bps"]["holdings"] == [0, 0]
    assert "cancelled" in missed["status"]


# Stale data starts only cash accounts and cannot create a backdated forecast or fill.
def test_stale_prices_do_not_backdate_and_model_changes_fail(tmp_path):
    path = bundle(tmp_path)
    root = tmp_path / "market"
    history(root, date(2026, 9, 11), {})
    now = datetime(2026, 9, 14, 21, tzinfo=UTC)
    state = shadow.observe(root, now, path)
    assert state["sequence"] == 0
    assert state["session"] is None
    assert state["started_at"] == now.isoformat()
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="Frozen experiment changed"):
        shadow.observe(root, now, path)


# Competing writers cannot overwrite or duplicate the same account transition.
def test_duplicate_sequence_is_rejected(tmp_path):
    row = {"sequence": 0, "cash": 100}
    shadow.append(tmp_path, row)
    with pytest.raises(FileExistsError):
        shadow.append(tmp_path, {"sequence": 0, "cash": 200})
    assert shadow.latest(tmp_path) == row


# Missing held prices invalidate a prospective account instead of erasing the loss.
def test_missing_held_mark_fails_closed(tmp_path):
    state = shadow.initialize(tmp_path, ("ABC",), "fixed", datetime.now(UTC))
    state["session"] = "2026-09-14"
    state["accounts"]["neural@10bps"]["holdings"] = [100]
    with pytest.raises(ValueError, match="Missing held"):
        shadow.advance(
            state,
            "2026-09-15",
            datetime.now(UTC),
            np.ones(1),
            np.array([np.nan]),
            {name: np.zeros(1) for name in shadow.POLICIES},
        )


# Historical invocations never initialize or observe a prospective experiment.
def test_historical_run_has_no_side_effects(tmp_path):
    assert shadow.observe_if_current(tmp_path, False) is None
    assert list(tmp_path.iterdir()) == []


# The nightly wrapper persists cash accounts while current inputs are absent.
def test_nightly_wrapper_initializes_separate_accounts(tmp_path, monkeypatch):
    real_observe = shadow.observe
    path = bundle(tmp_path)
    root = tmp_path / "market"
    history(root, date(2026, 9, 11), {})
    monkeypatch.setattr(
        shadow,
        "observe",
        lambda root: real_observe(root, datetime(2026, 9, 14, 21, tzinfo=UTC), path),
    )
    state = shadow.observe_if_current(root, True)
    assert state["sequence"] == 0
    summary = shadow.summary(root)
    assert len(summary["accounts"]) == 10
    assert summary["accounts"]["neural@10bps"]["total_return"] == 0
