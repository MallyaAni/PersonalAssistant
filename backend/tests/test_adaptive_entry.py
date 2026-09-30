"""Adaptive entry: the three registered buy fills on hand-made cubes and books.

What has to hold (docs/research/adaptive-entry-plan-2026-09-30.md):

- E1 fills at the first bar close at or below open × (1 − 0.5σ_t), E2 at
  open × (1 − σ_t), each in session t+1 only, else at t+1's official
  close; a dip that reaches the half-sigma level but not the one-sigma
  level fills E1 at the bar and E2 at the close.
- E3 is the control's 1% rule, except that when t+1 opens more than 2σ_t
  below t's close it waits for the official close; otherwise it is the
  control to the bit.
- Every price is on the adjusted basis via `cube_scale`: a split between t
  and t+1 is no gap-down, and a dip in raw bars fills at its adjusted
  price.
- A session whose t+1 is not a complete cube session, or whose σ_t is not
  finite, is unpriced (the control needs no σ); with `next_bar` a bar fill
  moves to the next bar's open.
- The book: g = 1e4 ln(control / candidate) per buy, 0 where either has no
  price (counted as unpriced), the wait is 0, the session series is the
  weight-sum per decision session, and the statistics are stage 4's.
- The verdict: REPLACES only when all six criteria hold at the median
  offset; each moved past its edge is RECORD; "real but immaterial" needs a
  failed floor and 25 bp at t 3 per re-timed order.
- `stage4_orders.run_offsets` passes `allocator` through to the simulator.
- The command runs end to end on a stub loader, writes the payload with the
  per-order rows an independent check can recompute the verdict from,
  and prints one verdict line per candidate.
"""

from __future__ import annotations

import hashlib
import io as textio
import json
import math

import numpy as np
import pytest

from backend.agents.trading.desk import point_in_time, policy_v5
from backend.market import adaptive_entry as ae
from backend.market import candidate_stats, fill_timing
from backend.market import stage4_decisions as sd
from backend.market import stage4_labels as lab
from backend.market import stage4_orders as so
from backend.market.fill_timing import clustered_t
from backend.market.sip_cube import FULL_SESSION_SLOTS
from backend.tests.test_stage4_decisions import _orders, _session_cube, _weekdays
from backend.tests.test_stage4_labels import _agree, _cube, _dates, _series, _zigzag
from backend.tests.test_stage4_orders import _history, _report

SLOTS = FULL_SESSION_SLOTS
T = 60
t0 = 40


# A zigzag series with a cube whose session t0+1 follows `path` (26 bar
# closes; the first is the open, the last the official close); returns
# (series, cube, sigma at t0).
def _scene(path, split=None):
    dates = _dates(T)
    closes = _zigzag(T)
    raw = closes if split is None else closes * split
    cube = _cube(dates, raw, paths={t0 + 1: path})
    panel = closes if split is not None else _agree(closes, cube, dates)
    series = _series(dates, panel)
    return series, cube, series.sigma[t0]


# The sigma of the zigzag at t0, from the panel alone.
def _sigma():
    return _series(_dates(T), _zigzag(T)).sigma[t0]


# E1 reaches at 0.5σ where E2 and the control do not: a dip of 0.7σ under
# the open (about 0.7%, under the fixed 1%) fills E1 at that bar and E2 and
# the control at the official close; g(E1) > 0, g(E2) = 0; next_bar moves
# the E1 fill to the next bar's open.
def test_half_sigma_dip_reached_but_not_one_sigma():
    sigma = _sigma()
    closes = _zigzag(T)
    base = closes[t0 + 1]
    path = np.full(SLOTS, base)
    dip = base * (1.0 - 0.7 * sigma)
    path[5] = dip
    path[6] = base * (1.0 - 0.6 * sigma)
    series, cube, s = _scene(path)
    assert s == pytest.approx(sigma) and 0.7 * sigma < fill_timing.DIP
    fills = ae.name_fills(series, cube)
    e1, e2, ctrl = fills[ae.SIGMA_HALF], fills[ae.SIGMA_ONE], fills[ae.CONTROL]
    assert (
        e1.price[t0] == pytest.approx(dip)
        and e1.reached[t0]
        and e1.slot[t0] == 5
        and e1.active[t0]
    )
    assert (
        e2.price[t0] == pytest.approx(base) and not e2.reached[t0] and e2.slot[t0] == -1
    )
    assert ctrl.price[t0] == pytest.approx(base) and not ctrl.reached[t0]
    assert lab.gain(ctrl.price[t0 : t0 + 1], e1.price[t0 : t0 + 1], "buy")[0] > 0
    assert lab.gain(ctrl.price[t0 : t0 + 1], e2.price[t0 : t0 + 1], "buy")[
        0
    ] == pytest.approx(0.0)
    nb = ae.name_fills(series, cube, next_bar=True)
    assert (
        nb[ae.SIGMA_HALF].price[t0] == pytest.approx(path[6])
        and nb[ae.SIGMA_HALF].slot[t0] == 5
    )
    # A deeper dip past 1σ fills E2 at its bar too.
    deep = np.full(SLOTS, base)
    deep[9] = base * (1.0 - 1.2 * sigma)
    series2, cube2, _ = _scene(deep)
    fills2 = ae.name_fills(series2, cube2)
    assert (
        fills2[ae.SIGMA_ONE].price[t0] == pytest.approx(deep[9])
        and fills2[ae.SIGMA_ONE].slot[t0] == 9
    )
    assert fills2[ae.CONTROL].reached[t0] == (1.2 * sigma >= fill_timing.DIP)


# The gap guard: t+1 opening 2.5σ under t's close holds the buy to the
# official close although the 1% dip is reached; opening 1.5σ under it
# leaves E3 as the control, to the bit, and inactive.
def test_gap_guard_fires_only_past_two_sigma():
    sigma = _sigma()
    closes = _zigzag(T)
    for gap, fires in ((2.5, True), (1.5, False)):
        open_ = closes[t0] * math.exp(-gap * sigma)
        path = np.full(SLOTS, open_)
        path[3] = open_ * 0.985  # the 1% dip
        path[-1] = open_ * 0.97  # the official close, lower still
        series, cube, _ = _scene(path)
        fills = ae.name_fills(series, cube)
        e3, ctrl = fills[ae.GAP_GUARD], fills[ae.CONTROL]
        assert ctrl.reached[t0] and ctrl.price[t0] == pytest.approx(path[3])
        assert e3.active[t0] == fires
        if fires:
            assert (
                e3.price[t0] == pytest.approx(path[-1])
                and not e3.reached[t0]
                and e3.slot[t0] == -1
            )
            assert (
                lab.gain(ctrl.price[t0 : t0 + 1], e3.price[t0 : t0 + 1], "buy")[0] > 0
            )
        else:
            assert (
                e3.price[t0] == ctrl.price[t0] and e3.reached[t0] and e3.slot[t0] == 3
            )


# The store's convention: the panel is split-adjusted and the cube raw. A
# 2-for-1 split between t and t+1 halves the raw bars; on the adjusted
# basis (`cube_scale`) it is no gap-down, so E3 stays the control, and a
# real 0.7σ dip in the raw bars fills E1 at its adjusted price.
def test_split_between_t_and_t_plus_one_is_no_gap():
    sigma = _sigma()
    closes = _zigzag(T)
    split = np.where(np.arange(T) <= t0, 2.0, 1.0)
    base = closes[t0 + 1]  # raw = adjusted after the split
    path = np.full(SLOTS, base)
    path[4] = base * (1.0 - 0.7 * sigma)
    series, cube, _ = _scene(path, split=split)
    np.testing.assert_allclose(lab.cube_scale(series, cube), 1.0 / split)
    fills = ae.name_fills(series, cube)
    assert not fills[ae.GAP_GUARD].active[t0]
    assert fills[ae.GAP_GUARD].price[t0] == pytest.approx(fills[ae.CONTROL].price[t0])
    assert (
        fills[ae.SIGMA_HALF].price[t0] == pytest.approx(path[4])
        and fills[ae.SIGMA_HALF].reached[t0]
    )
    # The window before the split: raw bars are twice the adjusted price
    # and a 0.7σ dip there fills at its adjusted (halved) price.
    t1 = 30
    dip = np.full(SLOTS, closes[t1 + 1] * 2.0)
    dip[7] = closes[t1 + 1] * 2.0 * (1.0 - 0.7 * sigma)
    cube2 = _cube(_dates(T), closes * split, paths={t1 + 1: dip})
    series2 = _series(_dates(T), closes)
    fills2 = ae.name_fills(series2, cube2)
    assert fills2[ae.SIGMA_HALF].price[t1] == pytest.approx(dip[7] / 2.0)
    assert not fills2[ae.GAP_GUARD].active[t1]


# Unpriced: the last session (no t+1), a dropped cube session, and a
# session whose σ is not yet defined leave the rules NaN; the control needs
# only t+1. An empty cube prices nothing.
def test_unpriced_sessions():
    dates = _dates(T)
    closes = _zigzag(T)
    cube = _cube(dates, closes, drop=(t0 + 1,))
    series = _series(dates, _agree(closes, cube, dates))
    fills = ae.name_fills(series, cube)
    for name in ae.CONVENTIONS:
        assert math.isnan(fills[name].price[T - 1]) and math.isnan(
            fills[name].price[t0]
        )
        assert not fills[name].active[t0] and fills[name].slot[t0] == -1
    assert math.isnan(series.sigma[10]) and np.isfinite(fills[ae.CONTROL].price[10])
    for name in ae.CANDIDATES.values():
        assert math.isnan(fills[name].price[10])
        assert np.isfinite(fills[name].price[t0 + 5])
    empty = _cube(dates, closes, drop=tuple(range(T)))
    assert all(np.isnan(f.price).all() for f in ae.name_fills(series, empty).values())


# A grid where every convention fills at `control` with nothing reached.
def _grid(rows, cols, next_bar=False, control=100.0) -> ae.Grid:
    return ae.Grid(
        next_bar=next_bar,
        price={c: np.full((rows, cols), control) for c in ae.CONVENTIONS},
        reached={c: np.zeros((rows, cols), dtype=bool) for c in ae.CONVENTIONS},
        active={c: np.zeros((rows, cols), dtype=bool) for c in ae.CONVENTIONS},
        slot={c: np.full((rows, cols), -1, dtype=np.int64) for c in ae.CONVENTIONS},
    )


# A market over weekdays from 2023-12-01 (the windows straddle 2024) with
# the given grids, grades A+, flat closes and no oracle unless given.
def _market(
    dates, tickers, fills, next_bar=None, oracle=None, closes=None
) -> ae.Market:
    rows, cols = len(dates), len(tickers)
    nan = np.full((rows, cols), np.nan)
    return ae.Market(
        dates=np.asarray(dates, dtype="datetime64[D]"),
        tickers=tuple(tickers),
        fills=fills,
        next_bar=next_bar if next_bar is not None else _grid(rows, cols, next_bar=True),
        oracle=nan if oracle is None else np.asarray(oracle, dtype=float),
        oracle_five=nan.copy(),
        grades=np.full((rows, cols), so.A_PLUS),
        closes=np.full((rows, cols), 100.0)
        if closes is None
        else np.asarray(closes, dtype=float),
    )


# The book against the control: g per buy, 0 where either price is missing
# (counted), the wait 0, acted and reached from the grid; sells are not
# priced; the session series and the window statistics follow stage 4;
# the fill grids from a real cube feed the grid the same fills.
def test_book_accounting_against_the_control():
    from datetime import date

    dates = _weekdays(date(2023, 12, 1), 40)
    tickers = ("AAA", "BBB")
    grid = _grid(40, 2)
    grid.price[ae.SIGMA_HALF][3, 0] = 99.0  # pays less: +100.5 bp
    grid.reached[ae.SIGMA_HALF][3, 0] = True
    grid.active[ae.SIGMA_HALF][3, 0] = True
    grid.slot[ae.SIGMA_HALF][3, 0] = 4
    grid.price[ae.SIGMA_HALF][5, 1] = 101.0  # pays more
    grid.active[ae.SIGMA_HALF][5, 1] = True
    grid.price[ae.SIGMA_HALF][7, 0] = np.nan  # unpriced: the control
    grid.price[ae.CONTROL][9, 1] = np.nan  # the control unpriced
    grid.price[ae.SIGMA_HALF][9, 1] = 98.0
    grid.active[ae.GAP_GUARD][3, 0] = True
    grid.price[ae.GAP_GUARD][3, 0] = 100.0  # the guard held, no difference
    oracle = np.full((40, 2), 98.0)
    market = _market(dates, tickers, grid, oracle=oracle)
    orders = _orders(
        [
            (3, 0, "buy", 0.10),
            (5, 1, "buy", 0.20),
            (7, 0, "buy", 0.05),
            (9, 1, "buy", 0.10),
            (3, 1, "sell", 0.30),
        ],
        tickers,
        start=0,
        stop=40,
    )
    book = ae.price_book(orders, market, "E1")
    assert len(book.rows) == 4 and book.side == "buy" and (book.wait == 0).all()
    expect = 1e4 * np.log(np.array([100 / 99, 100 / 101, 1.0, 1.0]))
    np.testing.assert_allclose(book.gain, expect)
    assert book.unpriced.tolist() == [False, False, True, True]
    assert book.acted.tolist() == [True, True, False, False]
    assert book.reached.tolist() == [True, False, False, False]
    assert book.slot.tolist() == [4, -1, -1, -1]
    assert np.isfinite(book.oracle[0]) and book.oracle[0] == pytest.approx(
        1e4 * math.log(100 / 98)
    )
    series = sd.session_series(book, book.gain)
    assert len(series) == 40 and series[3] == pytest.approx(0.10 * expect[0])
    assert series[5] == pytest.approx(0.20 * expect[1]) and series[7] == 0.0
    stats = ae.summarize(book, market.dates, date(2023, 12, 1), date(2024, 1, 1), 0.0)
    assert stats["orders"] == 4 and stats["unpriced"] == 2 and stats["retimed"] == 2
    assert (
        stats["priced"] == 2 and stats["reached"] == 1 and stats["reached_share"] == 0.5
    )
    assert (
        stats["acted_share"] == 1.0
        and stats["bars"][4] == 1
        and sum(stats["bars"]) == 1
    )
    assert stats["mean_bp"] == pytest.approx(series[:21].mean())
    assert stats["hac_t"] == pytest.approx(candidate_stats.hac_t(series[:21], 20))
    assert stats["drift_mean_bp"] == pytest.approx(stats["mean_bp"])  # wait 0
    assert stats["retimed_bp"] == pytest.approx(expect[:2].mean())
    assert stats["retimed_t"] == pytest.approx(
        clustered_t(expect[:2], np.array([3, 5]))
    )
    assert stats["waited"] == 0 and stats["mean_wait_all"] == 0.0
    e3 = ae.price_book(orders, market, "E3")
    assert e3.acted.tolist() == [True, False, False, False] and (e3.gain == 0).all()
    with pytest.raises(ValueError, match="unknown candidate"):
        ae.price_book(orders, market, "E9")
    # The grids from a real cube carry name_fills' prices, cell for cell.
    rng = np.random.default_rng(3)
    closes = 100.0 * np.exp(rng.normal(0, 0.02, size=(40, 2)).cumsum(axis=0))
    cubes = {
        t: _session_cube(t, dates, closes[:, j], rng) for j, t in enumerate(tickers)
    }
    panel = type("P", (), {})()
    panel.dates, panel.tickers = dates, tickers
    panel.close = panel.adj_close = panel.high = panel.low = closes
    fills, nb, oracle1, oracle5, coverage = ae.fill_grids(panel, cubes)
    assert coverage["names_with_cube"] == 2 and nb.next_bar and not fills.next_bar
    series = lab.name_series(
        dates, closes[:, 1], closes[:, 1], closes[:, 1], closes[:, 1]
    )
    own = ae.name_fills(series, cubes["BBB"])
    for name in ae.CONVENTIONS:
        np.testing.assert_allclose(
            fills.price[name][:, 1], own[name].price, equal_nan=True
        )
    assert np.isfinite(oracle1[25, 1]) and oracle5[25, 1] <= oracle1[25, 1]
    with pytest.raises(ValueError, match="bar-close"):
        ae.build_market(panel, np.zeros((40, 2)), nb, fills, oracle1, oracle5)


# A payload skeleton whose every candidate clears every criterion exactly
# at its edge, for the verdict tests to move one number at a time.
def _passing_payload() -> dict:
    stats = {
        "mean_bp": 2.0,
        "hac_t": 2.0,
        "drift_mean_bp": 1.0,
        "drift_hac_t": 2.0,
        "retimed_bp": 20.0,
        "retimed_t": 4.0,
        "orders": 100,
        "retimed": 60,
        "reached_share": 0.4,
        "acted_share": 0.1,
        "capture": 0.3,
    }
    later = dict(stats, mean_bp=0.0)
    results, dsr = {}, {}
    for c in ae.CANDIDATES:
        results[c] = {
            "default": {"model": dict(stats), "2024-2026": dict(later)},
            "next_bar": {"model": dict(stats), "2024-2026": dict(later)},
            "across_offsets": {"positive": 15, "offsets": 20},
        }
        dsr[c] = {"dsr": 0.95, "dsr_cumulative": 0.5, "passes": True}
    return {
        "results": results,
        "deflated": dsr,
        "offsets": {"registered": 20, "priced": 20, "median": 10, "smoke": False},
    }


# Every criterion at its edge: the passing skeleton REPLACES; each number
# moved just past its floor makes a RECORD; "real but immaterial" needs the
# floor to fail and 25 bp at t 3 per re-timed order; a smoke run says so;
# the lines carry the numbers.
def test_verdict_criteria_at_their_edges():
    base = _passing_payload()
    record = ae.verdict(base)
    assert record["replaces"] == list(ae.CANDIDATES) and record["immaterial"] == []
    assert record["text"].startswith("REPLACES: E1, E2, E3")
    assert len(record["lines"]) == 3 and record["lines"][0].startswith(
        "E1 (sigma_half): model window +2.0"
    )
    assert (
        record["lines"][2].endswith("- REPLACES")
        and "guard held 10%" in record["lines"][2]
    )
    assert (
        "level reached 40%" in record["lines"][0]
        and "positive at 15 of 20 offsets" in record["lines"][0]
    )

    # The label of E1 after `change` edits a fresh skeleton.
    def label(change) -> str:
        payload = _passing_payload()
        change(payload["results"]["E1"], payload["deflated"]["E1"])
        return ae.verdict(payload)["candidates"]["E1"]["label"]

    def criteria(change) -> dict:
        payload = _passing_payload()
        change(payload["results"]["E1"], payload["deflated"]["E1"])
        return ae.verdict(payload)["candidates"]["E1"]["criteria"]

    edges = {
        "1_floor": lambda r, d: r["default"]["model"].update(mean_bp=1.99),
        "1_floor_t": lambda r, d: r["default"]["model"].update(hac_t=1.99),
        "2_next_bar": lambda r, d: r["next_bar"]["model"].update(hac_t=1.99),
        "3_not_negative_2024_2026": lambda r, d: r["default"]["2024-2026"].update(
            mean_bp=-0.01
        ),
        "4_deflated_sharpe": lambda r, d: d.update(dsr=0.94, passes=False),
        "5_drift_adjusted": lambda r, d: r["default"]["model"].update(
            drift_mean_bp=0.99
        ),
        "6_offsets_positive": lambda r, d: r["across_offsets"].update(positive=14),
    }
    for name, change in edges.items():
        assert label(change) == ae.RECORD, name
        failed = [k for k, v in criteria(change).items() if not v]
        assert failed == [name.replace("_t", "") if name == "1_floor_t" else name], name
    # Real but immaterial: the floor fails and the per-order reading is 25 bp at t 3.
    assert (
        label(
            lambda r, d: r["default"]["model"].update(
                mean_bp=1.0, retimed_bp=25.0, retimed_t=3.0
            )
        )
        == ae.IMMATERIAL
    )
    assert (
        label(
            lambda r, d: r["default"]["model"].update(
                mean_bp=1.0, retimed_bp=25.0, retimed_t=2.9
            )
        )
        == ae.RECORD
    )
    assert (
        label(lambda r, d: r["default"]["model"].update(retimed_bp=30.0, retimed_t=5.0))
        == ae.REPLACES
    )
    smoke = _passing_payload()
    smoke["offsets"].update(priced=2, smoke=True)
    assert ae.verdict(smoke)["text"].startswith("SMOKE RUN (2 of 20 offsets)")
    # Nothing replaces: the headline keeps the fixed 1%.
    none = _passing_payload()
    for c in ae.CANDIDATES:
        none["results"][c]["default"]["model"]["mean_bp"] = 0.5
    assert ae.verdict(none)["text"].startswith("RECORD: no candidate")


# The deflated Sharpe at N = 3 and at the cumulative 457 from the three
# candidates' model-window moments, with the across-candidate variance;
# NaN with fewer than two finite Sharpes.
def test_deflated_sharpe_at_three_trials():
    excess = {
        "E1": {"sharpe": 0.12, "skew": 0.1, "kurtosis": 3.5, "length": 1500},
        "E2": {"sharpe": 0.02, "skew": 0.0, "kurtosis": 3.0, "length": 1500},
        "E3": {"sharpe": -0.03, "skew": -0.2, "kurtosis": 4.0, "length": 1500},
    }
    record = ae.deflated(excess, "E1")
    variance = float(np.var([0.12, 0.02, -0.03], ddof=1))
    assert record["trial_variance"] == pytest.approx(variance) and record["trials"] == 3
    assert record["dsr"] == pytest.approx(
        candidate_stats.deflated_sharpe(0.12, 1500, 0.1, 3.5, 3, variance)
    )
    assert record["dsr_cumulative"] == pytest.approx(
        candidate_stats.deflated_sharpe(0.12, 1500, 0.1, 3.5, 457, variance)
    )
    assert record["dsr_cumulative"] < record["dsr"] and record["passes"] == (
        record["dsr"] >= 0.95
    )
    alone = ae.deflated({"E1": excess["E1"], "E2": {"sharpe": None}}, "E1")
    assert math.isnan(alone["dsr"]) and not alone["passes"]


# `run_offsets` hands `allocator` to the simulator: a spy around the /5
# allocator is called at every session, and the orders are the /5 book's.
def test_run_offsets_passes_the_allocator(tmp_path):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, _history(tmp_path))
    calls = []
    inner = policy_v5.allocator(mask)

    # The /5 allocator, counting its calls.
    def spy(report_, panel, config, t):
        calls.append(int(t))
        return inner(report_, panel, config, t)

    runs = so.run_offsets(restricted, mask, 1, allocator=spy)
    assert calls and len(runs) == 1 and len(runs[0]) > 0
    v5 = so.run_offsets(restricted, mask, 1, allocator=policy_v5.allocator(mask))[0]
    assert np.array_equal(v5.session, runs[0].session) and np.allclose(
        v5.weight, runs[0].weight
    )


# The command end to end on a stub loader: the synthetic book of the
# orders tests with a cube per name, two of twenty offsets. The payload
# names the plan, the revision and the membership's sha256, prices every
# buy at the median offset, carries the per-order rows from which the
# model-window mean and its Newey-West t recompute exactly, and prints one
# verdict line per candidate; bad arguments are refused before the desk
# runs.
def test_command_end_to_end(tmp_path):
    from backend.cli import market_adaptive_entry as cli

    report = _report()
    panel = report.panel
    rng = np.random.default_rng(11)
    cubes = {
        t: _session_cube(t, panel.dates, panel.close[:, j], rng)
        for j, t in enumerate(panel.tickers)
        if t != panel.benchmark
    }
    history = _history(tmp_path)
    calls = []

    # The stub loader: the synthetic report and its cubes.
    def loader(store, workers, log):
        calls.append(str(store.root))
        return report, cubes, {}

    out_path = tmp_path / "out" / "entry.json"
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--offsets",
            "20",
            "--max-offsets",
            "2",
            "--out",
            str(out_path),
        ]
    )
    text = textio.StringIO()
    assert cli.run(args, out=text, loader=loader) == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["plan"] == ae.PLAN and payload["study"] == ae.STUDY
    assert payload["offsets"] == {
        "registered": 20,
        "priced": 2,
        "median": 1,
        "smoke": True,
        "starts": [0, 1],
    }
    assert payload["windows"]["model"] == ["2018-01-02", "2024-01-01"]
    assert (
        payload["run"]["inputs"]["membership"]["sha256"]
        == hashlib.sha256(history.read_bytes()).hexdigest()
    )
    assert (
        payload["run"]["policy"] == policy_v5.POLICY_VERSION
        and payload["run"]["cubes"]["names_with_cube"] == 6
    )
    revision = payload["run"]["revision"]
    assert revision is None or (
        set(revision) == {"commit", "dirty"} and len(revision["commit"]) == 40
    )
    assert set(payload["results"]) == set(ae.CANDIDATES) == set(payload["deflated"])
    model = payload["results"]["E1"]["default"]["model"]
    assert (
        model["orders"] > 0
        and model["orders"] == payload["orders"]["median_by_window"]["model"]["buys"]
    )
    assert model["waited"] == 0 and model["drift_mean_bp"] == pytest.approx(
        model["mean_bp"]
    )
    assert 0 < model["reached_share"] <= 1 and sum(model["bars"]) == model["reached"]
    assert len(payload["per_offset"]["E2"]["model_bp"]) == 2
    assert set(payload["results"]["E3"]["splits"]) == {"grade", "detail"}
    labels = {c: v["label"] for c, v in payload["verdict"]["candidates"].items()}
    assert set(labels) == set(ae.CANDIDATES) and all(
        v == ae.RECORD for v in labels.values()
    )
    printed = text.getvalue()
    assert "SMOKE RUN (2 of 20 offsets)" in printed and printed.count("\n  E") == 3
    assert f"wrote {out_path}" in printed and calls == [str(tmp_path)]
    # The independent recomputation from the rows: the model-window mean
    # and its Newey-West t per candidate, and the per re-timed order mean.
    rows = payload["rows"]
    buys = len(rows["date"])
    assert buys == payload["orders"]["per_offset"][1]["buys"]
    lo, hi = payload["windows"]["model"]
    sessions = [d for d in rows["sessions"] if lo <= d < hi]
    finite = set()
    for c in ae.CANDIDATES:
        g = np.array(
            [v if v is not None else 0.0 for v in rows["candidates"][c]["g_bp"]]
        )
        assert len(g) == buys
        per = dict.fromkeys(sessions, 0.0)
        for d, w, v in zip(rows["date"], rows["weight"], g, strict=True):
            if lo <= d < hi:
                per[d] += w * v
        series = np.array([per[d] for d in sessions])
        ref = payload["results"][c]["default"]["model"]
        assert len(series) == ref["sessions"]
        assert series.mean() == pytest.approx(ref["mean_bp"])
        t = candidate_stats.hac_t(series, 20)
        if ref["hac_t"] is None:
            assert math.isnan(t) and (series == 0).all()  # nothing re-timed
        else:
            assert t == pytest.approx(ref["hac_t"])
            finite.add(c)
        inside = np.array([lo <= d < hi for d in rows["date"]])
        retimed = inside & (g != 0)
        assert int(retimed.sum()) == ref["retimed"]
        if retimed.any():
            assert g[retimed].mean() == pytest.approx(ref["retimed_bp"])
        assert (
            sum(rows["candidates"][c]["unpriced"][k] for k in np.flatnonzero(inside))
            == ref["unpriced"]
        )
    assert "E1" in finite  # the sigma dips re-time buys here: the check is not vacuous
    # --json prints the payload; bad arguments are refused before the desk runs.
    text = textio.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--max-offsets",
            "1",
            "--json",
            "--out",
            str(tmp_path / "j.json"),
        ]
    )
    assert cli.run(args, out=text, loader=loader) == 0
    body = text.getvalue()
    assert (
        json.loads(body[body.index("{") : body.rindex("}") + 1])["offsets"]["priced"]
        == 1
    )
    before = len(calls)
    for extra, code in (
        (["--membership", str(tmp_path / "none.csv")], 1),
        (["--offsets", "0"], 2),
    ):
        args = cli.build_parser().parse_args(
            ["--root", str(tmp_path), "--membership", str(history), *extra]
        )
        assert cli.run(args, out=textio.StringIO(), loader=loader) == code
    assert len(calls) == before
