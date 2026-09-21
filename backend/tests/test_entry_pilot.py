"""Causality and funded accounting for the isolated entry-timing experiment."""

import numpy as np
import pytest

from backend.market import entry_pilot as ep


# A single explicit decision whose entry and exit prices can be varied independently.
def sample():
    return ep.Dataset(
        x=np.ones((1, len(ep.NAMES)), dtype=np.float32),
        sequence=np.ones((1, ep.SEQUENCE, 7), dtype=np.float32),
        y=np.array([[0.0, 0.0]]),
        day=np.array([0]),
        slot=np.array([3]),
        name=np.array([0]),
        entry_prices=np.array([[100.0, 110.0]]),
        exit_day=np.array([2]),
        dates=np.arange("2025-01-02", "2025-01-05", dtype="datetime64[D]"),
        closes=np.array([[100.0], [110.0], [120.0]]),
        tickers=np.array(["EXAMPLE"]),
        candidate=np.array([True]),
        horizon=2,
    )


# Changing unseen bars must not alter a feature or sequence at the decision time.
def test_intraday_prefix_is_invariant_to_the_future():
    bars = np.tile([100.0, 102.0, 99.0, 101.0, 1000.0], (26, 1))
    before = ep.prefix_features(bars, 3, 100.0, np.ones(26) * 1000)
    bars[4:] *= 100
    after = ep.prefix_features(bars, 3, 100.0, np.ones(26) * 1000)
    for first, second in zip(before, after, strict=True):
        np.testing.assert_array_equal(first, second)
    assert np.count_nonzero(before[2][4:]) == 0


# Data already missing at decision time makes that setup unavailable without backfill.
def test_missing_observed_bar_is_not_backfilled():
    bars = np.tile([100.0, 102.0, 99.0, 101.0, 1000.0], (26, 1))
    bars[2, 3] = np.nan
    assert ep.prefix_features(bars, 3, 100.0, np.ones(26)) is None


# An immediate-entry policy cannot earn a move that happened before its actual fill.
def test_account_uses_delayed_execution_price():
    data = sample()
    data.entry_prices[0, 0] = 120
    result = ep.evaluate(data, np.array([True]), np.array([0]), cost_bps=0)
    assert result["net_return"] == pytest.approx(0)


# Waiting changes the purchase price while preserving the exact exit and allocation.
def test_waiting_is_paired_to_the_same_exit():
    data = sample()
    immediate = ep.evaluate(data, np.array([True]), np.array([0]), 0)
    waiting = ep.evaluate(data, np.array([True]), np.array([1]), 0)
    budget = 1 / 30
    assert immediate["net_return"] == pytest.approx(budget * (120 / 100 - 1))
    assert waiting["net_return"] == pytest.approx(budget * (120 / 110 - 1))
    assert immediate["dates"] == waiting["dates"]


# The funded ledger pays entry and exit costs exactly once, even on a flat price path.
def test_cash_funds_both_sides_of_cost():
    data = sample()
    data.closes[:] = 100
    result = ep.evaluate(data, np.array([True]), np.array([0]), 30)
    budget = 1 / 30
    assert result["net_return"] == pytest.approx(budget * (0.997 / 1.003 - 1))
    assert result["max_drawdown"] == pytest.approx(result["net_return"])


# A missing future label must not remove a candidate from retrospective evaluation.
def test_evaluation_membership_does_not_require_future_labels():
    data = sample()
    data.y[:] = np.nan
    assert not ep.split(data, "2025-01-01", "2026-01-01").any()
    assert ep.split(data, "2025-01-01", "2026-01-01", labelled=False).all()


# Crossing the split with the outcome is leakage even when the decision precedes it.
def test_split_purges_the_label_endpoint():
    data = sample()
    assert not ep.split(data, "2025-01-01", "2025-01-04").any()
    assert ep.split(data, "2025-01-01", "2025-01-05").all()


# An unquoted entry remains a recorded cash slot; a missing held mark invalidates NAV.
def test_missing_future_price_fails_the_account():
    data = sample()
    data.entry_prices[0, 0] = np.nan
    result = ep.evaluate(data, np.array([True]), np.array([0]))
    assert result["unfilled_no_price"] == 1
    assert result["decisions"] == [[0, 0, 0.0]]
    assert result["net_return"] == 0
    data = sample()
    data.closes[1, 0] = np.nan
    with pytest.raises(ValueError, match="held-asset"):
        ep.evaluate(data, np.array([True]), np.array([0]))


# Abstention leaves the assigned capital in cash and requires no future quote.
def test_skip_is_cash_not_a_free_reallocation():
    data = sample()
    data.entry_prices[:] = np.nan
    result = ep.evaluate(data, np.array([True]), np.array([2]))
    assert result["net_return"] == 0
    assert result["average_exposure"] == 0
    assert result["turnover_total"] == 0


# Cost can make an apparent edge untradeable; forced timing must still choose a fill.
def test_action_uses_net_value_and_forced_timing_cannot_skip():
    pred = np.array([[0.1, 0.0], [1.0, 0.5], [1.0, -0.5]])
    assert ep.actions(pred, 10).tolist() == [2, 1, 0]
    assert ep.actions(pred, 10, False).tolist() == [0, 1, 0]


# Pairing a strategy with itself yields a zero interval without fictitious precision.
def test_paired_interval_self_comparison():
    data = sample()
    result = ep.evaluate(data, np.array([True]), np.array([0]))
    comparison = ep.paired_interval(result, result, repetitions=20)
    assert comparison["ci95_daily_bps"] == [0, 0]


# Frozen artifacts round-trip their fingerprint, including the scalar horizon.
def test_dataset_fingerprint_survives_serialization(tmp_path):
    pytest.importorskip("torch")
    from dataclasses import fields

    from backend.cli.market_entry_pilot import digest

    data = sample()
    path = tmp_path / "dataset.npz"
    np.savez(path, **{f.name: getattr(data, f.name) for f in fields(data)})
    with np.load(path, allow_pickle=False) as saved:
        restored = ep.Dataset(**{k: saved[k] for k in saved.files})
    assert digest(data) == digest(restored)


# Changing future daily prices and tape cannot change earlier features or candidates.
def test_full_builder_is_causal(tmp_path, monkeypatch):
    from backend.market.panel import Panel

    dates = np.arange("2020-01-01", "2020-09-07", dtype="datetime64[D]")
    close = np.repeat((100 + np.arange(len(dates)))[:, None], 2, axis=1).astype(float)
    panel = Panel(
        dates,
        ("EXAMPLE", "SPY"),
        close.copy(),
        close + 2,
        close - 2,
        close.copy(),
        close.copy(),
        np.ones_like(close) * 1000,
        {"EXAMPLE": ("theme",)},
        "SPY",
    )
    bars = np.empty((len(dates), 26, 5))
    for d in range(len(dates)):
        bars[d] = [close[d, 0], close[d, 0] + 2, close[d, 0] - 2, close[d, 0] + 1, 1000]
    (tmp_path / "EXAMPLE.parquet").touch()
    monkeypatch.setattr(ep, "bar_grid", lambda *args: bars)
    before = ep.build(panel, tmp_path)
    for prices in (panel.open, panel.high, panel.low, panel.close, panel.adj_close):
        prices[225:] *= 5
    bars[225:, :, :4] *= 5
    after = ep.build(panel, tmp_path)
    a, b = before.day < 225, after.day < 225
    np.testing.assert_array_equal(before.x[a], after.x[b])
    np.testing.assert_array_equal(before.sequence[a], after.sequence[b])
    np.testing.assert_array_equal(before.candidate[a], after.candidate[b])


# Neither feature scaling nor target scaling may learn from validation or test rows.
def test_normalization_uses_training_only():
    pytest.importorskip("torch")
    from backend.cli.market_entry_pilot import transform

    data = sample()
    data.x = np.repeat(data.x, 2, axis=0)
    data.sequence = np.repeat(data.sequence, 2, axis=0)
    data.y = np.repeat(data.y, 2, axis=0)
    train = np.array([True, False])
    _, _, _, before = transform(data, train)
    data.x[1] *= 100
    data.sequence[1] *= 100
    data.y[1] = 100
    _, _, _, after = transform(data, train)
    for key in before:
        np.testing.assert_array_equal(before[key], after[key])


# Recurrent outputs stop at the decision slot even if later padded slots change.
def test_sequence_network_never_reads_later_slots():
    torch = pytest.importorskip("torch")
    from backend.cli.market_entry_pilot import TimingNetwork

    model = TimingNetwork(len(ep.NAMES)).eval()
    x = torch.zeros((1, len(ep.NAMES)))
    seq = torch.zeros((1, ep.SEQUENCE, 7))
    slot = torch.tensor([3])
    before = model(x, seq, slot).detach()
    seq[:, 4:] = 100
    torch.testing.assert_close(before, model(x, seq, slot).detach())


# Competing cohorts cannot borrow cash even if their requested budgets exceed NAV.
def test_competing_entries_are_cash_limited():
    data = sample()
    for attr in (
        "x",
        "sequence",
        "y",
        "day",
        "slot",
        "name",
        "entry_prices",
        "exit_day",
        "candidate",
    ):
        setattr(data, attr, np.repeat(getattr(data, attr), 100, axis=0))
    data.closes[:] = 100
    result = ep.evaluate(data, np.ones(100, dtype=bool), np.zeros(100, dtype=int), 0)
    assert sum(row[2] for row in result["decisions"]) <= 1 + 1e-12
    assert result["net_return"] == pytest.approx(0)
    assert max(result["nav"]) <= 1 + 1e-12
