"""Learn buy-now versus next-session waiting on strictly matured price outcomes."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from backend.cli import market_sequential_execution as primary
from backend.cli import market_sequential_first_available as saved

from carried_entry import account
from rule_relative_entry import CONFIG, FREEZE, fit_month, technical_prefix

CLOCKS = (0, 3, 9, 19, 24)


# Label the same-clock next-session saving, preserving missing execution prices.
def labels(execution, observed, volatility):
    result = np.full(execution.shape, np.nan, dtype=np.float32)
    current, future = execution[:-1], execution[1:]
    divisor = observed[:-1] * volatility[:-1]
    valid = (np.isfinite(current) & (current > 0) & np.isfinite(future)
             & (future > 0) & np.isfinite(divisor) & (divisor > 0))
    np.divide(current - future, divisor, out=result[:-1], where=valid)
    return result


# Purge the latest session so every next-session outcome preceded publication.
def mature_days(dates, first):
    days = np.arange(max(0, first - 756), first - 1)
    days = days[dates[days + 1] < min(dates[first], FREEZE)]
    return days if len(days) >= 504 else np.array([], dtype=int)


# Publish monthly numeric trees and forecasts without adjusting any model parameter.
def fit(dataset, folder):
    x = np.concatenate((dataset["X"], technical_prefix(dataset["current_close"])), axis=-1)
    y = labels(dataset["next_open"], dataset["current_close"], dataset["X"][..., 4])
    dates, valid = dataset["dates"], dataset["valid"]
    predictions = np.full(valid.shape, np.nan, dtype=np.float32)
    months = dates.astype("datetime64[M]")
    receipts = []
    for month in np.unique(months[dates >= np.datetime64("2018-02-01")]):
        test = np.flatnonzero(months == month)
        days = mature_days(dates, int(test[0]))
        if not len(days):
            raise ValueError("Insufficient matured training history")
        mask = (valid[days][:, CLOCKS] & dataset["training_symbols"]
                & np.isfinite(y[days][:, CLOCKS]))
        local, clock, stock = np.nonzero(mask)
        row_days, row_clocks = days[local], np.asarray(CLOCKS)[clock]
        path = folder / f"model-{month}.npz"
        model = fit_month(x[row_days, row_clocks, stock], y[row_days, row_clocks, stock], path)
        day, clock, stock = np.nonzero(valid[test])
        predictions[test[day], clock, stock] = model.predict(x[test[day], clock, stock])
        receipt = {"month": str(month), "rows": len(row_days),
                   "last_label_session": str(dates[row_days + 1].max()),
                   "model_sha256": primary.sha256(path)}
        receipts.append(receipt)
        print(json.dumps(receipt), flush=True)
    with (folder / "predictions.npz").open("xb") as handle:
        np.savez_compressed(handle, predictions=predictions, dates=dates)
    with (folder / "fit.json").open("x") as handle:
        json.dump({"receipts": receipts, "config": CONFIG, "clocks": CLOCKS}, handle)
    return predictions


# Evaluate the frozen next-session entry model against both original and carried rules.
def main():
    args = SimpleNamespace(snapshot=Path("/inputs/portfolio.npz"),
                           provenance=Path("/inputs/portfolio.json"),
                           cubes=Path("/cubes"), prepared=Path("/prepared"))
    panel, grades, eligible, cubes, dataset = primary.load_inputs(args)
    _, comparisons = saved.load_primary(panel, dataset, Path("/primary/evaluation.json"),
                                       Path("/primary/evaluation-proof.json"))
    output = Path("/output")
    models = output / "models"
    models.mkdir()
    with (output / "identity.json").open("x") as handle:
        json.dump({"source": {name: primary.sha256(Path("/experiment") / name)
                              for name in ("next_session_entry.py", "carried_entry.py", "rule_relative_entry.py")},
                   "primary_sha256": saved.PRIMARY_SHA256,
                   "prepared_sha256": primary.sha256(args.prepared / "prepared.npz"),
                   "adoption_eligible": False}, handle, indent=2)
    forecasts = fit(dataset, models)
    first = primary.comparison_first(panel)
    opens, support = primary.session_opens(panel, cubes), primary.execution_support(panel, first)
    for phase in range(20):
        result = account(panel, grades, eligible, dataset, opens, first, phase, support,
                         True, buy_forecasts=forecasts)
        evidence = primary.account_evidence(result, comparisons[(0, phase)],
                                            panel.adj_close[:, panel.tickers.index("SPY")])
        with (output / f"carry-{phase}.json").open("x") as handle:
            json.dump(evidence, handle, allow_nan=False)
        print(json.dumps({"phase": phase, "gain": float(result["nav"][-1] - 1)}), flush=True)


if __name__ == "__main__":
    main()
