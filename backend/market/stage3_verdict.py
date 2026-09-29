"""Stage 3's kill criteria, as pure functions over the decision tests' payloads.

`docs/research/stage3-plan-2026-09-29.md` ("Kill criteria, fixed now",
"Trials and multiplicity") fixes what a stage-3 candidate needs before it
may change anything. Both decision tests use these functions: the T-I fill
conventions (`fill_timing`, the payload's "stage3_ti" block) and the T-S1
overlay (`stage3_overlay`). Nothing here prices anything; every function
reads payload dicts, as written to JSON (a NaN may be read back as None,
and a missing number passes nothing).

A T-I convention REPLACES `dip_or_close` only if all five hold
(`ti_verdict`):

1. on the model window (its family's first forecast session through
   2023-12-29) it beats dip_or_close by at least FLOOR_BP a session with a
   paired Newey-West t of at least FLOOR_T at the median offset, in each of
   the 10, 16 and 25 bp runs;
2. the same floor holds in the `--next-bar` run (every one supplied);
3. its mean paired difference on 2024-2026 is not negative;
4. its model-window excess clears the deflated Sharpe gate at N =
   OUTER_CANDIDATES, with the trial variance the across-candidate variance
   of the supplied candidates' excess Sharpe ratios (`deflated`);
5. it is seed-stable: its model-window mean paired difference does not
   change sign in two or more of the five single-seed runs
   (`seed_stability`).

Anything else is RECORD, or IMMATERIAL ("RECORD: real but immaterial")
when the floor (1) fails but candidate minus control per differing order
is at least IMMATERIAL_BP_PER_ORDER with a date-clustered t of at least
IMMATERIAL_T.

The T-S1 overlay is ADOPT (registered) only if (`s1_verdict`): the floor
holds on the model window at 25 bp and at 10 and 16 too; it is above the
control in at least OFFSETS_ABOVE of the OFFSETS registered offsets; its
median worst drawdown is within DRAWDOWN_POINTS of the control's; its
2024-2026 mean paired difference is not negative; and it clears the
deflated Sharpe and seed-stability conditions above. Otherwise RECORD.

Decisions the plan left open, fixed here before any run:

* Criterion 1 is read in each cost run, as the plan says; every other
  criterion (2024-2026, offsets, drawdown, the deflated Sharpe, the per-order
  reading) is read at VERDICT_COST_BPS (25 bp, the most conservative cost),
  the way `profit_taking` and `midcycle_ew` read theirs, and is reported at
  the other costs where the payload has them.
* The seed runs are compared with the ensemble run at their own cost; a
  seed whose mean is missing, zero or of the other sign is a change, and a
  missing seed fails the condition (it is not judged on fewer than five).
* The deflated Sharpe needs at least two candidates' excess Sharpe ratios
  for a trial variance; with fewer it is not judged and the gate fails.
  N stays the registered 8 whatever the number supplied; the values at the
  configuration-level (50) and cumulative (282) counts are printed beside.
* The runs a verdict reads must share their forecast files (sha256 per
  family) and offsets; a mix is refused rather than judged.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np

from backend.market import candidate_stats
from backend.market import stage3_io as io

REPLACES = "REPLACES"
ADOPT = "ADOPT (registered)"
RECORD = "RECORD"
IMMATERIAL = "RECORD: real but immaterial"
# The three costs every floor is read at, and the one the rest is read at.
COSTS = (10.0, 16.0, 25.0)
VERDICT_COST_BPS = 25.0
# The windows: the model's choosing window, and the reported one.
MODEL = "model"
REPORTED = "2024-2026"
# T-S1: the registered offsets, how many must beat the control, and the
# drawdown the overlay may add (CAGR points, on the model window).
OFFSETS = 20
OFFSETS_ABOVE = 15
DRAWDOWN_POINTS = 3.0
# A mean that changes sign in this many of the five single-seed runs is not accepted.
SEED_CHANGES = 2
# The deflated Sharpe's trial counts: the gate, and the two printed beside it.
TRIAL_COUNTS = {
    "outer": io.OUTER_CANDIDATES,
    "configurations": io.CONFIG_TRIALS,
    "cumulative": io.CUMULATIVE_TRIALS,
}
# The eight outer candidates, by the names the payloads carry.
TI_RULES = ("filter", "free")
TI_CANDIDATES = tuple(
    f"{family}_{rule}" for family in io.FAMILIES[io.TI] for rule in TI_RULES
)
S1_CANDIDATES = tuple(f"s1_{family}" for family in io.FAMILIES[io.S1])

assert len(TI_CANDIDATES) + len(S1_CANDIDATES) == io.OUTER_CANDIDATES


# A payload number as a float: None (a NaN written to JSON) and anything
# missing read as NaN.
def _f(value: Any) -> float:
    """Return `value` as a float, NaN for None."""
    return math.nan if value is None else float(value)


# Whether a payload number is a finite float.
def _finite(value: Any) -> bool:
    """Return True when `value` is a finite number."""
    return value is not None and math.isfinite(float(value))


# The key a cost is filed under in a verdict record: "10", "16", "25".
def cost_key(cost: float) -> str:
    """Return the cost as its record key."""
    return f"{float(cost):g}"


# The plan's floor on a paired comparison: at least FLOOR_BP a session with
# a paired t of at least FLOOR_T. A missing number passes nothing.
def passes_floor(bp: Any, t: Any) -> bool:
    """Return True when bp >= FLOOR_BP and t >= FLOOR_T, both finite."""
    return bool(
        _finite(bp)
        and _finite(t)
        and float(bp) >= io.FLOOR_BP
        and float(t) >= io.FLOOR_T
    )


# The "real but immaterial" reading: at least IMMATERIAL_BP_PER_ORDER per
# differing order with a clustered t of at least IMMATERIAL_T.
def is_real(bp_per_order: Any, t: Any) -> bool:
    """Return True when the per-order gain and its t clear the immaterial reading."""
    return bool(
        _finite(bp_per_order)
        and _finite(t)
        and float(bp_per_order) >= io.IMMATERIAL_BP_PER_ORDER
        and float(t) >= io.IMMATERIAL_T
    )


# The expected best t of `trials` independent null trials, the plan's
# (1 - gamma) Phi^-1(1 - 1/N) + gamma Phi^-1(1 - 1/(N e)): 1.46 at 8, 2.28
# at 50, 2.88 at 282.
def expected_best_null_t(trials: int) -> float:
    """Return the expected maximum of `trials` standard normal draws."""
    return candidate_stats.expected_max_sharpe(int(trials), 1.0)


# The deflated Sharpe ratio of one candidate's excess, from the per-period
# moments the payloads carry ({"sharpe", "skew", "kurtosis", "length"} per
# candidate), against the expected best of N = OUTER_CANDIDATES null trials
# whose Sharpe variance is the across-candidate variance of the finite
# excess Sharpes supplied. Also at the configuration-level and cumulative
# counts, printed beside. Not judged (NaN, gate failed) with fewer than
# two finite Sharpes or no record for the candidate.
def deflated(excess: Mapping[str, Mapping[str, Any]], candidate: str) -> dict[str, Any]:
    """Return the deflated Sharpe record of `candidate` among those supplied."""
    sharpes = np.array(
        [_f((e or {}).get("sharpe")) for e in excess.values()], dtype=float
    )
    sharpes = sharpes[np.isfinite(sharpes)]
    variance = float(sharpes.var(ddof=1)) if len(sharpes) >= 2 else math.nan
    own = excess.get(candidate) or {}
    sharpe = _f(own.get("sharpe"))
    length = int(own.get("length") or 0)
    skew = _f(own.get("skew"))
    kurtosis = _f(own.get("kurtosis"))
    values: dict[str, float] = {}
    for label, trials in TRIAL_COUNTS.items():
        if math.isfinite(variance) and math.isfinite(sharpe):
            values[label] = candidate_stats.deflated_sharpe(
                sharpe, length, skew, kurtosis, trials, variance
            )
        else:
            values[label] = math.nan
    dsr = values["outer"]
    return {
        "candidate": candidate,
        "sharpe": sharpe,
        "length": length,
        "candidates": int(len(sharpes)),
        "trial_variance": variance,
        "trials": io.OUTER_CANDIDATES,
        "dsr": dsr,
        "dsr_configurations": values["configurations"],
        "dsr_cumulative": values["cumulative"],
        "gate": io.DEFLATED_SHARPE_GATE,
        "passes": bool(_finite(dsr) and dsr >= io.DEFLATED_SHARPE_GATE),
    }


# The plan's seed stability on the numbers: the ensemble's mean paired
# difference and each single seed's. A seed whose mean is missing, zero or
# of the other sign than the ensemble's is a change; SEED_CHANGES or more
# changes, fewer than five seeds, or an ensemble mean that is missing or
# zero is not stable.
def seed_stability(reference: Any, seeds: Sequence[Any]) -> dict[str, Any]:
    """Return {"reference", "seeds", "sign_changes", "complete", "stable"}."""
    ref = _f(reference)
    values = [_f(v) for v in seeds]
    sign = float(np.sign(ref)) if math.isfinite(ref) else math.nan
    changes = sum(
        1
        for v in values
        if not (math.isfinite(v) and math.isfinite(sign) and float(np.sign(v)) == sign)
    )
    complete = len(values) == len(io.SEEDS)
    stable = bool(
        complete and math.isfinite(ref) and ref != 0.0 and changes < SEED_CHANGES
    )
    return {
        "reference": ref,
        "seeds": values,
        "sign_changes": int(changes),
        "complete": complete,
        "stable": stable,
    }


# --- T-I: the fill conventions ------------------------------------------------


# A fill-timing payload's "stage3_ti" block, refused when the payload is
# not a stage-3 T-I run.
def ti_block(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the payload's "stage3_ti" block."""
    block: Mapping[str, Any] | None = payload.get("stage3_ti")
    if not block:
        raise ValueError("not a stage-3 T-I fill-timing payload (no stage3_ti block)")
    return block


# The block's row for a convention and window, empty when absent.
def _ti_row(
    block: Mapping[str, Any] | None, convention: str, window: str
) -> Mapping[str, Any]:
    """Return the T-I row of (convention, window), {} when absent."""
    if not block:
        return {}
    row: Mapping[str, Any]
    for row in block.get("rows", []):
        if row.get("convention") == convention and row.get("window") == window:
            return row
    return {}


# The candidate-minus-control reading over every order side of a row.
def _per_order(row: Mapping[str, Any]) -> tuple[float, float]:
    """Return (bp per differing order, clustered t) of a T-I row."""
    versus = (row.get("versus_control") or {}).get("all") or {}
    return _f(versus.get("bp_per_differing_order")), _f(versus.get("clustered_t"))


# One run's reading of the T-I floors, per convention, from the block's
# rows: the model-window floor, the 2024-2026 sign and the per-order
# reading. A single run cannot REPLACE anything; `ti_verdict` reads the
# runs the plan names.
def ti_reading(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return {convention: this run's floor, reported and per-order reading}."""
    block = {"rows": list(rows)}
    out: dict[str, dict[str, Any]] = {}
    for convention in dict.fromkeys(r["convention"] for r in block["rows"]):
        model = _ti_row(block, convention, MODEL)
        later = _ti_row(block, convention, REPORTED)
        bp, t = _f(model.get("mean_daily_bp_vs_dip")), _f(model.get("hac_t_vs_dip"))
        reported = _f(later.get("mean_daily_bp_vs_dip"))
        per_bp, per_t = _per_order(model)
        floor = passes_floor(bp, t)
        out[convention] = {
            "model_bp": bp,
            "model_t": t,
            "passes_floor": floor,
            "reported_bp": reported,
            "not_worse_reported": bool(_finite(reported) and reported >= 0.0),
            "per_order_bp": per_bp,
            "per_order_t": per_t,
            "real_but_immaterial": bool(not floor and is_real(per_bp, per_t)),
        }
    return out


# Each T-I convention's model-window excess moments in one payload, for the
# deflated Sharpe's trial variance.
def ti_excess(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return {convention: excess moments} of the payload's model-window rows."""
    block = ti_block(payload)
    return {
        row["convention"]: dict(row.get("excess") or {})
        for row in block.get("rows", [])
        if row.get("window") == MODEL
    }


# The forecast files a block priced (sha256 per family) and its offsets: two
# blocks a verdict reads together must agree on both.
def _ti_identity(block: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    """Return ({family: sha256}, offsets) of a T-I block."""
    families = {
        family: (info or {}).get("sha256")
        for family, info in (block.get("families") or {}).items()
    }
    return families, int(block.get("offsets") or 0)


# Refuse to judge blocks that priced different forecast files or offsets.
def _same_ti_runs(blocks: Sequence[Mapping[str, Any]]) -> None:
    """Raise ValueError unless every block shares the first one's files and offsets."""
    if not blocks:
        return
    first = _ti_identity(blocks[0])
    for block in blocks[1:]:
        if _ti_identity(block) != first:
            raise ValueError(
                "the T-I runs priced different forecast files or offsets: "
                f"{first} against {_ti_identity(block)}"
            )


# Seed stability of one T-I convention: its model-window mean paired
# difference in each single-seed run against the ensemble run at the same
# cost. The five seed columns 0-4 must each be there exactly once.
def ti_seed_stability(
    reference: Mapping[str, Any] | None,
    seeds: Sequence[Mapping[str, Any]],
    convention: str,
) -> dict[str, Any]:
    """Return the seed-stability record of `convention` over the seed blocks."""
    ordered = sorted(seeds, key=lambda b: int(b.get("seed_column", -1)))
    columns = [int(b.get("seed_column", -1)) for b in ordered]
    ref = _ti_row(reference, convention, MODEL).get("mean_daily_bp_vs_dip")
    values = [
        _ti_row(b, convention, MODEL).get("mean_daily_bp_vs_dip") for b in ordered
    ]
    out = seed_stability(ref, values)
    complete = out["complete"] and columns == list(range(len(io.SEEDS)))
    out.update(
        {
            "columns": columns,
            "complete": complete,
            "stable": bool(out["stable"] and complete and reference is not None),
            "cost_bps": _f(reference.get("cost_bps")) if reference else math.nan,
        }
    )
    return out


# The T-I verdict per the plan's five criteria (see the module docstring),
# for every convention the cost runs priced. `runs` are the default-fill
# ensemble runs, one per cost in COSTS; `next_bar` the `--next-bar` runs;
# `seeds` the five single-seed runs (`--seed-column 0..4`, default fills,
# one cost that one of `runs` has); `others` the excess moments of the
# other outer candidates ({name: {"sharpe", "skew", "kurtosis",
# "length"}}, e.g. `outer_excess(s1_runs=...)`), which join the T-I
# candidates' own for the deflated Sharpe's trial variance. Payloads that
# mix forecast files or offsets, or runs passed in the wrong place, are
# refused.
def ti_verdict(  # noqa: C901 - five criteria and their evidence, in one pass
    runs: Sequence[Mapping[str, Any]],
    next_bar: Sequence[Mapping[str, Any]] = (),
    seeds: Sequence[Mapping[str, Any]] = (),
    others: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the T-I verdict: each convention's label and criteria, and the text."""
    by_cost: dict[float, Mapping[str, Any]] = {}
    for payload in runs:
        block = ti_block(payload)
        if block.get("next_bar"):
            raise ValueError(
                "a --next-bar run was passed as a cost run; pass it as next_bar"
            )
        if block.get("seed_column") is not None:
            raise ValueError(
                "a single-seed run was passed as a cost run; pass it in seeds"
            )
        cost = float(block["cost_bps"])
        if cost in by_cost:
            raise ValueError(f"two cost runs at {cost:g} bp")
        by_cost[cost] = block
    bars = [ti_block(p) for p in next_bar]
    for block in bars:
        if not block.get("next_bar") or block.get("seed_column") is not None:
            raise ValueError("a next_bar run must be an ensemble --next-bar run")
    seed_blocks = [ti_block(p) for p in seeds]
    for block in seed_blocks:
        if block.get("next_bar") or block.get("seed_column") is None:
            raise ValueError("a seed run must be a default-fill --seed-column run")
    _same_ti_runs([*by_cost.values(), *bars, *seed_blocks])
    seed_costs = {float(b["cost_bps"]) for b in seed_blocks}
    if len(seed_costs) > 1:
        raise ValueError("the seed runs must share one cost")
    seed_reference = by_cost.get(next(iter(seed_costs))) if seed_costs else None
    reference = by_cost.get(VERDICT_COST_BPS)
    excess: dict[str, Mapping[str, Any]] = dict(others or {})
    if reference is not None:
        excess.update(
            {
                r["convention"]: r.get("excess") or {}
                for r in reference.get("rows", [])
                if r.get("window") == MODEL
            }
        )
    priced = {c for block in by_cost.values() for c in block.get("conventions", [])}
    conventions = [c for c in TI_CANDIDATES if c in priced]
    candidates: dict[str, dict[str, Any]] = {}
    for convention in conventions:
        floor: dict[str, dict[str, Any]] = {}
        for cost in COSTS:
            row = _ti_row(by_cost.get(cost), convention, MODEL)
            bp, t = _f(row.get("mean_daily_bp_vs_dip")), _f(row.get("hac_t_vs_dip"))
            floor[cost_key(cost)] = {
                "priced": bool(row),
                "bp": bp,
                "t": t,
                "passes": passes_floor(bp, t),
            }
        floor_ok = all(v["passes"] for v in floor.values())
        next_bars = []
        for block in bars:
            row = _ti_row(block, convention, MODEL)
            bp, t = _f(row.get("mean_daily_bp_vs_dip")), _f(row.get("hac_t_vs_dip"))
            next_bars.append(
                {
                    "cost_bps": _f(block.get("cost_bps")),
                    "priced": bool(row),
                    "bp": bp,
                    "t": t,
                    "passes": passes_floor(bp, t),
                }
            )
        next_bar_ok = bool(next_bars) and all(v["passes"] for v in next_bars)
        reported = {
            cost_key(cost): _f(
                _ti_row(block, convention, REPORTED).get("mean_daily_bp_vs_dip")
            )
            for cost, block in sorted(by_cost.items())
        }
        later = reported.get(cost_key(VERDICT_COST_BPS), math.nan)
        reported_ok = bool(_finite(later) and later >= 0.0)
        dsr = deflated(excess, convention)
        stability = ti_seed_stability(seed_reference, seed_blocks, convention)
        per_bp, per_t = _per_order(_ti_row(reference, convention, MODEL))
        real = bool(not floor_ok and is_real(per_bp, per_t))
        passes = bool(
            floor_ok
            and next_bar_ok
            and reported_ok
            and dsr["passes"]
            and stability["stable"]
        )
        label = REPLACES if passes else (IMMATERIAL if real else RECORD)
        candidates[convention] = {
            "label": label,
            "floor": floor,
            "passes_floor": floor_ok,
            "next_bar": next_bars,
            "passes_next_bar": next_bar_ok,
            "reported_bp": reported,
            "not_worse_reported": reported_ok,
            "deflated": dsr,
            "seeds": stability,
            "per_order_bp": per_bp,
            "per_order_t": per_t,
            "real_but_immaterial": real,
            "below_cumulative_null_t": bool(
                not _finite(floor.get(cost_key(VERDICT_COST_BPS), {}).get("t"))
                or floor[cost_key(VERDICT_COST_BPS)]["t"]
                < expected_best_null_t(io.CUMULATIVE_TRIALS)
            ),
        }
    replaces = [c for c, v in candidates.items() if v["label"] == REPLACES]
    immaterial = [c for c, v in candidates.items() if v["label"] == IMMATERIAL]
    return {
        "plan": io.PLAN,
        "control": "dip_or_close",
        "costs": [cost_key(c) for c in COSTS],
        "costs_supplied": [cost_key(c) for c in sorted(by_cost)],
        "verdict_cost_bps": VERDICT_COST_BPS,
        "next_bar_runs": len(bars),
        "seed_runs": len(seed_blocks),
        "floors": _floors(),
        "candidates": candidates,
        "replaces": replaces,
        "immaterial": immaterial,
        "text": _ti_text(candidates, replaces, immaterial),
    }


# The floors a verdict applied, for its record.
def _floors() -> dict[str, Any]:
    """Return the plan's frozen floors as a record."""
    return {
        "FLOOR_BP": io.FLOOR_BP,
        "FLOOR_T": io.FLOOR_T,
        "HAC_LAG": io.HAC_LAG,
        "OUTER_CANDIDATES": io.OUTER_CANDIDATES,
        "DEFLATED_SHARPE_GATE": io.DEFLATED_SHARPE_GATE,
        "IMMATERIAL_BP_PER_ORDER": io.IMMATERIAL_BP_PER_ORDER,
        "IMMATERIAL_T": io.IMMATERIAL_T,
        "SEED_CHANGES": SEED_CHANGES,
        "expected_best_null_t": {
            label: expected_best_null_t(n) for label, n in TRIAL_COUNTS.items()
        },
    }


# A signed number for a verdict line, "n/a" when missing.
def _signed(x: Any, digits: int = 2) -> str:
    """Return `x` to `digits` decimals with its sign, "n/a" when missing."""
    return f"{float(x):+.{digits}f}" if _finite(x) else "n/a"


# The T-I verdict as one paragraph: each convention's floor per cost, the
# other criteria, its label; then which replace and which are immaterial.
def _ti_text(
    candidates: Mapping[str, Mapping[str, Any]],
    replaces: Sequence[str],
    immaterial: Sequence[str],
) -> str:
    """Return the T-I verdict text."""
    parts = []
    for name, info in candidates.items():
        floors = ", ".join(
            f"{k} bp {_signed(v['bp'], 1)} (t {_signed(v['t'])})"
            for k, v in info["floor"].items()
        )
        later = info["reported_bp"].get(cost_key(VERDICT_COST_BPS))
        seeds = info["seeds"]
        parts.append(
            f"{name}: model window {floors}; next-bar "
            f"{'holds' if info['passes_next_bar'] else 'fails'}; {REPORTED} "
            f"{_signed(later, 1)} bp/session; deflated Sharpe "
            f"{_signed(info['deflated']['dsr'])} at N = {io.OUTER_CANDIDATES}; seeds "
            f"{'stable' if seeds['stable'] else 'not stable'} "
            f"({seeds['sign_changes']} sign changes of {len(seeds['seeds'])}); "
            f"per differing order {_signed(info['per_order_bp'], 1)} bp "
            f"(t {_signed(info['per_order_t'])}) - {info['label']}"
        )
    if replaces:
        head = (
            f"{REPLACES}: {', '.join(replaces)} clear every criterion against "
            "dip_or_close; the board's rule changes only as a separate, registered "
            "live change with the operator's go-ahead"
        )
    else:
        head = (
            f"{RECORD}: no T-I convention clears every criterion against dip_or_close; "
            "the board keeps dip_or_close"
        )
    if immaterial:
        head += f". {IMMATERIAL}: {', '.join(immaterial)}"
    return head + (". " + "; ".join(parts) if parts else "")


# --- T-S1: the overlay --------------------------------------------------------


# An overlay payload's paired entry (the overlay against the control) for a
# window and cost, empty when absent.
def _s1_pair(payload: Mapping[str, Any], window: str, cost: float) -> Mapping[str, Any]:
    """Return the paired entry of the overlay on (window, cost), {} when absent."""
    pair: Mapping[str, Any]
    for pair in payload.get("paired", []):
        if (
            pair.get("line") == payload.get("line")
            and pair.get("against") == payload.get("control")
            and pair.get("window") == window
            and _f(pair.get("cost_bps")) == float(cost)
        ):
            return pair
    return {}


# An overlay payload's row for a line, window and cost, empty when absent.
def _s1_row(
    payload: Mapping[str, Any], line: str, window: str, cost: float
) -> Mapping[str, Any]:
    """Return the summary row of (line, window, cost), {} when absent."""
    row: Mapping[str, Any]
    for row in payload.get("rows", []):
        if (
            row.get("line") == line
            and row.get("window") == window
            and _f(row.get("cost_bps")) == float(cost)
        ):
            return row
    return {}


# One overlay run's reading of the criteria it can judge alone: the floor
# at each cost, the offsets above the control, the drawdown gap and the
# 2024-2026 sign (at the verdict cost), and the exposure reading beside
# them (the control's CAGR scaled to the overlay's invested share, as
# `profit_taking` reads it). The deflated Sharpe and the seeds need other
# runs (`s1_verdict`).
def s1_reading(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return this overlay run's reading of criteria 1-4."""
    line, control = str(payload.get("line")), str(payload.get("control"))
    offsets = int(payload.get("offsets") or 0)
    floor: dict[str, dict[str, Any]] = {}
    for cost in COSTS:
        pair = _s1_pair(payload, MODEL, cost)
        bp, t = _f(pair.get("mean_daily_bp")), _f(pair.get("hac_t"))
        floor[cost_key(cost)] = {
            "priced": bool(pair),
            "bp": bp,
            "t": t,
            "passes": passes_floor(bp, t),
        }
    row = _s1_row(payload, line, MODEL, VERDICT_COST_BPS)
    base = _s1_row(payload, control, MODEL, VERDICT_COST_BPS)
    above = int(row.get("offsets_above_control") or 0)
    gap = (_f(row.get("median_drawdown")) - _f(base.get("median_drawdown"))) * 100.0
    later = _f(_s1_pair(payload, REPORTED, VERDICT_COST_BPS).get("mean_daily_bp"))
    control_cagr = _f(base.get("median_cagr"))
    invested = 1.0 - _f(row.get("cash_share"))
    control_invested = 1.0 - _f(base.get("cash_share"))
    adjusted = (
        control_cagr * invested / control_invested
        if math.isfinite(control_invested)
        and control_invested > 0
        and math.isfinite(invested)
        else math.nan
    )
    return {
        "cost_bps": VERDICT_COST_BPS,
        "floor": floor,
        "passes_floor": all(v["passes"] for v in floor.values()),
        "offsets": offsets,
        "offsets_above_control": above,
        "passes_offsets": bool(offsets == OFFSETS and above >= OFFSETS_ABOVE),
        "drawdown_gap_points": gap,
        "passes_drawdown": bool(math.isfinite(gap) and gap >= -DRAWDOWN_POINTS),
        "reported_bp": later,
        "not_worse_reported": bool(_finite(later) and later >= 0.0),
        "cagr_points": (_f(row.get("median_cagr")) - control_cagr) * 100.0,
        "invested_share": invested,
        "control_invested_share": control_invested,
        "exposure_adjusted_points": (_f(row.get("median_cagr")) - adjusted) * 100.0,
    }


# An overlay payload's candidate name and its model-window excess moments
# at `cost`, for the deflated Sharpe's trial variance.
def s1_excess(
    payload: Mapping[str, Any], cost: float = VERDICT_COST_BPS
) -> dict[str, dict[str, Any]]:
    """Return {candidate: excess moments} of an overlay payload."""
    pair = _s1_pair(payload, MODEL, cost)
    if not pair:
        return {}
    return {str(payload["candidate"]): dict(pair.get("excess") or {})}


# The forecast file an overlay payload priced and its offsets: runs read
# together must agree on both.
def _s1_identity(payload: Mapping[str, Any]) -> tuple[Any, Any, int]:
    """Return (candidate, forecast sha256, offsets) of an overlay payload."""
    return (
        payload.get("candidate"),
        (payload.get("forecast") or {}).get("sha256"),
        int(payload.get("offsets") or 0),
    )


# Seed stability of the overlay: the model-window mean paired difference at
# the verdict cost in each single-seed run against the ensemble run's. The
# seed runs must be of the same candidate, file and offsets, and the five
# seed columns 0-4 must each be there exactly once.
def s1_seed_stability(
    reference: Mapping[str, Any], seeds: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Return the seed-stability record of an overlay run."""
    for payload in seeds:
        if payload.get("seed_column") is None:
            raise ValueError("a seed run must be a --seed-column run")
        if _s1_identity(payload) != _s1_identity(reference):
            raise ValueError(
                "the overlay seed runs priced another candidate, file or offsets: "
                f"{_s1_identity(payload)} against {_s1_identity(reference)}"
            )
    ordered = sorted(seeds, key=lambda p: int(p["seed_column"]))
    columns = [int(p["seed_column"]) for p in ordered]
    ref = _s1_pair(reference, MODEL, VERDICT_COST_BPS).get("mean_daily_bp")
    values = [
        _s1_pair(p, MODEL, VERDICT_COST_BPS).get("mean_daily_bp") for p in ordered
    ]
    out = seed_stability(ref, values)
    complete = out["complete"] and columns == list(range(len(io.SEEDS)))
    out.update(
        {
            "columns": columns,
            "complete": complete,
            "stable": bool(out["stable"] and complete),
            "cost_bps": VERDICT_COST_BPS,
        }
    )
    return out


# The T-S1 verdict per the plan: ADOPT (registered) when this run's
# reading passes criteria 1-4, its excess clears the deflated Sharpe gate
# among the supplied candidates (this one's and `others`, e.g.
# `outer_excess(...)` of the other families' overlay runs and the T-I
# 25 bp run), and it is seed-stable over `seeds`; else RECORD. The payload
# must be the ensemble run.
def s1_verdict(
    payload: Mapping[str, Any],
    seeds: Sequence[Mapping[str, Any]] = (),
    others: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the T-S1 verdict record of an overlay payload."""
    if payload.get("seed_column") is not None:
        raise ValueError("the verdict reads the ensemble run, not a --seed-column run")
    reading = s1_reading(payload)
    excess: dict[str, Mapping[str, Any]] = dict(others or {})
    excess.update(s1_excess(payload))
    candidate = str(payload.get("candidate"))
    dsr = deflated(excess, candidate)
    stability = s1_seed_stability(payload, seeds)
    passes = bool(
        reading["passes_floor"]
        and reading["passes_offsets"]
        and reading["passes_drawdown"]
        and reading["not_worse_reported"]
        and dsr["passes"]
        and stability["stable"]
    )
    label = ADOPT if passes else RECORD
    floors = ", ".join(
        f"{k} bp {_signed(v['bp'], 1)} (t {_signed(v['t'])})"
        for k, v in reading["floor"].items()
    )
    text = (
        f"{label}: {candidate} against {payload.get('control')} on the model window: "
        f"{floors}; {reading['offsets_above_control']}/{reading['offsets']} offsets "
        f"above the control (needs {OFFSETS_ABOVE}/{OFFSETS}); median worst drawdown "
        f"{_signed(reading['drawdown_gap_points'], 1)} pt against the control (within "
        f"{DRAWDOWN_POINTS:g}); {REPORTED} {_signed(reading['reported_bp'], 1)} "
        "bp/session; "
        f"deflated Sharpe {_signed(dsr['dsr'])} at N = {io.OUTER_CANDIDATES} over "
        f"{dsr['candidates']} candidates; seeds "
        f"{'stable' if stability['stable'] else 'not stable'} "
        f"({stability['sign_changes']} sign changes of {len(stability['seeds'])}). "
        f"Exposure-adjusted {_signed(reading['exposure_adjusted_points'], 1)} pt."
    )
    if passes:
        text += (
            " The overlay changes nothing by itself: it becomes a separate, registered "
            "live change only with the operator's go-ahead."
        )
    return {
        "plan": io.PLAN,
        "candidate": candidate,
        "label": label,
        "reading": reading,
        "deflated": dsr,
        "seeds": stability,
        "floors": {
            **_floors(),
            "OFFSETS": OFFSETS,
            "OFFSETS_ABOVE": OFFSETS_ABOVE,
            "DRAWDOWN_POINTS": DRAWDOWN_POINTS,
        },
        "text": text,
    }


# The excess moments of every outer candidate in the payloads given: the
# T-I conventions of each ensemble default-fill run at the verdict cost,
# and each ensemble overlay run's candidate - what `others` wants.
def outer_excess(
    ti_runs: Iterable[Mapping[str, Any]] = (),
    s1_runs: Iterable[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any]]:
    """Return {candidate: excess moments} gathered from T-I and T-S1 payloads."""
    out: dict[str, dict[str, Any]] = {}
    for payload in ti_runs:
        block = ti_block(payload)
        if (
            _f(block.get("cost_bps")) == VERDICT_COST_BPS
            and not block.get("next_bar")
            and block.get("seed_column") is None
        ):
            out.update(ti_excess(payload))
    for payload in s1_runs:
        if payload.get("seed_column") is None:
            out.update(s1_excess(payload))
    return out
