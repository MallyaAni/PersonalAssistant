"""The strict independent SPY/QQQ benchmark boundary.

The comparison must price each benchmark on its own against the strategy's
executable calendar: adjusted prices and complete coverage are required, an
absent benchmark or an interior gap is reported as unavailable rather than
silently dropped or zero-filled, the first fill carries the same one-way cost
(at the funded ledger's convention) at the first next-open, holding returns
are dividend-adjusted, and terminal holdings are marked at the last close
without hypothetical liquidation. The intentional initial NAV of 1 is distinct
from an unknown market return: only that single slot may be absent, and a
missing evaluated session rejects the whole measurement instead of becoming a
shorter, favorable window.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import simulate
from backend.market import benchmarks, strategy_bench
from backend.market.yahoo import DailyBar, TickerHistory


# Make a fixed calendar for deterministic account comparisons.
def _sessions(days: int, first: date = date(2024, 1, 2)) -> np.ndarray:
    """Return `days` consecutive session dates starting at `first`."""
    return np.array(
        [first + timedelta(days=i) for i in range(days)], dtype="datetime64[D]"
    )


# Construct stored bars with explicit raw and dividend-adjusted prices.
def _history(
    symbol: str,
    sessions: np.ndarray,
    adj: np.ndarray | None = None,
    close: np.ndarray | None = None,
    open_: np.ndarray | None = None,
    drop: set[int] | None = None,
) -> TickerHistory:
    """Return a TickerHistory whose bars match `sessions` (close==adj by default)."""
    n = len(sessions)
    adj = np.full(n, 100.0) if adj is None else np.asarray(adj, dtype=float)
    close = adj.copy() if close is None else np.asarray(close, dtype=float)
    open_ = close.copy() if open_ is None else np.asarray(open_, dtype=float)
    drop = drop or set()
    bars = []
    for i, session in enumerate(sessions):
        if i in drop:
            continue
        bars.append(
            DailyBar(
                session_date=session.astype(object),
                open=float(open_[i]),
                high=float(close[i]),
                low=float(close[i]),
                close=float(close[i]),
                adjusted_close=float(adj[i]),
                volume=1_000_000,
            )
        )
    return TickerHistory(
        ticker=symbol,
        bars=tuple(bars),
        actions=(),
        complete_through=date(2024, 12, 31),
        source_time=datetime(2024, 12, 31, tzinfo=UTC),
    )


class _Store:
    """A store surface the loader reads through; tests hold histories in memory."""

    # Keep the immutable histories needed by the loader.
    def __init__(self, histories: dict[str, TickerHistory]) -> None:
        self.histories = histories

    # Return the requested history without network or filesystem access.
    def read(self, symbol: str, asof=None):
        return self.histories.get(symbol)


# The first value of the series is the intentional starting NAV of 1, and the
# first return is an unknown market return (NaN), never a manufactured zero.
def test_initial_nav_of_one_is_distinct_from_an_unknown_market_return():
    sessions = _sessions(20)
    store = _Store({"SPY": _history("SPY", sessions)})
    series = benchmarks.load_benchmark(store, "SPY", sessions)
    assert series.available
    assert series.equity[0] == pytest.approx(1.0)
    assert np.isnan(series.daily[0])
    assert series.sessions is not None
    np.testing.assert_array_equal(series.sessions, sessions)


# An absent benchmark is reported as unavailable with a reason and null metric
# keys, never dropped and never fabricated as a flat cash line.
def test_absent_qqq_is_reported_unavailable_not_dropped():
    sessions = _sessions(20)
    store = _Store({"SPY": _history("SPY", sessions)})
    spy = benchmarks.load_benchmark(store, "SPY", sessions)
    qqq = benchmarks.load_benchmark(store, "QQQ", sessions)
    assert spy.available
    assert not qqq.available
    assert "QQQ" in qqq.reason
    payload = strategy_bench.build(sessions, {"SPY": spy, "QQQ": qqq}, note="")
    names = {row["name"] for block in payload["blocks"] for row in block["rows"]}
    assert names == {"SPY", "QQQ"}
    assert payload["unavailable"] == [{"name": "QQQ", "reason": qqq.reason}]
    spy_row = next(
        row
        for block in payload["blocks"]
        for row in block["rows"]
        if row["name"] == "SPY"
    )
    qqq_row = next(
        row
        for block in payload["blocks"]
        for row in block["rows"]
        if row["name"] == "QQQ"
    )
    assert spy_row["total"] is not None
    # Unavailable rows keep the measured row's metric keys, null-valued.
    assert qqq_row["unavailable"] == qqq.reason
    for key in strategy_bench.METRIC_KEYS:
        assert key in qqq_row
        assert qqq_row[key] is None


# A missing interior bar is a coverage failure, reported explicitly; it must
# not become apparent cash performance through a zero return.
def test_missing_interior_bar_fails_coverage():
    sessions = _sessions(20)
    store = _Store({"SPY": _history("SPY", sessions, drop={10})})
    series = benchmarks.load_benchmark(store, "SPY", sessions)
    assert not series.available
    assert "no adjusted price" in series.reason


# A benchmark whose own trading sessions do not line up with the strategy's
# calendar (a session the strategy has but the benchmark never traded) is a
# mismatched calendar and fails coverage explicitly.
def test_mismatched_calendars_fail_coverage():
    sessions = _sessions(20)
    short = sessions[:-1]  # the benchmark has no bar for the last session
    store = _Store({"SPY": _history("SPY", short)})
    series = benchmarks.load_benchmark(store, "SPY", sessions)
    assert not series.available
    assert "no adjusted price" in series.reason


# A benchmark that cannot be bought at the first next-open (no bar there) is
# unavailable, because the strategy's first fill also happens at that open.
def test_missing_first_fill_open_fails_coverage():
    sessions = _sessions(20)
    store = _Store({"SPY": _history("SPY", sessions, drop={1})})
    series = benchmarks.load_benchmark(store, "SPY", sessions)
    assert not series.available
    assert "first next-open" in series.reason


# Holding returns are dividend-adjusted: the daily return follows adjusted
# close (dividends reinvested), not the raw close.
def test_dividend_adjustment_flows_into_holding_returns():
    sessions = _sessions(20)
    close = np.full(20, 100.0)
    close[10:] = 95.0  # A $5 distribution lowers the quoted ex-dividend price.
    adj = np.full(20, 95.0)  # Reinvested total return stays flat across the dividend.
    store = _Store({"SPY": _history("SPY", sessions, adj=adj, close=close)})
    series = benchmarks.load_benchmark(store, "SPY", sessions, cost_bps=0.0)
    assert series.available
    assert series.daily[10] == pytest.approx(0.0)
    assert series.daily[9] == pytest.approx(0.0)


# The first fill charges the same configured one-way cost as the strategy, at
# the funded ledger's convention: whole-capital investment buys
# capital / (adjusted_open * (1 + cost)), so the cost is paid on the gross
# notional, not netted off the capital first.
def test_initial_cost_is_charged_once():
    sessions = _sessions(20)
    store = _Store({"SPY": _history("SPY", sessions)})
    free = benchmarks.load_benchmark(store, "SPY", sessions, cost_bps=0.0)
    dear = benchmarks.load_benchmark(store, "SPY", sessions, cost_bps=10.0)
    assert free.available
    assert dear.available
    np.testing.assert_allclose(free.daily[1:], np.zeros(19), atol=1e-12)
    assert dear.daily[1] == pytest.approx(1.0 / (1.0 + 10.0 / 1e4) - 1.0)
    np.testing.assert_allclose(dear.daily[2:], np.zeros(18), atol=1e-12)


# The benchmark's first-fill cost convention is the real simulator ledger's:
# run the desk's own account with an allocator that holds only the index and
# compare the resulting NAV to the benchmark's, at a large diagnostic cost
# that would expose a (1 - cost) vs 1 / (1 + cost) discrepancy.
def test_benchmark_matches_the_funded_ledger_cost_convention():
    from backend.tests.test_trading_simulate import _report

    sessions = _sessions(40)
    flat = np.full((40, 6), 100.0)
    report = _report(close=flat)
    spy_col = report.panel.index("SPY")
    target = np.zeros(6)
    target[spy_col] = 1.0
    cost_bps = 1000.0  # 10%: (1 - cost) = 0.90 differs clearly from 1/1.10
    result = simulate.run(
        report,
        use_exits=False,
        cost_bps=cost_bps,
        allocator=lambda r, p, c, t: target,
    )
    bench = benchmarks.load_benchmark(
        _Store({"SPY": _history("SPY", sessions)}),
        "SPY",
        sessions,
        cost_bps=cost_bps,
    )
    assert bench.available
    np.testing.assert_allclose(result.equity, bench.equity, rtol=1e-12)
    np.testing.assert_allclose(result.returns[1:], bench.daily[1:], rtol=1e-12)
    # The ledger pays the cost on the gross notional, so the first mark is
    # 1 / (1 + cost), not (1 - cost).
    assert bench.equity[1] == pytest.approx(1.0 / 1.10)


# An initial loss on the first fill shows up in the drawdown (the running
# maximum starts at the initial NAV of 1), not hidden behind a zero return.
def test_initial_loss_shows_in_drawdown():
    sessions = _sessions(20)
    adj = np.full(20, 100.0)
    open_ = np.full(20, 100.0)
    open_[1] = 105.0  # the first fill buys at 105, then marks at 100: a loss
    store = _Store({"SPY": _history("SPY", sessions, adj=adj, open_=open_)})
    series = benchmarks.load_benchmark(store, "SPY", sessions, cost_bps=0.0)
    assert series.available
    assert series.daily[1] == pytest.approx(100.0 / 105.0 - 1.0)
    s = strategy_bench.stats(series.daily[1:])
    assert s["drawdown"] == pytest.approx(100.0 / 105.0 - 1.0)


# Both benchmarks start at the same NAV and share the same executable dates.
def test_both_benchmarks_share_starting_nav_and_calendar():
    sessions = _sessions(30)
    store = _Store(
        {
            "SPY": _history("SPY", sessions, adj=np.linspace(100, 130, 30)),
            "QQQ": _history("QQQ", sessions, adj=np.linspace(100, 160, 30)),
        }
    )
    spy = benchmarks.load_benchmark(store, "SPY", sessions)
    qqq = benchmarks.load_benchmark(store, "QQQ", sessions)
    assert spy.available
    assert qqq.available
    assert spy.equity[0] == pytest.approx(1.0)
    assert qqq.equity[0] == pytest.approx(1.0)
    np.testing.assert_array_equal(spy.sessions, qqq.sessions)
    np.testing.assert_array_equal(spy.sessions, sessions)


# A missing evaluated return - leading, interior, or later-regime boundary -
# rejects the whole measurement (None), never a shorter, favorable window.
def test_stats_rejects_any_missing_evaluated_return():
    base = np.full(10, 0.01)
    for daily in (
        np.concatenate([[np.nan], base]),  # a missing return before the first
        np.array([0.01, 0.01, np.nan, *[0.01] * 7]),  # interior
        np.array([*[0.01] * 9, np.nan]),  # trailing / boundary
    ):
        s = strategy_bench.stats(daily)
        assert s["total"] is None
        assert s["drawdown"] is None


# build removes exactly the single intentional initial NAV slot at its
# calendar position (index 0); an extra missing early return is a missing
# evaluated session and rejects the block rather than shortening the window.
def test_build_drops_only_the_initial_nav_slot():
    sessions = _sessions(10)
    one_slot = np.concatenate([[np.nan], np.full(9, 0.01)])
    two_slots = np.concatenate([[np.nan], [np.nan], np.full(8, 0.01)])
    payload = strategy_bench.build(
        sessions, {"one slot": one_slot, "two slots": two_slots}, note=""
    )
    whole = next(b for b in payload["blocks"] if b["regime"] == "Whole sample")
    assert whole["sessions"] == 10  # the window is not shortened for either
    one = next(row for row in whole["rows"] if row["name"] == "one slot")
    assert one["total"] == pytest.approx(1.01**9 - 1)
    two = next(row for row in whole["rows"] if row["name"] == "two slots")
    assert two["total"] is None
    assert "Missing" in two["unavailable"]


# A NaN at the first session of a later regime block rejects that block only;
# the block still reports the same session count, so the window is identical.
def test_later_regime_boundary_missingness_rejects_that_block_only():
    sessions = np.array(
        [
            date(2021, 12, 30),
            date(2021, 12, 31),
            *[date(2022, 1, 3) + timedelta(days=i) for i in range(8)],
            date(2023, 1, 3),
            date(2023, 1, 4),
            date(2023, 1, 5),
        ],
        dtype="datetime64[D]",
    )
    clean = np.concatenate([[np.nan], np.full(len(sessions) - 1, 0.01)])
    boundary = clean.copy()
    boundary[2] = np.nan  # the first session of the 2022 bear block
    payload = strategy_bench.build(
        sessions, {"clean": clean, "boundary": boundary}, note=""
    )
    bear = next(b for b in payload["blocks"] if b["regime"] == "2022 bear")
    assert bear["sessions"] == 8
    clean_row = next(row for row in bear["rows"] if row["name"] == "clean")
    boundary_row = next(row for row in bear["rows"] if row["name"] == "boundary")
    assert clean_row["total"] == pytest.approx(1.01**8 - 1)
    assert boundary_row["total"] is None


# The loader rejects a malformed executable calendar rather than producing a
# fake available series or an IndexError.
@pytest.mark.parametrize(
    "bad",
    [
        [],
        [date(2024, 1, 2)],
        [date(2024, 1, 3), date(2024, 1, 2)],  # unsorted
        [date(2024, 1, 2), date(2024, 1, 2)],  # duplicate
        [np.datetime64("NaT", "D"), np.datetime64("NaT", "D")],  # NaT
    ],
)
def test_invalid_calendar_is_rejected_not_faked(bad):
    store = _Store({})
    with pytest.raises(ValueError, match="calendar"):
        benchmarks.load_benchmark(store, "SPY", bad)


# Non-finite or non-positive equity and non-finite or negative costs are
# caller errors, refused before any pricing.
def test_invalid_equity_and_cost_are_rejected():
    sessions = _sessions(10)
    store = _Store({})
    with pytest.raises(ValueError, match="equity"):
        benchmarks.load_benchmark(store, "SPY", sessions, start_equity=0.0)
    with pytest.raises(ValueError, match="equity"):
        benchmarks.load_benchmark(
            store, "SPY", sessions, start_equity=float("nan")
        )
    with pytest.raises(ValueError, match="cost"):
        benchmarks.load_benchmark(store, "SPY", sessions, cost_bps=-1.0)
    with pytest.raises(ValueError, match="cost"):
        benchmarks.load_benchmark(store, "SPY", sessions, cost_bps=float("nan"))


# A series that does not line up with the comparison's calendar is reported
# unavailable in the payload, never silently aligned by array offset.
def test_build_rejects_length_and_calendar_mismatch_as_unavailable():
    sessions = _sessions(10)
    short = np.full(9, 0.01)
    payload = strategy_bench.build(sessions, {"short": short}, note="")
    whole = next(b for b in payload["blocks"] if b["regime"] == "Whole sample")
    row = next(r for r in whole["rows"] if r["name"] == "short")
    assert row["total"] is None
    assert "short series has 9 returns" in row["unavailable"]
    # A BenchmarkSeries aligned to a different calendar is also unavailable.
    other = _sessions(10, first=date(2025, 1, 2))
    store = _Store({"SPY": _history("SPY", other)})
    wrong_cal = benchmarks.load_benchmark(store, "SPY", other)
    payload = strategy_bench.build(sessions, {"SPY": wrong_cal}, note="")
    whole = next(b for b in payload["blocks"] if b["regime"] == "Whole sample")
    row = next(r for r in whole["rows"] if r["name"] == "SPY")
    assert row["total"] is None
    assert "calendar does not match" in row["unavailable"]


# A valid benchmark calendar cannot conceal a malformed daily-return vector.
@pytest.mark.parametrize("daily", [None, 0.01, np.ones(9), np.ones((10, 1))])
def test_build_rejects_malformed_benchmark_returns(daily):
    sessions = _sessions(10)
    good = benchmarks.load_benchmark(
        _Store({"SPY": _history("SPY", sessions)}), "SPY", sessions
    )
    payload = strategy_bench.build(sessions, {"SPY": replace(good, daily=daily)})
    assert payload["unavailable"]
    assert payload["blocks"][0]["rows"][0]["total"] is None


# Reading a historical comparison preserves its original accounting version.
def test_legacy_payload_roundtrips_without_relabelling(tmp_path):
    old = {"version": "strategy-bench/1", "blocks": [], "note": "frozen"}
    strategy_bench.save(tmp_path, old)
    assert strategy_bench.load(tmp_path) == old


# Unavailability metadata is populated outside the regime loop, so it is
# present even when no regime block holds five sessions.
def test_unavailable_metadata_survives_when_no_regime_has_five_sessions():
    sessions = _sessions(2)
    qqq = benchmarks.load_benchmark(_Store({}), "QQQ", sessions)
    payload = strategy_bench.build(sessions, {"QQQ": qqq}, note="")
    assert payload["blocks"] == []
    assert payload["unavailable"] == [{"name": "QQQ", "reason": qqq.reason}]


# The comparison payload carries the new version and both benchmark rows when
# both are available, alongside a candidate's daily return array.
def test_build_emits_version_two_and_both_benchmark_rows():
    sessions = _sessions(30)
    store = _Store(
        {
            "SPY": _history("SPY", sessions, adj=np.linspace(100, 130, 30)),
            "QQQ": _history("QQQ", sessions, adj=np.linspace(100, 160, 30)),
        }
    )
    spy = benchmarks.load_benchmark(store, "SPY", sessions)
    qqq = benchmarks.load_benchmark(store, "QQQ", sessions)
    candidate = np.concatenate([[np.nan], np.full(29, 0.001)])
    payload = strategy_bench.build(
        sessions,
        {"Adopted strategy": candidate, "SPY": spy, "QQQ": qqq},
        note="focused boundary check",
    )
    assert payload["version"] == "strategy-bench/2"
    assert payload["unavailable"] == []
    whole = next(b for b in payload["blocks"] if b["regime"] == "Whole sample")
    names = {row["name"] for row in whole["rows"]}
    assert names == {"Adopted strategy", "SPY", "QQQ"}
    spy_row = next(row for row in whole["rows"] if row["name"] == "SPY")
    assert spy_row["total"] is not None
    assert spy_row["total"] > 0
    qqq_row = next(row for row in whole["rows"] if row["name"] == "QQQ")
    assert qqq_row["total"] is not None
    assert qqq_row["total"] > spy_row["total"]
