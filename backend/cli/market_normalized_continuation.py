"""Fit one fixed nonlinear timing model and reuse audited comparison accounts."""

import argparse
import json
from pathlib import Path

import numpy as np

from backend.cli import market_sequential_execution as primary
from backend.cli import market_sequential_first_available as saved
from backend.cli.market_learned_entry import sha256, write_json
from backend.market import normalized_continuation as model
from backend.market import sequential_execution_replay as replay

FIRST_SHA = "9cac7247ffe28847a1d83ffa7a976f575a5d687115e71163102d7b06a78b15c8"
REPORT = "normalized-evaluation"


# Pin the complete unchanged account boundary and this experiment's executable code.
def source_identity():
    identity = saved.source_identity()
    root = Path(__file__).resolve().parents[2]
    identity["files"].update(
        {
            name: sha256(root / name)
            for name in (
                "backend/cli/market_normalized_continuation.py",
                "backend/market/normalized_continuation.py",
                "docs/research/normalized-continuation-plan-2026-10-03.md",
            )
        }
    )
    return identity


# Reuse all sixty first-available books after checking their fixed original bytes.
def first_accounts(path, dates, provenance):
    if sha256(path) != FIRST_SHA:
        raise ValueError("Original completed first-available report required")
    report = json.loads(Path(path).read_text())
    expected = [(cost, phase) for cost in primary.COSTS for phase in range(20)]
    if (
        report["identity"]["data"] != provenance
        or report["dates"] != dates.astype(str).tolist()
        or [(r["cost_bps"], r["phase"]) for r in report["phases"]] != expected
    ):
        raise ValueError("First-available input identity or account schedule changed")
    return {
        (r["cost_bps"], r["phase"]): saved._saved_account(r["first_available"], dates)
        for r in report["phases"]
    }


# Preserve paired compounded wealth in each declared window without choosing phases.
def summarize(rows):
    output = []
    for cost in primary.COSTS:
        phases = [r for r in rows if r["cost_bps"] == cost]
        if len(phases) != 20:
            raise ValueError("All twenty phases required")
        windows = []
        for position, label in enumerate(
            ("all", "2018-20", "2021-26", "reused_recent")
        ):
            pairs = {}
            for name in ("control", "linear", "first_available", "SPY", "QQQ"):
                values = np.array(
                    [
                        r["candidate"]["score"]["windows"][position]["total_net_gain"]
                        - r["comparison_scores"][name]["windows"][position][
                            "total_net_gain"
                        ]
                        for r in phases
                    ]
                )
                pairs[name] = {
                    "median_gain_difference": float(np.median(values)),
                    "positive_phases": int((values > 0).sum()),
                    "minimum": float(values.min()),
                    "maximum": float(values.max()),
                }
            keys = (
                "total_net_gain",
                "cagr",
                "max_drawdown_loss",
                "sharpe",
                "turnover_one_way",
                "fees_initial_nav_units",
            )
            windows.append(
                {
                    "window": label,
                    "paired": pairs,
                    "median_candidate": {
                        key: float(
                            np.median(
                                [
                                    r["candidate"]["score"]["windows"][position][key]
                                    for r in phases
                                ]
                            )
                        )
                        for key in keys
                    },
                }
            )
        output.append({"cost_bps": cost, "phases": 20, "windows": windows})
    return output


# Replay new books against authenticated saved timing controls and ETF curves.
def evaluate(args, loaded, predictions, manifest, comparisons):
    panel, grades, eligible, cubes, dataset = loaded
    output = args.output
    first = primary.comparison_first(panel)
    dates = panel.dates[first - 1 :]
    first_books = first_accounts(args.first_available, dates, dataset["provenance"])
    opens = primary.session_opens(panel, cubes)
    supported = primary.execution_support(panel, first)
    identity = {
        "source": source_identity(),
        "model_identity": manifest["identity_sha256"],
        "forecast_sha256": manifest["forecast"]["sha256"],
        "primary_sha256": saved.PRIMARY_SHA256,
        "first_sha256": FIRST_SHA,
        "data": dataset["provenance"],
        "cost_bps": list(primary.COSTS),
        "phases": list(range(20)),
        "dates": dates.astype(str).tolist(),
    }
    complete = saved._read_report(output, REPORT, identity)
    if complete is not None:
        if (
            complete["status"] != "complete_conditional_research"
            or len(complete["phases"]) != 60
            or complete["adoption_eligible"] is not False
        ):
            raise ValueError("Invalid completed candidate comparison")
        return complete
    report = saved._read_report(output, REPORT + "-progress", identity)
    if report is None:
        report = {
            "identity": identity,
            "status": "running",
            "policy": model.POLICY,
            "adoption_eligible": False,
            "runtime": primary.runtime_identity(),
            "phases": [],
            "limitations": [
                "Current-vintage conditional fixed-v5-book research; "
                "not full live parity.",
                "Recent32sessions reused; no untouched-test claim.",
                "Sparse-clock interpolation; clocks20-23 beyond training clock19.",
                "Volatility scale is not calibrated confidence or a distribution.",
                "Early closes unsupported; next-open proxies are not broker fills.",
                "Phase accounts overlap and are not independent samples.",
                "Grade-B hold-versus-sell selection is unchanged.",
            ],
        }
    spy = panel.adj_close[:, panel.tickers.index("SPY")]
    schedule = [(cost, phase) for cost in primary.COSTS for phase in range(20)]
    for cost, phase in schedule[len(report["phases"]) :]:
        previous = comparisons[(cost, phase)]
        refs = {
            "control": previous["control"],
            "linear": previous["candidate"],
            "first_available": first_books[(cost, phase)],
            "SPY": previous["SPY"],
            "QQQ": previous["QQQ"],
        }
        account = replay.account(
            panel,
            grades,
            eligible,
            dataset,
            predictions,
            opens,
            first,
            cost,
            phase,
            method="candidate",
            supported_days=supported,
        )
        account["policy"] = model.POLICY
        row = {
            "cost_bps": cost,
            "phase": phase,
            "candidate": primary.account_evidence(account, refs, spy),
            "comparison_scores": {
                name: primary.scoring.score(value, {"candidate": account}, spy)
                for name, value in refs.items()
            },
        }
        report["phases"].append(row)
        if source_identity() != identity["source"]:
            raise ValueError("Source changed during candidate account replay")
        saved._save_report(output, REPORT + "-progress", report)
        print(
            json.dumps({"status": "candidate_phase", "cost_bps": cost, "phase": phase}),
            flush=True,
        )
    report.update(
        status="complete_conditional_research", summary=summarize(report["phases"])
    )
    saved._save_report(output, REPORT, report)
    return report


# Preflight all original data and comparison bytes before any new model fit or replay.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "snapshot",
        "provenance",
        "cubes",
        "prepared",
        "teacher",
        "output",
        "primary",
        "primary-proof",
        "first-available",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    loaded = primary.load_inputs(args)
    panel, _, _, _, dataset = loaded
    _, comparisons = saved.load_primary(
        panel, dataset, args.primary, args.primary_proof
    )
    first_accounts(
        args.first_available,
        panel.dates[primary.comparison_first(panel) - 1 :],
        dataset["provenance"],
    )
    source = source_identity()
    predictions, manifest = model.walk_forward(
        dataset, args.teacher, args.output / "models"
    )
    if source_identity() != source:
        raise ValueError("Source changed during nonlinear fitting")
    write_json(
        args.output / "fit-complete.json",
        {
            "source": source,
            "runtime": primary.runtime_identity(),
            "model_identity": manifest["identity_sha256"],
            "model_manifest_sha256": sha256(args.output / "models/manifest.json"),
        },
    )
    evaluate(args, loaded, predictions, manifest, comparisons)


if __name__ == "__main__":
    main()
