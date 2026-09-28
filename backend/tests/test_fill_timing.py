"""The fill-timing trial's engine, statistics, verdict and command.

What has to hold: each convention's fill price is the plan's arithmetic
on a hand-made session; `next_open` priced by the engine reproduces the
plain simulator's daily returns to 1e-10 on a store whose bar-0 opens are
the panel's opens; a store whose price always dips in the first hour and
recovers makes `dip_or_close` beat `next_open` with a large t and the
verdict ADOPTED; iid intraday noise leaves every convention inside the
noise and the verdict RECORDED; `breakout_gate` defers a buy while the band
rejects and fills at the open otherwise, capped at five deferrals; and the
command runs end to end on a temporary SIP store.
"""

from __future__ import annotations

import io
import json
import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import exit as exit_analyst
from backend.agents.trading.desk import grading, paper, policy_v4, regime, simulate
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_fill_timing as cli
from backend.market import fill_timing as ft
from backend.market import intraday_sip as sip
from backend.market.alpaca import IntradayBar, bars_expected
from backend.market.panel import Panel
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.market.store import MarketStore
from backend.market.universe import AI_COMPUTE
from backend.market.yahoo import DailyBar, TickerHistory

SLOTS = FULL_SESSION_SLOTS
NAMES = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH")
PROVENANCE = sip.Provenance(
    fetched_at="2026-09-26T01:00:00+00:00", source_revision="abc123"
)


# `n` weekdays from `start`, as datetime64[D].
def _dates(n: int, start: date = date(2022, 1, 3)) -> np.ndarray:
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return np.array(out, dtype="datetime64[D]")


# A desk report over `dates` whose grades churn between A+ and C on every
# name so each reset rotates much of the book, with the given raw
# open/close and an adjustment factor per name on the close.
def _report(
    dates: np.ndarray,
    open_: np.ndarray,
    close: np.ndarray,
    grades: np.ndarray,
    factor: np.ndarray | None = None,
) -> DeskReport:
    t, n = close.shape
    tickers = NAMES[: n - 1] + ("SPY",)
    adj = close * (factor if factor is not None else 1.0)
    panel = Panel(
        dates=dates,
        tickers=tickers,
        open=open_,
        high=np.maximum(open_, close) * 1.001,
        low=np.minimum(open_, close) * 0.999,
        close=close,
        adj_close=adj,
        volume=np.full_like(close, 1e6),
        themes={k: (AI_COMPUTE,) for k in tickers[:-1]},
        benchmark="SPY",
    )
    conviction = grades.astype(float)
    graded = grading.Graded(grades, conviction.copy(), {}, conviction)
    state = regime.RegimeState(
        0.0, 0.0, 0.5, 0.0, 0.0, 0.0, "ai", 0.1, 0.0, 1.0, 1.0, (), 0.0, False
    )
    view = regime.RegimeView([state] * t, Opinion("rotation", np.full((t, n), np.nan)))
    return DeskReport(
        panel, {k: "ai" for k in tickers[:-1]}, {}, view, graded, graded.as_scores(), []
    )


# Churning grades: each name flips between A+ and C independently.
def _grades(rng, t: int, n: int) -> np.ndarray:
    grades = rng.choice(
        [grading.ORDINAL[grading.A_PLUS], grading.ORDINAL[grading.C]], size=(t, n)
    )
    grades[:, -1] = 0
    return grades


# Daily raw opens and closes: a random walk with an overnight gap.
def _daily(rng, t: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    close = 100.0 * np.exp(rng.normal(0.0003, 0.015, size=(t, n)).cumsum(axis=0))
    prior = np.vstack([close[:1], close[:-1]])
    open_ = prior * np.exp(rng.normal(0.0, 0.004, size=(t, n)))
    return open_, close


# One name's cube from its daily opens and closes: bar 0 opens at the
# daily open and bar 25 closes at the daily close, with the path between
# them either a Brownian bridge ("noise") or a dip of `dip` on the first
# bar's close that recovers through the first hour and then linearly to
# the close ("dip"). The auction print is the daily close.
def _cube(
    ticker: str,
    dates: np.ndarray,
    open_: np.ndarray,
    close: np.ndarray,
    rng,
    shape: str = "noise",
    dip: float = 0.03,
) -> SessionCube:
    n = len(dates)
    log_ratio = np.log(close / open_)
    if shape == "noise":
        walk = rng.normal(0.0, 0.003, size=(n, SLOTS)).cumsum(axis=1)
        steps = (np.arange(SLOTS) + 1) / SLOTS
        path = walk + steps[None, :] * (log_ratio[:, None] - walk[:, -1:])
    else:
        depth = np.log1p(-dip)
        first = np.array([depth, depth * 2 / 3, depth / 3, depth / 6])
        rest = depth / 6 + (np.arange(4, SLOTS) - 3) / (SLOTS - 4) * (
            log_ratio[:, None] - depth / 6
        )
        path = np.hstack([np.tile(first, (n, 1)), rest])
    bar_close = open_[:, None] * np.exp(path)
    bar_open = np.column_stack([open_, bar_close[:, :-1]])
    return SessionCube(
        ticker=ticker,
        dates=dates,
        open=bar_open,
        high=np.maximum(bar_open, bar_close),
        low=np.minimum(bar_open, bar_close),
        close=bar_close,
        volume=np.full((n, SLOTS), 1000.0),
        prior_close=np.full(n, np.nan),
        excluded={"early_close": 0, "incomplete": 0, "no_prior_close": 0},
        auction_open=close.copy(),
        auction_volume=np.full(n, np.nan),
    )


# A report, its all-member mask and one cube per name.
def _world(
    t: int = 300,
    n: int = 5,
    seed: int = 0,
    shape: str = "noise",
    dip: float = 0.03,
    factor: np.ndarray | None = None,
    start: date = date(2022, 1, 3),
):
    rng = np.random.default_rng(seed)
    dates = _dates(t, start)
    open_, close = _daily(rng, t, n)
    report = _report(dates, open_, close, _grades(rng, t, n), factor)
    mask = np.ones((t, n), dtype=bool)
    mask[:, -1] = False
    cubes = {
        name: _cube(name, dates, open_[:, j], close[:, j], rng, shape, dip)
        for j, name in enumerate(report.panel.tickers[:-1])
    }
    return report, mask, cubes


# A hand-made session: bar closes from 100 rising a tenth a bar, with a
# dip to 98.5 at slot 2 and equal volume except the late bars.
def _row(dip: bool = True, auction: float = math.nan) -> dict:
    close = 100.0 + 0.1 * np.arange(SLOTS)
    if dip:
        close[2] = 98.5
    volume = np.full(SLOTS, 100.0)
    volume[22:26] = [100.0, 200.0, 300.0, 400.0]
    return {
        "open": np.concatenate([[100.0], close[:-1]]),
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": volume,
        "auction_open": auction,
    }


# The constants are the plan's, frozen.
def test_constants_are_the_plans():
    assert ft.CONVENTIONS == (
        "next_open",
        "first_hour_vwap",
        "session_vwap",
        "next_close",
        "dip_or_close",
        "late_day",
        "breakout_gate",
    )
    assert ft.DIP == 0.01
    assert ft.LATE_SLOTS == (22, 23, 24, 25)
    assert ft.FIRST_HOUR_SLOTS == 4
    assert ft.COST_BPS == (10.0,)
    assert ft.ADOPT_BP == 5.0
    assert ft.ADOPT_T == 2.5
    assert ft.TRIALS == 7
    assert ft.MAX_DEFERRALS == 5
    assert ft.HAC_LAG == 20


# Each convention's price on the hand-made session is the plan's arithmetic.
def test_fill_price_per_convention():
    row = _row()
    close = row["close"]
    assert ft.fill_price(row, "next_open", "buy") == 100.0
    assert ft.fill_price(row, "first_hour_vwap", "buy") == pytest.approx(
        close[:4].mean()
    )
    assert ft.fill_price(row, "session_vwap", "sell") == pytest.approx(
        (close * row["volume"]).sum() / row["volume"].sum()
    )
    # The dip at slot 2 (98.5 <= 99) is the buy; the first close >= 101 is
    # slot 10, the sell.
    assert ft.fill_price(row, "dip_or_close", "buy") == 98.5
    assert ft.fill_price(row, "dip_or_close", "sell") == pytest.approx(101.0)
    # No dip: the buy falls back to the official close, the auction when
    # present and the last bar's close otherwise.
    flat = _row(dip=False)
    assert ft.fill_price(flat, "dip_or_close", "buy") == pytest.approx(close[25])
    assert ft.fill_price(_row(dip=False, auction=102.7), "dip_or_close", "buy") == 102.7
    assert ft.fill_price(flat, "next_close", "buy") == pytest.approx(close[25])
    assert ft.fill_price(_row(auction=102.7), "next_close", "sell") == 102.7
    late = (close[22:26] * np.array([100.0, 200.0, 300.0, 400.0])).sum() / 1000.0
    assert ft.fill_price(row, "late_day", "buy") == pytest.approx(late)
    assert ft.fill_price(row, "breakout_gate", "buy") == 100.0
    assert math.isnan(ft.fill_price(row, "breakout_gate", "buy", blocked=True))
    # A blocked sell never waits.
    assert ft.fill_price(row, "breakout_gate", "sell", blocked=True) == 100.0
    with pytest.raises(ValueError, match="unknown convention"):
        ft.fill_price(row, "midnight", "buy")
    with pytest.raises(ValueError, match="side must be"):
        ft.fill_price(row, "next_open", "hold")


# The target path is the simulator's decision clock: every 20 sessions
# from the `since` row while a next session exists, the policy's targets
# on those rows and nothing on the others.
def test_target_path_is_the_simulators_clock():
    report, mask, _ = _world(t=65)
    path = ft.target_path(report, mask, ft.since_offset(report.panel, 3))
    assert path.start == 3
    assert path.decisions == (3, 23, 43, 63)
    allocate = policy_v4.allocator(mask)
    for t in path.decisions:
        np.testing.assert_array_equal(
            path.weights[t], allocate(report, report.panel, None, t)
        )
    assert np.isnan(path.weights[4]).all()
    assert np.isnan(path.weights[64]).all()
    # `since=None` starts on row 0; a `since` beyond the last decision row
    # still records the start.
    assert ft.target_path(report, mask, None).start == 0
    assert (
        ft.target_path(report, mask, ft.since_offset(report.panel, 64)).decisions == ()
    )


# The acceptance path: `next_open` priced here reproduces `simulate.run`
# with the policy's allocator, element for element to 1e-10, at several
# offsets, on a store whose bar-0 opens are the panel's opens and with a
# per-name adjustment factor so the basis scaling is exercised too.
@pytest.mark.parametrize("offset", [0, 7, 19])
def test_next_open_reproduces_the_simulator(offset):
    factor = np.array([1.0, 0.5, 2.0, 0.9, 1.1])
    report, mask, cubes = _world(t=260, factor=factor[None, :])
    panel = report.panel
    since = ft.since_offset(panel, offset)
    sim = simulate.run(
        report,
        since=since,
        allocator=policy_v4.allocator(mask),
        cost_bps=10.0,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
    )
    prices = ft.cube_prices(cubes, panel, "next_open")
    ours = ft.price_book(
        ft.target_path(report, mask, since), report, prices, "next_open", 10.0
    )
    np.testing.assert_array_equal(
        np.isnan(ours.returns[offset:]), np.isnan(sim.returns)
    )
    np.testing.assert_allclose(
        ours.returns[offset:], sim.returns, atol=1e-10, rtol=0, equal_nan=True
    )
    assert ours.fills > 0
    assert ours.fallbacks == 0
    assert ours.deferrals == 0
    assert sim.rebalances == len(ft.target_path(report, mask, since).decisions)
    gap = ft.simulator_gap(report, mask, ours, 10.0)
    assert gap["max_abs_bp"] < 1e-6
    assert gap["nan_mismatch"] == 0


# A name with no cube session on its fill day fills at the panel's open,
# the simulator's price, and is counted.
def test_missing_cube_session_falls_back_to_the_open():
    report, mask, cubes = _world(t=80)
    panel = report.panel
    missing = {k: v for k, v in cubes.items() if k != "AAA"}
    sim = simulate.run(
        report,
        allocator=policy_v4.allocator(mask),
        cost_bps=10.0,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
    )
    prices = ft.cube_prices(missing, panel, "next_open")
    assert not prices.available[:, 0].any()
    assert prices.available[:, 1].all()
    ours = ft.price_book(
        ft.target_path(report, mask, None), report, prices, "next_open", 10.0
    )
    np.testing.assert_allclose(ours.returns, sim.returns, atol=1e-10, equal_nan=True)
    assert ours.fallbacks > 0


# A store whose price always dips 5% in the first hour and recovers makes
# `dip_or_close` beat `next_open` on every buy: the paired difference is
# large with a large t and the verdict is ADOPTED. (The plan's example is a
# 1.5% dip, which on this churning eight-name book is worth about 1.5 bp a
# session - real, and below the floor; 5% is used so the 5 bp-a-session
# floor is crossed. The direction is the point, the floor is the plan's.)
def test_dip_store_adopts_dip_or_close():
    report, mask, cubes = _world(t=620, n=9, seed=3, shape="dip", dip=0.05)
    payload = ft.study(report, cubes, mask, offsets=3, cost=10.0)
    rows = {(r["convention"], r["window"]): r for r in payload["rows"]}
    dip = rows[("dip_or_close", ft.CHOOSING)]
    assert dip["mean_daily_bp_vs_open"] >= ft.ADOPT_BP
    assert dip["hac_t_vs_open"] >= ft.ADOPT_T
    assert dip["offsets_above_open"] == 3
    assert rows[("dip_or_close", ft.REPORTED)]["mean_daily_bp_vs_open"] > 0
    assert rows[("dip_or_close", ft.REPORTED)]["sessions"] > 50
    assert "dip_or_close" in payload["adopted"]
    assert payload["verdict"].startswith(ft.ADOPTED)
    assert payload["best"][ft.CHOOSING]["convention"] == "dip_or_close"
    assert payload["best"][ft.CHOOSING]["trials"] == 7
    assert 0.0 <= payload["best"][ft.CHOOSING]["deflated_sharpe"] <= 1.0
    # The control's own row is the zero line.
    control = rows[("next_open", ft.CHOOSING)]
    assert control["mean_daily_bp_vs_open"] == 0.0
    assert control["offsets_above_open"] == 0


# iid intraday noise leaves every convention inside the noise: nothing
# clears the floor and the verdict is RECORDED, NOT ACTED ON.
def test_noise_store_records_and_does_not_act():
    report, mask, cubes = _world(t=620, seed=2, shape="noise")
    payload = ft.study(report, cubes, mask, offsets=3, cost=10.0)
    assert payload["adopted"] == []
    assert payload["verdict"].startswith(ft.RECORDED)
    for row in payload["rows"]:
        if row["window"] == ft.CHOOSING and row["convention"] != "next_open":
            assert abs(row["mean_daily_bp_vs_open"]) < ft.ADOPT_BP
            assert abs(row["hac_t_vs_open"]) < ft.ADOPT_T or math.isnan(
                row["hac_t_vs_open"]
            )
    assert len(payload["rows"]) == 7 * 3
    assert set(payload["criteria"]) == set(ft.CONVENTIONS) - {"next_open"}
    assert payload["breakout_gate"].startswith("breakout_gate")
    assert payload["simulator_gap"]["max_abs_bp"] < 1e-6


# The band flags the engine reads are the executor's own function.
def test_band_rejecting_is_the_executors_signal():
    report, _, _ = _world(t=80)
    np.testing.assert_array_equal(
        ft.band_rejecting(report.panel), exit_analyst.evidence(report.panel).signalled()
    )


# `breakout_gate` with nothing rejecting is `next_open`; a buy decided
# while its name rejects the band waits one session and fills at the
# following open; the deferrals are counted and a sell never waits.
def test_breakout_gate_defers_while_the_band_rejects():
    report, mask, cubes = _world(t=90, seed=1)
    panel = report.panel
    targets = ft.target_path(report, mask, None)
    prices = ft.cube_prices(cubes, panel, "breakout_gate")
    clear = np.zeros(panel.adj_close.shape, dtype=bool)
    open_only = ft.price_book(
        targets, report, ft.cube_prices(cubes, panel, "next_open"), "next_open", 10.0
    )
    same = ft.price_book(targets, report, prices, "breakout_gate", 10.0, blocked=clear)
    np.testing.assert_allclose(
        same.returns, open_only.returns, atol=1e-12, equal_nan=True
    )
    assert same.deferrals == 0
    # AAA rejects on the second decision date only: its buy (if any) waits
    # one session. Make sure it is a buy by holding nothing in it before.
    t = targets.decisions[1]
    blocked = clear.copy()
    blocked[t, 0] = True
    gated = ft.price_book(
        targets, report, prices, "breakout_gate", 10.0, blocked=blocked
    )
    buying = targets.weights[t, 0] > 0
    assert gated.deferrals == (1 if buying else 0)
    if buying:
        # Until the deferred fill nothing differs; the sessions t+1 and t+2
        # carry the difference of filling at the later open.
        np.testing.assert_allclose(
            gated.returns[: t + 1], open_only.returns[: t + 1], equal_nan=True
        )
        assert (
            gated.returns[t + 1] != open_only.returns[t + 1]
            or gated.returns[t + 2] != open_only.returns[t + 2]
        )
    # A sell on a rejecting name fills at the open regardless.
    with pytest.raises(ValueError, match="band-rejection"):
        ft.price_book(targets, report, prices, "breakout_gate", 10.0)


# A name rejecting the band on every session waits five sessions and then
# fills at the open regardless.
def test_deferral_cap():
    report, mask, cubes = _world(t=90, seed=2)
    panel = report.panel
    targets = ft.target_path(report, mask, None)
    prices = ft.cube_prices(cubes, panel, "breakout_gate")
    always = np.zeros(panel.adj_close.shape, dtype=bool)
    always[:, 1] = True
    gated = ft.price_book(
        targets, report, prices, "breakout_gate", 10.0, blocked=always
    )
    buys = 0
    shares = np.zeros(len(panel.tickers))
    # Count BBB's buys on the decision clock the way the ledger sees them
    # (a weight above zero from zero, or an increase).
    for t in targets.decisions:
        w = targets.weights[t, 1]
        if w > 0 and w > shares[1]:
            buys += 1
        shares[1] = w
    assert buys >= 1
    assert gated.deferrals == ft.MAX_DEFERRALS * buys
    assert ft._gated_fill_session(always, 10, 1) == (16, 5)
    assert ft._gated_fill_session(always, 10, 0) == (11, 0)
    # A rejection that clears after two sessions is two deferrals.
    two = np.zeros((30, 3), dtype=bool)
    two[10:12, 2] = True
    assert ft._gated_fill_session(two, 10, 2) == (13, 2)


# The verdict reads the rows alone and applies the plan's floors: ADOPTED
# needs both floors on the choosing window and no loss on the reported
# window; a missing reported window is not "not worse".
def test_verdict_applies_the_kill_criteria():
    def payload(bp, t, later):
        rows = [
            {
                "convention": "late_day",
                "window": ft.CHOOSING,
                "mean_daily_bp_vs_open": bp,
                "hac_t_vs_open": t,
            },
            {
                "convention": "late_day",
                "window": ft.REPORTED,
                "mean_daily_bp_vs_open": later,
                "hac_t_vs_open": 0.0,
            },
            {
                "convention": "breakout_gate",
                "window": ft.CHOOSING,
                "mean_daily_bp_vs_open": -2.0,
                "hac_t_vs_open": -3.0,
            },
        ]
        return {
            "conventions": ["next_open", "late_day", "breakout_gate"],
            "control": "next_open",
            "rows": rows,
        }

    assert ft.verdict(payload(6.0, 3.0, 0.5))["adopted"] == ["late_day"]
    assert ft.verdict(payload(6.0, 3.0, 0.5))["verdict"].startswith(ft.ADOPTED)
    assert ft.verdict(payload(4.9, 3.0, 0.5))["adopted"] == []
    assert ft.verdict(payload(6.0, 2.4, 0.5))["adopted"] == []
    assert ft.verdict(payload(6.0, 3.0, -0.1))["adopted"] == []
    assert ft.verdict(payload(6.0, 3.0, math.nan))["adopted"] == []
    out = ft.verdict(payload(1.0, 1.0, 0.0))
    assert out["verdict"].startswith(ft.RECORDED)
    assert "loses to next_open" in out["breakout_gate"]
    assert "removed from the /4 executor path" in out["breakout_gate"]


# One New York session's bars from `open0` with per-bar log returns, and
# a closing-auction bar at 16:00 with the last close as its print.
def _bars(day: date, open0: float, returns: np.ndarray) -> list[IntradayBar]:
    start = datetime(day.year, day.month, day.day, 9, 30, tzinfo=sip.NEW_YORK)
    out = []
    price = open0
    for i, r in enumerate(returns):
        close = price * float(np.exp(r))
        out.append(
            IntradayBar(
                start + timedelta(minutes=15 * i),
                price,
                max(price, close),
                min(price, close),
                close,
                1000.0,
            )
        )
        price = close
    out.append(
        IntradayBar(
            start + timedelta(minutes=15 * SLOTS), price, price, price, price, 500.0
        )
    )
    return out


# A temporary SIP store with three names and a benchmark over seventy full
# exchange sessions, the membership file listing the three, and a desk
# hook returning a churning report on the store's own sessions. Returns
# (membership path, the hook, the sessions, the names, the roots the hook
# was called with).
def _sip_store(tmp_path):
    store = MarketStore(tmp_path)
    rng = np.random.default_rng(9)
    # Seventy full exchange sessions from the reviewed calendar, so every
    # partition is complete and the cubes hold every session.
    sessions = [
        d
        for d in sip.calendar_sessions(date(2023, 1, 9), date(2023, 6, 30))[0]
        if bars_expected(d) == SLOTS
    ][:70]
    assert len(sessions) == 70
    names = ("AAA", "BBB", "CCC")
    opens = np.zeros((len(sessions), 4))
    closes = np.zeros((len(sessions), 4))
    for j, ticker in enumerate((*names, "SPY")):
        price = 100.0
        daily = []
        for i, day in enumerate(sessions):
            open0 = price * float(np.exp(rng.normal(0, 0.003)))
            bars = _bars(day, open0, rng.normal(0.0, 0.003, size=SLOTS))
            assert sip.write_session(store, ticker, day, bars, PROVENANCE)
            price = bars[SLOTS - 1].close
            opens[i, j], closes[i, j] = open0, price
            daily.append(DailyBar(day, open0, price, open0, price, price, 26000))
        prior = date(2023, 1, 6)
        daily.insert(0, DailyBar(prior, 100.0, 100.0, 100.0, 100.0, 100.0, 26000))
        store.write(
            date(2026, 9, 26),
            TickerHistory(
                ticker=ticker,
                bars=tuple(daily),
                actions=(),
                complete_through=sessions[-1],
                source_time=datetime(2026, 9, 26, tzinfo=UTC),
            ),
        )
    membership = tmp_path / "membership.csv"
    membership.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        + "".join(f"{t},2016-01-04,2016-01-04,,,test,test\n" for t in names),
        encoding="utf-8",
    )
    dates = np.array(sessions, dtype="datetime64[D]")
    grades = _grades(rng, len(dates), 4)
    calls: list[str] = []

    # The desk hook: the churning report on the store's sessions, recorded.
    def fake_desk(store_):
        calls.append(str(store_.root))
        return _report(dates, opens, closes, grades)

    return membership, fake_desk, sessions, names, calls


# The command end to end on a temporary SIP store with three names and a
# benchmark: cubes from the store, the mask from the membership file, the
# report from the desk hook on the store's own sessions, the payload at
# <root>/desk/fill_timing.json with every row and the verdict, and the
# table and verdict in the text.
def test_cli_end_to_end(tmp_path):
    membership, fake_desk, sessions, names, calls = _sip_store(tmp_path)
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(membership),
            "--offsets",
            "2",
            "--workers",
            "1",
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    assert calls == [str(tmp_path)]
    text = out.getvalue()
    target = tmp_path / "desk" / "fill_timing.json"
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["policy"] == policy_v4.POLICY_VERSION
    assert payload["conventions"] == list(ft.CONVENTIONS)
    assert payload["offsets"] == 2
    assert payload["cost_bps"] == 10.0
    assert len(payload["rows"]) == 7 * 3
    assert {r["convention"] for r in payload["rows"]} == set(ft.CONVENTIONS)
    assert set(payload["windows"]) == {"2016-2023", "2024-2026", "all"}
    assert payload["verdict"].startswith(ft.RECORDED) or payload["verdict"].startswith(
        ft.ADOPTED
    )
    assert payload["cube_coverage"] == {"names_with_cube": 3, "names_in_panel": 4}
    assert payload["sessions_per_ticker"] == {t: len(sessions) for t in names}
    # The store's bar-0 opens are the panel's opens, so the control matches
    # the simulator on this store.
    assert payload["simulator_gap"]["max_abs_bp"] < 1e-6
    assert "fill-timing trial" in text
    assert "verdict:" in text
    assert "breakout_gate" in text
    assert "dip_or_close" in text
    # `--json` prints the payload.
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(membership),
            "--offsets",
            "1",
            "--workers",
            "1",
            "--tickers",
            "AAA,BBB",
            "--json",
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    printed = json.loads(out.getvalue())
    assert printed["cube_coverage"]["names_with_cube"] == 2


# A split: the daily store shows split-adjusted history (a tenth of the
# raw price before the split date) while the cube keeps the raw tape. The
# first real-store run scaled raw fills by `adj_close / close`, which does
# not undo a split, and marked a pre-split raw fill against a post-split
# close (a 1190x "gap" on the worst day). With the cube's own official
# close as the basis, `next_open` reproduces the simulator through the
# split to 1e-10.
def test_next_open_reproduces_the_simulator_through_a_split():
    from dataclasses import replace

    report, mask, cubes = _world(t=260, seed=3)
    panel = report.panel
    split_row, ratio = 150, 10.0
    scale = np.ones_like(panel.close)
    scale[:split_row, 0] = 1.0 / ratio  # name 0's history, as the daily store shows it
    adjusted = replace(
        panel,
        open=panel.open * scale,
        high=panel.high * scale,
        low=panel.low * scale,
        close=panel.close * scale,
        adj_close=panel.adj_close * scale,
    )
    split_report = replace(report, panel=adjusted)
    since = ft.since_offset(adjusted, 5)
    sim = simulate.run(
        split_report,
        since=since,
        allocator=policy_v4.allocator(mask),
        cost_bps=10.0,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
    )
    prices = ft.cube_prices(cubes, adjusted, "next_open")
    # The raw cube's bar-0 open is ten times the panel's before the split
    # and the scaled fill price is the panel's adjusted open.
    j = 0
    assert cubes[adjusted.tickers[j]].open[10, 0] == pytest.approx(adjusted.open[10, j] * ratio)
    assert prices.buy[10, j] == pytest.approx(simulate.adjusted_open(adjusted)[10, j])
    ours = ft.price_book(
        ft.target_path(split_report, mask, since), split_report, prices, "next_open", 10.0
    )
    np.testing.assert_allclose(ours.returns[5:], sim.returns, atol=1e-10, rtol=0, equal_nan=True)
