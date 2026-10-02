"""Read-only short-horizon risk fitting and unchanged-plan timing diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from backend.cli.market_learned_entry import inputs, sha256, source_identity, write_json
from backend.cli.market_learned_entry_compare import learned_forecasts
from backend.market import learned_entry_evaluation as replay
from backend.market import learned_entry_models as original
from backend.market import learned_execution_risk as risk_model
from backend.market import learned_execution_timing as timing

CONTROL_REPORT = "f340f1329ec67645ba4f534eb9c34afde5cee5e47d85ce88dab7de87ab72f608"
PLAN = "docs/research/learned-execution-risk-plan-2026-10-02.md"


# Record exact new execution sources alongside the already frozen input/model sources.
def execution_source():
    root = Path(__file__).resolve().parents[2]
    source = source_identity()
    source["files"].update(
        {
            name: sha256(root / name)
            for name in (
                "backend/market/learned_execution_risk.py",
                "backend/market/learned_execution_timing.py",
                "backend/cli/market_execution_risk.py",
                PLAN,
            )
        }
    )
    return source


# Complete one immutable risk fit with original input, schema and array receipts.
def fit(dataset, output):
    output = Path(output)
    if (output / "complete.json").exists():
        raise FileExistsError("a completed risk fit already exists")
    predictions, manifest = risk_model.walk_forward(dataset, output)
    artifact = output / "predictions.npz"
    with artifact.open("wb") as handle:
        np.savez_compressed(handle, predictions=predictions, dates=dataset["dates"])
    receipt = {
        "status": "COMPLETE",
        "source": execution_source(),
        "artifact_sha256": sha256(artifact),
        "manifest": manifest,
        "prediction_array_sha256": original._array_hash(predictions),
    }
    write_json(output / "complete.json", receipt)
    return receipt


# Verify every monthly fit belongs to its prediction month and uses mature labels.
def verify_months(directory, months, dates):
    calendar = dates.astype("datetime64[M]")
    expected = [str(value) for value in np.unique(calendar)]
    if [row["month"] for row in months] != expected:
        raise ValueError("risk fit month schedule differs")
    for month in months:
        actual = str(
            dates[np.flatnonzero(calendar == np.datetime64(month["month"]))[0]]
        )
        cutoff = min(actual, "2026-08-17")
        if month["fit_date"] != actual or month["label_end_before"] != cutoff:
            raise ValueError("risk fit availability or maturity cutoff differs")
        if month["status"] != "fitted":
            continue
        if month["maximum_label_end"] >= cutoff or month["training_days"] < 504:
            raise ValueError("risk fit used immature or holdout labels")
        if len(month["models"]) != 1 or month["models"][0]["head"] != 0:
            raise ValueError("exactly one risk model head required")
        for model in month["models"]:
            if sha256(directory / model["file"]) != model["sha256"]:
                raise ValueError("risk fitted model artifact differs")


# Authenticate short-horizon risk against original causal arrays and its actual fit.
def load_risk(directory, dataset):
    directory = Path(directory)
    receipt = json.loads((directory / "complete.json").read_text())
    identity = receipt["manifest"]["identity"]
    x, y, valid, dates, features = original._validate(dataset)
    target = risk_model.waiting_second_moment(dataset)
    expected = risk_model.identity(dataset, x, y, valid, dates, features, target)
    if receipt["status"] != "COMPLETE" or identity != json.loads(json.dumps(expected)):
        raise ValueError("risk schema, target, source or original inputs differ")
    verify_months(directory, receipt["manifest"]["months"], dates)
    path = directory / "predictions.npz"
    if sha256(path) != receipt["artifact_sha256"]:
        raise ValueError("risk artifact bytes differ")
    with np.load(path, allow_pickle=False) as saved:
        predictions = saved["predictions"]
        if not np.array_equal(saved["dates"], dates):
            raise ValueError("risk forecast calendar differs")
    if predictions.dtype != np.float32 or predictions.shape != valid.shape:
        raise ValueError("risk forecast dimensions or numeric representation differ")
    if original._array_hash(predictions) != receipt["prediction_array_sha256"]:
        raise ValueError("risk forecast array receipt differs")
    if np.isfinite(predictions[~valid]).any():
        raise ValueError("risk predicts on invalid causal inputs")
    return predictions, receipt


# Measure saved waiting-risk forecasts without using calibration to tune decisions.
def calibration(dataset, risk, means, first):
    target = risk_model.waiting_second_moment(dataset)
    reports = {}
    for name, mean in means.items():
        rows = dataset["valid"].copy()
        rows[:first] = False
        rows[:, 23:] = False
        rows[:, :, ~dataset["training_symbols"]] = False
        known = (
            rows & np.isfinite(target) & np.isfinite(risk) & np.isfinite(mean[..., 2])
        )
        usable = known & (risk >= 0) & (risk >= mean[..., 2] ** 2)
        error = dataset["y"][..., 2] - mean[..., 2]
        reports[name] = {
            "requested_causal_rows": int(rows.sum()),
            "label_and_forecast_known": int(known.sum()),
            "consistent_moments": int(usable.sum()),
            "waiting_mean_rmse": float(np.sqrt(np.mean(error[known] ** 2)))
            if known.any()
            else None,
            "mean_predicted_second_moment": float(np.mean(risk[known]))
            if known.any()
            else None,
            "mean_realized_second_moment": float(np.mean(target[known]))
            if known.any()
            else None,
            "negative_second_moment_forecasts": int(
                (rows & np.isfinite(risk) & (risk < 0)).sum()
            ),
            "note": (
                "reused diagnostic; no thresholds fitted; "
                "moments are not epistemic confidence intervals"
            ),
        }
    return reports


# Reuse immutable baseline curves and evaluate only the new same-plan timing accounts.
def evaluate(
    panel, grades, eligible, cubes, dataset, means, risk, receipts, reference, output
):
    output = Path(output)
    if output.exists():
        raise FileExistsError("a completed timing-only evaluation already exists")
    if sha256(reference) != CONTROL_REPORT:
        raise ValueError("the original authenticated baseline report is required")
    baseline = json.loads(Path(reference).read_text())
    if baseline["data"] != dataset["provenance"]:
        raise ValueError("baseline and candidate original inputs differ")
    first = int(
        np.flatnonzero(panel.dates == np.datetime64(baseline["common_start"]))[0]
    )
    dates = panel.dates[first - 1 :]
    closes = timing.closing_prices(panel, cubes)
    report = {
        "status": "reused_conditional_timing_diagnostic",
        "adoption_eligible": False,
        "policy": timing.POLICY,
        "start": str(panel.dates[first]),
        "end": str(panel.dates[-1]),
        "source": execution_source(),
        "forecast_receipts": receipts,
        "baseline_report_sha256": sha256(reference),
        "risk_calibration": calibration(dataset, risk, means, first),
        "limitations": [
            "known outcome window, not a new untouched holdout",
            "same v5 target plans; quantities depend on each account's carried wealth",
            "one-step utility and closing deadline; not exact optimal stopping",
            "conditional current-vintage grades/universe and fractional NAV1",
            "bar-open/observed-auction proxies, not live quotes or broker fills",
            "closing lifecycle completion is separate from model-driven timing",
        ],
        "costs": [],
    }
    for cost in baseline["costs"]:
        references = {
            name: {
                **{key: np.asarray(value) for key, value in curve.items()},
                "dates": dates,
            }
            for name, curve in cost["curves"].items()
            if name != "learned"
        }
        if len(references) != 22 or any(
            len(row["nav"]) != len(dates) for row in references.values()
        ):
            raise ValueError("baseline phase/calendar dimensions differ")
        entry = {"cost_bps": cost["cost_bps"], "methods": {}}
        for name, forecasts in means.items():
            phases = []
            for offset in range(20):
                book = timing.account(
                    panel,
                    grades,
                    eligible,
                    dataset,
                    forecasts,
                    risk,
                    closes,
                    first,
                    cost["cost_bps"],
                    offset,
                )
                statistics = replay.score(
                    book, references, panel.adj_close[:, panel.tickers.index("SPY")]
                )
                phases.append(
                    {
                        "offset": offset,
                        "statistics": statistics,
                        "paired_control": cost["controls"][offset],
                        "curve": {
                            key: value.astype(str).tolist()
                            if key == "dates"
                            else value.tolist()
                            for key, value in book.items()
                            if isinstance(value, np.ndarray)
                        },
                    }
                )
                print(
                    json.dumps(
                        {
                            "method": name,
                            "cost": cost["cost_bps"],
                            "phase": offset,
                            "net_gain": statistics["windows"][0]["total_net_gain"],
                        }
                    ),
                    flush=True,
                )
            entry["methods"][name] = phases
        report["costs"].append(entry)
        write_json(output.with_suffix(".progress.json"), report)
    write_json(output, report)
    write_json(
        output.with_suffix(".proof.json"),
        {
            "status": "COMPLETE_NOT_INDEPENDENTLY_VERIFIED",
            "artifact_sha256": sha256(output),
            "source": report["source"],
        },
    )
    return report


# Require existing original preparation and separate private outputs for this extension.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fit", "evaluate"))
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--provenance", required=True, type=Path)
    parser.add_argument("--cubes", required=True, type=Path)
    parser.add_argument("--prepared-directory", required=True, type=Path)
    parser.add_argument("--risk-directory", required=True, type=Path)
    parser.add_argument("--boosting-directory", type=Path)
    parser.add_argument("--ridge-directory", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not all(
        (args.prepared_directory / name).is_file()
        for name in ("prepared.npz", "prepared.json")
    ):
        parser.error("the existing original prepared archive and receipt are required")
    panel, grades, eligible, cubes, dataset = inputs(
        args.snapshot,
        args.provenance,
        args.cubes,
        args.prepared_directory,
    )
    if args.mode == "fit":
        fit(dataset, args.risk_directory)
        return
    if any(
        value is None
        for value in (
            args.boosting_directory,
            args.ridge_directory,
            args.reference,
            args.output,
        )
    ):
        parser.error(
            "evaluation requires both original mean models, reference and output"
        )
    risk, receipt = load_risk(args.risk_directory, dataset)
    means, evidence = {}, {"risk": receipt}
    for name, path in (
        ("boosting", args.boosting_directory),
        ("ridge", args.ridge_directory),
    ):
        means[name], evidence[name] = learned_forecasts(path, dataset, name)
    evaluate(
        panel,
        grades,
        eligible,
        cubes,
        dataset,
        means,
        risk,
        evidence,
        args.reference,
        args.output,
    )


if __name__ == "__main__":
    main()
