"""Sector-aware sells S2: the peer groups, the two rules and the book, on test data.

What has to hold (docs/research/sector-sells-plan-2026-10-01.md):

- The peer group at t is computed from closes on or before t only:
  tampering with every price after t leaves t's peers, correlations and
  sigma_g unchanged to the bit.
- Peers are the k = 5 highest residual-to-market correlations among the
  point-in-time members with a complete 60-session window; the market
  column and non-members are never peers; with fewer than 5 eligible there
  is no group; sigma_g is the 20-session std of the peers' mean return.
- R_g is the mean first-bar return of t+1 over the priced peers, undefined
  with fewer than 3 priced.
- G1/G3 (defer): a fired sell is filled at t+2 by the control rule, wait
  1, unpriced without t+2; G2 (close): a fired sell fills at the official
  close of t+1. Unfired sessions are the control to the bit.
- Scopes: G1/G2 the rotation and reset exits; G3 trims and exits graded
  C, never grade-B exits; event sells are in no scope.
- The null case (rules that never fire) reproduces the control bit for
  bit on every cell and gives g = 0 on every sell.
- The book's deferral is drift-adjusted as a one-session sell wait; the
  verdict is the structure-rules judge at N = 3, cumulative 485.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from backend.agents.trading.desk import grading
from backend.market import sector_sells as ss
from backend.market import stage4_decisions as sd
from backend.market import stage4_labels as lab
from backend.market import stage4_orders as so
from backend.market import structure_rules as sr
from backend.market.sip_cube import FULL_SESSION_SLOTS
from backend.tests.test_stage4_decisions import _orders, _weekdays
from backend.tests.test_stage4_labels import _dates, _series
from backend.tests.test_structure_rules import _agree, _cube, _path

SLOTS = FULL_SESSION_SLOTS
C = grading.ORDINAL[grading.C]


# A factor panel of closes: SPY plus two blocks of names, each block
# sharing its own factor on top of the market (block A `a` names, block B
# `b` names), with idiosyncratic noise; returns (closes (T, N), tickers,
# market column).
def _factor_closes(length=160, a=6, b=6, seed=3):
    rng = np.random.default_rng(seed)
    m = rng.normal(0.0003, 0.01, length)
    fa = rng.normal(0, 0.012, length)
    fb = rng.normal(0, 0.012, length)
    cols = [m]
    cols += [1.1 * m + fa + rng.normal(0, 0.004, length) for _ in range(a)]
    cols += [0.9 * m + fb + rng.normal(0, 0.004, length) for _ in range(b)]
    rets = np.stack(cols, axis=1)
    closes = 100.0 * np.exp(np.cumsum(rets, axis=0))
    tickers = (
        ("SPY",) + tuple(f"A{i}" for i in range(a)) + tuple(f"B{i}" for i in range(b))
    )
    return closes, tickers, 0


# The residual removes the market: equal to numpy's least-squares residual
# with an intercept, and orthogonal to the market.
def test_residuals_are_the_ols_residuals_on_the_market():
    rng = np.random.default_rng(0)
    m = rng.normal(0, 0.01, 60)
    r = np.stack([2.0 * m + rng.normal(0, 0.005, 60), -m + 0.001], axis=1)
    e = ss.residuals(r, m)
    x = np.column_stack([np.ones(60), m])
    for k in range(2):
        coef, *_ = np.linalg.lstsq(x, r[:, k], rcond=None)
        np.testing.assert_allclose(e[:, k], r[:, k] - x @ coef, atol=1e-12)
        assert abs(float(e[:, k] @ (m - m.mean()))) < 1e-12


# Peers come from the name's own block, never the market column, sigma_g
# is the 20-session std of the peers' equal-weight log return, and no
# group exists before the 60-session window is complete.
def test_peers_are_the_block_by_residual_correlation():
    closes, tickers, market = _factor_closes()
    g = ss.peer_groups(_dates(len(closes)), tickers, closes, market)
    t = 120
    assert not g.has[: ss.CORR_SESSIONS].any()
    assert not g.has[:, market].any()
    for j, name in enumerate(tickers):
        if j == market:
            continue
        assert g.has[t, j]
        peers = {tickers[p] for p in g.members[t, j]}
        assert len(peers) == ss.K_PEERS
        assert name not in peers
        assert "SPY" not in peers
        assert {p[0] for p in peers} == {name[0]}
        assert (np.diff(g.corr[t, j]) <= 0).all()
        rets = ss.log_returns(closes)
        mean = rets[t - 19 : t + 1][:, g.members[t, j]].mean(axis=1)
        assert g.sigma[t, j] == pytest.approx(mean.std(ddof=1), rel=1e-12)


# Tampering with every price after t leaves t's peer group, correlations
# and sigma_g unchanged to the bit (and every session before t too).
def test_peer_groups_at_t_ignore_every_price_after_t():
    closes, tickers, market = _factor_closes(seed=8)
    dates = _dates(len(closes))
    before = ss.peer_groups(dates, tickers, closes, market)
    t = 100
    tampered = closes.copy()
    rng = np.random.default_rng(1)
    tampered[t + 1 :] *= rng.uniform(0.5, 2.0, size=tampered[t + 1 :].shape)
    after = ss.peer_groups(dates, tickers, tampered, market)
    np.testing.assert_array_equal(before.members[: t + 1], after.members[: t + 1])
    np.testing.assert_array_equal(before.corr[: t + 1], after.corr[: t + 1])
    np.testing.assert_array_equal(before.sigma[: t + 1], after.sigma[: t + 1])
    np.testing.assert_array_equal(before.has[: t + 1], after.has[: t + 1])
    assert not np.array_equal(before.corr[t + 1 :], after.corr[t + 1 :], equal_nan=True)


# A name that is not a member at t is never a peer at t (though it keeps
# its own group); with fewer than 5 eligible peers there is no group; a
# missing return in the window takes the name out.
def test_membership_and_missing_data_shape_the_group():
    closes, tickers, market = _factor_closes(a=6, b=6)
    n_t, n_n = closes.shape
    mask = np.ones((n_t, n_n), dtype=bool)
    mask[:, market] = False
    out = tickers.index("A0")
    mask[110:, out] = False
    g = ss.peer_groups(_dates(n_t), tickers, closes, market, mask)
    t = 120
    for j in range(1, n_n):
        assert out not in set(g.members[t, j].tolist())
    assert g.has[t, out]
    assert out in set(g.members[100, tickers.index("A1")].tolist())
    # Only four members besides the name: no group anywhere.
    few = np.zeros((n_t, n_n), dtype=bool)
    few[:, 1:5] = True
    assert not ss.peer_groups(_dates(n_t), tickers, closes, market, few).has[1:5].any()
    # A gap in the window drops the name and makes it no one's peer.
    gappy = closes.copy()
    gappy[115, tickers.index("A2")] = np.nan
    h = ss.peer_groups(_dates(n_t), tickers, gappy, market)
    a2 = tickers.index("A2")
    assert not h.has[t, a2]
    assert all(a2 not in set(h.members[t, j].tolist()) for j in range(1, n_n))


# R_g is the mean first-bar return of the priced peers when at least 3 of
# the 5 are priced, else NaN; the triggers compare it with sigma_g and
# with ln(1.01); never fires nowhere.
def test_peer_morning_and_the_triggers():
    n_t, n_n = 3, 7
    members = np.full((n_t, n_n, 5), -1, dtype=np.int64)
    members[1, 0] = [1, 2, 3, 4, 5]
    members[2, 0] = [1, 2, 3, 4, 5]
    has = members[:, :, 0] >= 0
    groups = ss.PeerGroups(
        dates=_dates(n_t),
        tickers=tuple("ABCDEFG"),
        members=members,
        corr=np.where(members >= 0, 0.5, np.nan),
        sigma=np.where(has, 0.02, np.nan),
        has=has,
    )
    first = np.full((n_t, n_n), np.nan)
    first[1, 1:4] = [0.01, 0.03, 0.05]  # three priced: mean 0.03
    first[2, 1:3] = [0.10, 0.10]  # two priced: undefined
    morning, count = ss.peer_morning(groups, first)
    assert morning[1, 0] == pytest.approx(0.03)
    assert count[1, 0] == 3
    assert math.isnan(morning[2, 0])
    assert count[2, 0] == 2
    assert math.isnan(morning[0, 0])
    fire = ss.fire_masks(groups, morning)
    assert fire[ss.PEER_DEFER][1, 0]
    assert fire[ss.PEER_CLOSE][1, 0]
    groups2 = ss.PeerGroups(**{**groups.__dict__, "sigma": np.where(has, 0.04, np.nan)})
    fire2 = ss.fire_masks(groups2, morning)
    assert not fire2[ss.PEER_DEFER][1, 0]
    assert fire2[ss.PEER_CLOSE][1, 0]
    assert pytest.approx(math.log(1.01)) == ss.CLOSE_THRESHOLD
    never = ss.fire_masks(groups, morning, never=True)
    assert not never[ss.PEER_DEFER].any()
    assert not never[ss.PEER_CLOSE].any()


# The first-bar return of t+1 is read off the cube on the adjusted basis:
# a cube twice the panel's price level gives the same return.
def test_first_bar_returns_use_the_session_scale():
    dates = _dates(5)
    prices = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
    cube = _cube(
        dates,
        prices * 2.0,
        paths={2: {"close": _path(200.0, b0=206.0), "auction": 200.0}},
    )
    adj = np.stack([prices, prices], axis=1)
    out = ss.first_bar_returns(dates, ("SPY", "T"), adj, {"T": cube})
    assert out[1, 1] == pytest.approx(math.log(103.0 / 100.0))
    assert out[0, 1] == pytest.approx(0.0)
    assert math.isnan(out[4, 1])
    assert np.isnan(out[:, 0]).all()


T = 70
t0 = 50


# A flat history at 100 with sessions t0+1 and t0+2 following `paths`.
def _scene(paths, drop=()):
    dates = _dates(T)
    prices = np.full(T, 100.0)
    cube = _cube(dates, prices, paths=paths, drop=drop)
    series = _series(dates, _agree(prices, cube, dates))
    return series, cube


# t+1 pops 1% at bar 2 and closes at 99; t+2 pops at bar 4 (102.5) and
# closes at 101.
DAY1 = {"close": _path(100.0, b2=101.5, b25=99.0), "open": np.full(SLOTS, 100.0)}
DAY2 = {"close": _path(101.0, b4=102.5), "open": np.full(SLOTS, 101.0)}


# G1's deferral: a fired sell fills at t+2 by the control rule (bar 4's
# 102.5), wait 1, its slot and reached from t+2; the next-bar run moves the
# t+2 fill to bar 5's open; without t+2 it is unpriced; unfired sessions
# are the control to the bit.
def test_g1_defers_a_fired_sell_to_the_control_at_t_plus_two():
    series, cube = _scene({t0 + 1: DAY1, t0 + 2: DAY2})
    fire = np.zeros(T, dtype=bool)
    fire[t0] = True
    none = np.zeros(T, dtype=bool)
    f = ss.name_fills(series, cube, fire, none)
    ctrl, wait = f[ss.CONTROL], f[ss.PEER_DEFER]
    assert ctrl.price[t0] == pytest.approx(101.5)
    assert ctrl.slot[t0] == 2
    assert wait.price[t0] == pytest.approx(102.5)
    assert wait.slot[t0] == 4
    assert wait.reached[t0]
    assert wait.wait[t0] == 1
    assert wait.active[t0]
    assert wait.tagged[t0]
    others = np.arange(T) != t0
    np.testing.assert_array_equal(wait.price[others], ctrl.price[others])
    np.testing.assert_array_equal(wait.slot[others], ctrl.slot[others])
    np.testing.assert_array_equal(wait.reached[others], ctrl.reached[others])
    assert (wait.wait[others] == 0).all()
    assert lab.gain(ctrl.price[t0 : t0 + 1], wait.price[t0 : t0 + 1], "sell")[0] > 0
    nb = ss.name_fills(series, cube, fire, none, next_bar=True)
    assert nb[ss.PEER_DEFER].price[t0] == pytest.approx(cube.open[t0 + 2, 5])
    # No t+2 session in the cube: unpriced, not acted.
    s2, c2 = _scene({t0 + 1: DAY1}, drop=(t0 + 2,))
    g = ss.name_fills(s2, c2, fire, none)
    assert math.isnan(g[ss.PEER_DEFER].price[t0])
    assert not g[ss.PEER_DEFER].active[t0]


# G2's close: a fired sell fills at the official close of t+1 (99), not
# the pop bar; the next-bar run leaves it at the close; unfired sessions
# are the control to the bit.
def test_g2_sells_at_the_close_when_the_group_has_rallied():
    series, cube = _scene({t0 + 1: DAY1, t0 + 2: DAY2})
    fire = np.zeros(T, dtype=bool)
    fire[t0] = True
    none = np.zeros(T, dtype=bool)
    for mode in (False, True):
        f = ss.name_fills(series, cube, none, fire, next_bar=mode)
        ctrl, moc = f[ss.CONTROL], f[ss.PEER_CLOSE]
        assert moc.price[t0] == pytest.approx(99.0)
        assert moc.slot[t0] == -1
        assert not moc.reached[t0]
        assert moc.wait[t0] == 0
        assert moc.tagged[t0]
        others = np.arange(T) != t0
        np.testing.assert_array_equal(moc.price[others], ctrl.price[others])
    assert lab.gain(np.array([101.5]), np.array([99.0]), "sell")[0] < 0


# A hand-made Market over two names with given control and rule prices.
def _market(control=100.0, defer=None, close=None, fire=None, wait=None):
    dates = _weekdays(date(2023, 1, 2), 12)
    shape = (len(dates), 2)
    grid = {}
    for mode in (False, True):
        price = {r: np.full(shape, control) for r in ss.RULES}
        for r, cells in ((ss.PEER_DEFER, defer), (ss.PEER_CLOSE, close)):
            for (t, j), v in (cells or {}).items():
                price[r][t, j] = v
        waits = {r: np.zeros(shape, dtype=np.int64) for r in ss.RULES}
        for (t, j), v in (wait or {}).items():
            waits[ss.PEER_DEFER][t, j] = v
        tagged = {r: np.zeros(shape, dtype=bool) for r in ss.RULES}
        for r, cells in (fire or {}).items():
            for t, j in cells:
                tagged[r][t, j] = True
        grid[mode] = sr.Grid(
            next_bar=mode,
            price=price,
            reached={r: np.zeros(shape, dtype=bool) for r in ss.RULES},
            active={r: np.zeros(shape, dtype=bool) for r in ss.RULES},
            slot={r: np.full(shape, -1, dtype=np.int64) for r in ss.RULES},
            wait=waits,
            tagged=tagged,
        )
    zeros = np.zeros(shape)
    groups = ss.PeerGroups(
        dates=dates,
        tickers=("SPY", "X"),
        members=np.full(shape + (5,), -1, dtype=np.int64),
        corr=np.full(shape + (5,), np.nan),
        sigma=np.full(shape, np.nan),
        has=np.zeros(shape, dtype=bool),
    )
    return ss.Market(
        dates=dates,
        tickers=("SPY", "X"),
        fills=grid[False],
        next_bar=grid[True],
        oracle=np.full(shape, np.nan),
        oracle_five=np.full(shape, np.nan),
        grades=np.full(shape, so.A_PLUS),
        closes=np.full(shape, 100.0),
        peers=groups,
        morning=np.full(shape, np.nan),
        priced_peers=zeros.astype(np.int64),
        fire={
            ss.PEER_DEFER: np.zeros(shape, bool),
            ss.PEER_CLOSE: np.zeros(shape, bool),
        },
    )


# The scopes: G1 and G2 re-time the rotation and reset exits only; G3 the
# trims and the exits graded C, never a grade-B exit; event sells and buys
# are in no scope; g is ln(rule / control) in bp where in scope.
def test_each_candidate_prices_only_the_sells_in_its_scope():
    cells = {(t, 1): 101.0 for t in range(1, 7)}
    fire = {r: list(cells) for r in (ss.PEER_DEFER, ss.PEER_CLOSE)}
    market = _market(defer=cells, close=cells, fire=fire, wait={c: 1 for c in cells})
    orders = _orders(
        [
            (1, 1, "sell", 0.05, "midcycle", so.ROTATION_EXIT, so.B),
            (2, 1, "sell", 0.05, "rebalance", so.RESET_EXIT, C),
            (3, 1, "sell", 0.05, "midcycle", so.TRIM, so.A),
            (4, 1, "sell", 0.05, "event", so.EVENT_SELL, C),
            (5, 1, "sell", 0.05, "midcycle", so.ROTATION_EXIT, C),
            (6, 1, "buy", 0.05, "midcycle", so.ADD, so.A),
        ],
        ("SPY", "X"),
        start=0,
        stop=10,
    )
    up = 1e4 * math.log(101.0 / 100.0)
    expect = {
        "G1": [up, up, 0, 0, up],
        "G2": [up, up, 0, 0, up],
        "G3": [0, up, up, 0, up],
    }
    for c, gains in expect.items():
        book = ss.price_book(orders, market, c)
        assert book.side == "sell"
        assert len(book.rows) == 5
        np.testing.assert_allclose(book.gain, gains, atol=1e-9)
        assert (book.acted == (np.asarray(gains) != 0)).all()
        assert (book.tagged == book.acted).all()
        rule, _ = ss.rule_of(c)
        want_wait = (np.asarray(gains) != 0).astype(int) if rule == ss.PEER_DEFER else 0
        np.testing.assert_array_equal(book.wait, np.zeros(5, int) + want_wait)
    with pytest.raises(ValueError, match="unknown candidate"):
        ss.rule_of("G4")


# The deferral's drift adjustment is a sell's: g - mu x 1 per waited sell,
# so the drift-adjusted session mean sits mu x weight under the plain one.
def test_the_deferral_is_drift_adjusted_as_a_one_session_sell_wait():
    cells = {(2, 1): 102.0}
    market = _market(defer=cells, fire={ss.PEER_DEFER: [(2, 1)]}, wait={(2, 1): 1})
    orders = _orders(
        [(2, 1, "sell", 0.1, "midcycle", so.ROTATION_EXIT, so.B)],
        ("SPY", "X"),
        start=0,
        stop=10,
    )
    book = ss.price_book(orders, market, "G1")
    stats = ss.summarize(book, market.dates, None, None, 8.0)
    g = 1e4 * math.log(1.02)
    assert stats["mean_bp"] == pytest.approx(0.1 * g / 10)
    assert stats["drift_mean_bp"] == pytest.approx(0.1 * (g - 8.0) / 10)
    assert stats["waited"] == 1
    assert stats["in_scope"] == 1
    assert stats["fired"] == 1
    assert stats["fired_share"] == 1.0


# The null case on a synthetic panel with real peer groups and cubes:
# never-firing rules reproduce the control on every cell, both modes, and
# every candidate's gain on the executor's sells is exactly zero; with the
# rules live, every unfired cell is still the control's to the bit.
def test_the_null_reproduces_the_control_bit_for_bit():
    from backend.tests.test_stage4_decisions import _session_cube
    from backend.tests.test_stage4_orders import _report

    report = _report()
    panel = report.panel
    rng = np.random.default_rng(5)
    cubes = {
        t: _session_cube(t, panel.dates, panel.close[:, j], rng)
        for j, t in enumerate(panel.tickers)
        if t != panel.benchmark
    }
    fills, nb, block, coverage = ss.fill_grids(panel, cubes, never=True)
    assert coverage["never"]
    assert coverage["name_sessions_with_peers"] > 0
    assert ss.null_mismatches(fills, nb) == []
    market = ss.build_market(panel, report.graded.grades, fills, nb, block)
    mask = np.ones(report.graded.grades.shape, dtype=bool)
    mask[:, panel.index("SPY")] = False
    runs = so.run_offsets(report, mask, 1)
    assert (runs[0].side == "sell").any()
    for c in ss.CANDIDATES:
        for mode in (False, True):
            book = ss.price_book(runs[0], market, c, next_bar=mode)
            assert (book.gain == 0.0).all()
            assert not book.acted.any()
    live, live_nb, live_block, _ = ss.fill_grids(panel, cubes)
    for grid in (live, live_nb):
        for rule in (ss.PEER_DEFER, ss.PEER_CLOSE):
            quiet = ~live_block["fire"][rule]
            np.testing.assert_array_equal(
                grid.price[rule][quiet], grid.price[ss.CONTROL][quiet]
            )
            np.testing.assert_array_equal(
                grid.slot[rule][quiet], grid.slot[ss.CONTROL][quiet]
            )
    assert ss.null_mismatches(live, live_nb) != [] or not any(
        live_block["fire"][r].any() for r in live_block["fire"]
    )


# The deflated Sharpe is at N = 3 with the cumulative 485 beside it, and
# the module's registered constants are the plan's.
def test_the_registered_constants():
    assert ss.TRIALS == {"registered": 3, "cumulative": 485}
    assert (ss.K_PEERS, ss.CORR_SESSIONS, ss.PEER_SIGMA_SESSIONS) == (5, 60, 20)
    assert ss.MIN_PRICED_PEERS == 3
    assert set(ss.CANDIDATES) == {"G1", "G2", "G3"}
    excess = {
        "G1": {"sharpe": 0.1, "length": 100, "skew": 0.0, "kurtosis": 3.0},
        "G2": {"sharpe": 0.0, "length": 100, "skew": 0.0, "kurtosis": 3.0},
        "G3": {"sharpe": -0.1, "length": 100, "skew": 0.0, "kurtosis": 3.0},
    }
    d = ss.deflated(excess, "G1")
    assert d["trials"] == 3
    assert d["candidates"] == 3
    assert math.isfinite(d["dsr"])
    assert math.isfinite(d["dsr_cumulative"])


# The command end to end on stub loaders: the null test passes and reads
# no result; a two-offset smoke run writes a payload whose per-sell rows
# recompute the model-window figures, carries the peer summary, the named
# groups and the case, and prints a verdict line per candidate; --peers
# prints from the daily panel alone; bad arguments are refused.
def test_command_end_to_end(tmp_path):
    import io as textio
    import json

    from backend.cli import market_sector_sells as cli
    from backend.tests.test_stage4_decisions import _session_cube
    from backend.tests.test_stage4_orders import _history, _report

    report = _report()
    panel = report.panel
    rng = np.random.default_rng(11)
    cubes = {
        t: _session_cube(t, panel.dates, panel.close[:, j], rng)
        for j, t in enumerate(panel.tickers)
        if t != panel.benchmark
    }
    history = _history(tmp_path)

    # The stub loader: the synthetic report and its cubes.
    def loader(store, workers, log):
        return report, cubes, {}

    base = ["--root", str(tmp_path), "--membership", str(history)]
    text = textio.StringIO()
    args = cli.build_parser().parse_args(base + ["--null-test"])
    assert cli.run(args, out=text, loader=loader) == 0
    assert cli.NULL_PASS in text.getvalue()
    assert "bp/session" not in text.getvalue()

    out_path = tmp_path / "out" / "ss.json"
    args = cli.build_parser().parse_args(
        base + ["--offsets", "20", "--max-offsets", "2", "--out", str(out_path)]
    )
    text = textio.StringIO()
    assert cli.run(args, out=text, loader=loader) == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["plan"] == ss.PLAN
    assert payload["study"] == ss.STUDY
    assert payload["offsets"]["smoke"]
    assert payload["offsets"]["priced"] == 2
    assert set(payload["results"]) == set(ss.CANDIDATES) == set(payload["deflated"])
    assert payload["deflated"]["G1"]["trials"] == 3
    assert payload["constants"]["TRIALS"]["cumulative"] == 485
    summary = payload["peers"]["summary"]
    assert set(summary) == {"model", "2024-2026"}
    assert payload["peers"]["named"]["date"] == "2026-09-30"
    assert payload["case"] is None  # the synthetic panel has no 2026-09-30
    rows = payload["rows"]
    sells = len(rows["date"])
    assert (
        sells
        == payload["orders"]["median_by_window"]["model"]["sells"]
        + payload["orders"]["median_by_window"]["2024-2026"]["sells"]
    )
    window = payload["windows"]["2024-2026"]
    sessions = [d for d in rows["sessions"] if d >= window[0]]
    for c in ss.CANDIDATES:
        cand = rows["candidates"][c]
        g = np.asarray(cand["g_bp"], dtype=float)
        w = np.asarray(rows["weight"], dtype=float)
        per = dict.fromkeys(sessions, 0.0)
        for d, wt, v in zip(rows["date"], w, g, strict=True):
            if d >= window[0]:
                per[d] += wt * v
        series = np.asarray([per[d] for d in sessions])
        ref = payload["results"][c]["default"]["2024-2026"]
        assert series.mean() == pytest.approx(ref["mean_bp"], abs=1e-9)
        for k in range(sells):
            control, fill = rows["control"][k], cand["fill"][k]
            if cand["unpriced"][k]:
                assert g[k] == 0.0
            elif not cand["in_scope"][k]:
                assert fill == control
                assert g[k] == 0.0
            else:
                assert g[k] == pytest.approx(1e4 * math.log(fill / control), abs=1e-9)
    out = text.getvalue()
    for c in ss.CANDIDATES:
        assert f"{c} (" in out
    assert "SMOKE RUN" in out

    # --peers from the daily panel only.
    def panel_loader(store):
        return panel

    day = str(panel.dates[200])
    args = cli.build_parser().parse_args(base + ["--peers", "AAA,ZZZ", "--on", day])
    text = textio.StringIO()
    assert cli.run(args, out=text, loader=None, panel_loader=panel_loader) == 0
    lines = text.getvalue()
    assert "AAA: " in lines
    assert "mean corr" in lines
    assert "ZZZ: not in the panel" in lines

    bad = cli.build_parser().parse_args(base + ["--offsets", "0"])
    assert cli.run(bad, out=textio.StringIO(), loader=loader) == 2
    missing = cli.build_parser().parse_args(
        ["--root", str(tmp_path), "--membership", str(tmp_path / "none.csv")]
    )
    assert cli.run(missing, out=textio.StringIO(), loader=loader) == 1


# The case record reads one (ticker, day) off the grids whether or not the
# book traded it: the grade, the peers, both rules' fills and gains.
def test_the_case_reads_one_name_and_day_off_the_grids():
    market = _market(
        defer={(3, 1): 102.0},
        close={(3, 1): 99.0},
        fire={ss.PEER_DEFER: [(3, 1)]},
        wait={(3, 1): 1},
    )
    market.fire[ss.PEER_DEFER][3, 1] = True
    day = market.dates[3].astype(object)
    rec = ss.case(market, "X", day)
    assert rec["decision"] == str(day)
    assert rec["execution"] == str(market.dates[4])
    assert rec["rules"][ss.PEER_DEFER]["fired"]
    assert rec["rules"][ss.PEER_DEFER]["g_bp"] == pytest.approx(1e4 * math.log(1.02))
    assert not rec["rules"][ss.PEER_CLOSE]["fired"]
    assert rec["rules"][ss.PEER_CLOSE]["g_bp"] == pytest.approx(1e4 * math.log(0.99))
    assert rec["scopes"] == {"G1": False, "G2": False, "G3": True}  # graded A+
    assert ss.case(market, "NOPE", day) is None
    assert ss.case(market, "X", date(2030, 1, 1)) is None


# The changed-sells list keeps the sells from 2026 that a candidate
# re-timed, with each re-timing candidate's fill and g.
def test_changed_sells_lists_the_2026_re_timed_sells():
    rows = {
        "date": ["2025-12-31", "2026-01-05", "2026-02-02"],
        "ticker": ["A", "B", "C"],
        "detail": [so.ROTATION_EXIT] * 3,
        "grade": [so.B] * 3,
        "weight": [0.05] * 3,
        "control": [100.0] * 3,
        "peers": [[], ["X"], []],
        "morning": [0.0, 0.03, 0.0],
        "sigma_g": [0.02] * 3,
        "candidates": {
            "G1": {
                "fill": [101.0, 101.0, 100.0],
                "g_bp": [99.5, 99.5, 0.0],
                "wait": [1, 1, 0],
            },
            "G2": {"fill": [100.0] * 3, "g_bp": [0.0] * 3, "wait": [0] * 3},
        },
    }
    out = ss.changed_sells(rows)
    assert [r["ticker"] for r in out] == ["B"]
    assert set(out[0]["candidates"]) == {"G1"}
    assert sd.MODEL == "model"
