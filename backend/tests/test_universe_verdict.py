"""The registered criteria on payloads whose answers are known.

Two synthetic scorecard payloads are built by hand: a control and an arm
that beats it by a fixed daily margin. Every criterion is then a number
that can be computed on paper, and each is flipped in turn to check that
the verdict reads it.
"""

import copy
import json
import math
from datetime import date, timedelta

import numpy as np
import pytest

from backend.cli import universe_verdict as cli
from backend.market import candidate_stats
from backend.market import universe_verdict as uv

T = 400


# Business days from 2023-01-02, spanning both windows.
def _dates(n=T):
    out, d = [], date(2023, 1, 2)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(str(d))
        d += timedelta(days=1)
    return out


# A payload whose rule line returns `daily` at the median offset, with the
# summary rows set from the arguments.
def _payload(daily, median_cagr, cagrs, worst_dd, worst_day, share_below):
    windows = {
        "2016-2023": ["2016-01-01", "2024-01-01"],
        "2024-2026": ["2024-01-01", None],
        "all": [None, None],
    }
    rows = []
    for line in (uv.RULE_PIT, uv.EW_PIT, "SPY", "QQQ"):
        for w in windows:
            rows.append(
                {
                    "line": line,
                    "cost_bps": 25.0,
                    "window": w,
                    "median_cagr": median_cagr if line == uv.RULE_PIT else 0.05,
                    "worst_cagr": 0.0,
                    "median_drawdown": -0.1,
                    "worst_drawdown": worst_dd if line == uv.RULE_PIT else -0.2,
                    "median_sharpe": 1.0,
                    "offsets_above_ew_pit": 10,
                    "offsets_above_qqq": 10,
                    "cagrs": list(cagrs)
                    if line == uv.RULE_PIT
                    else [0.05] * len(cagrs),
                }
            )
    lines = {
        label: [math.nan] * T
        for label in (
            uv.RULE_PIT,
            uv.EW_PIT,
            "SPY",
            "QQQ",
            "rule / today's book",
            "equal weight / today's book",
        )
    }
    lines[uv.RULE_PIT] = list(map(float, daily))
    return {
        "windows": windows,
        "rows": rows,
        "paired": [
            {
                "cost_bps": 25.0,
                "window": "2016-2023",
                "line": uv.RULE_PIT,
                "against": uv.EW_PIT,
                "hac_t": 1.0,
                "psr": 0.9,
                "mean_daily_bp": 1.0,
                "sessions": T,
            }
        ],
        "curves": {"25": {"offset": 10, "dates": _dates(), "lines": lines}},
        "concentration": {w: {"worst_single_name_day": worst_day} for w in windows},
        "candidates": {w: {"share_below": share_below, "below": 5} for w in windows},
        "book": {"names_today": 6},
        "arm": "test",
    }


@pytest.fixture
def payloads():
    rng = np.random.default_rng(3)
    base = rng.normal(0.0005, 0.01, size=T)
    control = _payload(base, 0.20, [0.20] * 20, -0.30, -0.05, 0.40)
    # The arm earns about 4 bp a day more, at a tenth of the noise: a strong edge.
    margin = rng.normal(0.0004, 0.001, size=T)
    arm = _payload(base + margin, 0.25, [0.23] * 20, -0.31, -0.04, 0.01)
    return control, arm


# The paired difference is exactly the added margin, and the criteria
# read the rows and blocks as registered.
def test_criteria_read_the_registered_numbers(payloads):
    control, arm = payloads
    paired = uv.paired_difference(arm, control)
    # Only 2023 sessions are in the deciding window.
    n_2023 = sum(1 for d in _dates() if d < "2024-01-01")
    assert paired["sessions"] == n_2023
    assert paired["mean_daily_bp"] == pytest.approx(4.0, abs=1.0)
    assert paired["hac_t"] > 2.0
    result = uv.criteria(arm, control, trial_variance=1e-4)
    assert result["c1"]["lead"] == {
        "2016-2023": pytest.approx(0.05),
        "2024-2026": pytest.approx(0.05),
    }
    assert result["c3"]["above"] == 20 and result["c3"]["ok"]
    assert result["c4"]["ok"] and result["c5"]["ok"]
    assert result["c1"]["ok"] and result["c2"]["ok"] and result["c6"]["ok"]
    assert result["pass"]


# Each criterion fails on its own when its number is moved.
def test_each_criterion_can_fail(payloads):
    control, arm = payloads

    def moved(change):
        other = copy.deepcopy(arm)
        change(other)
        return uv.criteria(other, control, trial_variance=1e-4)

    def lead(p):
        for r in p["rows"]:
            if r["line"] == uv.RULE_PIT and r["window"] == "2024-2026":
                r["median_cagr"] = 0.21

    assert not moved(lead)["c1"]["ok"]

    def flat(p):
        p["curves"]["25"]["lines"][uv.RULE_PIT] = control["curves"]["25"]["lines"][
            uv.RULE_PIT
        ]

    assert not moved(flat)["c2"]["ok"]

    def offsets(p):
        for r in p["rows"]:
            if r["line"] == uv.RULE_PIT and r["window"] == "2016-2023":
                r["cagrs"] = [0.19] * 6 + [0.23] * 14

    assert moved(offsets)["c3"]["above"] == 14 and not moved(offsets)["c3"]["ok"]

    def drawdown(p):
        for r in p["rows"]:
            if r["line"] == uv.RULE_PIT and r["window"] == "all":
                r["worst_drawdown"] = -0.34

    assert not moved(drawdown)["c4"]["ok"]

    def worst_day(p):
        p["concentration"]["2024-2026"]["worst_single_name_day"] = -0.06

    assert not moved(worst_day)["c4"]["ok"]

    def few(p):
        p["candidates"]["2016-2023"]["share_below"] = 0.05

    assert not moved(few)["c5"]["ok"]

    # A huge trial variance makes the expected best-of-457 hurdle unreachable.
    assert not uv.criteria(arm, control, trial_variance=1.0)["c6"]["ok"]
    assert math.isnan(uv.criteria(arm, control, trial_variance=math.nan)["c6"]["dsr"])


# The deflated Sharpe here is the library's, at the registered count, with
# the across-arm variance `judge` computes; only the primary arm can PASS.
def test_judge_uses_across_arm_variance_and_names_the_verdict(payloads):
    control, arm = payloads
    rng = np.random.default_rng(4)
    weaker = _payload(
        np.asarray(control["curves"]["25"]["lines"][uv.RULE_PIT])
        + rng.normal(0.0003, 0.001, size=T),
        0.21,
        [0.21] * 20,
        -0.30,
        -0.05,
        0.02,
    )
    judged = uv.judge(control, {"sector": arm, "flat": arm, "tone": weaker})
    sharpes = [uv.paired_difference(a, control)["sharpe"] for a in (arm, arm, weaker)]
    assert judged["trial_variance"] == pytest.approx(float(np.var(sharpes, ddof=1)))
    p = judged["arms"]["sector"]["criteria"]["c2"]["paired"]
    expected = candidate_stats.deflated_sharpe(
        p["sharpe"],
        p["length"],
        p["skew"],
        p["kurtosis"],
        uv.CUMULATIVE_TRIALS,
        judged["trial_variance"],
    )
    assert judged["arms"]["sector"]["criteria"]["c6"]["dsr"] == pytest.approx(expected)
    assert judged["verdict"]["sector"] == "PASS"
    assert judged["verdict"]["flat"].startswith("RECORD")
    assert judged["verdict"]["tone"] == "RECORD"
    text = uv.render(judged)
    assert "sector: PASS" in text and "c5 ok" in text and "flat: RECORD" in text


# The CLI reads the directory, prints the digests and writes verdict.json.
def test_cli_reads_the_directory_and_writes_the_verdict(payloads, tmp_path, capsys):
    control, arm = payloads
    (tmp_path / "control.json").write_text(json.dumps(control), encoding="utf-8")
    (tmp_path / "universe_sector.json").write_text(json.dumps(arm), encoding="utf-8")
    assert cli.main(["--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "payload sha256" in out and cli.digest(tmp_path / "control.json") in out
    written = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    assert set(written["payload_sha256"]) == {"control", "sector"}
    assert written["verdict"]["sector"] in ("PASS", "RECORD")
    assert cli.main(["--dir", str(tmp_path / "missing")]) == 1
