"""The support/resistance event study (docs/research/sr-levels-plan-2026-09-29.md).

What has to hold:

- The match rules on hand-built events: same name, year and slot first,
  within 0.25 points of depth (the edge inside); the pooled same-year slot
  set on other dates next; unmatched otherwise. The controls' means,
  including bounce and break against the touch's own zone edges and
  forward returns over the controls that have them, and their per-month
  sums.
- A cell's estimate is the mean over dates of the daily average of touch
  minus control. Its t is the month-clustered t of every observation's
  influence, checked by brute force. The registered daily Newey-West t is
  kept beside it.
- On a random-walk world, where nothing can be predicted, the new t stays
  near its nominal rate while the registered one does not. A world where
  a dip to the prior day's low bounces reads SUPPORTED.
- The command runs end to end on a temporary SIP store and writes
  `<root>/desk/sr_study.json`.
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from backend.agents.trading.desk import grading, regime
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_sr_study as cli
from backend.market import sr_levels
from backend.market import sr_study as st
from backend.market.candidate_stats import hac_t
from backend.market.panel import Panel
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.tests import test_fill_timing as base

SLOTS = FULL_SESSION_SLOTS
SUPPORT = sr_levels.SUPPORT


# One side's events from hand-written rows: each touch (date, slot, depth,
# upper, lower, returns, graded, families, confluence) and each control
# (date, slot, depth, returns).
def _side(touches: list[tuple], controls: list[tuple]) -> st.SideEvents:
    t_dates = np.array([t[0] for t in touches], dtype="datetime64[D]")
    c_dates = np.array([c[0] for c in controls], dtype="datetime64[D]")
    return st.SideEvents(
        touch_date=t_dates,
        touch_slot=np.array([t[1] for t in touches], dtype=np.int64),
        touch_depth=np.array([t[2] for t in touches], dtype=float),
        touch_families=np.array([t[7] for t in touches], dtype=np.int64),
        touch_confluence=np.array([t[8] for t in touches], dtype=np.int64),
        touch_upper=np.array([t[3] for t in touches], dtype=float),
        touch_lower=np.array([t[4] for t in touches], dtype=float),
        touch_graded=np.array([t[6] for t in touches], dtype=bool),
        touch_returns=np.array([t[5] for t in touches], dtype=float).reshape(-1, 3),
        control_date=c_dates,
        control_slot=np.array([c[1] for c in controls], dtype=np.int64),
        control_depth=np.array([c[2] for c in controls], dtype=float),
        control_returns=np.array([c[3] for c in controls], dtype=float).reshape(-1, 3),
    )


# A NameEvents with the given support side and an empty resistance side.
def _name(ticker: str, support: st.SideEvents) -> st.NameEvents:
    return st.NameEvents(
        ticker, {SUPPORT: support, sr_levels.RESISTANCE: st._empty_side()}, 10, 10, 10
    )


# The plan's constants, frozen, with the addendum's.
def test_constants_are_the_plans():
    assert st.TRIALS == 640
    assert abs(st.BONFERRONI_T - 3.95) < 0.005
    assert st.MATCH_POINTS == 0.25
    assert st.CLEARANCE == 2.0
    assert (st.MIN_CELL_DATES, st.MIN_MONTHS) == (30, 12)
    assert st.HAC_LAG == 10
    assert st.OUTCOMES == ("r_close_bp", "bounce_pp", "break_pp", "r_next_bp", "r_5_bp")
    assert len(st.GROUPS) == 16
    assert st.POPULATIONS == ("members", "graded_a")
    assert st.PRIMARY == {
        "side": "support",
        "population": "members",
        "group": "all",
        "outcome": "r_close_bp",
    }
    assert st.PRIMARY_T == 2.0
    assert grading.ORDINAL[grading.A] == st.GRADE_FLOOR
    assert set(st.WINDOWS) == {st.CHOOSING, st.REPORTED}


# The match rules. Name A's first touch finds its two same-name controls:
# one 0.2 points away and one exactly 0.25 away. It ignores one 0.26 away,
# one in another slot and one in another year. Its second touch has none of
# its own and takes name B's pooled bar in its slot and year, not B's bar
# on the same date. Its third has no control anywhere. The means follow the
# plan: bounce and break are scored on the touch's own edges, and r_5 over
# the controls that have one.
def test_matching_rules_by_hand():
    a = _side(
        touches=[
            ("2020-03-02", 5, -1.0, 0.004, -0.006, (0.002, 0.01, 0.02), True, 1, 1),
            ("2020-06-01", 5, -3.0, 0.001, -0.001, (-0.003, 0.0, 0.01), False, 3, 2),
            ("2020-03-03", 9, -1.0, 0.004, -0.006, (0.001, 0.0, 0.0), False, 1, 3),
        ],
        controls=[
            ("2020-01-06", 5, -1.2, (0.001, 0.02, math.nan)),
            ("2020-02-03", 5, -0.74, (0.5, 0.5, 0.5)),
            ("2020-04-06", 6, -1.0, (0.5, 0.5, 0.5)),
            ("2021-01-04", 5, -1.0, (0.5, 0.5, 0.5)),
            ("2020-05-04", 5, -0.75, (0.009, -0.01, 0.04)),
        ],
    )
    b = _side(
        touches=[],
        controls=[
            ("2020-07-06", 5, -3.1, (0.004, 0.002, -0.01)),
            ("2020-06-01", 5, -3.0, (0.5, 0.5, 0.5)),
            ("2020-03-02", 5, -1.0, (0.5, 0.5, 0.5)),
        ],
    )
    matched = st.match(SUPPORT, [_name("A", a), _name("B", b)])
    assert matched.kind.tolist() == [st.OWN_NAME, st.POOLED, st.UNMATCHED]
    assert matched.controls[0].tolist() == [2, 2, 1]
    assert matched.controls[1].tolist() == [1, 1, 1]
    first = matched.control[0]
    assert first[0] == pytest.approx((0.001 + 0.009) / 2)
    # Bounce: the control's return to the close above the touch's upper edge
    # (0.004): only the 0.009 one. Break: below -0.006: none.
    assert first[1] == pytest.approx(0.5)
    assert first[2] == pytest.approx(0.0)
    assert first[3] == pytest.approx((0.02 - 0.01) / 2)
    assert first[4] == pytest.approx(0.04)  # the NaN r_5 left out
    np.testing.assert_allclose(matched.control[1], [0.004, 1.0, 0.0, 0.002, -0.01])
    assert np.isnan(matched.control[2]).all()
    # The touch's own outcomes: 0.002 is under its upper edge 0.004 (no
    # bounce) and over -0.006 (no break).
    np.testing.assert_allclose(matched.touch[0], [0.002, 0.0, 0.0, 0.01, 0.02])
    # Per-month pairs: the first touch's controls sit in 2020-01 and 2020-05.
    first_pairs = matched.pair_touch == 0
    months = sorted(matched.pair_month[first_pairs].tolist())
    assert months == [
        int(np.datetime64("2020-01", "M").astype(np.int64)),
        int(np.datetime64("2020-05", "M").astype(np.int64)),
    ]
    np.testing.assert_allclose(
        matched.pair_sum[first_pairs].sum(axis=0), [0.010, 1.0, 0.0, 0.01, 0.04]
    )
    np.testing.assert_array_equal(
        matched.pair_count[first_pairs].sum(axis=0), [2, 2, 1]
    )
    summary = st.match_summary(matched)[st.CHOOSING]
    assert (summary["own_name"], summary["pooled"], summary["unmatched"]) == (1, 1, 1)
    assert summary["median_controls"] == 1.5


# Resistance mirrors bounce and break: a close under the touch's lower edge
# is a bounce (turned back), over its upper edge a break. Two controls close
# over the upper edge and one under the lower, so the two rates differ.
def test_resistance_bounce_and_break_mirror():
    side = _side(
        touches=[("2020-03-02", 5, 1.0, 0.004, -0.006, (-0.01, 0.0, 0.0), False, 1, 1)],
        controls=[
            ("2020-01-06", 5, 1.1, (0.005, 0.0, 0.0)),
            ("2020-01-13", 5, 1.2, (0.006, 0.0, 0.0)),
            ("2020-02-03", 5, 0.9, (-0.007, 0.0, 0.0)),
        ],
    )
    names = [
        st.NameEvents(
            "A", {SUPPORT: st._empty_side(), sr_levels.RESISTANCE: side}, 1, 1, 1
        )
    ]
    matched = st.match(sr_levels.RESISTANCE, names)
    np.testing.assert_allclose(matched.touch[0, 1:3], [1.0, 0.0])
    np.testing.assert_allclose(matched.control[0, 1:3], [1 / 3, 2 / 3])
    # The same bars on the support side: bounce over the upper edge.
    names = [
        st.NameEvents(
            "A", {SUPPORT: side, sr_levels.RESISTANCE: st._empty_side()}, 1, 1, 1
        )
    ]
    supported = st.match(SUPPORT, names)
    np.testing.assert_allclose(supported.touch[0, 1:3], [0.0, 1.0])
    np.testing.assert_allclose(supported.control[0, 1:3], [2 / 3, 1 / 3])


# The A/A+ population is read at the prior close, the grade the /4 order
# filling that session was decided on. Grades alternate A+ and C by panel
# row, so every touch is graded exactly when its session's previous row
# was A+. Non-member sessions give no events, and member ones are counted.
def test_grade_is_read_at_the_prior_close():
    report, mask, cubes = _walk_world(t=120, names=2, seed=7)
    panel = report.panel
    rows = len(panel.dates)
    grades = np.where(
        np.arange(rows)[:, None] % 2 == 0,
        grading.ORDINAL[grading.A_PLUS],
        grading.ORDINAL[grading.C],
    )
    grades = np.repeat(grades, len(panel.tickers), axis=1)
    member = mask.copy()
    member[:60, 0] = False
    names = st.collect(cubes, panel, member, grades)
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    for events in names:
        for side in st.SIDES:
            got = events.sides[side]
            row = np.searchsorted(dates, got.touch_date)
            assert len(row) > 0
            np.testing.assert_array_equal(got.touch_graded, (row - 1) % 2 == 0)
    assert names[0].member_sessions == rows - 60
    assert names[1].member_sessions == rows
    assert (np.searchsorted(dates, names[0].sides[SUPPORT].touch_date) >= 60).all()
    assert (np.searchsorted(dates, names[0].sides[SUPPORT].control_date) >= 60).all()


# The estimate is the mean over dates of the daily average of touch minus
# control, and its t is the month-clustered t of every observation, here
# recomputed by brute force from the matched pairs. The registered t is the
# Newey-West t of the daily series.
def test_cell_estimate_and_month_clustered_t_by_brute_force(monkeypatch):
    monkeypatch.setattr(st, "MIN_CELL_DATES", 3)
    monkeypatch.setattr(st, "MIN_MONTHS", 3)
    rng = np.random.default_rng(3)
    # Touches on the 6th and 13th of ten months, one to three a date; one
    # control bar on the 20th or 27th, so every control sits in a month of
    # its own date, never the touch's day.
    days = [(m, d) for m in range(1, 11) for d in (6, 13)]
    touches, controls = [], []
    for i, (month, day) in enumerate(days):
        for k in range(1 + i % 3):
            touches.append(
                (
                    f"2020-{month:02d}-{day:02d}",
                    5,
                    round(-1.0 + 0.1 * k, 2),
                    0.004,
                    -0.006,
                    tuple(rng.normal(0, 0.01, 3)),
                    bool(k % 2),
                    1,
                    1,
                )
            )
        controls.append(
            (
                f"2020-{month:02d}-{day + 14:02d}",
                5,
                -1.0 + 0.05 * (i % 4),
                tuple(rng.normal(0, 0.01, 3)),
            )
        )
    side = _side(touches, controls)
    matched = st.match(SUPPORT, [_name("A", side)])
    assert (matched.kind == st.OWN_NAME).all()
    _, inverse = np.unique(matched.date, return_inverse=True)
    days = int(inverse.max()) + 1
    for k, outcome in enumerate(st.OUTCOMES):
        select = np.ones(len(matched.date), dtype=bool)
        got = st.cell(matched, select, outcome, inverse, days)
        scale = st.OUTCOME_SCALE[outcome]
        diff = (matched.touch[:, k] - matched.control[:, k]) * scale
        daily = np.array([diff[inverse == d].mean() for d in range(days)])
        assert got["diff"] == pytest.approx(daily.mean(), rel=1e-12)
        assert got["t_daily_hac"] == pytest.approx(hac_t(daily, st.HAC_LAG))
        assert got["touches"] == len(diff)
        assert got["dates"] == days
        # Brute force: every touch and every control bar, each in its month.
        w = np.array(
            [1.0 / ((inverse == inverse[i]).sum() * days) for i in range(len(diff))]
        )
        y = matched.touch[:, k] * scale
        c = matched.control[:, k] * scale
        mu_t, mu_c = (w * y).sum(), (w * c).sum()
        parts: dict[int, float] = {}
        for i in range(len(diff)):
            m = int(st.month_of(matched.date[i : i + 1])[0])
            parts[m] = parts.get(m, 0.0) + w[i] * (y[i] - mu_t)
            for j in range(len(side.control_date)):
                if (
                    abs(side.control_depth[j] - side.touch_depth[i])
                    > st.MATCH_POINTS + st.MATCH_SLACK
                ):
                    continue
                if k == 0:
                    value = side.control_returns[j, 0]
                elif k == 1:
                    value = float(side.control_returns[j, 0] > side.touch_upper[i])
                elif k == 2:
                    value = float(side.control_returns[j, 0] < side.touch_lower[i])
                else:
                    value = side.control_returns[j, k - 2]
                n = matched.controls[i, st.COUNT_OF[k]]
                cm = int(st.month_of(side.control_date[j : j + 1])[0])
                parts[cm] = parts.get(cm, 0.0) - w[i] / n * (value * scale - mu_c)
        sums = np.array(list(parts.values()))
        assert abs(sums.sum()) < 1e-9 * max(1.0, np.abs(sums).max())
        variance = (sums**2).sum() * len(sums) / (len(sums) - 1)
        assert got["t"] == pytest.approx(got["diff"] / math.sqrt(variance), rel=1e-9)
        assert got["months"] == len(sums)


# A cell with too few dates or months reports no t; a cell with no touches
# reports zeros and NaN.
def test_cell_thresholds():
    side = _side(
        [("2020-03-02", 5, -1.0, 0.004, -0.006, (0.002, 0.01, 0.02), True, 1, 1)],
        [("2020-01-06", 5, -1.0, (0.001, 0.02, 0.03))],
    )
    matched = st.match(SUPPORT, [_name("A", side)])
    _, inverse = np.unique(matched.date, return_inverse=True)
    got = st.cell(matched, np.ones(1, dtype=bool), "r_close_bp", inverse, 1)
    assert got["diff"] == pytest.approx(10.0)
    assert math.isnan(got["t"])
    assert math.isnan(got["t_daily_hac"])
    empty = st.cell(matched, np.zeros(1, dtype=bool), "r_close_bp", inverse, 1)
    assert empty["touches"] == 0
    assert math.isnan(empty["diff"])


# The groups: a family's touches are those whose zone holds it; confluence
# buckets split 1, 2 and 3 or more.
def test_group_masks():
    families = np.array([0b1, 0b10, 0b11, 1 << 11], dtype=np.int64)
    matched = replace(
        st.match(SUPPORT, []),
        date=np.array(["2020-01-02"] * 4, dtype="datetime64[D]"),
        families=families,
        confluence=np.array([1, 2, 3, 5]),
    )
    assert st.group_mask(matched, "swing_20").tolist() == [True, False, True, False]
    assert st.group_mask(matched, "swing_60").tolist() == [False, True, True, False]
    assert st.group_mask(matched, "vwap").tolist() == [False, False, False, True]
    assert st.group_mask(matched, "confluence_1").tolist() == [
        True,
        False,
        False,
        False,
    ]
    assert st.group_mask(matched, "confluence_3+").tolist() == [
        False,
        False,
        True,
        True,
    ]
    with pytest.raises(ValueError, match="unknown group"):
        st.group_mask(matched, "tea leaves")


# A desk report over `panel` with churning grades and an all-member mask
# (the benchmark excluded).
def _report(panel: Panel, seed: int) -> tuple[DeskReport, np.ndarray]:
    rng = np.random.default_rng(seed)
    t, n = panel.adj_close.shape
    grades = base._grades(rng, t, n)
    conviction = grades.astype(float)
    graded = grading.Graded(grades, conviction.copy(), {}, conviction)
    state = regime.RegimeState(
        0.0, 0.0, 0.5, 0.0, 0.0, 0.0, "ai", 0.1, 0.0, 1.0, 1.0, (), 0.0, False
    )
    view = regime.RegimeView([state] * t, Opinion("rotation", np.full((t, n), np.nan)))
    names = panel.tickers[:-1]
    report = DeskReport(
        panel, {k: "ai" for k in names}, {}, view, graded, graded.as_scores(), []
    )
    mask = np.ones((t, n), dtype=bool)
    mask[:, -1] = False
    return report, mask


# A world whose fifteen-minute bars are a pure random walk and whose daily
# bars are built from them. With `bounce`, a bar that dips from above to
# within 0.8% of the prior day's low starts a drift of +0.15% a bar for the
# rest of the session: a planted support. Returns (report, mask, cubes).
def _walk_world(
    t: int = 1000,
    names: int = 10,
    seed: int = 0,
    bounce: bool = False,
    start: date = date(2021, 1, 4),
):
    rng = np.random.default_rng(seed)
    dates = base._dates(t, start)
    tickers = tuple(f"N{i:02d}" for i in range(names)) + ("SPY",)
    shape = (t, len(tickers))
    daily = {k: np.zeros(shape) for k in ("open", "high", "low", "close")}
    cubes = {}
    for j, ticker in enumerate(tickers):
        bars = {k: np.zeros((t, SLOTS)) for k in ("open", "high", "low", "close")}
        price, prior_low = 100.0, math.nan
        for d in range(t):
            o = price * math.exp(rng.normal(0, 0.004))
            steps = rng.normal(0, 0.004, SLOTS)
            wick = np.abs(rng.normal(0, 0.002, (2, SLOTS)))
            closes = np.zeros(SLOTS)
            last, drift = o, 0.0
            for s in range(SLOTS):
                c = last * math.exp(steps[s] + drift)
                closes[s] = c
                lo = min(last, c) * math.exp(-wick[1, s])
                if (
                    bounce
                    and s >= sr_levels.FIRST_SLOT
                    and drift == 0.0
                    and last > prior_low * 1.012
                    and lo <= prior_low * 1.008
                ):
                    drift = 0.0015
                last = c
            opens = np.concatenate([[o], closes[:-1]])
            highs = np.maximum(opens, closes) * np.exp(wick[0])
            lows = np.minimum(opens, closes) * np.exp(-wick[1])
            for k, v in (
                ("open", opens),
                ("high", highs),
                ("low", lows),
                ("close", closes),
            ):
                bars[k][d] = v
            daily["open"][d, j], daily["close"][d, j] = o, closes[-1]
            daily["high"][d, j], daily["low"][d, j] = highs.max(), lows.min()
            price, prior_low = closes[-1], lows.min()
        cubes[ticker] = SessionCube(
            ticker,
            dates,
            bars["open"],
            bars["high"],
            bars["low"],
            bars["close"],
            rng.uniform(500, 1500, (t, SLOTS)),
            np.full(t, np.nan),
            {"early_close": 0, "incomplete": 0, "no_prior_close": 0},
            bars["close"][:, -1].copy(),
            np.full(t, np.nan),
        )
    panel = Panel(
        dates=dates,
        tickers=tickers,
        adj_close=daily["close"].copy(),
        volume=np.full(shape, 1e6),
        themes={k: () for k in tickers},
        benchmark="SPY",
        **daily,
    )
    report, mask = _report(panel, seed)
    return report, mask, {k: v for k, v in cubes.items() if k != "SPY"}


# On a random-walk world nothing is predictable. The primary cell is inside
# the noise, and the month-clustered t puts few cells beyond |t| 2 and at
# most one beyond the Bonferroni line. The registered daily t, blind to the
# reused controls, puts several times as many beyond |t| 2: the addendum's
# finding.
def test_null_world_is_calibrated():
    report, mask, cubes = _walk_world(t=900, names=12, seed=0)
    payload = st.study(st.collect(cubes, report.panel, mask, report.graded.grades))
    ts = np.array([c["t"] for c in payload["cells"] if c["t"] is not None])
    old = np.array(
        [c["t_daily_hac"] for c in payload["cells"] if c["t_daily_hac"] is not None]
    )
    assert len(ts) > 200
    assert (np.abs(ts) > 2).mean() < 0.12
    assert len(payload["bonferroni_survivors"]) <= 1
    assert (np.abs(old) > 2).mean() > 2 * (np.abs(ts) > 2).mean()
    first = payload["primary"]
    assert abs(first["choosing"]["t"]) < 2.5
    assert first["verdict"] == st.NOT_SUPPORTED
    assert len(payload["cells"]) == st.TRIALS
    assert payload["trials"] == 640


# Where a dip from above to the prior day's low starts a rally, the study
# finds it: the primary cell is positive with a large t, SUPPORTED, and the
# prior-day family carries more than the touches without it.
def test_planted_bounce_is_supported():
    report, mask, cubes = _walk_world(t=1000, names=8, seed=5, bounce=True)
    payload = st.study(st.collect(cubes, report.panel, mask, report.graded.grades))
    first = payload["primary"]
    assert first["verdict"] == st.SUPPORTED
    assert first["choosing"]["diff"] > 5.0
    assert first["choosing"]["t"] > 4.0
    assert first["reported"]["diff"] > 0
    cells = st.by_key(payload["cells"])
    key = ("support", "members", st.CHOOSING)
    assert (
        cells[(*key, "prior_day", "r_close_bp")]["diff"]
        > cells[(*key, "all", "r_close_bp")]["diff"]
    )
    assert cells[(*key, "prior_day", "bounce_pp")]["diff"] > 0
    assert payload["bonferroni_survivors"]


# A study of no names is a payload of empty cells, not an error.
def test_empty_study():
    payload = st.study([])
    assert payload["primary"]["verdict"] == st.NOT_SUPPORTED
    assert len(payload["cells"]) == st.TRIALS
    assert payload["member_sessions"] == 0


# The command end to end on a temporary SIP store with three names and a
# benchmark. It reads cubes from the store and the mask from the
# membership file, runs the desk hook once, and writes the payload with
# every cell, the primary test and the match rates. The text has the
# tables. `--json` prints the payload; `--tickers` narrows the names and
# reports one the panel lacks. The process pool gives the same payload as
# one process.
def test_cli_end_to_end(tmp_path):
    membership, fake_desk, sessions, names, calls = base._sip_store(tmp_path)
    common = ["--root", str(tmp_path), "--membership", str(membership)]
    out = io.StringIO()
    args = cli.build_parser().parse_args([*common, "--workers", "1"])
    assert cli.run(args, out, desk_run=fake_desk) == 0
    assert calls == [str(tmp_path)]
    target = tmp_path / "desk" / "sr_study.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["study"] == "sr_levels"
    assert payload["tickers"] == list(names)
    assert len(payload["cells"]) == st.TRIALS
    assert payload["member_sessions"] == 3 * len(sessions)
    assert payload["official_close"]["auction"] == 3 * len(sessions)
    assert set(payload["match"]) == {"support", "resistance"}
    assert payload["primary"]["verdict"] in (st.SUPPORTED, st.NOT_SUPPORTED)
    assert payload["exclusions"]["AAA"] == {
        "early_close": 0,
        "incomplete": 0,
        "no_prior_close": 0,
    }
    touches = payload["touches"]["support"][st.CHOOSING]["touches"]
    assert touches > 0
    assert 0.0 < payload["coverage"]["vwap"] <= 1.0
    text = out.getvalue()
    assert "support/resistance study" in text
    assert "primary (support, every member" in text
    assert "Bonferroni: 640 cells" in text
    assert "support touches, every member, 2016-2023" in text
    assert "resistance touches, graded A/A+ at the prior close, 2024-2026" in text
    # --json, --tickers, and a name the panel lacks.
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [*common, "--workers", "1", "--tickers", "BBB,ZZZ", "--json"]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    printed = json.loads(out.getvalue())
    assert printed["tickers"] == ["BBB"]
    # Two processes give the same cells as one.
    args = cli.build_parser().parse_args([*common, "--workers", "2", "--json"])
    out = io.StringIO()
    assert cli.run(args, out, desk_run=fake_desk) == 0
    pooled = json.loads(out.getvalue())
    assert pooled["cells"] == payload["cells"]
