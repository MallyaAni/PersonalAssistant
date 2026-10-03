"""Frozen-path monthly continuation fit and matched funded timing evaluation."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np

from backend.cli.market_learned_entry import inputs, sha256, write_json
from backend.market import learned_entry_evaluation as scoring
from backend.market import learned_entry_models as original
from backend.market import sequential_execution_models as models
from backend.market import sequential_execution_replay as replay
from backend.market.fill_timing import session_scale

BASELINE_SHA256 = "f340f1329ec67645ba4f534eb9c34afde5cee5e47d85ce88dab7de87ab72f608"
START = np.datetime64("2018-02-01", "D")
END = np.datetime64("2026-09-30", "D")
COSTS = (0, 10, 25)
CURVES = ("nav", "cash", "exposure", "turnover", "fees")
FIT_REVISION = "b37c2b689b903f7b37e506041ed542d77af175af"
FIT_CLI_SHA256 = "9f81cb4f036b0d1b012d1dba744fe76349c2279e6e200c813ccfd9f014da3d4e"
CLI_FILE = "backend/cli/market_sequential_execution.py"


# Pin the whole research execution boundary, including the unchanged target and ledger.
def source_identity():
    root = Path(__file__).resolve().parents[2]
    names = (
        "backend/cli/market_sequential_execution.py",
        "backend/cli/market_learned_entry.py",
        "backend/market/sequential_execution_models.py",
        "backend/market/sequential_execution_replay.py",
        "backend/market/learned_execution_timing.py",
        "backend/market/learned_entry_data.py",
        "backend/market/learned_entry_models.py",
        "backend/market/learned_intraday_moments.py",
        "backend/market/learned_entry_evaluation.py",
        "backend/market/learned_entry_policy.py",
        "backend/market/allocation_evaluation.py",
        "backend/market/open_source_portfolio.py",
        "backend/market/panel.py",
        "backend/market/sip_cube.py",
        "backend/market/fill_timing.py",
        "backend/market/entry_timing.py",
        "backend/market/calendar.py",
        "backend/market/data/nyse_historical_sessions.json",
        "backend/market/data/nyse_holidays.json",
        "backend/market/data/nyse_early_closes.json",
        "backend/market/data/fomc_decisions.csv",
        "backend/agents/trading/desk/policy_v5.py",
        "backend/agents/trading/desk/simulate.py",
        "docs/research/sequential-execution-plan-2026-10-02.md",
        "docs/research/learned-entry-risk-plan-2026-10-02.md",
        "docs/research/learned-linear-plan-2026-10-02.md",
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "source_revision": os.environ.get(
            "ANIOS_RESEARCH_SOURCE_REVISION",
            revision.stdout.strip() if revision.returncode == 0 else "unavailable",
        ),
        "files": {name: sha256(root / name) for name in names},
    }


# Record the actual runtime with unavailable image identity explicitly disclosed.
def runtime_identity():
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "image_id": os.environ.get("ANIOS_RESEARCH_IMAGE_ID", "unavailable"),
        "container_hostname": os.environ.get("HOSTNAME", "unavailable"),
        "numpy": np.__version__,
        "thread_limits": {
            name: os.environ.get(name, "unavailable")
            for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")
        },
    }


# Require existing prepared evidence before the reusable loader can write anything.
def load_inputs(args):
    if (
        not (args.prepared / "prepared.npz").is_file()
        or not (args.prepared / "prepared.json").is_file()
    ):
        raise ValueError("Existing original prepared archive and receipt required")
    before = {
        name: sha256(args.prepared / name) for name in ("prepared.npz", "prepared.json")
    }
    result = inputs(args.snapshot, args.provenance, args.cubes, args.prepared)
    if before != {name: sha256(args.prepared / name) for name in before}:
        raise ValueError("Read-only prepared inputs changed while loading")
    return result


# Align the opening reference with observed prices using the frozen unit conversion.
def session_opens(panel, cubes):
    result = np.full(panel.adj_close.shape, np.nan)
    for stock, ticker in enumerate(panel.tickers):
        cube = cubes.get(ticker)
        if cube is None:
            continue
        rows, available, scale = session_scale(
            cube, panel.dates, panel.adj_close[:, stock]
        )
        value = cube.open[:, 0] * scale
        known = available & np.isfinite(value) & (value > 0)
        result[rows[known], stock] = value[known]
    return result


# Fit the frozen monthly model once, recording exact forecasts and execution source.
def fit(dataset, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    source = source_identity()
    completed = output / "fit-complete.json"
    if completed.exists():
        forecasts, manifest, _ = fitted(dataset, output)
        return forecasts, manifest
    forecasts, manifest = models.walk_forward(dataset, output / "models")
    if source != source_identity():
        raise ValueError("Source changed during model fitting")
    write_json(
        completed,
        {
            "status": "fitted",
            "source": source,
            "runtime": runtime_identity(),
            "manifest_sha256": sha256(output / "models/manifest.json"),
            "forecast_sha256": sha256(output / "models/predictions.npz"),
            "forecast_array_sha256": original._array_hash(forecasts),
            "identity_sha256": original._json_hash(models.identity(dataset)),
        },
    )
    return forecasts, manifest


# Permit only the pinned evaluation-boundary correction, never altered model inputs.
def validate_fit_source(training, current, *, evaluation_only=False):
    if training == current:
        return
    old, new = training.get("files", {}), current.get("files", {})
    accepted = (
        evaluation_only
        and training.get("source_revision") == FIT_REVISION
        and old.get(CLI_FILE) == FIT_CLI_SHA256
        and old.keys() == new.keys()
        and all(old[key] == new[key] for key in old if key != CLI_FILE)
    )
    if not accepted:
        raise ValueError("Fitted execution source changed")


# Authenticate completed model bytes, with an explicit evaluation-only source lineage.
def fitted(dataset, output, *, evaluation_only=False):
    output = Path(output)
    receipt = json.loads((output / "fit-complete.json").read_text())
    if receipt["status"] != "fitted":
        raise ValueError("Fitted execution source changed")
    validate_fit_source(
        receipt["source"], source_identity(), evaluation_only=evaluation_only
    )
    if receipt["manifest_sha256"] != sha256(output / "models/manifest.json") or receipt[
        "forecast_sha256"
    ] != sha256(output / "models/predictions.npz"):
        raise ValueError("Completed fit artifact changed")
    forecasts, manifest = models.validate_saved(output / "models", dataset)
    if receipt["forecast_array_sha256"] != original._array_hash(forecasts) or receipt[
        "identity_sha256"
    ] != original._json_hash(models.identity(dataset)):
        raise ValueError("Completed forecast or input identity changed")
    return forecasts, manifest, receipt


# Establish the registered comparison period without selecting forecast dates.
def comparison_first(panel):
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    matches = np.flatnonzero(dates == START)
    if len(matches) != 1 or matches[0] == 0 or dates[-1] != END:
        raise ValueError(
            "Fixed2018-02-01 through2026-09-30 comparison calendar required"
        )
    return int(matches[0])


# Validate execution clocks only for the registered account cohort, not context warmup.
def execution_support(panel, first):
    supported = np.zeros(len(panel.dates), dtype=bool)
    supported[first:] = replay.supported_sessions(panel.dates[first:])
    return supported


# Validate saved ETF wealth and fees against the original entry and daily marks.
def _reference(panel, first, curves, name, cost):
    expected_shape = (len(panel.dates) - first + 1,)
    result = {key: np.asarray(curves[key], dtype=np.float64) for key in CURVES}
    if any(
        value.shape != expected_shape or not np.isfinite(value).all()
        for value in result.values()
    ):
        raise ValueError("Saved benchmark curve shape or values invalid")
    stock = panel.tickers.index(name)
    opening = (
        panel.open[first, stock]
        * panel.adj_close[first, stock]
        / panel.close[first, stock]
    )
    shares = 1 / (opening * (1 + cost / 1e4))
    expected_nav = np.r_[1.0, panel.adj_close[first:, stock] * shares]
    if (
        not np.isfinite(opening)
        or opening <= 0
        or not np.allclose(result["nav"], expected_nav, rtol=1e-12, atol=1e-12)
    ):
        raise ValueError("Benchmark prices or NAV1 units differ from original panel")
    expected = {
        "cash": np.r_[1.0, np.zeros(expected_shape[0] - 1)],
        "exposure": np.r_[0.0, np.ones(expected_shape[0] - 1)],
        "turnover": np.zeros(expected_shape),
        "fees": np.zeros(expected_shape),
    }
    expected["turnover"][1] = shares * opening
    expected["fees"][1] = 1 - shares * opening
    if any(
        not np.allclose(result[key], value, rtol=1e-12, atol=1e-12)
        for key, value in expected.items()
    ):
        raise ValueError("Saved benchmark costs or cash contract changed")
    result["dates"] = panel.dates[first - 1 :].copy()
    return result


# Reuse only the authenticated SPY/QQQ curves, never the old auction-terminal controls.
def references(panel, first, baseline):
    if sha256(baseline) != BASELINE_SHA256:
        raise ValueError("Original completed baseline report SHA required")
    report = json.loads(Path(baseline).read_text())
    if report["common_start"] != str(START) or report["common_end"] != str(END):
        raise ValueError("Original benchmark comparison period changed")
    costs = report["costs"]
    if [row["cost_bps"] for row in costs] != list(COSTS):
        raise ValueError("Original benchmark fixed costs changed")
    return {
        cost: {
            name: _reference(panel, first, row["curves"][name], name, cost)
            for name in ("SPY", "QQQ")
        }
        for cost, row in zip(COSTS, costs, strict=True)
    }


# Preserve complete accounting, score and attempted-action evidence for each phase.
def account_evidence(account, comparisons, spy):
    return {
        "score": scoring.score(account, comparisons, spy),
        "curves": {key: account[key].tolist() for key in CURVES},
        "counts": account["counts"],
        "stocks": account["stocks"],
        "intent_trace": account["intent_trace"],
    }


# Measure both funded books and their paired wealth without any phase or cost selection.
def evaluate_phase(
    panel,
    grades,
    eligible,
    dataset,
    forecasts,
    opens,
    first,
    cost,
    phase,
    refs,
    supported,
):
    accounts = {
        method: replay.account(
            panel,
            grades,
            eligible,
            dataset,
            forecasts,
            opens,
            first,
            cost,
            phase,
            method=method,
            supported_days=supported,
        )
        for method in ("candidate", "control")
    }
    spy = panel.adj_close[:, panel.tickers.index("SPY")]
    result = {"phase": phase}
    for method, account in accounts.items():
        other = "control" if method == "candidate" else "candidate"
        result[method] = account_evidence(
            account, {**refs, other: accounts[other]}, spy
        )
    result["paired_gain_initial_nav_units"] = float(
        accounts["candidate"]["nav"][-1] - accounts["control"]["nav"][-1]
    )
    return result


# Authenticate resumable phase evidence and reject gaps or altered completed bytes.
def _progress(output, identity):
    path = output / "evaluation-progress.json"
    receipt = output / "evaluation-progress-proof.json"
    if not path.exists():
        return {"identity": identity, "phases": []}
    proof = json.loads(receipt.read_text())
    if sha256(path) != proof["report_sha256"] or proof["identity"] != identity:
        raise ValueError("Saved evaluation progress bytes changed")
    report = json.loads(path.read_text())
    expected = [(cost, phase) for cost in COSTS for phase in range(20)]
    actual = [(row["cost_bps"], row["phase"]) for row in report["phases"]]
    if report["identity"] != identity or actual != expected[: len(actual)]:
        raise ValueError("Saved evaluation identity or phase sequence changed")
    return report


# Summarize every phase together without choosing the strongest phase or regime.
def phase_summary(phases):
    summary = []
    for cost in COSTS:
        rows = [row for row in phases if row["cost_bps"] == cost]
        paired = np.array([row["paired_gain_initial_nav_units"] for row in rows])
        if len(rows) != 20:
            raise ValueError("All20 paired phases required for completion")
        summary.append(
            {
                "cost_bps": cost,
                "phases": 20,
                "positive_paired_phases": int((paired > 0).sum()),
                "median_paired_gain_initial_nav_units": float(np.median(paired)),
                "minimum_paired_gain_initial_nav_units": float(paired.min()),
                "maximum_paired_gain_initial_nav_units": float(paired.max()),
                "median_total_net_gain": {
                    method: float(
                        np.median(
                            [
                                row[method]["score"]["windows"][0]["total_net_gain"]
                                for row in rows
                            ]
                        )
                    )
                    for method in ("candidate", "control")
                },
            }
        )
    return summary


# Publish report bytes before their checksum to authenticate completion evidence.
def _report(output, name, report):
    path = output / f"{name}.json"
    write_json(path, report)
    write_json(
        output / f"{name}-proof.json",
        {"report_sha256": sha256(path), "identity": report["identity"]},
    )


# Evaluate every fixed paired phase once, using saved forecasts and original ETF curves.
def evaluate(panel, grades, eligible, cubes, dataset, output, baseline):
    output = Path(output)
    forecasts, _, receipt = fitted(dataset, output, evaluation_only=True)
    first = comparison_first(panel)
    refs = references(panel, first, baseline)
    opens = session_opens(panel, cubes)
    supported = execution_support(panel, first)
    identity = {
        "source": source_identity(),
        "training_source": receipt["source"],
        "fit_receipt_sha256": sha256(output / "fit-complete.json"),
        "forecast_sha256": receipt["forecast_sha256"],
        "baseline_sha256": sha256(baseline),
        "data": dataset["provenance"],
        "session_open_sha256": original._array_hash(opens),
        "supported_sessions_sha256": original._array_hash(supported),
        "common_start": str(START),
        "common_end": str(END),
        "cost_bps": list(COSTS),
        "phases": list(range(20)),
    }
    completed = output / "evaluation.json"
    if completed.exists():
        proof = json.loads((output / "evaluation-proof.json").read_text())
        report = json.loads(completed.read_text())
        expected_phases = [(cost, phase) for cost in COSTS for phase in range(20)]
        actual_phases = [
            (row["cost_bps"], row["phase"]) for row in report.get("phases", [])
        ]
        if (
            proof["report_sha256"] != sha256(completed)
            or report.get("identity") != identity
            or proof["identity"] != identity
            or report.get("status") != "complete_reused_conditional_research"
            or actual_phases != expected_phases
            or report.get("adoption_eligible") is not False
        ):
            raise ValueError("Completed evaluation differs; refusing overwrite")
        return report
    report = _progress(output, identity)
    report.update(
        policy=replay.POLICY,
        control=replay.CONTROL,
        status="reused_conditional_research",
        adoption_eligible=False,
        evaluation_correction=(
            "Validate exchange clocks only for the preregistered execution cohort; "
            "2015 context warmup is outside reviewed calendar coverage and has "
            "zero valid training prefixes. No model, data, date or fit changed."
        ),
        runtime=runtime_identity(),
        dates=panel.dates[first - 1 :].astype(str).tolist(),
        limitations=[
            "Reused current-vintage diagnostic; holdout is not untouched.",
            "Next-open proxies do not prove broker or midpoint fills.",
            "Unsupported early closes and missing opportunities are retained.",
            "FractionalNAV1 component ledger; full historical live parity unavailable.",
            "Session-scale converts common units; crossings use causal session ratios.",
        ],
        benchmarks={
            str(cost): {
                name: {
                    "curves": {key: account[key].tolist() for key in CURVES},
                    "score": scoring.score(
                        account, {}, panel.adj_close[:, panel.tickers.index("SPY")]
                    ),
                }
                for name, account in refs[cost].items()
            }
            for cost in COSTS
        },
    )
    completed_count = len(report["phases"])
    for index, (cost, phase) in enumerate((c, p) for c in COSTS for p in range(20)):
        if index < completed_count:
            continue
        row = evaluate_phase(
            panel,
            grades,
            eligible,
            dataset,
            forecasts,
            opens,
            first,
            cost,
            phase,
            refs[cost],
            supported,
        )
        row["cost_bps"] = cost
        report["phases"].append(row)
        if source_identity() != identity["source"]:
            raise ValueError("Source changed during evaluation")
        _report(output, "evaluation-progress", report)
        print(
            json.dumps(
                {
                    "status": "evaluated_phase",
                    "cost_bps": cost,
                    "phase": phase,
                    "paired_gain_initial_nav_units": row[
                        "paired_gain_initial_nav_units"
                    ],
                }
            ),
            flush=True,
        )
    report["status"] = "complete_reused_conditional_research"
    report["phase_summary"] = phase_summary(report["phases"])
    _report(output, "evaluation", report)
    return report


# Require explicit frozen inputs, prepared evidence, baseline and output paths.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "provenance", "cubes", "prepared", "output", "baseline"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--stage", choices=("fit", "evaluate"), required=True)
    args = parser.parse_args()
    panel, grades, eligible, cubes, dataset = load_inputs(args)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.stage == "fit":
        fit(dataset, args.output)
    else:
        evaluate(panel, grades, eligible, cubes, dataset, args.output, args.baseline)


if __name__ == "__main__":
    main()
