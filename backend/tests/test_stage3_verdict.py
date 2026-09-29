"""Stage 3's kill criteria on hand-made payloads.

What has to hold (docs/research/stage3-plan-2026-09-29.md, "Kill criteria"
and "Trials and multiplicity"):

- The floor is bp >= 2.0 with t >= 2.0, the "real but immaterial" reading
  25 bp per differing order with t >= 3, each at its edge; a missing number
  (NaN, or None as JSON writes it) passes nothing.
- The expected best null t is the plan's table (1.46, 2.28, 2.88).
- The deflated Sharpe is `candidate_stats.deflated_sharpe` at N = 8 with the
  across-candidate variance of the supplied excess Sharpes; with fewer than
  two it is not judged.
- Seed stability: two or more sign changes of five, a missing seed, or a
  zero ensemble mean is not stable.
- A T-I convention REPLACES only when all five criteria hold (the floor at
  10, 16 and 25 bp, the next-bar run, 2024-2026 not negative at 25 bp, the
  deflated Sharpe, the seeds); breaking any one records it; "RECORD: real
  but immaterial" needs the floor to fail and the per-order reading to
  clear; runs that mix files, offsets or roles are refused; a payload read
  back from JSON is judged the same.
- The T-S1 overlay is ADOPT only when all hold (the floor at 25, 16 and 10
  bp, 15 of the registered 20 offsets, drawdown within 3 points, 2024-2026
  not negative, deflated Sharpe, seeds); breaking any one records it.
- `outer_excess` gathers the ensemble runs' excess at the verdict cost.
"""

from __future__ import annotations

import json
import math

import pytest

from backend.market import candidate_stats
from backend.market import stage3_verdict as sv
from backend.market.session_anatomy import json_ready

SHA = "a" * 64
CONVENTIONS = ("lgbm_filter", "lgbm_free", "seq_filter", "seq_free")


# One T-I row: the paired difference against dip_or_close on a window, the
# per-order reading and the excess moments.
def _ti_row(convention, window, bp, t, per_bp=0.0, per_t=0.0, sharpe=0.05, length=1500):
    return {
        "convention": convention,
        "window": window,
        "mean_daily_bp_vs_dip": bp,
        "hac_t_vs_dip": t,
        "versus_control": {
            "all": {"bp_per_differing_order": per_bp, "clustered_t": per_t}
        },
        "excess": {"sharpe": sharpe, "skew": 0.0, "kurtosis": 3.0, "length": length},
    }


# A fill-timing payload's T-I block: per convention its model-window (bp,
# t), 2024-2026 bp, per-order (bp, t) and excess Sharpe (defaults: a clear
# pass for lgbm_filter, a clear miss for the rest).
def _ti_payload(cost, spec=None, next_bar=False, seed=None, sha=SHA, offsets=20):
    spec = spec if spec is not None else {}
    rows = []
    for convention in CONVENTIONS:
        own = spec.get(convention, {})
        good = convention == "lgbm_filter"
        bp, t = own.get("model", (3.0, 3.0) if good else (0.5, 0.5))
        per = own.get("per_order", (0.0, 0.0))
        sharpe = own.get(
            "sharpe",
            0.2
            if good
            else {"lgbm_free": 0.05, "seq_filter": 0.04}.get(convention, 0.03),
        )
        length = own.get("length", 1500)
        rows.append(
            _ti_row(convention, "model", bp, t, *per, sharpe=sharpe, length=length)
        )
        rows.append(_ti_row(convention, "2016-2023", bp, t))
        rows.append(_ti_row(convention, "2024-2026", own.get("reported", 1.0), 1.0))
    return {
        "cost_bps": cost,
        "stage3_ti": {
            "cost_bps": cost,
            "next_bar": next_bar,
            "seed_column": seed,
            "offsets": offsets,
            "conventions": list(CONVENTIONS),
            "families": {"lgbm": {"sha256": sha}, "seq": {"sha256": sha}},
            "rows": rows,
        },
    }


# The full set of T-I runs: three cost runs, one next-bar run and five
# seeds, each with its own spec overrides; `seed_bp` sets the seeds' model
# means for lgbm_filter.
def _ti_runs(spec=None, next_spec=None, seed_bp=(1.0, 2.0, 3.0, 2.5, 0.5), costs=None):
    spec = spec or {}
    runs = [_ti_payload(c, (costs or {}).get(c, spec)) for c in (10.0, 16.0, 25.0)]
    next_bar = [_ti_payload(10.0, next_spec or spec, next_bar=True)]
    seeds = [
        _ti_payload(10.0, {"lgbm_filter": {"model": (bp, 1.0)}}, seed=k)
        for k, bp in enumerate(seed_bp)
    ]
    return runs, next_bar, seeds


# The floor and the immaterial reading at their edges, and missing numbers.
def test_floor_and_real_readings():
    assert sv.passes_floor(2.0, 2.0)
    assert not sv.passes_floor(1.99, 3.0) and not sv.passes_floor(3.0, 1.99)
    for missing in (None, math.nan):
        assert not sv.passes_floor(missing, 3.0) and not sv.passes_floor(3.0, missing)
    assert sv.is_real(25.0, 3.0)
    assert not sv.is_real(24.99, 5.0) and not sv.is_real(40.0, 2.99)
    assert not sv.is_real(None, 5.0) and not sv.is_real(40.0, math.nan)
    assert sv.cost_key(10.0) == "10" and sv.cost_key(16) == "16"


# The expected best null t is the plan's table.
def test_expected_best_null_t_is_the_plans_table():
    assert round(sv.expected_best_null_t(8), 2) == 1.46
    assert round(sv.expected_best_null_t(50), 2) == 2.28
    assert round(sv.expected_best_null_t(282), 2) == 2.88
    assert sv.TRIAL_COUNTS == {"outer": 8, "configurations": 50, "cumulative": 282}
    assert sv.TI_CANDIDATES + sv.S1_CANDIDATES == (
        "lgbm_filter",
        "lgbm_free",
        "seq_filter",
        "seq_free",
        "s1_lgbm",
        "s1_cnn_i5",
        "s1_cnn_i20",
        "s1_seq",
    )


# The deflated Sharpe: candidate_stats.deflated_sharpe at N = 8 with the
# sample variance of the finite supplied Sharpes; lower at 50 and 282; not
# judged with one Sharpe or for an absent candidate; JSON nulls read as NaN.
def test_deflated_sharpe_uses_the_supplied_candidates_spread():
    excess = {
        "a": {"sharpe": 0.2, "skew": 0.1, "kurtosis": 4.0, "length": 1500},
        "b": {"sharpe": 0.05, "skew": 0.0, "kurtosis": 3.0, "length": 1500},
        "c": {"sharpe": 0.04, "skew": 0.0, "kurtosis": 3.0, "length": 1500},
        "d": {"sharpe": 0.03, "skew": 0.0, "kurtosis": 3.0, "length": 1500},
        "e": {"sharpe": None, "skew": None, "kurtosis": None, "length": 0},
    }
    record = sv.deflated(excess, "a")
    mean = (0.2 + 0.05 + 0.04 + 0.03) / 4
    variance = sum((s - mean) ** 2 for s in (0.2, 0.05, 0.04, 0.03)) / 3
    assert record["trial_variance"] == pytest.approx(variance)
    assert record["candidates"] == 4 and record["trials"] == 8
    assert record["dsr"] == pytest.approx(
        candidate_stats.deflated_sharpe(0.2, 1500, 0.1, 4.0, 8, variance)
    )
    assert record["dsr_configurations"] == pytest.approx(
        candidate_stats.deflated_sharpe(0.2, 1500, 0.1, 4.0, 50, variance)
    )
    assert record["dsr"] > record["dsr_configurations"] > record["dsr_cumulative"]
    assert record["passes"] is True and record["gate"] == 0.95
    weak = sv.deflated({**excess, "a": {**excess["a"], "length": 200}}, "a")
    assert weak["dsr"] < 0.95 and weak["passes"] is False
    alone = sv.deflated({"a": excess["a"]}, "a")
    assert math.isnan(alone["dsr"]) and alone["passes"] is False
    absent = sv.deflated(excess, "zzz")
    assert math.isnan(absent["dsr"]) and absent["passes"] is False


# Seed stability: one sign change of five is stable; two are not; a missing
# or zero seed is a change; four seeds are incomplete; a zero or missing
# ensemble mean is not stable; negative means stable around a negative one.
def test_seed_stability_counts_sign_changes():
    assert sv.seed_stability(3.0, [1.0, 2.0, -1.0, 4.0, 0.5])["stable"]
    two = sv.seed_stability(3.0, [1.0, -2.0, -1.0, 4.0, 0.5])
    assert two["sign_changes"] == 2 and not two["stable"]
    assert sv.seed_stability(3.0, [1.0, None, -1.0, 4.0, 0.5])["sign_changes"] == 2
    assert sv.seed_stability(3.0, [1.0, 0.0, 2.0, 4.0, 0.5])["sign_changes"] == 1
    four = sv.seed_stability(3.0, [1.0, 2.0, 3.0, 4.0])
    assert not four["complete"] and not four["stable"]
    assert not sv.seed_stability(0.0, [1.0] * 5)["stable"]
    assert not sv.seed_stability(None, [1.0] * 5)["stable"]
    assert sv.seed_stability(-2.0, [-1.0, -3.0, -0.5, -2.0, 1.0])["stable"]


# The T-I verdict: lgbm_filter clears all five criteria and REPLACES; the
# others record. Breaking any one criterion records it: the floor at one
# cost, the t, the next-bar run (or its absence), 2024-2026 at 25 bp (a
# negative 10 bp reading alone does not), the deflated Sharpe, the seeds
# (two sign changes, or four seeds).
def test_ti_verdict_replaces_only_when_all_five_hold():
    runs, next_bar, seeds = _ti_runs()
    record = sv.ti_verdict(runs, next_bar, seeds)
    assert record["replaces"] == ["lgbm_filter"]
    best = record["candidates"]["lgbm_filter"]
    assert best["label"] == sv.REPLACES
    assert set(best["floor"]) == {"10", "16", "25"}
    assert (
        best["passes_floor"] and best["passes_next_bar"] and best["not_worse_reported"]
    )
    assert best["deflated"]["passes"] and best["seeds"]["stable"]
    assert (
        best["seeds"]["columns"] == [0, 1, 2, 3, 4]
        and best["seeds"]["cost_bps"] == 10.0
    )
    assert best["deflated"]["candidates"] == 4
    for name in ("lgbm_free", "seq_filter", "seq_free"):
        assert record["candidates"][name]["label"] == sv.RECORD
    assert record["text"].startswith(sv.REPLACES)
    assert record["costs_supplied"] == ["10", "16", "25"]

    # The label of lgbm_filter under a changed set of runs.
    def label(runs, next_bar, seeds, others=None) -> str:
        return sv.ti_verdict(runs, next_bar, seeds, others)["candidates"][
            "lgbm_filter"
        ]["label"]

    at16 = {"lgbm_filter": {"model": (1.99, 3.0)}}
    runs, next_bar, seeds = _ti_runs(costs={16.0: at16})
    assert label(runs, next_bar, seeds) == sv.RECORD
    runs, next_bar, seeds = _ti_runs(
        costs={25.0: {"lgbm_filter": {"model": (3.0, 1.99)}}}
    )
    assert label(runs, next_bar, seeds) == sv.RECORD
    runs, next_bar, seeds = _ti_runs(next_spec={"lgbm_filter": {"model": (2.5, 1.9)}})
    assert label(runs, next_bar, seeds) == sv.RECORD
    runs, _, seeds = _ti_runs()
    assert label(runs, [], seeds) == sv.RECORD
    later = {"lgbm_filter": {"reported": -0.01}}
    runs, next_bar, seeds = _ti_runs(costs={25.0: later})
    assert label(runs, next_bar, seeds) == sv.RECORD
    runs, next_bar, seeds = _ti_runs(costs={10.0: later})
    assert label(runs, next_bar, seeds) == sv.REPLACES
    weak = {"lgbm_filter": {"length": 150}}
    runs, next_bar, seeds = _ti_runs(costs={25.0: weak})
    assert label(runs, next_bar, seeds) == sv.RECORD
    runs, next_bar, seeds = _ti_runs(seed_bp=(1.0, -2.0, 3.0, -2.5, 0.5))
    assert label(runs, next_bar, seeds) == sv.RECORD
    runs, next_bar, seeds = _ti_runs()
    assert label(runs, next_bar, seeds[:4]) == sv.RECORD
    assert label(runs, next_bar, []) == sv.RECORD
    # A strong outer candidate from T-S1 widens the spread: deflated harder.
    others = {"s1_lgbm": {"sharpe": 0.6, "skew": 0.0, "kurtosis": 3.0, "length": 1500}}
    runs, next_bar, seeds = _ti_runs()
    widened = sv.ti_verdict(runs, next_bar, seeds, others)["candidates"]["lgbm_filter"]
    assert widened["deflated"]["candidates"] == 5
    assert widened["deflated"]["dsr"] < best["deflated"]["dsr"]


# "RECORD: real but immaterial": the floor fails (here at 25 bp) while the
# per-order reading clears 25 bp with t >= 3; either reading short of its
# edge is RECORD; a convention that clears the floor but fails elsewhere is
# RECORD, not immaterial.
def test_ti_real_but_immaterial():
    # lgbm_free's label with its model-window (bp, t) and per-order reading
    # at every cost.
    def label(model, per_order, next_spec=None) -> str:
        spec = {"lgbm_free": {"model": model, "per_order": per_order}}
        runs, next_bar, seeds = _ti_runs(spec=spec, next_spec=next_spec)
        record = sv.ti_verdict(runs, next_bar, seeds)
        return record["candidates"]["lgbm_free"]["label"], record

    name, record = label((1.5, 1.2), (30.0, 3.5))
    assert name == sv.IMMATERIAL and record["immaterial"] == ["lgbm_free"]
    assert sv.IMMATERIAL in record["text"]
    assert label((1.5, 1.2), (24.9, 3.5))[0] == sv.RECORD
    assert label((1.5, 1.2), (30.0, 2.9))[0] == sv.RECORD
    failing_next = {"lgbm_free": {"model": (0.1, 0.1)}}
    assert label((3.0, 3.0), (30.0, 3.5), next_spec=failing_next)[0] == sv.RECORD


# Runs in the wrong place or that do not belong together are refused: a
# next-bar run as a cost run, a seed run as a cost run, two runs at one
# cost, a cost run as a next-bar run, a next-bar run as a seed, seeds at two
# costs, another file's run, other offsets, a payload with no T-I block.
def test_ti_verdict_refuses_mixed_runs():
    runs, next_bar, seeds = _ti_runs()
    with pytest.raises(ValueError, match="pass it as next_bar"):
        sv.ti_verdict([*runs, next_bar[0]])
    with pytest.raises(ValueError, match="pass it in seeds"):
        sv.ti_verdict([*runs, seeds[0]])
    with pytest.raises(ValueError, match="two cost runs"):
        sv.ti_verdict([*runs, _ti_payload(10.0)])
    with pytest.raises(ValueError, match="ensemble --next-bar run"):
        sv.ti_verdict(runs, [runs[0]])
    with pytest.raises(ValueError, match="default-fill --seed-column run"):
        sv.ti_verdict(runs, next_bar, [_ti_payload(10.0, next_bar=True, seed=0)])
    with pytest.raises(ValueError, match="share one cost"):
        sv.ti_verdict(runs, next_bar, [*seeds[:4], _ti_payload(25.0, seed=4)])
    with pytest.raises(ValueError, match="different forecast files or offsets"):
        sv.ti_verdict([*runs[:2], _ti_payload(25.0, sha="b" * 64)])
    with pytest.raises(ValueError, match="different forecast files or offsets"):
        sv.ti_verdict(runs, [_ti_payload(10.0, next_bar=True, offsets=10)])
    with pytest.raises(ValueError, match="no stage3_ti block"):
        sv.ti_verdict([{"rows": []}])


# A payload read back from JSON (NaN written as null) is judged the same;
# a missing cost run records every convention.
def test_ti_verdict_on_json_payloads_and_missing_runs():
    runs, next_bar, seeds = _ti_runs()
    round_trip = [
        json.loads(json.dumps(json_ready(p))) for p in (*runs, *next_bar, *seeds)
    ]
    record = sv.ti_verdict(round_trip[:3], round_trip[3:4], round_trip[4:])
    assert record["replaces"] == ["lgbm_filter"]
    nulls = json.loads(
        json.dumps(
            json_ready(_ti_payload(25.0, {"lgbm_filter": {"model": (math.nan, 3.0)}}))
        )
    )
    record = sv.ti_verdict([*round_trip[:2], nulls], round_trip[3:4], round_trip[4:])
    assert record["candidates"]["lgbm_filter"]["label"] == sv.RECORD
    record = sv.ti_verdict(runs[:2], next_bar, seeds)
    assert record["replaces"] == []
    assert record["candidates"]["lgbm_filter"]["floor"]["25"]["priced"] is False
    assert record["costs_supplied"] == ["10", "16"]
    reading = sv.ti_reading(runs[0]["stage3_ti"]["rows"])
    assert (
        reading["lgbm_filter"]["passes_floor"]
        and not reading["lgbm_free"]["passes_floor"]
    )


# An overlay payload: rows for both lines on every window and cost, paired
# entries of the overlay with excess moments; `floor` gives the model
# window's (bp, t) per cost.
def _s1_payload(
    candidate="s1_lgbm",
    floor=None,
    above=16,
    dd_gap=-1.0,
    reported=0.5,
    sharpe=0.2,
    length=1500,
    offsets=20,
    seed=None,
    sha="b" * 64,
    costs=(10.0, 16.0, 25.0),
):
    floor = floor or {10.0: (3.0, 3.0), 16.0: (2.8, 2.8), 25.0: (2.5, 2.5)}
    rows, paired = [], []
    for cost in costs:
        for window in ("model", "2016-2023", "2024-2026", "all"):
            for line in ("ew-redeploy", "s1-overlay"):
                control = line == "ew-redeploy"
                rows.append(
                    {
                        "line": line,
                        "cost_bps": cost,
                        "window": window,
                        "offsets": offsets,
                        "median_cagr": 0.20 if control else 0.21,
                        "median_drawdown": -0.25 if control else -0.25 + dd_gap / 100.0,
                        "offsets_above_control": 0 if control else above,
                        "cash_share": 0.02 if control else 0.03,
                    }
                )
            if window == "model":
                bp, t = floor.get(cost, (0.0, 0.0))
            else:
                bp, t = (reported, 1.0) if window == "2024-2026" else (1.0, 1.0)
            paired.append(
                {
                    "cost_bps": cost,
                    "window": window,
                    "line": "s1-overlay",
                    "against": "ew-redeploy",
                    "mean_daily_bp": bp,
                    "hac_t": t,
                    "excess": {
                        "sharpe": sharpe,
                        "skew": 0.0,
                        "kurtosis": 3.0,
                        "length": length,
                    },
                }
            )
    return {
        "study": "stage3_overlay",
        "candidate": candidate,
        "control": "ew-redeploy",
        "line": "s1-overlay",
        "offsets": offsets,
        "costs_bps": list(costs),
        "seed_column": seed,
        "forecast": {"sha256": sha},
        "rows": rows,
        "paired": paired,
    }


# The other outer candidates' excess, for the deflated Sharpe's spread.
OTHERS = {
    "s1_cnn_i5": {"sharpe": 0.05, "skew": 0.0, "kurtosis": 3.0, "length": 1500},
    "s1_cnn_i20": {"sharpe": 0.04, "skew": 0.0, "kurtosis": 3.0, "length": 1500},
    "s1_seq": {"sharpe": 0.03, "skew": 0.0, "kurtosis": 3.0, "length": 1500},
}


# Five seed runs of an overlay payload with the given model-window means at 25 bp.
def _s1_seeds(bps=(2.0, 1.0, 3.0, 0.5, 2.5), **kwargs):
    return [
        _s1_payload(
            seed=k, floor={10.0: (b, 1.0), 16.0: (b, 1.0), 25.0: (b, 1.0)}, **kwargs
        )
        for k, b in enumerate(bps)
    ]


# The overlay's verdict: ADOPT when every criterion holds; RECORD when any
# one breaks - the floor at 10 bp, the offsets (14 of 20, or 19 of 19 when
# the run is not the registered 20), the drawdown just past 3 points (just
# inside is fine), 2024-2026 below zero, the deflated Sharpe with no other
# candidate to spread against, the seeds; the reading and the exposure
# figures come with it; the verdict reads the ensemble run only.
def test_s1_verdict_adopts_only_when_all_hold():
    record = sv.s1_verdict(_s1_payload(), _s1_seeds(), OTHERS)
    assert record["label"] == sv.ADOPT and record["text"].startswith(sv.ADOPT)
    reading = record["reading"]
    assert reading["passes_floor"] and reading["passes_offsets"]
    assert reading["drawdown_gap_points"] == pytest.approx(-1.0)
    assert reading["cagr_points"] == pytest.approx(1.0)
    assert reading["invested_share"] == pytest.approx(0.97)
    assert reading["exposure_adjusted_points"] == pytest.approx(
        (0.21 - 0.20 * 0.97 / 0.98) * 100
    )
    assert record["deflated"]["candidates"] == 4 and record["deflated"]["passes"]
    assert record["seeds"]["stable"] and record["seeds"]["columns"] == [0, 1, 2, 3, 4]
    for payload, seeds, others in (
        (
            _s1_payload(floor={10.0: (1.9, 3.0), 16.0: (3.0, 3.0), 25.0: (3.0, 3.0)}),
            _s1_seeds(),
            OTHERS,
        ),
        (_s1_payload(above=14), _s1_seeds(), OTHERS),
        (_s1_payload(offsets=19, above=19), _s1_seeds(offsets=19), OTHERS),
        (_s1_payload(dd_gap=-3.01), _s1_seeds(), OTHERS),
        (_s1_payload(reported=-0.01), _s1_seeds(), OTHERS),
        (_s1_payload(), _s1_seeds(), None),
        (_s1_payload(), _s1_seeds(bps=(2.0, -1.0, 3.0, -0.5, 2.5)), OTHERS),
        (_s1_payload(), _s1_seeds()[:4], OTHERS),
        (_s1_payload(costs=(10.0, 25.0)), _s1_seeds(costs=(10.0, 25.0)), OTHERS),
    ):
        assert sv.s1_verdict(payload, seeds, others)["label"] == sv.RECORD
    assert (
        sv.s1_verdict(_s1_payload(above=15), _s1_seeds(), OTHERS)["label"] == sv.ADOPT
    )
    assert (
        sv.s1_verdict(_s1_payload(dd_gap=-2.99), _s1_seeds(), OTHERS)["label"]
        == sv.ADOPT
    )
    with pytest.raises(ValueError, match="ensemble run"):
        sv.s1_verdict(_s1_payload(seed=0), _s1_seeds(), OTHERS)


# Seed runs of another candidate, file or offsets are refused, and so is an
# ensemble run passed as a seed.
def test_s1_seed_runs_must_match():
    for bad in (
        _s1_seeds(candidate="s1_seq"),
        _s1_seeds(sha="c" * 64),
        _s1_seeds(offsets=10),
    ):
        with pytest.raises(ValueError, match="another candidate, file or offsets"):
            sv.s1_verdict(_s1_payload(), bad, OTHERS)
    with pytest.raises(ValueError, match="--seed-column run"):
        sv.s1_verdict(_s1_payload(), [_s1_payload()], OTHERS)


# `outer_excess` takes each T-I convention's model-window excess from the
# ensemble default-fill run at 25 bp only, and each ensemble overlay run's.
def test_outer_excess_gathers_both_parts():
    runs, next_bar, seeds = _ti_runs()
    overlays = [
        _s1_payload(candidate=name, sharpe=0.01 * i)
        for i, name in enumerate(sv.S1_CANDIDATES)
    ]
    excess = sv.outer_excess(
        ti_runs=[*runs, *next_bar, *seeds], s1_runs=[*overlays, _s1_payload(seed=1)]
    )
    assert set(excess) == set(sv.TI_CANDIDATES) | set(sv.S1_CANDIDATES)
    assert excess["lgbm_filter"]["sharpe"] == 0.2
    assert excess["s1_cnn_i20"]["sharpe"] == pytest.approx(0.02)
    assert sv.ti_excess(runs[2])["seq_free"]["length"] == 1500
    assert sv.s1_excess(_s1_payload(costs=(10.0,))) == {}
