"""Execution quality as a series from the paper journal.

What has to hold: a buy filled above its reference is a positive cost and
a sell filled above its reference a negative one; the aggregate is
notional-weighted; FOMC fills are told apart from rebalance fills by the
event id; a fill without a reference is left out; the series runs by
session with a cumulative dollar figure.

And the split: every fill's distance from its decision price is drift to
the benchmark plus slippage from it, the two always add back to the
total, the benchmark follows the way the order was sent, a fill whose
benchmark bar is missing keeps its total and reports no split, and a
fill is dated to the session it completed in rather than the session it
was planned in.
"""

from backend.agents.trading.desk import paper
from backend.market import execution_quality as eq


def _row(session, symbol, side, qty, fill, reference, event=None, **execution):
    return {
        "session": session,
        "symbol": symbol,
        "side": side,
        "filled_qty": qty,
        "filled_price": fill,
        "event_id": event,
        "execution": {
            "reference_price": reference,
            "reference_source": "daily panel close",
            **execution,
        },
    }


class _Bar:
    """One session's prices, as the store returns them."""

    def __init__(self, session_date, open_, close):
        self.session_date = session_date
        self.open = open_
        self.close = close


class _History:
    def __init__(self, bars):
        self.bars = bars


class _Store:
    """The bars a benchmark needs, without a parquet file."""

    def __init__(self, bars):
        self.bars = bars
        self.asked = []

    def read(self, ticker, asof=None):
        self.asked.append((ticker, asof))
        rows = self.bars.get(ticker)
        return _History(rows) if rows else None


def _state(rows):
    state = paper.PaperState()
    state.journal = rows
    return state


def test_signs_weights_and_kinds():
    rows = eq.fill_rows(
        _state(
            [
                _row("2026-09-10", "NVDA", "buy", 10, 101.0, 100.0),  # paid up: +100 bp
                _row("2026-09-10", "AMD", "sell", 10, 101.0, 100.0),  # sold up: -100 bp
                _row("2026-09-14", "SMCI", "sell", 100, 9.9, 10.0, "fomc:2026-09-16"),
                _row("2026-09-14", "NONE", "buy", 5, 10.0, None),
            ]
        )
    )
    assert [r["symbol"] for r in rows] == ["AMD", "NVDA", "SMCI"]
    by = {r["symbol"]: r for r in rows}
    assert abs(by["NVDA"]["bps"] - 100.0) < 1e-9
    assert abs(by["NVDA"]["dollars"] - 10.0) < 1e-9
    assert abs(by["AMD"]["bps"] + 100.0) < 1e-9
    assert by["SMCI"]["kind"] == "fomc"
    assert abs(by["SMCI"]["bps"] - 100.0) < 1e-9  # sold 1% below the decision price
    agg = eq.aggregate(rows)
    assert agg["fills"] == 3
    assert abs(agg["notional"] - 3000.0) < 1e-9
    assert abs(agg["dollars"] - (10.0 - 10.0 + 10.0)) < 1e-9
    assert abs(agg["bps"] - 10.0 / 3000.0 * 1e4) < 1e-9


def test_report_series_and_kinds():
    block = eq.report(
        _state(
            [
                _row("2026-09-10", "NVDA", "buy", 10, 101.0, 100.0),
                _row("2026-09-14", "SMCI", "sell", 100, 9.9, 10.0, "fomc:2026-09-16"),
            ]
        )
    )
    assert [s["session"] for s in block["series"]] == ["2026-09-10", "2026-09-14"]
    assert abs(block["series"][-1]["cumulative_dollars"] - 20.0) < 1e-9
    assert block["by_kind"]["fomc"]["fills"] == 1
    assert block["by_kind"]["rebalance"]["fills"] == 1
    assert block["by_side"]["sell"]["fills"] == 1
    # Neither row has a broker stamp, so neither is split and neither can
    # be ranked by slippage.
    assert block["worst"] == []
    assert eq.report(_state([]))["all_time"]["bps"] is None


def test_write_and_load_round_trip(tmp_path, capsys):
    root = tmp_path
    paper.save_state(
        root, _state([_row("2026-09-10", "NVDA", "buy", 10, 101.0, 100.0)])
    )
    block = eq.write(root)
    assert block is not None
    printed = capsys.readouterr().out
    assert "1 fills" in printed
    assert "+100.0 bp in all against the decision price" in printed
    assert eq.load(root)["all_time"]["fills"] == 1


# Opposite-signed fills net toward zero; the absolute figure keeps their size.
def test_aggregate_keeps_the_absolute_distance_beside_the_net():
    rows = eq.fill_rows(
        _state(
            [
                _row("2026-09-10", "NVDA", "buy", 10, 101.0, 100.0),  # +100 bp
                _row("2026-09-10", "AMD", "buy", 10, 99.0, 100.0),  # -100 bp
            ]
        )
    )
    agg = eq.aggregate(rows)
    assert abs(agg["bps"]) < 1e-9
    assert abs(agg["abs_bps"] - 100.0) < 1e-9


# The whole point: an order decided at one close and filled at the next
# open carries the overnight move, and that move is not execution. The
# nine real FOMC restoration buys of 2026-09-17 measured +234 bp against
# their decision price; the split says +243 bp of it was the gap and
# -9 bp was the trading.
def test_the_overnight_gap_is_drift_and_the_rest_is_slippage():
    from datetime import date

    row = _row(
        "2026-09-16",
        "NVDA",
        "buy",
        12,
        217.865,
        213.89999389648438,
        event="fomc-3-session-weakness/2:2026-09-16",
        filled_at="2026-09-17T13:33:10.875610Z",
    )
    store = _Store({"NVDA": [_Bar(date(2026, 9, 17), 218.388, 219.0)]})
    (out,) = eq.fill_rows(_state([row]), store)
    assert out["session"] == "2026-09-17"  # the session it filled in
    assert out["decision_session"] == "2026-09-16"
    assert out["benchmark_kind"] == "open"
    assert out["benchmark"] == 218.388
    assert round(out["bps"], 1) == 185.4
    assert round(out["drift_bps"], 1) == 209.8
    assert round(out["slippage_bps"], 1) == -24.5
    # The split always adds back to the total, in dollars and in points.
    assert abs(out["drift_dollars"] + out["slippage_dollars"] - out["dollars"]) < 1e-9
    assert abs(out["drift_bps"] + out["slippage_bps"] - out["bps"]) < 1e-9
    assert store.asked == [("NVDA", None)]


# The benchmark follows the way the order was sent, because the order
# could not have traded anywhere else: a scheduled sell goes into the
# closing auction, an intraday cut is already trading against its bar.
def test_the_benchmark_follows_the_order_type():
    from datetime import date

    store = _Store({"AAA": [_Bar(date(2026, 9, 14), 100.0, 110.0)]})
    scheduled_sell = _row(
        "2026-09-11",
        "AAA",
        "sell",
        10,
        108.0,
        105.0,
        filled_at="2026-09-14T20:00:00Z",
    )
    (sell,) = eq.fill_rows(_state([scheduled_sell]), store)
    assert sell["benchmark_kind"] == "close"
    assert sell["benchmark"] == 110.0  # the closing auction it was sent to
    # Sold below the close it was aiming at: adverse, so positive.
    assert round(sell["slippage_bps"], 1) == 190.5
    assert round(sell["drift_bps"], 1) == -476.2

    event_sell = _row(
        "2026-09-14",
        "AAA",
        "sell",
        10,
        104.0,
        105.0,
        event="fomc-3-session-weakness/2:2026-09-16",
        reference_source="completed 15-minute bar",
        filled_at="2026-09-14T16:48:17Z",
    )
    (cut,) = eq.fill_rows(_state([event_sell]), store)
    assert cut["benchmark_kind"] == "reference"
    assert cut["benchmark"] == 105.0
    assert cut["drift_dollars"] == 0  # nothing was waited through
    assert abs(cut["slippage_dollars"] - cut["dollars"]) < 1e-9

    # An event sell is queued for the open like a buy, not into the close.
    queued = _row(
        "2026-09-11",
        "AAA",
        "sell",
        10,
        108.0,
        105.0,
        event="fomc-3-session-weakness/2:2026-09-16",
        filled_at="2026-09-14T13:31:00Z",
    )
    (opened,) = eq.fill_rows(_state([queued]), store)
    assert opened["benchmark_kind"] == "open"
    assert opened["benchmark"] == 100.0


# A fill whose benchmark bar is not on file keeps its total and says the
# split is unknown, rather than reporting a wrong one.
def test_a_missing_benchmark_leaves_the_total_and_no_split():
    row = _row("2026-09-10", "NVDA", "buy", 10, 101.0, 100.0)
    for store in (None, _Store({})):
        (out,) = eq.fill_rows(_state([row]), store)
        assert round(out["bps"], 1) == 100.0
        assert out["benchmark"] is None
        assert out["drift_bps"] is None
        assert out["slippage_bps"] is None
    agg = eq.aggregate(eq.fill_rows(_state([row]), None))
    assert agg["fills"] == 1
    assert agg["measured"] == 0
    assert agg["slippage_bps"] is None
    assert agg["drift_bps"] is None


# The aggregate weights the split over the fills that have one, and says
# how many that was, so a partial split never reads as every fill.
def test_the_aggregate_weights_the_split_over_the_fills_that_have_one():
    from datetime import date

    store = _Store({"AAA": [_Bar(date(2026, 9, 14), 100.0, 100.0)]})
    split = _row(
        "2026-09-11",
        "AAA",
        "buy",
        10,
        102.0,
        100.0,
        filled_at="2026-09-14T13:31:00Z",
    )
    unsplit = _row("2026-09-14", "BBB", "buy", 10, 110.0, 100.0)
    agg = eq.aggregate(eq.fill_rows(_state([split, unsplit]), store))
    assert agg["fills"] == 2
    assert agg["measured"] == 1
    assert agg["measured_notional"] == 1000
    assert abs(agg["drift_bps"] - 0.0) < 1e-9  # open equals the reference
    assert abs(agg["slippage_bps"] - 200.0) < 1e-9
    # The unsplit fill is still in the total.
    assert round(agg["bps"], 1) == 600.0


# The worst table is the worst trading, not the biggest gap: a name that
# gapped is not an execution failure and must not occupy the list.
def test_the_worst_fills_are_ranked_by_slippage():
    from datetime import date

    store = _Store(
        {
            "GAP": [_Bar(date(2026, 9, 14), 150.0, 150.0)],
            "BAD": [_Bar(date(2026, 9, 14), 100.0, 100.0)],
        }
    )
    gapped = _row(
        "2026-09-11",
        "GAP",
        "buy",
        10,
        150.5,
        100.0,
        filled_at="2026-09-14T13:31:00Z",
    )
    badly_traded = _row(
        "2026-09-11",
        "BAD",
        "buy",
        10,
        103.0,
        100.0,
        filled_at="2026-09-14T13:31:00Z",
    )
    block = eq.report(_state([gapped, badly_traded]), store=store)
    assert [r["symbol"] for r in block["worst"]] == ["BAD", "GAP"]
    assert block["version"] == "execution-quality/2"
    assert "slippage is the benchmark to the fill" in block["basis"]
    # Dated to the session they filled in, not the session they were planned.
    assert [r["session"] for r in block["series"]] == ["2026-09-14"]


# The blocking defect the review found: without the broker's stamp the fill
# session is unknown, and reading the plan session's bar instead produces a
# confident, wrong split. The store here HOLDS that bar, so the old
# empty-store test could never have caught it.
def test_a_fill_without_a_broker_stamp_is_never_split_from_the_plan_session():
    from datetime import date

    store = _Store(
        {
            "NVDA": [
                _Bar(date(2026, 9, 16), 205.0, 213.89999389648438),
                _Bar(date(2026, 9, 17), 218.388, 219.0),
            ]
        }
    )
    row = _row(
        "2026-09-16",
        "NVDA",
        "buy",
        12,
        217.865,
        213.89999389648438,
        event="fomc-3-session-weakness/2:2026-09-16",
    )  # no filled_at
    (out,) = eq.fill_rows(_state([row]), store)
    assert out["benchmark"] is None
    assert out["drift_bps"] is None
    assert out["slippage_bps"] is None
    assert round(out["bps"], 1) == 185.4  # the total still stands
    assert store.asked == []  # the store is never even asked


# A scheduled sell without a stamp would benchmark to its own decision close
# and report the entire gap as slippage. It must not be split either.
def test_a_scheduled_sell_without_a_stamp_reports_no_slippage():
    from datetime import date

    store = _Store({"BBB": [_Bar(date(2026, 9, 11), 99.0, 100.0)]})
    row = _row("2026-09-11", "BBB", "sell", 10, 90.0, 100.0)
    (out,) = eq.fill_rows(_state([row]), store)
    assert out["slippage_bps"] is None
    assert round(out["bps"], 1) == 1000.0


# The second blocking defect: the nightly labels its bars partition with the
# UTC date, so after 20:00 New York there is no partition at or before the
# session it just fetched. Reading the newest partition and matching on the
# bar's own session date finds it anyway. This uses the real MarketStore.
def test_the_benchmark_is_found_when_the_partition_is_labelled_the_next_day(tmp_path):
    import pytest

    pytest.importorskip("pyarrow")
    from datetime import UTC, date, datetime

    from backend.market.store import MarketStore
    from backend.market.yahoo import DailyBar, TickerHistory

    store = MarketStore(tmp_path)
    bars = (
        DailyBar(date(2026, 9, 16), 205.0, 214.0, 204.0, 213.9, 213.9, 1_000),
        DailyBar(date(2026, 9, 17), 218.388, 220.0, 217.0, 219.0, 219.0, 1_000),
    )
    # Fetched at 23:07 New York on the 17th, so the partition is the 18th.
    store.write(
        date(2026, 9, 18),
        TickerHistory(
            ticker="NVDA",
            bars=bars,
            actions=(),
            complete_through=date(2026, 9, 17),
            source_time=datetime(2026, 9, 18, 3, 7, tzinfo=UTC),
        ),
    )
    assert store.latest_asof("NVDA", date(2026, 9, 17)) is None  # the trap
    row = _row(
        "2026-09-16",
        "NVDA",
        "buy",
        12,
        217.865,
        213.89999389648438,
        event="fomc-3-session-weakness/2:2026-09-16",
        filled_at="2026-09-17T13:33:10.875610Z",
    )
    (out,) = eq.fill_rows(_state([row]), store)
    assert out["benchmark"] == 218.388
    assert round(out["drift_bps"], 1) == 209.8
    assert round(out["slippage_bps"], 1) == -24.5


# An order sent into the middle of the session it filled in was never queued
# for the open, so the morning's move is not its slippage.
def test_an_order_submitted_inside_the_session_has_no_opening_benchmark():
    from datetime import date

    store = _Store({"AAA": [_Bar(date(2026, 9, 14), 100.0, 105.0)]})
    queued = _row(
        "2026-09-11",
        "AAA",
        "buy",
        10,
        102.0,
        100.0,
        filled_at="2026-09-14T13:31:00Z",
        submitted_at="2026-09-14T08:00:41Z",  # 04:00 New York, before the open
    )
    (ahead,) = eq.fill_rows(_state([queued]), store)
    assert ahead["benchmark"] == 100.0
    assert round(ahead["slippage_bps"], 1) == 200.0

    retried = _row(
        "2026-09-11",
        "AAA",
        "buy",
        10,
        102.0,
        100.0,
        filled_at="2026-09-14T15:05:00Z",
        submitted_at="2026-09-14T15:00:00Z",  # 11:00 New York, mid-session
    )
    (inside,) = eq.fill_rows(_state([retried]), store)
    assert inside["benchmark"] is None
    assert inside["slippage_bps"] is None
    assert round(inside["bps"], 1) == 200.0
