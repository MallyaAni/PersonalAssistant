"""The forward scorecard: the nightly records walked as the strategy runs.

What has to hold: the first record establishes the book at the next session's
open and the walk carries it forward rather than re-pricing every night from
cash; a decision is filled at the open, not the close; the desk's cost is
charged on what moves at a rebalance and nothing is charged between them; a
record with no challenger block is an unknown gap that holds what it has, not
a sell; and fewer than two records answer empty.
"""

import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from backend.cli import market_scorecard
from backend.market.store import MarketStore

REBALANCE_COST = market_scorecard.COST_BPS / 1e4


def _record(session, book, challenger=None):
    rec = {"session": session, "book": [{"ticker": t, "weight": w} for t, w in book]}
    if challenger is not None:
        rec["challenger"] = {
            "book": [{"ticker": t, "weight": w} for t, w in challenger]
        }
    return rec


def _write_records(root: Path, records) -> None:
    for rec in records:
        path = root / "desk" / f"asof={rec['session']}" / "desk.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec), encoding="utf-8")


def _write_bars(store: MarketStore, ticker: str, rows) -> None:
    """Write one partition holding daily bars for all the sessions in `rows`."""
    store.write_frame(
        "bars",
        date(2026, 9, 30),
        ticker,
        {
            "session_date": [r[0] for r in rows],
            "open": [float(r[1]) for r in rows],
            "high": [max(float(r[1]), float(r[2])) for r in rows],
            "low": [min(float(r[1]), float(r[2])) for r in rows],
            "close": [float(r[2]) for r in rows],
            "adjusted_close": [float(r[2]) for r in rows],
            "volume": [1e6] * len(rows),
        },
    )


def _from(tmp_path: Path, records, bars_by_ticker) -> dict:
    _write_records(tmp_path, records)
    store = MarketStore(tmp_path)
    for ticker, rows in bars_by_ticker.items():
        _write_bars(store, ticker, rows)
    return market_scorecard.from_records(tmp_path, store)


def test_the_walk_holds_the_book_fills_at_the_open_and_pays_costs(tmp_path):
    records = [
        _record("2026-09-01", [("SNDK", 1.0)]),
        _record("2026-09-02", [("SNDK", 1.0)]),
        _record("2026-09-03", [("SNDK", 1.0)]),
    ]
    bars = {"SNDK": [("2026-09-01", 100, 100), ("2026-09-02", 110, 120), ("2026-09-03", 120, 120)]}
    results = _from(tmp_path, records, bars)
    rule = results["the rule"]
    # The book is bought at the 09-02 open (110) and carried to that close
    # (120), minus the cost of the buy: 120/110 - 1 - 10bp.
    assert rule.returns[0] == pytest.approx(120 / 110 - 1.0 - REBALANCE_COST)
    # The 09-02 -> 09-03 gap is held, not re-priced from cash: SNDK is flat,
    # so the return is exactly the zero of a held position, no cost.
    assert rule.returns[1] == pytest.approx(0.0, abs=1e-12)
    # The decision was filled at the open: a close-to-close reprice would
    # have bought at 120 on 09-02 and made nothing.
    assert rule.returns[0] < 120 / 100 - 1.0


def test_a_mid_walk_decision_is_ignored_until_a_rebalance(tmp_path, monkeypatch):
    # With the desk's real cadence (20 sessions) the only rebalance is the
    # first record: the empty books at 09-03 and 09-04 are never acted on,
    # and the position keeps earning the market instead.
    records = [
        _record("2026-09-01", [("SNDK", 1.0)]),
        _record("2026-09-02", [("SNDK", 1.0)]),
        _record("2026-09-03", []),
        _record("2026-09-04", []),
    ]
    bars = {
        "SNDK": [
            ("2026-09-01", 100, 100),
            ("2026-09-02", 110, 110),
            ("2026-09-03", 120, 120),
            ("2026-09-04", 132, 132),
        ]
    }
    rule = _from(tmp_path, records, bars)["the rule"]
    assert rule.returns[0] == pytest.approx(-REBALANCE_COST, abs=1e-12)
    # 09-02 -> 09-03: held, 110 -> 120 over the account after the buy's cost.
    assert rule.returns[1] == pytest.approx(
        (1.0 * (120 / 110) - REBALANCE_COST) / (1.0 - REBALANCE_COST) - 1.0
    )
    # 09-03 -> 09-04: the empty book is ignored (not a rebalance yet), the
    # position earns 120 -> 132 instead of being sold into cash.
    assert rule.returns[2] == pytest.approx(
        (1.0 * (132 / 110) - REBALANCE_COST) / (1.0 * (120 / 110) - REBALANCE_COST)
        - 1.0
    )


def test_a_rebalance_executes_the_latest_book_change(tmp_path, monkeypatch):
    monkeypatch.setattr(market_scorecard, "REBALANCE", 1)
    records = [
        _record("2026-09-01", [("SNDK", 1.0)]),
        _record("2026-09-02", [("SNDK", 1.0)]),
        _record("2026-09-03", []),
        _record("2026-09-04", []),
    ]
    bars = {
        "SNDK": [
            ("2026-09-01", 100, 100),
            ("2026-09-02", 110, 110),
            ("2026-09-03", 120, 120),
            ("2026-09-04", 132, 132),
        ]
    }
    rule = _from(tmp_path, records, bars)["the rule"]
    assert rule.returns[0] == pytest.approx(-REBALANCE_COST, abs=1e-12)
    # 09-02 -> 09-03: a rebalance to the same book is a no-trade (the drift
    # is under the trade floor), so the position just appreciates 110 -> 120.
    assert rule.returns[1] == pytest.approx(
        (1.0 * (120 / 110) - REBALANCE_COST) / (1.0 - REBALANCE_COST) - 1.0
    )
    # 09-03 -> 09-04: the rebalance executes the empty book, selling the
    # whole position at the 09-04 open (132) and paying the cost on its
    # grown notional; the position is gone.
    position = 1.0 * (132 / 110)
    equity_prev = 1.0 * (120 / 110) - REBALANCE_COST
    equity_now = -REBALANCE_COST + position - position * REBALANCE_COST
    assert rule.returns[2] == pytest.approx(equity_now / equity_prev - 1.0)


def test_a_missing_challenger_block_is_an_unknown_gap_not_a_sell(tmp_path):
    records = [
        _record("2026-09-01", [("SNDK", 1.0)], challenger=[("SNDK", 1.0)]),
        _record("2026-09-02", [("SNDK", 1.0)]),  # no challenger decision
        _record("2026-09-03", [("SNDK", 1.0)], challenger=[("SNDK", 1.0)]),
    ]
    bars = {"SNDK": [("2026-09-01", 100, 100), ("2026-09-02", 110, 110), ("2026-09-03", 110, 110)]}
    results = _from(tmp_path, records, bars)
    assert "the rule" in results
    challenger = results["challenger"]
    # The gap with no decision is NaN, not a liquidation.
    assert np.isnan(challenger.returns[1])
    # The rule track still walks every gap.
    assert np.isfinite(results["the rule"].returns).all()


def test_fewer_than_two_records_answers_empty(tmp_path):
    assert _from(tmp_path, [_record("2026-09-01", [("SNDK", 1.0)])], {}) == {}
