"""A5 tone expiry end to end on a synthetic desk, from the IC pairing to the check.

`tone_expiry_study` measures what an arm did on the point-in-time
scorecard run (the sentiment analyst's IC paired on the incumbent's
rebalance dates, the affected cells, the counts, the grades, the board's
words) and judges the control and both arms on the plan's
non-inferiority criteria. The synthetic desk here is built the way
`desk.run` builds one - the tone block through the desk loader's two steps
(`language.stored_records`, `tone_expiry.on_load`), every opinion through
`desk.assemble` - over 24 names, three of which stop reporting and one of
which has too short a history for its own gap.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from backend.agents.trading.desk import desk, regime, sentiment
from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_pit_scorecard as sc
from backend.cli import market_tone_expiry as cli
from backend.market import benchmarks, language
from backend.market import tone_expiry as te
from backend.market import tone_expiry_study as tes
from backend.market.harness import evaluate_scores
from backend.market.panel import Panel

NAMES = tuple(f"N{k:02d}" for k in range(24))
T = 420
CHECK = (
    Path(__file__).resolve().parents[2]
    / "docs/research/scorecards/tone-expiry/tone_expiry_check.py"
)


# Business days from 2023-01-02, T of them (to mid-2024: both windows).
def _days() -> list[date]:
    days, d = [], date(2023, 1, 2)
    while len(days) < T:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


# The synthetic panel: 24 names and SPY on a random walk.
def _panel(seed: int = 7) -> Panel:
    rng = np.random.default_rng(seed)
    names = NAMES + ("SPY",)
    shape = (T, len(names))
    close = 100.0 * np.exp(rng.normal(0.0004, 0.02, size=shape).cumsum(axis=0))
    return Panel(
        dates=np.array(_days(), dtype="datetime64[D]"),
        tickers=names,
        open=close * (1 + rng.normal(0, 0.002, size=shape)),
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=np.full(shape, 1e6),
        themes={t: ("ai",) for t in NAMES},
        benchmark="SPY",
    )


# Every name reports every 91 days from early 2022; N00-N02 stop after six
# releases (overdue from mid-2023), N03 has two (its gap is the book's and it
# is overdue throughout), the rest report past the panel's end.
def _records(seed: int = 11) -> dict[str, list[language.ToneRecord]]:
    rng = np.random.default_rng(seed)
    out = {}
    for k, name in enumerate(NAMES):
        count = 6 if k < 3 else 2 if k == 3 else 12
        start = date(2022, 1, 10) + timedelta(days=4 * k)
        rows = []
        for i in range(count):
            day = start + timedelta(days=91 * i)
            rows.append(
                language.ToneRecord(
                    accession=f"{name}-{day}",
                    reaction_date=day,
                    guidance=float(rng.choice([-1, 0, 1])),
                    demand=float(rng.choice([-1, 0, 1])),
                    pricing=float(rng.choice([-1, 0, 1])),
                    capex=0.0,
                    supply_constrained=0.0,
                    summary="A results release.",
                    model="deepseek-v4-flash",
                    prompt_version="release_tone/3",
                    truncated=False,
                )
            )
        # The stopped names leave on a bullish release, so the stale reading
        # has a vote to lose.
        if k < 3:
            rows[-1] = replace(rows[-1], guidance=1.0, demand=1.0, pricing=1.0)
        out[name] = rows
    return out


# The store the scorecard opens, stubbed: the tone frames as the tone
# layer writes them, and nothing else.
class _Store:
    records: dict = {}

    # Accept the root the scorecard passes.
    def __init__(self, root=None):
        self.root = root

    # The newest tone frame of a ticker, or None.
    def read_frame(self, kind, ticker, asof=None):
        rows = self.records.get(ticker)
        if kind != language.TONE_KIND or not rows:
            return None
        return language.tone_frame(rows), {}


# The other analysts' opinions: steady random rankings with a little noise.
def _opinions(panel: Panel, seed: int = 5) -> dict[str, Opinion]:
    rng = np.random.default_rng(seed)
    n = len(panel.tickers)
    out = {}
    for name in ("fundamental", "technical", "value"):
        base = rng.normal(size=n)
        scores = base[None, :] + 0.2 * rng.normal(size=(T, n))
        scores[:, panel.index("SPY")] = np.nan
        out[name] = Opinion(name, scores)
    return out


# The synthetic desk, built as `desk.run` builds one: the tone block through
# the loader's two steps (so the flag applies), every opinion assembled.
def _desk(panel: Panel, others: dict[str, Opinion]):
    state = regime.RegimeState(
        0.0, 0.0, 0.5, 0.0, 0.0, 0.0, "ai", 0.1, 0.0, 1.0, 1.0, (), 0.0, False
    )
    view = regime.RegimeView(
        [state] * T, Opinion("rotation", np.full((T, len(panel.tickers)), np.nan))
    )
    sides = {t: "ai" for t in NAMES}

    # Run the desk on the stub store.
    def run(store, asof=None, **kwargs):
        records = language.stored_records(store, panel.tickers, asof)
        tone = te.on_load(language.tone_features(panel, records), panel, records)
        opinions = {**others, "sentiment": sentiment.opine(tone)}
        return desk.assemble(panel, sides, opinions, view, ())

    return run


# Every name a book member throughout.
def _membership(path: Path) -> Path:
    rows = ["ticker,entered,entry_announced,exited,exit_announced,source,rule"]
    rows += [f"{t},2016-01-04,2016-01-04,,,test,member throughout" for t in NAMES]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# The whole study on the synthetic desk: both null tests, the control and
# the two arms through the scorecard, the verdict command, the check.
@pytest.fixture(scope="module")
def study(tmp_path_factory):
    root = tmp_path_factory.mktemp("tone_expiry")
    panel = _panel()
    records = _records()
    others = _opinions(panel)
    run = _desk(panel, others)
    history = _membership(root / "membership.csv")
    out = {"root": root, "panel": panel, "records": records, "run": run}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(_Store, "records", records)
        mp.setattr("backend.market.store.MarketStore", _Store)
        mp.setattr(desk, "run", run)
        mp.setattr(
            benchmarks,
            "load_benchmark",
            lambda store, symbol, sessions, **kwargs: benchmarks.BenchmarkSeries(
                symbol,
                True,
                np.zeros(len(sessions)),
                np.ones(len(sessions)),
                np.asarray(sessions),
            ),
        )
        common = [
            "--root",
            str(root),
            "--graded-cap",
            "0.25",
            "--costs",
            "10",
            "25",
            "--membership",
            str(history),
            "--offsets",
            "3",
        ]
        out["null"] = {
            mode: sc.main([*common, "--tone-expiry", mode, "--null-test"])
            for mode in te.MODES
        }
        out["flags_after_null"] = (te.TONE_EXPIRY, te.TONE_EXPIRY_NULL)
        paths = {}
        for name, extra in (
            ("control", []),
            ("hard", ["--tone-expiry", "hard"]),
            ("decay", ["--tone-expiry", "decay"]),
        ):
            paths[name] = root / f"{name}.json"
            code = sc.main(
                [
                    *common,
                    "--rank-ic",
                    "--sentiment-ic",
                    *extra,
                    "--output",
                    str(paths[name]),
                ]
            )
            assert code == 0
        out["flags_after_runs"] = (te.TONE_EXPIRY, te.TONE_EXPIRY_NULL)
        out["paths"] = paths
        out["payloads"] = {
            k: json.loads(p.read_text(encoding="utf-8")) for k, p in paths.items()
        }
        verdict_path = root / "tone_expiry_verdict.json"
        out["verdict_code"] = cli.main(
            [
                "--control",
                str(paths["control"]),
                "--hard",
                str(paths["hard"]),
                "--decay",
                str(paths["decay"]),
                "--out",
                str(verdict_path),
            ]
        )
        out["verdict_path"] = verdict_path
        out["history"] = history
    return out


# The arm is measured on the incumbent's grid: at the harness's own dates
# the incumbent's ICs are the harness's to the bit, and an arm identical to
# the incumbent pairs to a zero difference with t = 0 on every window.
def test_the_arm_is_measured_on_the_incumbents_grid(study):
    panel, records = study["panel"], study["records"]
    plain = sentiment.opine(language.tone_features(panel, records)).scores
    for horizon in tes.HORIZONS:
        rows, report = tes.grid(plain, panel, horizon)
        assert len(rows) == report.count > 2
        mine = tes.ics_at(plain, panel, horizon, rows)
        assert np.array_equal(mine, [p.rank_ic for p in report.periods], equal_nan=True)
        harness = evaluate_scores(plain, panel, horizon)
        assert harness.count == report.count
    unchanged = np.zeros(plain.shape, dtype=bool)
    block = tes.sentiment_ic(plain, plain.copy(), unchanged, panel, sc.WINDOWS)
    for horizon in ("h20", "h60"):
        for window in ("2016-2023", "2024-2026"):
            paired = block[horizon]["windows"][window]["paired"]
            assert paired["n"] >= 1
            assert paired["mean"] == 0.0
            assert paired["t"] == 0.0
            assert block[horizon]["windows"][window]["affected"]["dates"] == 0
        assert block[horizon]["affected_cells"] == []


# The paired t: the plain t over finite differences; all zero is t = 0, a
# constant non-zero difference is infinite with its sign, one entry has no t.
def test_paired_t_conventions():
    assert tes.paired_t([0.0, 0.0, 0.0]) == {"n": 3, "mean": 0.0, "t": 0.0}
    assert tes.paired_t([0.1, 0.1])["t"] == float("inf")
    assert tes.paired_t([-0.1, -0.1, np.nan])["t"] == float("-inf")
    got = tes.paired_t([0.1, 0.3, -0.1])
    assert got["n"] == 3
    assert got["mean"] == pytest.approx(0.1)
    assert got["t"] == pytest.approx(0.1 / (0.2 / np.sqrt(3)))
    assert np.isnan(tes.paired_t([0.2])["t"])
    assert tes.paired_t([])["n"] == 0


# The affected cells' IC, by hand on one date: q and p are centred
# percentiles in each side's own cross-section; a name the arm has no view
# of sits at p = 0; each side's IC on the cells is 12 x mean(p x q).
def test_the_affected_cells_ic_by_hand(study):
    panel = study["panel"]
    residual = panel.forward_residual(20)
    rng = np.random.default_rng(1)
    plain = rng.normal(size=residual.shape)
    plain[:, panel.index("SPY")] = np.nan
    arm = plain.copy()
    arm[:, 0] = np.nan  # N00 expired: no view
    arm[:, 1] = plain[:, 1] * 0.1  # N01 decayed toward the middle
    changed = np.zeros(plain.shape, dtype=bool)
    changed[:, :2] = True
    t = 40
    dates, cells = tes.affected_at(plain, arm, changed, panel, 20, [t])
    ok = np.isfinite(residual[t])
    ok[panel.index("SPY")] = False
    names = np.flatnonzero(ok)

    # Centred percentile of `values` among the `names`.
    def centred(values, among):
        order = values[among].argsort().argsort().astype(float)
        out = np.zeros(len(values))
        out[among] = order / (len(among) - 1) - 0.5
        return out

    q = centred(residual[t], names)
    p0 = centred(plain[t], names)
    p1 = centred(arm[t], names[names != 0])
    s0 = 12 * np.mean([p0[0] * q[0], p0[1] * q[1]])
    s1 = 12 * np.mean([0.0 * q[0], p1[1] * q[1]])
    assert len(dates) == 1
    assert dates[0]["cells"] == 2
    assert dates[0]["incumbent"] == pytest.approx(s0)
    assert dates[0]["arm"] == pytest.approx(s1)
    assert dates[0]["difference"] == pytest.approx(s1 - s0)
    assert [c["ticker"] for c in cells] == ["N00", "N01"]
    assert cells[0]["p_arm"] == 0.0


# The scorecard: both null tests pass to the bit and say how many readings
# the real arm would change (so they are not vacuous), the flags are put
# back, and the real arm's book is not the incumbent's.
def test_the_null_tests_pass_and_are_not_vacuous(study, monkeypatch):
    assert study["null"] == {"hard": 0, "decay": 0}
    assert study["flags_after_null"] == (None, False)
    assert study["flags_after_runs"] == (None, False)
    panel, run = study["panel"], study["run"]
    monkeypatch.setattr(_Store, "records", study["records"])
    plain = run(_Store())
    with sc._expiry_flags(te.HARD):
        hard = run(_Store())
    assert te.TONE_EXPIRY is None
    assert not np.array_equal(plain.graded.grades, hard.graded.grades)
    plain_tone, found, weight = sc._expiry_inputs(plain, _Store(), te.HARD)
    assert tes.changed_cells(plain_tone, weight).sum() > 100
    with pytest.raises(SystemExit):
        sc.main(["--root", str(study["root"]), "--null-test"])
    assert panel.tickers[-1] == "SPY"


# The arm payloads carry the plan's block: the rule built the report, the
# counts per year add up per window, the stopped names are the 2026-style
# list (here from 2024), the grades moved, the IC pairs, the incumbent desk
# is the control's, and the board's words are the plan's phrasing.
def test_the_arm_payloads_carry_the_plans_block(study):
    control = study["payloads"]["control"]
    assert control["arm"] == "ew_graded_cap25"
    assert set(control["sentiment_ic"]) == {"h20", "h60"}
    assert "desk_fingerprint" in control
    assert "tone_expiry" not in control
    for name, mode in (("hard", te.HARD), ("decay", te.DECAY)):
        payload = study["payloads"][name]
        assert payload["arm"] == f"ew_graded_cap25 + tone_expiry_{mode}"
        block = payload["tone_expiry"]
        assert block["mode"] == mode
        assert block["report_matches_rule"] is True
        assert block["incumbent_fingerprint"] == control["desk_fingerprint"]
        assert block["rule"]["horizon"] == 1.5
        windows = block["affected"]["windows"]
        assert windows["2016-2023"]["book"]["cells"] > 0
        assert windows["2024-2026"]["book"]["cells"] > 0
        assert windows["all"]["panel"]["names"] >= 4
        years = block["affected"]["years"]
        assert (
            sum(v["panel"]["cells"] for v in years.values())
            == windows["all"]["panel"]["cells"]
        )
        assert block["grades"]["all"]["changed_cells"] > 0
        for horizon in ("h20", "h60"):
            ic = block["sentiment_ic"][horizon]
            assert (
                ic["periods"]["incumbent"]
                == control["sentiment_ic"][horizon]["periods"]["ic"]
            )
            assert len(ic["periods"]["arm"]) == len(ic["periods"]["dates"])
        assert block["sentiment_ic"]["h20"]["affected_cells"]
        stopped = {e["ticker"] for e in block["affected_2026"]}
        assert stopped == set()  # the synthetic panel ends in 2024
        for entry in block["board_words"]:
            assert "Sentiment" in entry["words"]
            assert set(entry["words"].lower().split()).isdisjoint(te.ADVICE)
    hard_words = {
        e["ticker"]: e["words"]
        for e in study["payloads"]["hard"]["tone_expiry"]["board_words"]
    }
    assert set(hard_words) == {"N00", "N01", "N02", "N03"}
    assert "no current earnings reading (last release read 2023-" in hard_words["N00"]
    assert "usually every 91 days)" in hard_words["N00"]
    assert hard_words["N03"].endswith("across the book)")


# The 2026 list on a panel that reaches 2026: every (name, reading) changed
# from the first of the year, with its dates, gap and largest age ratio.
def test_affected_names_list_the_recent_readings():
    days = [date(2025, 10, 1) + timedelta(days=k) for k in range(150)]
    panel = Panel(
        dates=np.array(days, dtype="datetime64[D]"),
        tickers=("OKLO", "SPY"),
        open=np.ones((150, 2)),
        high=np.ones((150, 2)),
        low=np.ones((150, 2)),
        close=np.ones((150, 2)),
        adj_close=np.ones((150, 2)),
        volume=np.ones((150, 2)),
        themes={},
        benchmark="SPY",
    )
    history = {"OKLO": [date(2024, 6, 1), date(2024, 9, 1), date(2025, 3, 25)]}
    found = te.ages(panel.dates, panel.tickers, history, "SPY")
    weight = te.weights(found, te.HARD)
    tone = np.zeros((150, 2, language.FEATURE_COUNT), dtype=np.float32)
    tone[:, 0, te.HAS_TONE] = 1.0
    changed = tes.changed_cells(tone, weight)
    names = tes.affected_names(changed, found, weight, panel)
    assert len(names) == 1
    entry = names[0]
    assert entry["ticker"] == "OKLO"
    assert entry["last_read"] == "2025-03-25"
    assert entry["first"] == "2026-01-01"
    assert entry["sessions"] == 58
    assert entry["cadence_from"] == "book"
    assert entry["min_weight"] == 0.0
    assert entry["max_age_days"] == (date(2026, 2, 27) - date(2025, 3, 25)).days


# The verdict command agrees with the independent check, and the check
# re-derives every number from the payloads by its own arithmetic.
def test_the_verdict_and_the_independent_check_agree(study):
    assert study["verdict_code"] == 0
    reading = json.loads(study["verdict_path"].read_text(encoding="utf-8"))
    assert set(reading["arms"]) == {"A5-hard", "A5-decay"}
    assert reading["trials"] == {"registered": 2, "cumulative": 482}
    for judged in reading["arms"].values():
        assert judged["label"] in (tes.REPLACES, tes.RECORD)
        assert set(judged["windows"]) == {"2016-2023", "2024-2026"}
        for w in judged["windows"].values():
            assert set(w["checks"]) == {"ic_h20", "ic_h60", "book_t", "cagr"}
    assert set(reading["files"]) == {"control", "A5-hard", "A5-decay"}
    paths = study["paths"]
    done = subprocess.run(
        [
            sys.executable,
            str(CHECK),
            str(paths["control"]),
            str(paths["hard"]),
            str(paths["decay"]),
            str(study["verdict_path"]),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "independent check: OK" in done.stdout


# The criteria: an arm passing everything REPLACES; an IC t under -1 at 60
# sessions, a book t under -1 or a CAGR 0.6 point lower on one window is
# RECORD; when both pass, A5-hard is proposed; and the check catches a
# verdict whose label was changed.
def test_the_non_inferiority_criteria(study, tmp_path):
    control = study["payloads"]["control"]

    # An arm payload set to pass every criterion: its curves and CAGRs are
    # the control's, its IC differences zero.
    def passing(name):
        arm = json.loads(json.dumps(study["payloads"][name]))
        arm["curves"] = control["curves"]
        arm["rows"] = control["rows"]
        for h in ("h20", "h60"):
            for w in arm["tone_expiry"]["sentiment_ic"][h]["windows"].values():
                w["paired"] = {"n": 5, "mean": 0.0, "t": 0.0}
        return arm

    arms = {"A5-hard": passing("hard"), "A5-decay": passing("decay")}
    reading = tes.verdict(control, arms)
    assert [reading["arms"][n]["label"] for n in arms] == [tes.REPLACES, tes.REPLACES]
    assert reading["proposed"] == "A5-hard"
    worse = json.loads(json.dumps(arms))
    worse["A5-hard"]["tone_expiry"]["sentiment_ic"]["h60"]["windows"]["2024-2026"][
        "paired"
    ]["t"] = -1.01
    reading = tes.verdict(control, worse)
    assert reading["arms"]["A5-hard"]["label"] == tes.RECORD
    assert (
        reading["arms"]["A5-hard"]["windows"]["2024-2026"]["checks"]["ic_h60"] is False
    )
    assert reading["proposed"] == "A5-decay"
    poorer = json.loads(json.dumps(arms))
    for row in poorer["A5-decay"]["rows"]:
        if (
            row["line"] == tes.RULE_LINE
            and row["window"] == "2016-2023"
            and row["cost_bps"] == 25.0
        ):
            row["median_cagr"] = row["median_cagr"] - 0.006
    reading = tes.verdict(control, poorer)
    assert (
        reading["arms"]["A5-decay"]["windows"]["2016-2023"]["checks"]["cagr"] is False
    )
    assert reading["arms"]["A5-decay"]["label"] == tes.RECORD
    slower = json.loads(json.dumps(arms))
    curve = slower["A5-hard"]["curves"]["25"]
    lines = curve["lines"][tes.RULE_LINE]
    curve["lines"] = {
        **curve["lines"],
        tes.RULE_LINE: [
            x - 0.002 * (1.5 + np.sin(i)) if x is not None and d >= "2024-01-01" else x
            for i, (d, x) in enumerate(zip(curve["dates"], lines, strict=True))
        ],
    }
    reading = tes.verdict(control, slower)
    assert (
        reading["arms"]["A5-hard"]["windows"]["2024-2026"]["checks"]["book_t"] is False
    )
    assert (
        reading["arms"]["A5-hard"]["windows"]["2016-2023"]["checks"]["book_t"] is True
    )


# Pairs that do not describe the same desk are refused: another session,
# an incumbent IC series or desk unlike the control's, a report its rule
# did not build, an arm under the wrong name; the command exits 2 and
# writes nothing.
def test_mismatched_payloads_are_refused(study, tmp_path):
    control = study["payloads"]["control"]
    hard, decay = study["payloads"]["hard"], study["payloads"]["decay"]
    for change in (
        lambda p: p.update(asof="2099-01-01"),
        lambda p: p["tone_expiry"].update(report_matches_rule=False),
        lambda p: p["tone_expiry"]["incumbent_fingerprint"].update(grades_sha256="0"),
        lambda p: p["tone_expiry"]["sentiment_ic"]["h20"]["periods"][
            "incumbent"
        ].__setitem__(0, 9.0),
    ):
        bad = json.loads(json.dumps(hard))
        change(bad)
        with pytest.raises(ValueError, match="refused"):
            tes.verdict(control, {"A5-hard": bad, "A5-decay": decay})
    with pytest.raises(ValueError, match="mode is 'decay', not 'hard'"):
        tes.verdict(control, {"A5-hard": decay, "A5-decay": decay})
    with pytest.raises(ValueError, match="missing arms \\['A5-decay'\\]"):
        tes.verdict(control, {"A5-hard": hard})
    wrong = tmp_path / "wrong.json"
    shifted = json.loads(json.dumps(hard))
    shifted["asof"] = "2099-01-01"
    wrong.write_text(json.dumps(shifted), encoding="utf-8")
    target = tmp_path / "verdict.json"
    code = cli.main(
        [
            "--control",
            str(study["paths"]["control"]),
            "--hard",
            str(wrong),
            "--decay",
            str(study["paths"]["decay"]),
            "--out",
            str(target),
        ]
    )
    assert code == 2
    assert not target.exists()
