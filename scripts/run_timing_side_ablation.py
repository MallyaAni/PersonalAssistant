"""Run two zero-cost side interventions using authenticated frozen research code."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.cli import market_sequential_execution as primary
from backend.cli import market_sequential_first_available as saved
from backend.market import sequential_execution_models as models
from backend.market import sequential_execution_replay as replay
from backend.market.learned_execution_timing import replay_account


# Apply the learned selector only to the declared side, retaining the other gate.
def select_side(learned_side, forecasts, opened, observed, delta, known,
                pending, final, counts):
    if learned_side not in ("buy", "sell"):
        raise ValueError("Explicit buy or sell intervention required")
    mask = delta > 0 if learned_side == "buy" else delta < 0
    learned = replay.choose(forecasts, delta, known, pending & mask, final, counts)
    control = replay.gate(opened, observed, delta, known, pending & ~mask,
                          final, counts)
    return learned | control


# Carry the original ledger while replacing exactly one ordinary timing decision.
def account(panel, grades, eligible, dataset, forecasts, opens, first, phase, side):
    # Choose from present observations before execution prices enter the ledger.
    def choose(day, clock, delta, known, pending, observed, nav, budget, cost,
               final, counts):
        return select_side(side, forecasts[day, clock], opens[day], observed,
                           delta, known, pending, final, counts)

    # Preserve the original subsequent-open execution convention on both sides.
    def prices(day, clock, final):
        return dataset["next_open"][day, clock]

    return replay_account(
        panel, grades, eligible, dataset, first, 0, phase, choose, prices, 24,
        supported_days=primary.execution_support(panel, first), record_intents=True,
        decision_counts=dict(waiting_decisions=0, forecast_unavailable=0,
                             opening_unavailable=0, unsupported_plan_sessions=0),
    )


# Reuse original inputs and forecasts, persisting each new carried account once.
def main():
    args = SimpleNamespace(snapshot=Path("/inputs/portfolio.npz"),
                           provenance=Path("/inputs/portfolio.json"),
                           cubes=Path("/cubes"), prepared=Path("/prepared"))
    panel, grades, eligible, cubes, dataset = primary.load_inputs(args)
    report, comparisons = saved.load_primary(
        panel, dataset, Path("/primary/evaluation.json"),
        Path("/primary/evaluation-proof.json"))
    receipt = json.loads(Path("/primary/fit-complete.json").read_text())
    if primary.sha256(Path("/primary/fit-complete.json")) != report["identity"]["fit_receipt_sha256"]:
        raise ValueError("Original fitted receipt changed")
    path = Path("/primary/models/predictions.npz")
    if primary.sha256(path) != receipt["forecast_sha256"]:
        raise ValueError("Original predictions changed")
    with np.load(path, allow_pickle=False) as archive:
        forecasts = archive["predictions"].copy()
        if not np.array_equal(archive["dates"], panel.dates):
            raise ValueError("Forecast dates changed")
    if models.original._array_hash(forecasts) != receipt["forecast_array_sha256"]:
        raise ValueError("Forecast array changed")
    opens = primary.session_opens(panel, cubes)
    first = primary.comparison_first(panel)
    output = Path("/output")
    for side in ("buy", "sell"):
        for phase in range(20):
            path = output / f"{side}-{phase}.json"
            if path.exists():
                raise ValueError("Refusing to replace an existing economic result")
            result = account(panel, grades, eligible, dataset, forecasts, opens,
                             first, phase, side)
            evidence = primary.account_evidence(
                result, comparisons[(0, phase)],
                panel.adj_close[:, panel.tickers.index("SPY")])
            evidence.update(side=side, phase=phase, cost_bps=0,
                            primary_sha256=saved.PRIMARY_SHA256)
            # Read back the actual saved account and validate its cash/wealth invariants.
            with path.open("x") as handle:
                json.dump(evidence, handle, allow_nan=False)
            reloaded = json.loads(path.read_text())
            saved._saved_account(reloaded, result["dates"])
            print(json.dumps({"side": side, "phase": phase,
                              "gain": float(result["nav"][-1] - 1),
                              "sha256": primary.sha256(path)}), flush=True)


if __name__ == "__main__":
    main()
