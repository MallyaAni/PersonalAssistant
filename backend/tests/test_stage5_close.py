"""Stage 5: buying at the decision day's close, decided at 15:30.

What has to hold (docs/research/stage5-plan-2026-09-29.md, and the timing
audit's section 3 for the proxy):

- The one step reads row t and the final history before it. With row t
  set to the final row it reproduces the report cell for cell (the null
  test), and with any other row it equals the desk's own analysts run on
  the panel with row t replaced.
- The proxy row is the 15:15-15:30 bar's close, the high and low through
  it with the day's open, on the panel's bases by the session's scale, the
  volume through 15:15 times the trailing-20 median ratio; a name with no
  bar carries t - 1's close. A release accepted in [15:30, 16:00) reacts a
  day later.
- The control is stage 4's executor under `/5`; replaying its planner on
  its own book with the null row reproduces its journal's submitted units,
  and each buy's leg comes from the planner's own orders.
- Matched / missed / extra per (session, name), with FOMC restorations,
  early closes and names without a bar filling as the control; an extra is
  a round trip at t's close and the board's sell rule in t + 1, less 25 bp
  each way.
- The candidate fills at t's official close times the session's scale (the
  adjusted close); the control is dip_or_close in t + 1.
- The windows and the plan's criteria 1-4, PASS or RECORD.
- The ledger walk without the close buys is the control run to the bit.
- The command runs the null test alone, or the whole test, with a stub
  loader.
"""

from __future__ import annotations

import functools
import io
import json
import math
import tempfile
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import (
    desk,
    entry,
    fundamental,
    opinions,
    point_in_time,
    policy_v4,
    policy_v5,
    regime,
    sentiment,
    simulate,
    technical,
    value,
)
from backend.agents.trading.desk import exit as exit_analyst
from backend.agents.trading.desk.opinions import Opinion, stances_from_ranks
from backend.cli import market_stage5_close as cli
from backend.market import challenger, fill_timing, language, profit_taking
from backend.market import stage3_io as sio
from backend.market import stage4_orders as so
from backend.market import stage5_close as s5
from backend.market import technical as market_technical
from backend.market.panel import Panel
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.market.universe import AI_COMPUTE, SOFTWARE

T = 470
PROXY_FROM = 260
DROPPED = ("A03", "A05", "S02")


# The desk's report from its analysts, as `desk.run` assembles it: the
# regime, the technical, sentiment and value analysts, a given fundamental
# score, the value analyst blended with the gap.
def _report_of(panel, sides, levels, gap, tone, fund):
    view = regime.opine(panel, sides, None)
    ops = {
        fundamental.NAME: Opinion(fundamental.NAME, fund),
        technical.NAME: technical.opine(panel, view.ai_trend),
        sentiment.NAME: sentiment.opine(language.tone_features(panel, tone)),
        value.NAME: value.opine(panel, levels, sides),
    }
    plain = desk.assemble(panel, sides, ops, view, ())
    live = desk.assemble(
        panel, sides, challenger.with_gap(ops, gap), view, (desk.EXPECTATIONS_GAP,)
    )
    return replace(live, alternate=plain)


# A synthetic book over weekdays from 2024-11-01: fourteen AI names, ten
# software names and SPY on random walks, SPY pushed down in the week
# before the 2026-07-29 FOMC decision (so the event lifecycle runs),
# quarterly filing levels (and the same levels one day later for "strictly
# before t"), release tone with acceptance times after the close, at
# 15:40, at 15:50 and before the open, and SIP cubes that agree with the
# daily bars, skip the calendar's early closes and miss every other
# session of three names from row 280.
@functools.lru_cache(maxsize=1)
def _world():
    rng = np.random.default_rng(0)
    names = tuple(f"A{i:02d}" for i in range(14)) + tuple(
        f"S{i:02d}" for i in range(10)
    )
    tickers = names + ("SPY",)
    n = len(tickers)
    days, day = [], date(2024, 11, 1)
    while len(days) < T:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    dates = np.array(days, dtype="datetime64[D]")
    ret = rng.normal(0.0006, 0.02, size=(T, n))
    fomc = int(np.searchsorted(dates, np.datetime64("2026-07-29")))
    ret[fomc - 8 : fomc + 1, -1] = -0.01
    close = 50.0 * np.exp(ret.cumsum(axis=0))
    adj = close * np.linspace(0.97, 1.0, T)[:, None]
    opn = close * np.exp(rng.normal(0, 0.006, size=close.shape))
    high = np.maximum(close, opn) * np.exp(
        np.abs(rng.normal(0, 0.01, size=close.shape))
    )
    low = np.minimum(close, opn) * np.exp(
        -np.abs(rng.normal(0, 0.01, size=close.shape))
    )
    vol = np.exp(rng.normal(13, 0.4, size=close.shape))
    themes = {t: ((AI_COMPUTE,) if t.startswith("A") else (SOFTWARE,)) for t in names}
    panel = Panel(dates, tickers, opn, high, low, close, adj, vol, themes, "SPY")
    sides = {t: ("ai" if t.startswith("A") else "software") for t in names}
    filings = np.arange(0, T, 63)
    base = {
        "revenue": np.exp(rng.normal(20, 1, size=(len(filings), n))),
        "earnings": np.exp(rng.normal(18, 1, size=(len(filings), n))),
        "equity": np.exp(rng.normal(19, 1, size=(len(filings), n))),
        "shares": np.exp(rng.normal(18, 0.3, size=(len(filings), n))),
        "revenue_growth": rng.normal(0.1, 0.2, size=(len(filings), n)),
    }
    known = np.searchsorted(filings, np.arange(T), side="right") - 1
    levels = {k: v[known] for k, v in base.items()}
    later = np.searchsorted(filings + 1, np.arange(T), side="right") - 1
    strict = {
        k: np.where((later >= 0)[:, None], v[np.maximum(later, 0)], np.nan)
        for k, v in base.items()
    }
    gap = rng.normal(0, 1, size=(T, n))
    tone, edgar = {}, {}
    for t in names:
        records, events = [], []
        for k, at in enumerate(range(5, T, 63)):
            d = days[min(T - 1, at + int(rng.integers(0, 20)))]
            hour, minute = [(16, 30), (15, 40), (15, 50), (9, 0)][k % 4]
            when = datetime(
                d.year, d.month, d.day, hour, minute, tzinfo=s5.calendar.NEW_YORK
            )
            reaction = d + timedelta(days=1) if hour >= 16 else d
            scores = rng.integers(-1, 2, size=5).astype(float)
            records.append(
                language.ToneRecord(f"{t}-{k}", reaction, *scores, "", "m", "p", False)
            )
            events.append(
                SimpleNamespace(accession=f"{t}-{k}", accepted=when.astimezone(UTC))
            )
        tone[t] = tuple(records)
        edgar[t] = SimpleNamespace(events=tuple(events))
    fund = rng.normal(0, 1, size=(T, n))
    report = _report_of(panel, sides, levels, gap, tone, fund)
    folder = Path(tempfile.mkdtemp(prefix="stage5-test-"))
    members = folder / "membership.csv"
    rows = ["ticker,entered,entry_announced,exited,exit_announced,source,rule"]
    rows += [f"{t},2014-01-02,2014-01-02,,,test,member" for t in names]
    members.write_text("\n".join(rows) + "\n", encoding="utf-8")
    early = s5.early_closes(dates)
    cubes = {}
    for j, t in enumerate(tickers):
        keep = ~early
        if t in DROPPED:
            keep = keep.copy()
            keep[280::2] = False
        o, c, m = opn[keep, j], close[keep, j], int(keep.sum())
        path = o[:, None] * np.exp(rng.normal(0, 0.003, size=(m, 26)).cumsum(axis=1))
        path = path * (c / path[:, -1])[:, None] ** (np.arange(26) / 25.0)[None, :]
        opens = np.concatenate([o[:, None], path[:, :-1]], axis=1)
        cubes[t] = SessionCube(
            t,
            dates[keep],
            opens,
            np.maximum(opens, path) * 1.001,
            np.minimum(opens, path) * 0.999,
            path,
            np.exp(rng.normal(10, 0.3, size=(m, 26))),
            np.r_[np.nan, c[:-1]],
            {},
            c.copy(),
            np.ones(m),
        )
    restricted, mask = point_in_time.point_in_time(report, members)
    final = s5.final_state(report)
    return SimpleNamespace(
        panel=panel,
        sides=sides,
        levels=levels,
        strict=strict,
        gap=gap,
        tone=tone,
        edgar=edgar,
        fund=fund,
        report=report,
        members=members,
        cubes=cubes,
        early=early,
        restricted=restricted,
        mask=mask,
        final=final,
    )


# The world's null grid, its control runs from offsets 0-2 and their null
# replays, the 15:30 and 15:45 proxy grids and the fills.
@functools.lru_cache(maxsize=1)
def _study():
    w = _world()
    stop = len(w.final.dates) - 1
    sent = s5.sentiment_raw(w.panel, w.tone)
    null = s5.null_grid(w.final, w.levels, sent, PROXY_FROM, stop)
    runs = s5.run_offsets(w.restricted, w.mask, 3)
    replays = [s5.replay(r, w.restricted, w.mask, null, compare=True) for r in runs]
    acceptance = s5.acceptance_times(w.edgar)
    grids = {}
    for when in (s5.AT_1530, s5.AT_1545):
        bars = s5.bars(w.panel, w.cubes, when)
        cut, _ = s5.tone_cutoff(w.tone, acceptance, when.tone_cutoff)
        grids[when.label] = s5.proxy_grid(
            w.final, bars, w.strict, s5.sentiment_raw(w.panel, cut), PROXY_FROM, stop
        )
    return SimpleNamespace(
        null=null,
        check=s5.null_check(w.final, null),
        runs=runs,
        replays=replays,
        grids=grids,
        fills=s5.fill_grid(w.panel, w.cubes),
    )


# --- the one step --------------------------------------------------------------


# The running EMA states give `technical.ema` exactly, the week ends are
# the ones `technical._weekly_ema` steps on, and the run lengths restart
# where `opinions.persist` restarts them.
def test_ema_states_week_ends_and_runs_mirror_the_desk():
    w = _world()
    f = w.final
    e21 = np.where(f.e21_count >= 21, f.e21_state, np.nan)
    np.testing.assert_array_equal(e21, market_technical.ema(f.adj, 21))
    e50 = np.where(f.e50_count >= 50, f.e50_state, np.nan)
    np.testing.assert_array_equal(e50, market_technical.ema(f.adj, 50))
    weekly = np.where(f.weekly_count >= 21, f.weekly_state, np.nan)
    rows = np.flatnonzero(f.week_end)
    np.testing.assert_array_equal(weekly, market_technical.ema(f.adj[rows], 21))
    np.testing.assert_array_equal(f.w21[rows], weekly)
    days = f.dates.astype(int)
    for t in rows[:-1]:
        # A Friday, or the last session before a new week.
        assert (days[t] + 3) % 7 == 4 or (days[t + 1] + 3) // 7 != (days[t] + 3) // 7
    raw = np.array([[1, 0], [1, 0], [1, 1], [0, 1], [0, 1]])
    resets = np.zeros(raw.shape, dtype=bool)
    resets[2, 0] = True
    np.testing.assert_array_equal(
        s5._runs(raw, resets), [[1, 1], [2, 2], [1, 1], [1, 2], [2, 3]]
    )


# One step of persistence from the final state equals `opinions.persist`'s
# row t, with and without explicit resets.
def test_persist_step_matches_persist_with_resets():
    rng = np.random.default_rng(3)
    raw = rng.integers(-1, 2, size=(40, 6))
    resets = rng.random((40, 6)) < 0.1
    for rs in (None, resets):
        held = opinions.persist(raw, opinions.PERSISTENCE, resets=rs)
        final = SimpleNamespace(
            raw={"x": raw},
            runs={"x": s5._runs(raw, rs)},
            held={"x": held},
            resets={"x": rs},
        )
        for t in range(1, 40):
            np.testing.assert_array_equal(
                s5._persist_step(final, "x", t, raw[t]), held[t]
            )


# With row t set to the final row, the one step reproduces the report cell
# for cell on every session; a wrong input (the gap a session late) is
# caught, so the check has teeth.
def test_null_grid_reproduces_the_report_and_catches_a_wrong_input():
    w = _world()
    study = _study()
    check = study.check
    assert check["passes"], check
    assert check["sessions"] == T - 1 - PROXY_FROM
    assert set(check["mismatches"]) >= {"grade", "blocked", "z", "gate", "raw_value"}
    assert all(v == 0.0 for v in check["max_abs_diff"].values())
    # The report has real variety on these sessions: A/A+ grades, gated and
    # open rotation, blocked names, entry triggers.
    rows = slice(PROXY_FROM, T - 1)
    assert (w.final.grades[rows] >= s5.GRADE_A).sum() > 100
    assert 0 < w.final.gate[rows].mean() < 1
    assert w.final.blocked[rows].any()
    assert (w.final.z[rows] >= 1.10).any()
    late = replace(w.final, gap=np.vstack([w.final.gap[:1], w.final.gap[:-1]]))
    wrong = s5.null_grid(
        late, w.levels, s5.sentiment_raw(w.panel, w.tone), PROXY_FROM, PROXY_FROM + 40
    )
    bad = s5.null_check(w.final, wrong)
    assert not bad["passes"]
    assert bad["mismatches"]["value_score"] > 0


# The proxy's one step at a modified row equals the desk's own analysts
# (regime, technical, value with the gap, sentiment, the grade, the exit
# analyst's blocker and the band z) run on the panel with row t replaced -
# the price, the high and low, the volume, the levels, the gap and the
# tone - on week ends and not, gated sessions and not.
def test_one_step_equals_a_full_recompute_with_row_t_replaced():
    w = _world()
    f = w.final
    rng = np.random.default_rng(7)
    n = len(f.tickers)
    seen = {"week_end": 0, "gate": 0, "grade_changed": 0}
    for t in (262, 290, 301, 333, 347, 380, 404, 437, 466):
        d = rng.normal(0, 0.025, n)
        have = rng.random(n) > 0.1
        ap = np.where(have, f.adj[t] * np.exp(d), f.adj[t - 1])
        cp = np.where(have, f.close[t] * np.exp(d), f.close[t - 1])
        hp = np.where(have, np.maximum(cp * 1.012, f.open[t]), cp)
        lp = np.where(have, np.minimum(cp * 0.988, f.open[t]), cp)
        dp = np.where(have, f.dollar[t] + rng.normal(0, 0.3, n), np.nan)
        row = s5.Row(ap, cp, hp, lp, dp, have)
        levels = {k: v.copy() for k, v in w.levels.items()}
        for k in levels:
            levels[k][t] = w.strict[k][t] * np.exp(rng.normal(0, 0.05, n))
        gap = w.gap.copy()
        gap[t] = w.gap[t - 1]
        tone = {
            k: tuple(
                replace(r, reaction_date=r.reaction_date + timedelta(days=1))
                if np.datetime64(r.reaction_date, "D") == f.dates[t]
                else r
                for r in records
            )
            for k, records in w.tone.items()
        }
        arrays = {
            k: np.array(getattr(w.panel, k), copy=True)
            for k in ("open", "high", "low", "close", "adj_close", "volume")
        }
        arrays["close"][t], arrays["adj_close"][t] = cp, ap
        arrays["high"][t], arrays["low"][t] = hp, lp
        arrays["volume"][t] = np.where(np.isfinite(dp), np.exp(dp) / cp, np.nan)
        panel = replace(w.panel, **arrays)
        ref = _report_of(panel, w.sides, levels, gap, tone, w.fund)
        step = s5.one_step(f, t, row, levels, gap[t], s5.sentiment_raw(panel, tone)[t])
        np.testing.assert_array_equal(step.grade, ref.graded.grades[t])
        np.testing.assert_array_equal(
            step.blocked, exit_analyst.evidence(panel).signalled()[t]
        )
        np.testing.assert_allclose(
            step.z, entry.bollinger_z(panel.adj_close)[t], rtol=1e-12, atol=1e-12
        )
        np.testing.assert_allclose(
            step.technical_score,
            ref.opinions["technical"].scores[t],
            rtol=1e-12,
            atol=1e-12,
        )
        np.testing.assert_allclose(
            step.value_score, ref.opinions["value"].scores[t], rtol=1e-12, atol=1e-12
        )
        assert step.gate == bool(np.isnan(ref.regime.rotation.scores[t]).all())
        stepped = {
            "technical": ref.opinions["technical"],
            "value": ref.opinions["value"],
            "rotation": ref.regime.rotation,
            "sentiment": ref.opinions["sentiment"],
        }
        for name, opinion in stepped.items():
            raw = stances_from_ranks(opinion.ranks(), opinions.STANCE_FRACTION)[t]
            np.testing.assert_array_equal(step.raw[name], raw)
            np.testing.assert_array_equal(step.held[name], ref.graded.stances[name][t])
        seen["week_end"] += int(f.week_end[t])
        seen["gate"] += int(step.gate)
        seen["grade_changed"] += int((step.grade != f.grades[t]).any())
    assert seen["week_end"] >= 2
    assert 1 <= seen["gate"] < 9
    assert seen["grade_changed"] >= 3


# The proxy row: the decision bar's close, the high and low through it with
# the day's open, on the panel's adjusted and split-adjusted bases by the
# session's scale; the volume through the volume slot times the ratio; a
# name with no bar carries t - 1's close with no volume. The 15:30
# decision reads slot 23 and volume through slot 22; 15:45 slot 24 and 23.
def test_intraday_row_scales_the_bar_and_carries_a_missing_one():
    w = _world()
    f = w.final
    assert (s5.AT_1530.slot, s5.AT_1530.volume_slot, s5.AT_1530.tone_cutoff) == (
        23,
        22,
        time(15, 30),
    )
    assert (s5.AT_1545.slot, s5.AT_1545.volume_slot) == (
        24,
        23,
    )
    assert s5.REGISTERED is s5.AT_1530
    bars = s5.bars(w.panel, w.cubes, s5.AT_1530)
    t = 301
    j = f.tickers.index("A01")
    cube = w.cubes["A01"]
    r = int(np.searchsorted(cube.dates, f.dates[t]))
    official = cube.auction_open[r]
    assert bars.close[t, j] == cube.close[r, 23]
    assert bars.high[t, j] == cube.high[r, :24].max()
    assert bars.low[t, j] == cube.low[r, :24].min()
    assert bars.volume[t, j] == pytest.approx(cube.volume[r, :23].sum(), rel=1e-12)
    row = s5.intraday_row(f, bars, t)
    assert row.have[j]
    assert row.adj[j] == pytest.approx(
        cube.close[r, 23] * f.adj[t, j] / official, rel=1e-12
    )
    assert row.close[j] == pytest.approx(
        cube.close[r, 23] * f.close[t, j] / official, rel=1e-12
    )
    assert row.high[j] == pytest.approx(
        max(cube.high[r, :24].max() * f.close[t, j] / official, f.open[t, j]), rel=1e-12
    )
    assert row.low[j] == pytest.approx(
        min(cube.low[r, :24].min() * f.close[t, j] / official, f.open[t, j]), rel=1e-12
    )
    assert row.dollar[j] == pytest.approx(
        math.log(bars.volume[t, j] * bars.ratio[t, j] * cube.close[r, 23]), rel=1e-12
    )
    # A dropped session: A03 has no bar on every other row from 280.
    k = f.tickers.index("A03")
    t = 282
    assert not bars.have[t, k]
    missing = s5.intraday_row(f, bars, t)
    assert missing.adj[k] == f.adj[t - 1, k]
    assert missing.close[k] == f.close[t - 1, k]
    assert missing.high[k] == missing.low[k] == f.close[t - 1, k]
    assert math.isnan(missing.dollar[k])
    # Early closes have no bar for anyone.
    early = np.flatnonzero(w.early)
    assert len(early)
    assert not bars.have[early].any()
    assert [str(d) for d in f.dates[early]] == [
        "2024-11-29",
        "2024-12-24",
        "2025-07-03",
        "2025-11-28",
        "2025-12-24",
    ]


# The volume ratio is the trailing-20 median (t excluded) of the day's raw
# shares (the store's dollar volume over the official close) over the
# volume through the decision time; a ratio that is not finite and
# positive is skipped.
def test_volume_ratio_is_the_trailing_median():
    rows = 30
    volume = np.full((rows, 1), 1000.0)
    close = np.full((rows, 1), 10.0)
    official = np.full((rows, 1), 5.0)  # a 2:1 split since: raw shares are double
    through = np.arange(1.0, rows + 1.0)[:, None] * 10.0
    through[25] = 0.0  # no volume: skipped
    out = s5.volume_ratio(volume, close, through, official)
    raw = 1000.0 * 10.0 / 5.0 / through[:, 0]
    assert np.isnan(out[:20]).all()
    assert out[20, 0] == pytest.approx(np.median(raw[0:20]))
    assert out[29, 0] == pytest.approx(np.median(np.delete(raw[9:29], 25 - 9)))


# The tone at a cutoff: a release accepted at or after the cutoff and
# before 16:00 on its reaction day reacts one calendar day later; one
# accepted before the cutoff, after the close, without a time or without a
# zone is left alone.
def test_tone_cutoff_moves_only_releases_after_the_cutoff():
    day = date(2025, 3, 4)
    at = {
        "a": datetime(2025, 3, 4, 15, 29, tzinfo=s5.calendar.NEW_YORK),
        "b": datetime(2025, 3, 4, 15, 30, tzinfo=s5.calendar.NEW_YORK),
        "c": datetime(2025, 3, 4, 15, 59, tzinfo=s5.calendar.NEW_YORK),
        "d": datetime(2025, 3, 4, 16, 0, tzinfo=s5.calendar.NEW_YORK),
        "e": datetime(2025, 3, 4, 15, 50),  # no zone
    }
    reaction = {
        "a": day,
        "b": day,
        "c": day,
        "d": day + timedelta(days=1),
        "e": day,
        "f": day,
    }
    records = {
        "X": tuple(
            language.ToneRecord(
                k, reaction[k], 1.0, 0.0, 0.0, 0.0, 0.0, "", "m", "p", False
            )
            for k in "abcdef"
        )
    }
    edgar = {
        "X": SimpleNamespace(
            events=tuple(
                SimpleNamespace(accession=k, accepted=v) for k, v in at.items()
            )
        )
    }
    acceptance = s5.acceptance_times(edgar)
    assert acceptance["X"]["b"] == at["b"]
    out, moved = s5.tone_cutoff(records, acceptance, time(15, 30))
    got = {r.accession: r.reaction_date for r in out["X"]}
    assert got == {
        "a": day,
        "b": day + timedelta(days=1),
        "c": day + timedelta(days=1),
        "d": day + timedelta(days=1),
        "e": day,
        "f": day,
    }
    assert [m["accession"] for m in moved] == ["b", "c"]
    _, later = s5.tone_cutoff(records, acceptance, time(15, 45))
    assert [m["accession"] for m in later] == ["c"]


# --- the control and the planner -------------------------------------------------


# The control is stage 4's executor under `/5`: the same run as
# `simulate.run` with `policy_v5.allocator` and the control's options, its
# orders the journal's; `/5` holds a name at up to 25% where `/4` stops at
# 20%. Replaying its planner with the null grid reproduces the journal's
# submitted units on every decision the grid steps, at every offset.
def test_control_runs_policy_v5_and_the_null_replay_reproduces_the_journal():
    w = _world()
    study = _study()
    run = study.runs[1]
    reference = simulate.run(
        w.restricted,
        since=s5._since(w.panel, 1),
        cost_bps=so.COST_BPS,
        allocator=policy_v5.allocator(w.mask),
        **profit_taking.control_options(w.panel),
    )
    assert run.returns.tobytes() == np.asarray(reference.returns, dtype=float).tobytes()
    assert [r.orders.start for r in study.runs] == [0, 1, 2]
    assert isinstance(run.journal, s5.Journal)
    assert run.journal.deferred_units
    # Fewer than five A/A+ names: /5 targets 25%, /4 20%.
    grades = w.restricted.graded.grades
    count = (grades >= s5.GRADE_A).sum(axis=1)
    few = np.flatnonzero((count >= 1) & (count < 5))
    assert len(few)
    t = int(few[0])
    v5 = policy_v5.allocator(w.mask)(w.restricted, w.panel, None, t)
    v4 = policy_v4.allocator(w.mask)(w.restricted, w.panel, None, t)
    assert v5.max() == pytest.approx(0.25)
    assert v4.max() == pytest.approx(0.20)
    for replay_ in study.replays:
        assert replay_.checked == T - 1 - PROXY_FROM - replay_.skipped["event"]
        assert replay_.mismatched == ()
        assert replay_.max_abs_diff == 0.0
    assert study.replays[1].skipped["event"] > 0
    result = s5.null_test(study.check, study.replays)
    assert result["passes"]
    assert len(result["journal"]) == 3
    broken = s5.null_test({**study.check, "passes": False}, study.replays)
    assert not broken["passes"]


# Each buy's leg is the planner's own order's: a reset decision's buys are
# resets; a mid-cycle buy is the retry, the band entry, the rotation or the
# redeploy that bought it, with that priority when there are several; the
# legs a replay finds cover all five.
def test_plan_decision_attributes_legs_by_priority():
    assert (
        s5.leg_of("deferred buy: the remainder cash could not pay for last session")
        == s5.RETRY
    )
    assert (
        s5.leg_of("price entry: breakout through its own 20-day band") == s5.BAND_ENTRY
    )
    assert s5.leg_of("redeploying a downgraded name") == s5.ROTATION
    assert (
        s5.leg_of("redeploy: cash beyond the buffer put back to its target weights")
        == s5.REDEPLOY
    )
    assert s5.leg_of("grade rotation") == s5.OTHER
    assert s5.pick_leg({s5.REDEPLOY, s5.RETRY, s5.ROTATION}) == s5.RETRY
    assert s5.pick_leg({s5.REDEPLOY, s5.BAND_ENTRY, s5.ROTATION}) == s5.BAND_ENTRY
    assert s5.pick_leg({s5.REDEPLOY, s5.ROTATION}) == s5.ROTATION
    assert s5.pick_leg({s5.REDEPLOY}) == s5.REDEPLOY
    assert s5.pick_leg(set()) == s5.OTHER
    study = _study()
    run = study.runs[1]
    found = set()
    for t, legs in study.replays[1].legs.items():
        kind = run.journal.kinds[t]
        if kind == "rebalance":
            assert set(legs.values()) <= {s5.RESET}
        found |= set(legs.values())
        before = run.journal.marks[t][1]
        bought = np.flatnonzero(run.journal.submitted[t] > before)
        assert set(legs) == {int(j) for j in bought}
    assert found >= set(s5.LEGS)


# --- the fills ------------------------------------------------------------------


# The candidate fills at t's official close times the session's scale -
# the adjusted close, across a split; the control at the board's
# dip_or_close in t + 1 (a buy at the first bar close 1% under the open, a
# sell at the first 1% over it, else the close); next_open at t + 1's first
# bar's open; all on the adjusted basis.
def test_fills_candidate_is_the_official_close_and_control_is_dip_or_close():
    rows = 8
    dates = np.datetime64("2025-03-03", "D") + np.arange(rows)
    raw = np.array(
        [100.0, 101.0, 102.0, 51.0, 52.0, 53.0, 54.0, 55.0]
    )  # 2:1 split at row 3
    split_adjusted = np.where(np.arange(rows) < 3, raw / 2.0, raw)
    adj = split_adjusted * 0.98
    closes = np.repeat(raw[:, None], FULL_SESSION_SLOTS, axis=1)
    opens = closes.copy()
    closes[4, 5] = raw[4] * 0.985  # a 1% dip in session 4 at bar 5
    closes[4, 9] = raw[4] * 1.02  # and a 1% pop later
    auction = raw.copy()
    auction[2] = np.nan  # no print: the last bar is the close
    cube = SessionCube(
        "X",
        dates,
        opens,
        closes * 1.001,
        closes * 0.999,
        closes,
        np.ones((rows, FULL_SESSION_SLOTS)),
        np.r_[np.nan, raw[:-1]],
        {},
        auction,
        np.ones(rows),
    )
    panel = SimpleNamespace(
        dates=dates,
        tickers=("X",),
        close=split_adjusted[:, None],
        adj_close=adj[:, None],
        high=split_adjusted[:, None] * 1.01,
        low=split_adjusted[:, None] * 0.99,
    )
    fills = s5.fill_grid(panel, {"X": cube})
    np.testing.assert_allclose(fills.candidate[:, 0], adj, rtol=1e-12)
    scale = adj / raw
    assert fills.control_buy[3, 0] == pytest.approx(
        raw[4] * 0.985 * scale[4], rel=1e-12
    )
    assert fills.control_sell[3, 0] == pytest.approx(
        raw[4] * 1.02 * scale[4], rel=1e-12
    )
    assert fills.control_buy[2, 0] == pytest.approx(
        adj[3], rel=1e-12
    )  # no dip: the close
    assert fills.next_open[3, 0] == pytest.approx(raw[4] * scale[4], rel=1e-12)
    assert np.isnan(fills.control_buy[rows - 1, 0])
    assert np.isnan(fills.next_open[rows - 1, 0])
    assert fills.coverage["names_with_cube"] == 1
    raw_fill, _ = fill_timing._dip_or_close_fill(cube, "buy")
    assert fills.control_buy[3, 0] == pytest.approx(raw_fill[4] * scale[4], rel=1e-12)


# --- matched, missed, extra --------------------------------------------------------


# A hand-fed run on three names over seven sessions:
#   t0 a reset: the 19:30 plan buys A 10 and B 5, B executes 4 (cash);
#      the 15:30 plan buys A 10, B 3 and C 4 (C is extra);
#   t1 a mid-cycle retry of A 2 the 15:30 plan does not make (missed);
#   t2 an FOMC restoration of B 1;
#   t3 a mid-cycle buy of C 3 on an early close;
#   t4 a mid-cycle buy of C 3 with no bar for C;
#   t5 a mid-cycle buy of B 2, matched, with no cube session in t + 1.
def _hand_fed():
    tickers = ("A", "B", "C", "SPY")
    rows = 7
    dates = np.datetime64("2025-03-03", "D") + np.arange(rows)
    price = (
        np.array([[10.0, 20.0, 5.0, 100.0]] * rows)
        * (1 + 0.01 * np.arange(rows))[:, None]
    )
    journal = s5.Journal()
    journal.assert_inputs(dates, tickers, price, price, 25.0)
    journal.open_account(0, 1000.0, np.zeros(4))
    holdings = [
        [0, 0, 0, 0],
        [10, 4, 0, 0],
        [12, 4, 0, 0],
        [12, 5, 0, 0],
        [12, 5, 3, 0],
        [12, 5, 6, 0],
        [12, 7, 6, 0],
    ]
    decisions = [
        (
            [10, 5, 0, 0],
            {
                "scheduled": True,
                "topup": False,
                "event_changed": False,
                "deferred_units": {"B": 1.0},
            },
        ),
        (
            [12, 4, 0, 0],
            {
                "scheduled": False,
                "topup": False,
                "event_changed": False,
                "deferred_units": {},
            },
        ),
        ([12, 5, 0, 0], {"event_scale": 1.0}),
        (
            [12, 5, 3, 0],
            {
                "scheduled": False,
                "topup": False,
                "event_changed": False,
                "deferred_units": {},
            },
        ),
        (
            [12, 5, 6, 0],
            {
                "scheduled": False,
                "topup": False,
                "event_changed": False,
                "deferred_units": {},
            },
        ),
        (
            [12, 7, 6, 0],
            {
                "scheduled": False,
                "topup": False,
                "event_changed": False,
                "deferred_units": {},
            },
        ),
    ]
    for t, (units, meta) in enumerate(decisions):
        journal.mark(t, 500.0, np.array(holdings[t], dtype=float), 1000.0, 0.0)
        journal.decision(t, np.array(units, dtype=float), None, "test", meta)
    journal.mark(rows - 1, 500.0, np.array(holdings[-1], dtype=float), 1000.0, 0.0)
    grades = np.full((rows, 4), 3)
    orders = so.extract_orders(journal, grades)
    run = so.ControlRun(None, orders, journal, np.zeros(rows))
    wanted_final = {t: np.array(u, dtype=float) for t, (u, _) in enumerate(decisions)}
    wanted_proxy = dict(wanted_final)
    wanted_proxy[0] = np.array([10, 3, 4, 0], dtype=float)
    wanted_proxy[1] = np.array([10, 4, 0, 0], dtype=float)
    legs = {
        0: {0: s5.RESET, 1: s5.RESET},
        1: {0: s5.RETRY},
        3: {2: s5.REDEPLOY},
        4: {2: s5.BAND_ENTRY},
        5: {1: s5.ROTATION},
    }
    sessions = (0, 1, 3, 4, 5)
    null = s5.Replay("null", sessions, wanted_final, legs, 5, (), 0.0, {})
    proxy_legs = {0: {0: s5.RESET, 1: s5.RESET, 2: s5.RESET}}
    proxy = s5.Replay("15:30", (0, 1, 4, 5), wanted_proxy, proxy_legs, 0, (), 0.0, {})
    have = np.ones((rows, 4), dtype=bool)
    have[4, 2] = False
    blank = np.zeros((rows, 4))
    grid_grade = np.full((rows, 4), 3)
    grid_grade[0, 2] = 2
    final_grade = grid_grade.copy()
    final_grade[0, 2] = 1  # C is B at 19:30, A at 15:30 on t0
    kwargs = dict(
        start=0,
        stop=6,
        computed=np.ones(rows, dtype=bool),
        adj=price,
        have=have,
        blocked=np.zeros((rows, 4), dtype=bool),
        z=blank,
        gate=np.zeros(rows, dtype=bool),
        raw={},
        held={},
        technical_score=blank,
        value_score=blank,
        ai_trend=np.zeros(rows),
    )
    proxy_grid = s5.Grid(mode="15:30", grade=grid_grade, **kwargs)
    final_grid = s5.Grid(mode="null", grade=final_grade, **kwargs)
    candidate = price.copy()
    control_buy = price * 1.01  # the next session's fill is 1% dearer
    control_sell = price * 1.02
    control_buy[5] = np.nan  # no cube session in t + 1 of t5
    next_open = price * 1.005
    fills = s5.Fills(candidate, control_buy, control_sell, next_open, {})
    early = np.zeros(rows, dtype=bool)
    early[3] = True
    restricted = SimpleNamespace(
        panel=SimpleNamespace(adj_close=price, tickers=tickers)
    )
    mask = np.ones((rows, 4), dtype=bool)
    return SimpleNamespace(
        run=run,
        null=null,
        proxy=proxy,
        proxy_grid=proxy_grid,
        final_grid=final_grid,
        fills=fills,
        early=early,
        restricted=restricted,
        mask=mask,
        price=price,
        dates=dates,
    )


# The hand-fed run's comparison: the statuses (eligible, FOMC restoration,
# early close, no bar), the matched shares in executed units (B at t0:
# min(5, 3) of 5 submitted times 4 executed is 2.4 of 4), the gains
# (matched share times ln(control / candidate)), a missed buy at zero, an
# unpriced buy NaN, and C's extra round trip at t0 (the decision's own
# execution ratio, bought at t's close, sold at the board's sell rule,
# 25 bp each way).
def test_account_matched_missed_extra_and_eligibility():
    h = _hand_fed()
    acc = s5.account(
        h.run,
        h.restricted,
        h.mask,
        h.proxy_grid,
        h.proxy,
        h.null,
        h.final_grid,
        h.fills,
        h.early,
    )
    got = list(
        zip(
            acc.session.tolist(),
            acc.ticker.tolist(),
            acc.status.tolist(),
            acc.leg.tolist(),
            strict=True,
        )
    )
    assert got == [
        (0, "A", s5.ELIGIBLE, s5.RESET),
        (0, "B", s5.ELIGIBLE, s5.RESET),
        (1, "A", s5.ELIGIBLE, s5.RETRY),
        (2, "B", s5.NOT_EVENT, s5.FOMC),
        (3, "C", s5.NOT_EARLY, s5.REDEPLOY),
        (4, "C", s5.NOT_BAR, s5.BAND_ENTRY),
        (5, "B", s5.ELIGIBLE, s5.ROTATION),
    ]
    np.testing.assert_allclose(acc.matched, [1.0, 0.6, 0.0, 0.0, 0.0, 0.0, 1.0])
    step = 1e4 * math.log(1.01)
    np.testing.assert_allclose(acc.g[:3], [step, 0.6 * step, 0.0])
    assert acc.g[3] == acc.g[4] == acc.g[5] == 0.0
    assert math.isnan(acc.g[6])
    assert acc.gain_next_open[0] == pytest.approx(1e4 * math.log(1.005))
    assert acc.cause[1] == "other"
    assert acc.cause[2] == "other"
    assert acc.cause[0] == ""
    # C's extra: 4 units at the decision's execution ratio (A 10 of 10, B 4
    # of 5, by notional), bought at 5.00 and sold at 5.10.
    ratio = (10 * 10.0 + 4 * 20.0) / (10 * 10.0 + 5 * 20.0)
    assert acc.extra_session.tolist() == [0]
    assert acc.extra_ticker.tolist() == ["C"]
    assert acc.extra_weight[0] == pytest.approx(4 * ratio * 5.0 / 1000.0)
    assert acc.extra_gross[0] == pytest.approx(1e4 * math.log(1.02))
    assert acc.extra_pnl[0] == pytest.approx(1e4 * math.log(1.02) - 50.0)
    assert acc.extra_leg[0] == s5.RESET
    assert acc.extra_cause[0] == "grade"
    assert math.isnan(s5.round_trip_bp(np.array([5.0]), np.array([np.nan]))[0])


# A window's reading of the hand-fed run: the control's buys by status, the
# eligible buys' per-buy g (missed at zero, the unpriced one out) with its
# clustered t, the session series with the extra round trip in it, the
# drift-adjusted reading and the legs; and the registered windows.
def test_summaries_windows_and_session_series():
    assert {
        s5.DECIDING: (date(2016, 1, 4), date(2017, 12, 27)),
        s5.REPLICATION_A: (date(2018, 1, 1), date(2024, 1, 1)),
        s5.REPLICATION_B: (date(2024, 1, 1), None),
    } == s5.WINDOWS
    assert date(2016, 1, 4) == s5.PROXY_START
    assert s5.EXTRA_COST_BPS == 25.0
    days = np.array(
        ["2015-12-31", "2016-01-04", "2017-12-26", "2017-12-27", "2018-01-02"],
        dtype="datetime64[D]",
    )
    assert s5.point_in_time.window(days, *s5.WINDOWS[s5.DECIDING]).tolist() == [
        False,
        True,
        True,
        False,
        False,
    ]
    assert s5.proxy_span(np.datetime64("2015-01-02", "D") + np.arange(600))[0] == 367
    h = _hand_fed()
    acc = s5.account(
        h.run,
        h.restricted,
        h.mask,
        h.proxy_grid,
        h.proxy,
        h.null,
        h.final_grid,
        h.fills,
        h.early,
    )
    s = s5.summarize(acc, h.dates, None, None, mu_bp=10.0)
    assert s["control_buys"] == 7
    assert s["status"] == {
        s5.ELIGIBLE: 4,
        s5.NOT_EVENT: 1,
        s5.NOT_EARLY: 1,
        s5.NOT_BAR: 1,
        s5.NOT_PROXY: 0,
    }
    e = s["eligible"]
    assert (e["buys"], e["matched"], e["partial"], e["missed"], e["unpriced"]) == (
        4,
        2,
        1,
        1,
        1,
    )
    step = 1e4 * math.log(1.01)
    g = np.array([step, 0.6 * step, 0.0])
    assert s["per_buy"]["buys"] == 3
    assert s["per_buy"]["mean_bp"] == pytest.approx(g.mean())
    assert s["per_buy"]["t"] == pytest.approx(
        fill_timing.clustered_t(g, np.array([0, 0, 1]))
    )
    series = s5.book_series(acc, acc.g, acc.extra_pnl)
    w = acc.weight
    expected0 = w[0] * step + w[1] * 0.6 * step + acc.extra_weight[0] * acc.extra_pnl[0]
    assert series[0] == pytest.approx(expected0)
    assert series[1] == 0.0
    assert series[5] == 0.0
    assert s["session"]["mean_bp"] == pytest.approx(series.mean())
    drift = s5.summarize(acc, h.dates, None, None, mu_bp=10.0)["per_buy_drift"]
    assert drift["mean_bp"] == pytest.approx(
        (g - 10.0 * np.array([1.0, 0.6, 0.0])).mean()
    )
    assert s["extras"]["count"] == 1
    assert s["extras"]["pnl_bp"] == pytest.approx(acc.extra_pnl[0])
    assert s["by_leg"][s5.RESET]["buys"] == 2
    assert s["by_leg"][s5.RETRY]["mean_bp"] == 0.0
    # No drift in the window: the drift-adjusted reading is missing, not the
    # missed buys' zeros alone.
    blind = s5.summarize(acc, h.dates, None, None, mu_bp=math.nan)
    assert blind["per_buy_drift"]["buys"] == 0
    assert math.isnan(blind["session_drift"]["mean_bp"])
    assert blind["per_buy"]["buys"] == 3
    later = s5.summarize(acc, h.dates, date(2025, 3, 5), None, mu_bp=0.0)
    assert later["control_buys"] == 4
    assert later["per_buy"]["buys"] == 0


# --- the verdict ----------------------------------------------------------------------


# A payload holding just what the criteria read.
def _payload(d_mean=20.0, d_t=2.5, d_session=0.5, a=5.0, b=5.0, open_=3.0, null=True):

    # One window's readings: the per-buy mean and t, the session mean and
    # the next_open per-buy mean, the rest fixed.
    def window(m, t, s, o):
        return {
            "per_buy": {"mean_bp": m, "t": t, "buys": 400},
            "session": {"mean_bp": s, "hac_t": 1.0},
            "per_buy_next_open": {"mean_bp": o, "t": 1.0, "buys": 400},
            "session_next_open": {"mean_bp": 0.1, "hac_t": 0.5},
            "per_buy_drift": {"mean_bp": 1.0, "t": 0.1, "buys": 400},
            "session_drift": {"mean_bp": 0.1, "hac_t": 0.1},
            "eligible": {"buys": 400, "matched": 380, "partial": 10, "missed": 10},
            "control_buys": 423,
            "extras": {"count": 5, "pnl_bp": -40.0},
            "by_leg": {leg: {"mean_bp": 1.0, "buys": 80} for leg in s5.LEGS},
        }

    return {
        "results": {
            s5.REGISTERED.label: {
                s5.DECIDING: window(d_mean, d_t, d_session, open_),
                s5.REPLICATION_A: window(a, 1.0, 0.1, 1.0),
                s5.REPLICATION_B: window(b, 1.0, 0.1, 1.0),
            }
        },
        "null_test": {
            "passes": null,
            "report": {"mismatches": {}, "sessions": 10},
            "journal": [],
        },
        "windows": {s5.DECIDING: ["2016-01-04", "2017-12-27"]},
        "offsets": {"smoke": False},
    }


# Criteria 1-4 at their edges: the deciding window's per-buy mean above
# zero at a clustered t of at least 2.0 and a session mean above zero; both
# replication windows above zero; the next_open control above zero; the
# null test. All four: PASS; anything else: RECORD. A missing number fails.
def test_criteria_edges_and_verdict():
    assert s5.verdict(_payload())["label"] == s5.PASS
    assert s5.verdict(_payload(d_t=2.0))["label"] == s5.PASS
    for bad in (
        {"d_t": 1.999},
        {"d_mean": 0.0},
        {"d_session": 0.0},
        {"d_session": -0.1},
        {"a": 0.0},
        {"b": -1.0},
        {"open_": 0.0},
        {"null": False},
        {"d_t": None},
        {"d_mean": math.nan},
    ):
        v = s5.verdict(_payload(**bad))
        assert v["label"] == s5.RECORD, bad
        assert not all(v["criteria"].values())
    v = s5.verdict(_payload(a=-1.0))
    assert v["criteria"] == {
        "1_deciding_per_buy_and_session": True,
        "2_replication_per_buy": False,
        "3_deciding_next_open": True,
        "4_null_test": True,
    }
    assert v["text"].startswith("RECORD")
    assert "2_replication_per_buy" in v["text"]
    smoke = _payload()
    smoke["offsets"] = {"smoke": True, "priced": 2, "registered": 20}
    assert s5.verdict(smoke)["text"].startswith("SMOKE RUN (2 of 20 offsets)")
    assert s5.TRIALS["cumulative"] == 452
    assert s5.CRITERION_T == 2.0


# --- the walk and the whole test ------------------------------------------------------


# The ledger walk without the buys at the close is the `/5` control run to
# the bit; with them it buys at t's close and its returns differ.
def test_walk_without_the_close_buys_is_the_control_run():
    w = _world()
    study = _study()
    run = study.runs[1]
    grid = study.grids[s5.REGISTERED.label]
    control = s5.walk(w.restricted, w.mask, run.since, grid, w.early, moc=False)
    assert control.returns.tobytes() == run.returns.tobytes()
    assert control.fills == 0
    candidate = s5.walk(w.restricted, w.mask, run.since, grid, w.early, moc=True)
    assert candidate.fills > 50
    assert candidate.notional > 0
    assert not np.array_equal(candidate.returns, control.returns, equal_nan=True)
    assert np.array_equal(
        candidate.returns[: PROXY_FROM - 1],
        control.returns[: PROXY_FROM - 1],
        equal_nan=True,
    )
    reading = s5.walk_reading(
        control, candidate, run.returns, w.final.dates, {"all": (None, None)}
    )
    assert reading["control_is_the_simulator"]
    assert reading["windows"]["all"]["sessions"] > 400


# The whole test on the synthetic book: per offset the 15:30 replay and
# account, at the median offset every reading (the 15:45 variant, the
# legs, next_open, the drift, the walk), the rows and the verdict; the
# payload is strict JSON. FOMC restorations, early closes and names with
# no bar all fill as the control.
def test_evaluate_end_to_end():
    w = _world()
    study = _study()
    spans = {
        s5.DECIDING: (date(2025, 10, 31), date(2026, 3, 1)),
        s5.REPLICATION_A: (date(2026, 3, 1), date(2026, 6, 1)),
        s5.REPLICATION_B: (date(2026, 6, 1), None),
    }
    result = s5.null_test(study.check, study.replays)
    context = s5.Context(
        restricted=w.restricted,
        mask=w.mask,
        final_grid=study.null,
        fills=study.fills,
        early=w.early,
        given=(w.final.blocked, w.final.z),
    )
    payload = s5.evaluate(
        study.runs,
        study.replays,
        result,
        study.grids,
        context,
        registered=20,
        spans=spans,
    )
    json.dumps(sio.clean_json(payload), allow_nan=False)
    assert payload["offsets"] == {
        "registered": 20,
        "priced": 3,
        "median": 1,
        "smoke": True,
        "starts": [0, 1, 2],
    }
    main = payload["results"][s5.REGISTERED.label]
    assert set(payload["results"]) == {"15:30", "15:45"}
    rows = payload["rows"]["buys"]
    statuses = {r["status"] for r in rows}
    assert statuses >= {s5.ELIGIBLE, s5.NOT_EVENT, s5.NOT_PROXY, s5.NOT_BAR}
    for r in rows:
        if r["status"] != s5.ELIGIBLE:
            assert r["g_bp"] == 0.0
            assert r["matched"] == 0.0
        if r["status"] == s5.NOT_EVENT:
            assert r["leg"] == s5.FOMC
            assert r["kind"] == "event"
        if np.datetime64(r["date"]) in w.final.dates[w.early]:
            assert r["status"] == s5.NOT_EARLY
        if r["status"] == s5.NOT_BAR:
            assert r["ticker"] in DROPPED
    total = sum(main[s]["eligible"]["buys"] for s in spans)
    assert total == sum(r["status"] == s5.ELIGIBLE for r in rows)
    for s in spans:
        assert main[s]["per_buy"]["buys"] <= main[s]["eligible"]["buys"]
        assert set(main[s]["by_leg"]) == set(s5.LEGS)
    assert len(payload["per_offset"][s5.DECIDING]["per_buy_bp"]) == 3
    assert payload["walk"]["control_is_the_simulator"]
    assert payload["verdict"]["label"] in (s5.PASS, s5.RECORD)
    assert payload["verdict"]["text"].startswith("SMOKE RUN (3 of 20 offsets)")
    assert len(payload["verdict"]["lines"]) >= 9


# --- the command ------------------------------------------------------------------


# A loader that hands the command the synthetic book instead of the store.
def _loader(tone=None):
    w = _world()

    # Return the synthetic inputs; `full` False leaves out the cubes, as
    # the real loader does for the null test.
    def load(store, workers, log, full=True):
        log("stub loader")
        return cli.Loaded(
            report=w.report,
            cubes=w.cubes if full else {},
            edgar=w.edgar if full else {},
            tone=w.tone if tone is None else tone,
            levels=w.levels,
            strict_levels=w.strict if full else {},
        )

    return load


# The command's null test alone: no cube is read and no fill computed; the
# payload records the inputs' sha256 and the revision; the text says the
# test passes. A tone the report did not read fails it (exit 3, RECORD).
# The whole run (a smoke run over two of three offsets) writes the priced
# payload and prints the verdict.
def test_cli_null_test_only_and_full_run_with_a_stub_loader(tmp_path):
    w = _world()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(w.members),
            "--null-test-only",
            "--offsets",
            "2",
            "--out",
            str(tmp_path / "null.json"),
        ]
    )
    out = io.StringIO()
    assert cli.run(args, out=out, loader=_loader()) == cli.DONE
    null = json.loads((tmp_path / "null.json").read_text())
    assert null["priced"] is False
    assert "results" not in null
    assert null["null_test"]["passes"]
    assert null["run"]["inputs"]["membership"]["sha256"]
    assert null["run"]["inputs"]["cubes"] is None
    assert "revision" in null["run"]
    assert len(null["null_test"]["journal"]) == 2
    assert "PASSES" in out.getvalue()
    wrong = {k: v[:-1] for k, v in w.tone.items()}
    out = io.StringIO()
    code = cli.run(args, out=out, loader=_loader(wrong))
    assert code == cli.NULL_FAILED
    assert "FAILS" in out.getvalue()
    assert "RECORD" in out.getvalue()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(w.members),
            "--offsets",
            "3",
            "--max-offsets",
            "2",
            "--out",
            str(tmp_path / "full.json"),
        ]
    )
    out = io.StringIO()
    assert cli.run(args, out=out, loader=_loader()) == cli.DONE
    full = json.loads((tmp_path / "full.json").read_text())
    assert full["priced"]
    assert full["offsets"]["priced"] == 2
    assert full["offsets"]["smoke"]
    assert full["run"]["inputs"]["cubes"]
    assert full["run"]["inputs"]["strict_levels"]
    assert full["grids"]["15:30"]["tone_moved"]
    assert full["verdict"]["label"] in (
        s5.PASS,
        s5.RECORD,
    )
    assert "SMOKE RUN (2 of 3 offsets)" in out.getvalue()


# The command refuses a missing membership file (exit 1) and a count of
# offsets below one (exit 2) before loading anything.
def test_cli_refuses_bad_arguments(tmp_path):
    parser = cli.build_parser()
    out = io.StringIO()
    args = parser.parse_args(
        ["--membership", str(tmp_path / "missing.csv"), "--null-test-only"]
    )
    assert cli.run(args, out=out, loader=None) == cli.MISSING
    w = _world()
    args = parser.parse_args(["--membership", str(w.members), "--offsets", "0"])
    assert cli.run(args, out=io.StringIO(), loader=None) == cli.REFUSED
    args = parser.parse_args(["--membership", str(w.members), "--max-offsets", "0"])
    assert cli.run(args, out=io.StringIO(), loader=None) == cli.REFUSED
