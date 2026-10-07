"""Authenticate saved intraday heads and measure past-only probability estimates.

No estimators, accounts, fills or historical inputs are regenerated. Probability
scores describe the next15-minute price advantage, not portfolio profitability.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from backend.cli.market_learned_entry import sha256, write_json
from backend.market import calendar
from backend.market import probabilistic_execution as model

PREPARED_SHA = "c759ecb607e755631dacc0d28a147511a1eaa7e54e3cbcb23bdff4aafe8b76bf"
FORECAST_SHA = "b797bc49c33c23b70c75b5217aa052ad99f2bdae86df722e6badd12ece40917a"
RECEIPT_SHA = "7ea72fd7f8b67c0d5f95397d8472a83b587aa3f7c5882be6ca86f94a510931c9"
PROOF_SHA = "7c5024fadcf4ae313004a7cb8bb002c1bea5ae4b2d2fbc7de60ebd3bbe708df2"
SOURCE = "21ee02e9bbb2024c79e202c614168a681a6322f9"
AS_OF = "2026-09-30T20:00:00+00:00"
WINDOWS = (
    ("all", "2018-02-01", "2026-10-01"),
    ("2018-20", "2018-02-01", "2021-01-01"),
    ("2021-26", "2021-01-01", "2026-10-01"),
    ("reused_recent", "2026-08-17", "2026-10-01"),
)


# Refuse a changed source boundary rather than searching for another usable input.
def require(condition, message):
    if not condition:
        raise ValueError(message)


# Authenticate a regular immutable evidence file before parsing its contents.
def evidence(path, digest, *, json_file=False):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Regular evidence file required")
    require(sha256(path) == digest, f"Original bytes required: {path.name}")
    return json.loads(path.read_text()) if json_file else path


# Bind the prior independent proof and the completed monthly causal fit schedule.
def check_fit(receipt, proof, dates):
    require(
        proof["status"] == "VERIFIED_EXISTING_FIT_ARTIFACTS"
        and proof["source_revision"] == SOURCE
        and proof["prepared_sha256"] == PREPARED_SHA
        and proof["fit"]["receipt_sha256"] == RECEIPT_SHA
        and proof["fit"]["artifact_sha256"] == FORECAST_SHA
        and proof["no_resimulation_or_refit"] is True,
        "Original independent proof links required",
    )
    require(
        receipt["status"] == "COMPLETE" and receipt["artifact_sha256"] == FORECAST_SHA,
        "Completed duration-matched heads required",
    )
    identity = receipt["manifest"]["identity"]
    target = identity["target_schema"]
    require(
        identity["schema"] == "learned-intraday-moments/1"
        and target["mean"] == "log_immediate_open_over_fifteen_minute_later_open"
        and target["second_moment"]
        == "square_of_same_fifteen_minute_log_price_advantage"
        and target["prediction_clocks"] == list(range(23))
        and target["elapsed_minutes"] == 15
        and target["original_label_column"] == 2
        and identity["holdout_label_end_before"] == "2026-08-17",
        "Original same-duration target contract required",
    )
    months = receipt["manifest"]["months"]
    require(
        [row["month"] for row in months]
        == [str(month) for month in np.unique(dates.astype("datetime64[M]"))],
        "Original complete monthly schedule required",
    )
    for row in months:
        first = str(
            dates[
                np.flatnonzero(
                    dates.astype("datetime64[M]") == np.datetime64(row["month"], "M")
                )[0]
            ]
        )
        cutoff = min(first, "2026-08-17")
        require(
            row["fit_date"] == first and row["label_end_before"] == cutoff,
            "Monthly prediction availability differs",
        )
        if row["status"] == "fitted":
            require(
                row["maximum_label_end"] < cutoff
                and row["training_clocks"] == [0, 3, 9, 19]
                and row["training_days"] >= 504,
                "Original fit purge, clocks or support differ",
            )


# Reuse original labels and predictions with explicit clocks and excluded ETFs.
def load_inputs(prepared, moments, proof_path):
    prepared = evidence(prepared, PREPARED_SHA)
    forecast = evidence(Path(moments) / "predictions.npz", FORECAST_SHA)
    receipt = evidence(Path(moments) / "complete.json", RECEIPT_SHA, json_file=True)
    proof = evidence(proof_path, PROOF_SHA, json_file=True)
    with np.load(prepared, allow_pickle=False) as saved:
        dates, names = saved["dates"], tuple(saved["tickers"].tolist())
        valid, labels = saved["valid"], saved["y"]
    require(
        dates.dtype == np.dtype("datetime64[D]")
        and len(dates) == 2953
        and str(dates[0]) == "2015-01-02"
        and str(dates[-1]) == "2026-09-30"
        and len(names) == len(set(names)) == 96
        and {"SPY", "QQQ"} <= set(names),
        "Original session and symbol grid required",
    )
    shape = (len(dates), 25, len(names))
    require(
        valid.shape == shape
        and valid.dtype == np.bool_
        and labels.shape == (*shape, 3)
        and labels.dtype == np.float32,
        "Original typed label/support grids required",
    )
    check_fit(receipt, proof, dates)
    with np.load(forecast, allow_pickle=False) as saved:
        means = {name: saved[f"means_{name}"] for name in ("boosting", "ridge")}
        risk, elapsed = saved["risk"], saved["waiting_elapsed_minutes"]
        require(np.array_equal(saved["dates"], dates), "Prediction dates differ")
    require(
        risk.shape == shape
        and risk.dtype == np.float32
        and elapsed.shape == shape[:2]
        and elapsed.dtype == np.float64
        and np.all(elapsed[:, :23] == 15),
        "Risk or duration grid differs",
    )
    for value in means.values():
        require(
            value.shape == (*shape, 3)
            and value.dtype == np.float32
            and not np.isfinite(value[:, 23:, :, 2]).any(),
            "Waiting means must retain unavailable terminal clocks",
        )
    require(not np.isfinite(risk[:, 23:]).any(), "Terminal risk must stay unavailable")
    valid = valid.copy()
    valid[:, 23:] = False
    valid[:, :, [names.index("SPY"), names.index("QQQ")]] = False
    return (
        dates,
        names,
        labels[..., 2],
        valid,
        means,
        risk,
        {
            "source_revision": SOURCE,
            "prepared_sha256": PREPARED_SHA,
            "forecast_sha256": FORECAST_SHA,
            "completion_sha256": RECEIPT_SHA,
            "independent_fit_proof_sha256": PROOF_SHA,
            "observation": "09:45 America/New_York plus15minutes times clock0..22",
            "actual_outcome_endpoint": "10:00 New York plus15minutes times clock",
            "calibration_maturity": "conservatively same-session official close",
            "original_model_purge": "10sessions; unchanged, not calibration endpoints",
            "basis": "original session-scaled raw SIP opens; no repeated conversion",
        },
    )


# Build a historical reference on precisely the same available causal residual rows.
def reference(result, labels):
    probability = np.full(result.probability_positive.shape, np.nan)
    quantiles = np.full(result.quantiles.shape, np.nan)
    months = result.dates.astype("datetime64[M]")
    for month, stocks in result.samples.items():
        month_days = months == np.datetime64(month, "M")
        for stock, symbol in enumerate(result.symbols):
            sample = stocks.get(symbol)
            if sample is None:
                continue
            outcomes = labels[sample.day_indices, sample.clock_indices, stock]
            weights = sample.weights
            mask = result.score_mask[:, :, stock] & month_days[:, None]
            probability[:, :, stock][mask] = np.average(outcomes > 0, weights=weights)
            quantiles[:, :, stock][mask] = model.weighted_quantiles(outcomes, weights)
    return probability, quantiles


# Assign each measured session equal weight without pretending bars are independent.
def date_weights(mask):
    counts = mask.reshape(len(mask), -1).sum(axis=1)
    weights = np.zeros(mask.shape, dtype=np.float64)
    available = counts > 0
    weights[available] = mask[available] / counts[available, None, None]
    return weights


# Report probability quality, retaining impossible predictions and missing outcomes.
def probability_metrics(probability, quantiles, labels, mask):
    known = mask & np.isfinite(labels) & np.isfinite(probability)
    count = int(known.sum())
    if not count:
        return {"status": "unavailable", "observations": 0}
    p, target = probability[known], (labels[known] > 0).astype(float)
    require(np.all((p >= 0) & (p <= 1)), "Probability outside unit interval")
    w = date_weights(known)[known]
    impossible = ((p == 0) & (target == 1)) | ((p == 1) & (target == 0))
    with np.errstate(divide="ignore", invalid="ignore"):
        loss = -np.log(np.where(target == 1, p, 1 - p))
    covered = (labels[known] >= quantiles[..., 0][known]) & (
        labels[known] <= quantiles[..., 2][known]
    )
    reliability = []
    for bin_index in range(10):
        selected = (p >= bin_index / 10) & (
            (p < (bin_index + 1) / 10) if bin_index < 9 else (p <= 1)
        )
        reliability.append(
            {
                "lower": bin_index / 10,
                "upper": (bin_index + 1) / 10,
                "observations": int(selected.sum()),
                "mean_probability": float(np.average(p[selected], weights=w[selected]))
                if selected.any()
                else None,
                "positive_frequency": float(
                    np.average(target[selected], weights=w[selected])
                )
                if selected.any()
                else None,
            }
        )
    return {
        "status": "measured",
        "observations": count,
        "sessions": int(known.reshape(len(mask), -1).any(axis=1).sum()),
        "brier": float(np.average((p - target) ** 2, weights=w)),
        "log_loss": None if impossible.any() else float(np.average(loss, weights=w)),
        "infinite_log_loss_observations": int(impossible.sum()),
        "interval_10_90_coverage": float(np.average(covered, weights=w)),
        "interval_10_90_mean_width": float(
            np.average(quantiles[..., 2][known] - quantiles[..., 0][known], weights=w)
        ),
        "weighting": "equal_total_weight_per_measured_session",
        "reliability": reliability,
    }


# Compare paired probability estimates without dropping cold-start opportunities.
def summarize(dates, labels, valid, result, prior_p, prior_q, stock=None):
    probability, quantiles = result.probability_positive, result.quantiles
    if stock is not None:
        labels, valid = labels[:, :, stock : stock + 1], valid[:, :, stock : stock + 1]
        probability, quantiles = (
            probability[:, :, stock : stock + 1],
            quantiles[:, :, stock : stock + 1],
        )
        prior_p, prior_q = (
            prior_p[:, :, stock : stock + 1],
            prior_q[:, :, stock : stock + 1],
        )
    rows = []
    for name, start, end in WINDOWS:
        mask = (
            valid
            & ((dates >= np.datetime64(start)) & (dates < np.datetime64(end)))[
                :, None, None
            ]
        )
        support = mask & np.isfinite(probability) & np.isfinite(prior_p)
        known = support & np.isfinite(labels)
        rows.append(
            {
                "window": name,
                "requested_causal_observations": int(mask.sum()),
                "probability_available": int(support.sum()),
                "probability_unavailable": int((mask & ~support).sum()),
                "outcome_available": int(known.sum()),
                "outcome_missing": int((support & ~np.isfinite(labels)).sum()),
                "learned": probability_metrics(probability, quantiles, labels, support),
                "historical_reference": probability_metrics(
                    prior_p, prior_q, labels, support
                ),
            }
        )
    return rows


# Record the actual research code and calendar without claiming a deployed revision.
def source_identity():
    root = Path(__file__).resolve().parents[2]
    paths = [
        Path(__file__),
        Path(model.__file__),
        root / "backend/cli/market_learned_entry.py",
        root / "backend/market/daily_arithmetic_bridge.py",
        Path(calendar.__file__),
        calendar.HISTORICAL_SESSIONS_PATH,
        calendar.HOLIDAYS_PATH,
        calendar.EARLY_CLOSES_PATH,
        root / model.PROTOCOL,
    ]
    return {str(path.relative_to(root)): sha256(path) for path in paths}


# Run the fixed two saved methods once into a new private diagnostic directory.
def diagnose(prepared, moments, proof_path, output):
    output = Path(output)
    require(not output.exists(), "Fresh private output required; no overwrite")
    dates, names, labels, valid, means, risk, receipts = load_inputs(
        prepared, moments, proof_path
    )
    output.mkdir(parents=True)
    report = {
        "status": "COMPLETE_NOT_INDEPENDENTLY_VERIFIED",
        "adoption_eligible": False,
        "policy": model.POLICY,
        "source_files": source_identity(),
        "inputs": receipts,
        "data_as_of": AS_OF,
        "methods": {},
        "funded_timing_and_sizing": "not_measured_by_probability_diagnostics",
        "limitations": [
            "known outcome history; recent slice reused, not new untouched holdout",
            "current-vintage grades/universe and delayed retrospective SIP inputs",
            "execution advantage probability; not holding profit or confidence",
            "empirical probabilities can be zero or one; infinite log loss retained",
            "no account replay, benchmark gain, broker fill or live promotion",
        ],
    }
    for method, values in means.items():
        result = model.calibrate(
            dates,
            names,
            values[..., 2],
            risk,
            labels,
            valid,
            dates,
            data_as_of=AS_OF,
            horizon=model.HORIZON,
        )
        prior_p, prior_q = reference(result, labels)
        path = output / f"{method}.npz"
        with path.open("wb") as handle:
            np.savez_compressed(
                handle,
                probability=result.probability_positive,
                quantiles=result.quantiles,
                reference_probability=prior_p,
                reference_quantiles=prior_q,
                dates=dates,
                symbols=names,
            )
        write_json(output / f"{method}-calibration.json", result.manifest)
        report["methods"][method] = {
            "artifact_sha256": sha256(path),
            "calibration_sha256": sha256(output / f"{method}-calibration.json"),
            "windows": summarize(
                dates, labels, result.causal_mask, result, prior_p, prior_q
            ),
            "stocks": {
                symbol: summarize(
                    dates, labels, result.causal_mask, result, prior_p, prior_q, index
                )
                for index, symbol in enumerate(names)
                if symbol not in {"SPY", "QQQ"}
            },
        }
        print(json.dumps({"method": method, "complete": True}), flush=True)
        del result, prior_p, prior_q
    write_json(output / "report.json", report)
    return report


# Require explicit read-only inputs and a separate output; never offer a fitting mode.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--moments", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    diagnose(args.prepared, args.moments, args.proof, args.output)


if __name__ == "__main__":
    main()
