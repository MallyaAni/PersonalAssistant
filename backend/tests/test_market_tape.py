"""The tape tensor and the tape encoder: slots, normalisation, a planted pattern."""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from backend.market import alpaca, tape  # noqa: E402
from backend.market.harness import evaluate_scores  # noqa: E402
from backend.market.model import TrainConfig, walk_forward  # noqa: E402
from backend.market.panel import panel_from_histories  # noqa: E402
from backend.market.yahoo import DailyBar, TickerHistory  # noqa: E402


# Bars for one session placed by slot; `missing` slots are left out.
def _bars(session: date, closes: list[float], missing: set[int] = frozenset()):
    base = datetime(session.year, session.month, session.day, 13, 30, tzinfo=UTC)
    out = []
    for i, c in enumerate(closes):
        if i in missing:
            continue
        o = closes[i - 1] if i else c
        out.append(
            alpaca.IntradayBar(
                base + timedelta(minutes=15 * i),
                o,
                max(o, c) * 1.001,
                min(o, c) * 0.999,
                c,
                10.0,
            )
        )
    return out


# Slots are placed by time; a missing slot is a flat bar at the last close
# with zero volume; everything is relative to the session's open.
def test_session_tape_places_slots_and_fills_gaps():
    closes = [100.0 + i for i in range(26)]
    t = tape.session_tape(_bars(date(2025, 6, 3), closes, missing={5, 6}))
    assert t.shape == (26, 5)
    assert t[0, 3] == pytest.approx(0.0, abs=1e-6)  # first close == open0
    assert t[25, 3] == pytest.approx(np.log(125 / 100), abs=1e-5)
    assert t[5, 3] == t[4, 3]  # gap filled flat at the last close
    assert t[5, 4] == 0.0  # with no volume
    assert abs(t[:, 4].sum() - 1.0) < 1e-6  # volume shares sum to one
    assert tape.session_tape(_bars(date(2025, 6, 3), closes[:10])) is None  # too sparse


# The tape encoder finds a planted intraday pattern out of sample: names
# whose last session closed strong (top of range) tend to rise next.
def test_tape_encoder_finds_a_planted_intraday_pattern():
    rng = np.random.default_rng(4)
    n, t = 24, 300
    first = date(2024, 1, 1)
    # Daily returns: the next session's residual follows the previous
    # session's intraday strength for half the names.
    strength = rng.uniform(-1, 1, size=(t + 1, n))  # one per price, day 0..t
    returns = rng.normal(0.0, 0.01, size=(t, n))  # return into day 1..t
    returns += 0.012 * strength[:t]  # day k's strength drives the return into k+1
    histories = {}
    bars_by_ticker = {}
    for i in range(n):
        prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns[:, i])]))
        rows = []
        bars = []
        for k, p in enumerate(prices):
            day = first + timedelta(days=k)
            rows.append(DailyBar(day, p * 0.995, p * 1.01, p * 0.985, p, p, 1e6))
            # An intraday path whose finishing strength is `strength[k, i]`.
            s = strength[k, i]
            path = [
                p * (1 + 0.01 * s * (j / 25) + 0.001 * rng.normal()) for j in range(26)
            ]
            bars.extend(_bars(day, path))
        histories[f"N{i:02d}"] = TickerHistory(
            f"N{i:02d}",
            tuple(rows),
            (),
            rows[-1].session_date,
            datetime(2026, 1, 1, tzinfo=UTC),
        )
        bars_by_ticker[f"N{i:02d}"] = bars
    spy_returns = returns.mean(axis=1)
    prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(spy_returns)]))
    histories["SPY"] = TickerHistory(
        "SPY",
        tuple(
            DailyBar(first + timedelta(days=k), p, p, p, p, p, 1e6)
            for k, p in enumerate(prices)
        ),
        (),
        first + timedelta(days=len(prices) - 1),
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    panel = panel_from_histories(histories, "SPY", {})
    tensor = tape.tape_tensor(panel, bars_by_ticker)
    assert np.isfinite(tensor[:, panel.index("N00")]).all()
    assert np.isnan(tensor[:, panel.index("SPY")]).all()
    config = TrainConfig(
        window_size=5,
        horizon=1,
        momentum_length=30,
        momentum_skip=5,
        lookback=10,
        train_size=120,
        test_size=40,
        embargo=1,
        encoder="tape",
        tape_sessions=2,
        hidden=32,
        epochs=6,
        sessions_per_batch=8,
        patience=6,
        seed=1,
    )
    result = walk_forward(panel, config, tape=tensor)
    report = evaluate_scores(result.scores, panel, 1, cost_bps=0, min_names=10)
    assert report.count >= 60
    assert report.mean_ic > 0.15, report.mean_ic
