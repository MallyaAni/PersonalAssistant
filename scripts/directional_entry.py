"""Isolate advancing and deferring entries with the original frozen model."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from backend.cli import market_sequential_execution as primary
from backend.cli import market_sequential_first_available as saved
from backend.market import sequential_execution_replay as replay
from backend.market.learned_execution_timing import replay_account


# Advance or defer buys alone, retaining every original sell and terminal decision.
def choose(mode, forecasts, opened, observed, delta, known, pending, final, counts):
    if mode not in ("advance", "defer"):
        raise ValueError("Explicit timing direction required")
    control = replay.gate(opened, observed, delta, known, pending, final, counts)
    if final:
        return control
    buys = pending & known & (delta > 0)
    available = np.isfinite(forecasts[:, 0])
    learned_now = forecasts[:, 0] <= 0
    if mode == "advance":
        return control | (buys & available & learned_now)
    return control & (~buys | ~available | learned_now)


# Keep the original funded engine and exchange every ordinary timing choice once.
def account(panel, grades, eligible, dataset, forecasts, opens, first, phase, mode):
    # Use frozen predictions and completed observations before accessing the fill.
    def selector(day, clock, delta, known, pending, observed, nav, budget, cost,
                 final, counts):
        return choose(mode, forecasts[day, clock], opens[day], observed, delta,
                      known, pending, final, counts)

    # Preserve the incumbent next-bar convention without consulting prices to act.
    def prices(day, clock, final):
        return dataset["next_open"][day, clock]

    return replay_account(panel, grades, eligible, dataset, first, 0, phase,
                          selector, prices, 24,
                          supported_days=primary.execution_support(panel, first),
                          record_intents=True, decision_counts={
                              "waiting_decisions": 0, "opening_unavailable": 0,
                              "unsupported_plan_sessions": 0})


# Authenticate the original predictions and save all forty direction-isolated books.
def main():
    args = SimpleNamespace(snapshot=Path("/inputs/portfolio.npz"),
                           provenance=Path("/inputs/portfolio.json"),
                           cubes=Path("/cubes"), prepared=Path("/prepared"))
    panel, grades, eligible, cubes, dataset = primary.load_inputs(args)
    report, comparisons = saved.load_primary(panel, dataset, Path("/primary/evaluation.json"),
                                             Path("/primary/evaluation-proof.json"))
    path = Path("/primary/models/predictions.npz")
    if primary.sha256(path) != report["identity"]["forecast_sha256"]:
        raise ValueError("Original forecast hash changed")
    with np.load(path, allow_pickle=False) as source:
        forecasts = source["predictions"]
        if not np.array_equal(source["dates"], panel.dates):
            raise ValueError("Forecast calendar changed")
    first, opens = primary.comparison_first(panel), primary.session_opens(panel, cubes)
    output = Path("/output")
    with (output / "identity.json").open("x") as handle:
        json.dump({"source_sha256": primary.sha256(Path(__file__)),
                   "forecast_sha256": primary.sha256(path), "cost_bps": 0,
                   "adoption_eligible": False}, handle)
    for mode in ("advance", "defer"):
        for phase in range(20):
            result = account(panel, grades, eligible, dataset, forecasts, opens, first, phase, mode)
            evidence = primary.account_evidence(result, comparisons[(0, phase)],
                                                panel.adj_close[:, panel.tickers.index("SPY")])
            with (output / f"{mode}-{phase}.json").open("x") as handle:
                json.dump(evidence, handle, allow_nan=False)
            print(json.dumps({"mode": mode, "phase": phase,
                              "gain": float(result["nav"][-1] - 1)}), flush=True)


if __name__ == "__main__":
    main()
