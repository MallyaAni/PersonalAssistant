"""Compare carried buys with exact same-session control before further fitting."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.cli import market_sequential_execution as primary
from backend.cli import market_sequential_first_available as saved
from carried_entry import account


# Authenticate inputs and require control parity on every phase before reporting.
def main():
    args = SimpleNamespace(snapshot=Path("/inputs/portfolio.npz"),
                           provenance=Path("/inputs/portfolio.json"),
                           cubes=Path("/cubes"), prepared=Path("/prepared"))
    panel, grades, eligible, cubes, dataset = primary.load_inputs(args)
    _, comparisons = saved.load_primary(
        panel, dataset, Path("/primary/evaluation.json"),
        Path("/primary/evaluation-proof.json"))
    opens = primary.session_opens(panel, cubes)
    first = primary.comparison_first(panel)
    support = primary.execution_support(panel, first)
    output = Path("/output")
    identity = {"source": {name: primary.sha256(Path("/experiment") / name)
                           for name in ("carried_entry.py", "run_carried_entry.py")},
                "primary_sha256": saved.PRIMARY_SHA256,
                "prepared_sha256": primary.sha256(args.prepared / "prepared.npz"),
                "cost_bps": 0, "adoption_eligible": False}
    with (output / "identity.json").open("x") as handle:
        json.dump(identity, handle, indent=2)
    for phase in range(20):
        results = {}
        for carry in (False, True):
            result = account(panel, grades, eligible, dataset, opens, first,
                             phase, support, carry)
            results[carry] = result
            evidence = primary.account_evidence(
                result, comparisons[(0, phase)],
                panel.adj_close[:, panel.tickers.index("SPY")])
            name = "carry" if carry else "control"
            with (output / f"{name}-{phase}.json").open("x") as handle:
                json.dump(evidence, handle, allow_nan=False)
        original = comparisons[(0, phase)]["control"]
        for key in ("nav", "cash", "turnover", "fees", "exposure"):
            if not np.array_equal(results[False][key], original[key]):
                raise ValueError(f"Control parity failure {phase}/{key}")
        print(json.dumps({"phase": phase, "control_parity": True,
                          "control_gain": float(results[False]["nav"][-1] - 1),
                          "carry_gain": float(results[True]["nav"][-1] - 1)}),
              flush=True)


if __name__ == "__main__":
    main()
