"""Learn entry advantage against the incumbent's future continuation, offline."""

import hashlib
import json

import numpy as np

CONFIG = {
    "max_iter": 64,
    "max_leaf_nodes": 15,
    "learning_rate": 0.05,
    "min_samples_leaf": 200,
    "early_stopping": False,
    "random_state": 0,
}
CLOCKS = (0, 3, 9, 19)
FREEZE = np.datetime64("2026-08-17")


# Derive training outcomes from the first strictly later incumbent crossing.
def targets(observed, execution, opening, volatility):
    if observed.shape != execution.shape or observed.shape[1] != 25:
        raise ValueError("Aligned 25-clock observations and executions required")
    if opening.shape != observed.shape[::2] or volatility.shape != observed.shape:
        raise ValueError("Opening and observed volatility dimensions differ")
    result = np.full(observed.shape, np.nan, dtype=np.float32)
    future = execution[:, 24].astype(float).copy()
    future = np.where(
        np.isfinite(observed[:, 24]) & (observed[:, 24] > 0), future, np.nan
    )
    for clock in range(23, -1, -1):
        current, price = execution[:, clock], observed[:, clock]
        sigma = volatility[:, clock]
        valid = (
            np.isfinite(current) & (current > 0) & np.isfinite(future) & (future > 0)
        )
        valid &= np.isfinite(price) & (price > 0) & np.isfinite(sigma) & (sigma > 0)
        np.divide(current - future, price * sigma, out=result[:, clock], where=valid)
        crossed = np.isfinite(price) & (price > 0) & (price <= opening * 0.99)
        # Keep a selected missing fill missing instead of choosing a later price.
        future = np.where(crossed, current, future)
    return result


# Select only past same-session outcomes, retaining the fixed research freeze.
def training_days(dates, first, minimum=504):
    days = np.arange(max(0, first - 756), first)
    days = days[dates[days] < min(dates[first], FREEZE)]
    return days if len(days) >= minimum else np.array([], dtype=int)


# Replay numeric regression trees directly, without restoring executable estimators.
def numeric_predict(trees, baseline, x):
    output = np.full(len(x), baseline, dtype=float)
    for nodes in trees:
        indices = np.zeros(len(x), dtype=int)
        active = np.arange(len(x))
        while len(active):
            node = nodes[indices[active]]
            leaf = node["is_leaf"].astype(bool)
            output[active[leaf]] += node["value"][leaf]
            active = active[~leaf]
            node = node[~leaf]
            values = x[active, node["feature_idx"]]
            left = np.where(
                np.isnan(values),
                node["missing_go_to_left"].astype(bool),
                values <= node["num_threshold"],
            )
            indices[active] = np.where(left, node["left"], node["right"])
    return output


# Fit one fixed monthly regressor and prove portable numeric readback predictions.
def fit_month(x, y, destination):
    from sklearn.ensemble import HistGradientBoostingRegressor

    model = HistGradientBoostingRegressor(**CONFIG).fit(x, y)
    trees = [tree[0].nodes for tree in model._predictors]
    baseline = float(model._baseline_prediction[0, 0])
    with destination.open("xb") as handle:
        np.savez_compressed(
            handle,
            baseline=np.asarray(baseline),
            **{f"tree{i}": tree for i, tree in enumerate(trees)},
        )
    with np.load(destination, allow_pickle=False) as saved:
        restored = [saved[f"tree{i}"] for i in range(len(trees))]
        # Probe a fixed prefix of training inputs, including missing values.
        probe = x[:4096]
        if not np.allclose(
            numeric_predict(restored, float(saved["baseline"]), probe),
            model.predict(probe),
            rtol=1e-12,
            atol=1e-12,
        ):
            raise ValueError("Numeric model readback differs")
    return model


# Train once per month on earlier outcomes and publish immutable predictions/receipts.
def walk_forward(dataset, opening, output):
    x, dates, valid = dataset["X"], dataset["dates"], dataset["valid"]
    stock_mask = np.asarray(dataset["training_symbols"])
    labels = targets(dataset["current_close"], dataset["next_open"], opening, x[..., 4])
    predictions = np.full((*valid.shape, 2), np.nan, dtype=np.float32)
    months = dates.astype("datetime64[M]")
    receipts = []
    for month in np.unique(months):
        test = np.flatnonzero(months == month)
        if dates[test[-1]] < np.datetime64("2018-02-01"):
            continue
        days = training_days(dates, int(test[0]))
        if not len(days):
            receipts.append({"month": str(month), "status": "insufficient_history"})
            continue
        mask = (
            valid[days][:, CLOCKS] & stock_mask & np.isfinite(labels[days][:, CLOCKS])
        )
        local, clock, stock = np.nonzero(mask)
        row_days, row_clocks = days[local], np.asarray(CLOCKS)[clock]
        train_x, train_y = (
            x[row_days, row_clocks, stock],
            labels[row_days, row_clocks, stock],
        )
        path = output / f"model-{month}.npz"
        model = fit_month(train_x, train_y, path)
        selected = (
            valid[test, :24]
            & np.isfinite(x[test, :24, :, 4])
            & (x[test, :24, :, 4] > 0)
        )
        day, clock, stock = np.nonzero(selected)
        predictions[test[day], clock, stock, 0] = model.predict(
            x[test[day], clock, stock]
        )
        receipt = {
            "month": str(month),
            "status": "fitted",
            "rows": len(train_y),
            "last_training_session": str(dates[row_days].max()),
            "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        receipts.append(receipt)
        print(json.dumps(receipt), flush=True)
    with (output / "predictions.npz").open("xb") as handle:
        np.savez_compressed(handle, predictions=predictions, dates=dates)
    with (output / "fit.json").open("x") as handle:
        json.dump({"config": CONFIG, "clocks": CLOCKS, "receipts": receipts}, handle)
    return predictions
