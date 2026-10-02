"""Evaluate isolated specialist artifacts without orders, inference or source writes."""

import argparse
import hashlib
import importlib
import json
import subprocess
from pathlib import Path

from backend.market import open_source_forecast_evaluation as frozen
from backend.market.open_source_portfolio import load_snapshot
from backend.market.specialist_study import cohort_panel, evaluate, summary
from backend.market.specialist_timing_account import LINES, account, load_cases


# Require complete model evidence and write one fresh funded diagnostic artifact.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("portfolio", type=Path)
    parser.add_argument("provenance", type=Path)
    parser.add_argument("--baselines", nargs=4, type=Path, required=True)
    parser.add_argument("--joint", nargs=2, type=Path, required=True)
    parser.add_argument("--selector-history", type=Path)
    parser.add_argument("--timing-manifest", type=Path)
    parser.add_argument("--timing-paths", type=Path)
    parser.add_argument("--timing-basis", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    timing_paths = [args.timing_manifest, args.timing_paths, args.timing_basis]
    if any(timing_paths) and not all(timing_paths):
        parser.error("All three timing evidence files are required together")
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite a source or prior result")
    raw = args.input.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    if source_hash != frozen.SOURCE_SHA256:
        raise ValueError("Frozen original source bytes are required")
    panel, grades, eligible, provenance = load_snapshot(args.portfolio, args.provenance)
    baselines = [json.loads(p.read_bytes()) for p in args.baselines]
    joints = [json.loads(p.read_bytes()) for p in args.joint]
    history = (
        json.loads(args.selector_history.read_bytes()) if args.selector_history else []
    )
    result = evaluate(
        json.loads(raw),
        baselines,
        joints,
        panel,
        grades,
        eligible,
        provenance,
        source_sha256=source_hash,
        selector_history=history,
    )
    if all(timing_paths):
        cases, receipt = load_cases(*timing_paths)
        expanded, expanded_grades, expanded_members = cohort_panel(
            json.loads(raw), panel, grades, eligible
        )
        common, common_grades, common_members = frozen.common_panel(
            json.loads(raw), expanded, expanded_grades, expanded_members
        )
        regimes = [row["scenario"] for row in result["decisions"]]
        regimes.append({"key": None})
        timing_results = {}
        for line in LINES:
            timing_results[line] = {}
            for cost in frozen.COSTS:
                ledger = account(
                    common,
                    common_grades,
                    common_members,
                    cases,
                    line=line,
                    cost_bps=cost,
                )
                timing_results[line][str(cost)] = {
                    **summary(ledger, regimes),
                    "receipts": ledger["decisions"],
                    "no_funding_retry": True,
                    "no_sale_recycling": True,
                }
        result["timing"] = {
            "provenance": receipt,
            "costs": timing_results,
            "adoption_eligible": False,
            "research_units": "fractional_adjusted",
            "exact_live_strategy": False,
            "fill_proof": False,
        }
        result["timing_account_status"] = "funded_chronological_proxy_comparison"
    implementation = [
        "backend/cli/market_specialist_study.py",
        "backend/market/specialist_study.py",
        "backend/market/specialist_forecasts.py",
        "backend/market/specialist_risk.py",
        "backend/market/specialist_timing.py",
        "backend/market/specialist_timing_account.py",
        "backend/market/open_source_forecasts.py",
        "backend/market/open_source_forecast_evaluation.py",
        "backend/market/open_source_portfolio.py",
        "backend/market/allocation_replay.py",
        "backend/market/allocation_controls.py",
        "backend/market/allocation_evaluation.py",
        "backend/agents/trading/desk/policy_v5.py",
        "backend/agents/trading/desk/simulate.py",
    ]
    result["evaluation_source"] = {
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "files": {
            path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in implementation
        },
        "runtime": {
            name: str(importlib.import_module(module).__version__)
            for name, module in (
                ("numpy", "numpy"),
                ("cvxpy", "cvxpy"),
                ("skfolio", "skfolio"),
                ("scikit-learn", "sklearn"),
                ("clarabel", "clarabel"),
            )
        },
    }
    paths = [args.input, args.portfolio, args.provenance, *args.baselines, *args.joint]
    if args.selector_history:
        paths.append(args.selector_history)
    paths.extend(path for path in timing_paths if path)
    result["file_sha256"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
    }
    with args.output.open("x") as output:
        output.write(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )


if __name__ == "__main__":
    main()
