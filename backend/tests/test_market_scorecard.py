"""The forward scorecard: the nightly records walked as the strategy runs.

What has to hold: the first record establishes the book sized at the close
and filled at the next session's open, and the walk carries it forward
rather than re-pricing every night from cash; a decision is filled at the
open, not the close, and sized at the close, not the open; the desk's cost
is charged on what moves at a rebalance and nothing is charged between
them, and turnover is recorded; a record with no challenger block holds
what it has and records the real move, not a sell and not a NaN; a flat
price across a dividend books no fake move; and fewer than two records
answer empty.
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


def _write_bars(store: MarketStore, ticker: str, rows, adj=None) -> None:
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
            "adjusted_close": (
                [float(a) for a in adj]
                if adj is not None
                else [float(r[2]) for r in rows]
            ),
            "volume": [1e6] * len(rows),
        },
    )


def _from(tmp_path: Path, records, bars_by_ticker, adj_by_ticker=None) -> dict:
    _write_records(tmp_path, records)
    store = MarketStore(tmp_path)
    for ticker, rows in bars_by_ticker.items():
        _write_bars(store, ticker, rows, (adj_by_ticker or {}).get(ticker))
    return market_scorecard.from_records(tmp_path, store)


def test_the_walk_holds_the_book_fills_at_the_open_and_pays_costs(tmp_path):
    records = [
        _record("2026-09-01", [("SNDK", 1.0)]),
        _record("2026-09-02", [("SNDK", 1.0)]),
        _record("2026-09-03", [("SNDK", 1.0)]),
    ]
    bars = {
        "SNDK": [
            ("2026-09-01", 100, 100),
            ("2026-09-02", 110, 120),
            ("2026-09-03", 120, 120),
        ]
    }
    results = _from(tmp_path, records, bars)
    rule = results["plain-value"]
    # Sized at the 09-01 close (1.0 * $1 / $100 = 0.01 shares) and filled at
    # the 09-02 open (110), with the cost on the notional filled: 0.01 shares
    # bought at 110, worth 120 at that close.
    shares = 1.0 / 100.0
    assert rule.returns[0] == pytest.approx(
        (shares * 120 - shares * 110 - shares * 110 * REBALANCE_COST) / 1.0
    )
    # The buy's notional is recorded as turnover, so the forward track no
    # longer reports zero turnover despite trading.
    assert rule.traded == pytest.approx(shares * 110)
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
    rule = _from(tmp_path, records, bars)["plain-value"]
    shares = 1.0 / 100.0
    cost = shares * 110 * REBALANCE_COST
    assert rule.returns[0] == pytest.approx(-cost, abs=1e-12)
    # 09-02 -> 09-03: held, 110 -> 120 over the account after the buy's cost.
    after_buy = 1.0 - cost
    after_120 = 1.0 - cost + shares * (120 - 110)
    assert rule.returns[1] == pytest.approx(after_120 / after_buy - 1.0)
    # 09-03 -> 09-04: the empty book is ignored (not a rebalance yet), the
    # position earns 120 -> 132 instead of being sold into cash.
    after_132 = 1.0 - cost + shares * (132 - 110)
    assert rule.returns[2] == pytest.approx(after_132 / after_120 - 1.0)


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
    rule = _from(tmp_path, records, bars)["plain-value"]
    shares = 1.0 / 100.0
    cost = shares * 110 * REBALANCE_COST
    assert rule.returns[0] == pytest.approx(-cost, abs=1e-12)
    # 09-02 -> 09-03: a rebalance to the same book trims the grown position
    # back toward target (sizing at the close, the desk's rule), so the
    # return is the day's ~110 -> 120 gain, not the no-trade the open-sized
    # walk reported.
    assert rule.returns[1] == pytest.approx(0.1, abs=1e-3)
    assert rule.traded > 0
    # 09-03 -> 09-04: the rebalance executes the empty book, selling the
    # whole position at the 09-04 open; the position is gone.
    assert rule.returns[2] > 0
    assert rule.invested[2] == pytest.approx(0.0, abs=1e-9)


def test_a_missing_challenger_block_holds_what_it_has_and_records_the_real_move(
    tmp_path,
):
    records = [
        _record("2026-09-01", [("SNDK", 1.0)], challenger=[("SNDK", 1.0)]),
        _record("2026-09-02", [("SNDK", 1.0)]),  # no challenger decision
        _record("2026-09-03", [("SNDK", 1.0)], challenger=[("SNDK", 1.0)]),
    ]
    bars = {
        "SNDK": [
            ("2026-09-01", 100, 100),
            ("2026-09-02", 110, 110),
            ("2026-09-03", 110, 120),
        ]
    }
    results = _from(tmp_path, records, bars)
    assert "plain-value" in results
    challenger = results["expectations-gap"]
    # The gap with no decision holds what it has: the position is not
    # liquidated, and the real 110 -> 120 move is recorded rather than a NaN
    # the equity rebuild would flatten to zero.
    assert np.isfinite(challenger.returns[1])
    shares = 1.0 / 100.0
    after_buy = 1.0 - shares * 110 * REBALANCE_COST
    assert challenger.returns[1] == pytest.approx(
        (after_buy + shares * (120 - 110)) / after_buy - 1.0
    )
    # The rule track still walks every gap.
    assert np.isfinite(results["plain-value"].returns).all()


def test_flat_prices_across_a_dividend_do_not_book_a_fake_move(tmp_path):
    # Raw prices are flat at 100. A $5 dividend with ex-date on 09-02 makes
    # the adjusted closes 95 on the pre-ex sessions and 100 on 09-03. The
    # walk prices the open on the adjusted basis too, so a flat price books
    # only the buy's cost - not a fake loss from mixing a raw open with an
    # adjusted close - and the later 95 -> 100 move is the dividend's real
    # total return, not a second fake.
    records = [
        _record("2026-09-01", [("SNDK", 1.0)]),
        _record("2026-09-02", [("SNDK", 1.0)]),
        _record("2026-09-03", [("SNDK", 1.0)]),
    ]
    bars = {
        "SNDK": [
            ("2026-09-01", 100, 100),
            ("2026-09-02", 100, 100),
            ("2026-09-03", 100, 100),
        ]
    }
    adj = {"SNDK": [95.0, 95.0, 100.0]}
    rule = _from(tmp_path, records, bars, adj)["plain-value"]
    # The buy fills at the adjusted open (95): the return is only the 10bp
    # cost, nowhere near the fake -5% the raw-open/raw-close mix would book.
    assert rule.returns[0] == pytest.approx(-REBALANCE_COST, abs=1e-9)
    assert rule.returns[0] > -0.02
    # The adjusted 95 -> 100 move across 09-03 is the dividend's real return.
    assert rule.returns[1] == pytest.approx(
        (1.0 - REBALANCE_COST + (1.0 / 95.0) * 5.0) / (1.0 - REBALANCE_COST) - 1.0,
        rel=1e-6,
    )


def test_fewer_than_two_records_answers_empty(tmp_path):
    assert _from(tmp_path, [_record("2026-09-01", [("SNDK", 1.0)])], {}) == {}


def test_a_challenger_that_starts_mid_run_enters_at_its_first_decision(tmp_path):
    # A new strategy first decides at record 2. Indexing the rebalance off
    # the run (i % 20) would keep it in cash until record 20 and report the
    # challenger's live run as 0% invested; it must enter at its first real
    # decision whatever index that is.
    records = [
        _record("2026-09-01", [("SNDK", 1.0)]),
        _record("2026-09-02", [("SNDK", 1.0)]),
        _record("2026-09-03", [("SNDK", 1.0)], challenger=[("SNDK", 1.0)]),
        _record("2026-09-04", [("SNDK", 1.0)], challenger=[("SNDK", 1.0)]),
    ]
    bars = {
        "SNDK": [
            ("2026-09-01", 100, 100),
            ("2026-09-02", 100, 100),
            ("2026-09-03", 100, 100),
            ("2026-09-04", 110, 110),
        ]
    }
    challenger = _from(tmp_path, records, bars)["expectations-gap"]
    # Pure cash before it has decided.
    assert challenger.invested[0] == pytest.approx(0.0, abs=1e-9)
    assert challenger.invested[1] == pytest.approx(0.0, abs=1e-9)
    # Its first decision at record 2 is filled at the 09-04 open: it trades
    # (the day's return is the fill cost, not a flat zero) and is invested,
    # instead of sitting in cash until record 20.
    assert challenger.invested[2] > 0
    assert challenger.traded > 0
    assert challenger.returns[2] < 0.0

