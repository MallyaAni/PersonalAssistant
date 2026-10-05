"""Fit and evaluate one registered entry candidate against frozen zero-cost controls."""

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from backend.cli import market_sequential_execution as primary
from backend.cli import market_sequential_first_available as saved
from run_timing_side_ablation import account

from rule_relative_entry import walk_forward


# Authenticate original inputs, fit the candidate once and persist all twenty books.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eligible-only", action="store_true")
    options = parser.parse_args()
    args = SimpleNamespace(
        snapshot=Path("/inputs/portfolio.npz"),
        provenance=Path("/inputs/portfolio.json"),
        cubes=Path("/cubes"),
        prepared=Path("/prepared"),
    )
    panel, grades, eligible, cubes, dataset = primary.load_inputs(args)
    report, comparisons = saved.load_primary(
        panel,
        dataset,
        Path("/primary/evaluation.json"),
        Path("/primary/evaluation-proof.json"),
    )
    output = Path("/output")
    models = output / "models"
    models.mkdir()
    identity = {
        "original_report_sha256": saved.PRIMARY_SHA256,
        "original_source": report["identity"]["source"],
        "prepared_sha256": primary.sha256(args.prepared / "prepared.npz"),
        "source": {
            name: primary.sha256(Path("/experiment") / name)
            for name in (
                "rule_relative_entry.py",
                "run_rule_relative_entry.py",
                "run_timing_side_ablation.py",
            )
        },
        "cost_bps": 0,
        "eligible_only": options.eligible_only,
        "adoption_eligible": False,
    }
    with (output / "identity.json").open("x") as handle:
        json.dump(identity, handle, indent=2)
    opens = primary.session_opens(panel, cubes)
    forecasts = walk_forward(dataset, opens, models, eligible_only=options.eligible_only)
    first = primary.comparison_first(panel)
    for phase in range(20):
        result = account(
            panel, grades, eligible, dataset, forecasts, opens, first, phase, "buy"
        )
        evidence = primary.account_evidence(
            result,
            comparisons[(0, phase)],
            panel.adj_close[:, panel.tickers.index("SPY")],
        )
        evidence.update(
            side="buy", phase=phase, cost_bps=0, primary_sha256=saved.PRIMARY_SHA256
        )
        path = output / f"buy-{phase}.json"
        with path.open("x") as handle:
            json.dump(evidence, handle, allow_nan=False)
        saved._saved_account(json.loads(path.read_text()), result["dates"])
        print(
            json.dumps(
                {
                    "phase": phase,
                    "gain": float(result["nav"][-1] - 1),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
