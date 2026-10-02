"""Fixed common-clock funded holdout for the three preregistered challengers."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from backend.cli.market_learned_entry import inputs, sha256, source_identity, write_json
from backend.market import learned_entry_evaluation as replay
from backend.market.learned_entry_models import _array_hash
from backend.market.pretrained_entry_model import ARTIFACT_HASHES, MODEL_REVISION


# Verify causal arrays and training scope; record actual runtime versions separately.
def validate_training(identity, dataset, training_source):
    for key in ("X", "y", "valid", "dates"):
        if identity["arrays"][key] != _array_hash(dataset[key]):
            raise ValueError("learned forecast causal array identity differs")
    if identity.get("feature_names") != list(dataset["feature_names"]) or identity.get(
        "training_symbols_sha256"
    ) != _array_hash(dataset["training_symbols"]):
        raise ValueError("learned feature/training input identity differs")
    frozen = (
        "backend/market/learned_entry_data.py",
        "backend/market/learned_entry_models.py",
        "docs/research/learned-entry-risk-plan-2026-10-02.md",
        "docs/research/learned-linear-plan-2026-10-02.md",
        "docs/research/learned-entry-comparison-details-2026-10-02.md",
    )
    current = source_identity()["files"]
    if any(training_source["files"][key] != current[key] for key in frozen):
        raise ValueError("learned immutable training source differs")


# Verify a learned forecast's original data, actual fit clocks and executable identity.
def learned_forecasts(directory, dataset, method):
    directory = Path(directory)
    receipt = json.loads((directory / "complete.json").read_text())
    path = directory / "predictions.npz"
    if sha256(path) != receipt["artifact_sha256"]:
        raise ValueError("learned artifact bytes differ")
    identity = receipt["manifest"]["identity"]
    provenance = identity["source_provenance"]
    current = dataset["provenance"]
    for key in (
        "snapshot_sha256",
        "provenance_sha256",
        "cubes",
        "feature_source_sha256",
    ):
        if provenance[key] != current[key]:
            raise ValueError("learned forecast input differs from the shared cohort")
    validate_training(identity, dataset, receipt["source"])
    if identity["method"] != method:
        raise ValueError("learned forecast method or executable source differs")
    if identity["holdout_label_end_before"] != "2026-08-17":
        raise ValueError("learned forecast holdout is not frozen")
    for month in receipt["manifest"]["months"]:
        if (
            month["month"] >= "2026-08"
            and month["status"] == "fitted"
            and month["maximum_label_end"] >= "2026-08-17"
        ):
            raise ValueError("learned fit used holdout outcomes")
    with np.load(path, allow_pickle=False) as saved:
        predictions = saved["predictions"]
        if not np.array_equal(saved["dates"], dataset["dates"]):
            raise ValueError("learned forecast calendar differs")
    if (
        predictions.shape != dataset["y"].shape
        or _array_hash(predictions) != receipt["prediction_array_sha256"]
    ):
        raise ValueError("learned forecast array differs")
    return predictions, {"receipt": receipt, "artifact_sha256": sha256(path)}


# Verify publisher-pinned pretrained forecasts and their shared frozen original inputs.
def pretrained_forecasts(path, dataset, receipt_path=None):
    with np.load(path, allow_pickle=False) as saved:
        predictions = saved["predictions"]
        metadata = json.loads(str(saved["metadata"]))
        if (
            not np.array_equal(saved["dates"], dataset["dates"])
            or tuple(saved["tickers"].tolist()) != dataset["tickers"]
        ):
            raise ValueError("pretrained forecast book/calendar differs")
    provenance = metadata["source_identity"]
    for key in (
        "snapshot_sha256",
        "provenance_sha256",
        "cubes",
        "feature_source_sha256",
    ):
        if provenance[key] != dataset["provenance"][key]:
            raise ValueError("pretrained forecast input differs")
    if (
        predictions.dtype != np.dtype("float32")
        or predictions.shape != dataset["y"].shape
        or metadata["forecast_sha256"]
        != hashlib.sha256(predictions.tobytes()).hexdigest()
        or metadata["model_provenance"]["revision"] != MODEL_REVISION
        or metadata["model_provenance"]["artifact_hashes"] != ARTIFACT_HASHES
        or metadata["input_clock"] != 9
        or metadata["holdout_start"] != "2026-08-17"
        or metadata["holdout_end"] != "2026-09-30"
    ):
        raise ValueError("pretrained artifact contract differs")
    receipt = validate_pretrained_receipt(path, provenance, receipt_path)
    return predictions, {
        "metadata": metadata,
        "execution_receipt": receipt,
        "artifact_sha256": sha256(path),
    }


# Verify inference output, prepared input and the executed adapter source.
def validate_pretrained_receipt(path, provenance, receipt_path):
    if receipt_path is None:
        raise ValueError("actual pretrained execution receipt is required")
    receipt = json.loads(Path(receipt_path).read_text())
    if (
        receipt["status"] != "VERIFIED"
        or receipt["output_sha256"] != sha256(path)
        or receipt["prepared_sha256"] != provenance["prepared_sha256"]
    ):
        raise ValueError("pretrained execution artifact receipt differs")
    root = Path(__file__).resolve().parents[2]
    for key, value in receipt["source_hashes"].items():
        if sha256(root / key) != value:
            raise ValueError("pretrained adapter/protocol source differs")
    return receipt


# Keep the fixed holdout decision clock without filtering by future outcomes.
def common_clock(predictions, dataset):
    dates = dataset["dates"]
    cohort = (dates >= np.datetime64("2026-08-17")) & (
        dates <= np.datetime64("2026-09-30")
    )
    result = np.full_like(predictions, np.nan)
    result[cohort, 9] = predictions[cohort, 9]
    valid = dataset["valid"]
    if np.isinf(result).any() or np.isfinite(result[~valid]).any():
        raise ValueError("forecasts on invalid shared observations")
    return result


# Price all challengers against every control phase and both benchmarks at fixed costs.
def compare(panel, grades, eligible, cubes, dataset, forecasts, evidence, output):
    first = int(np.searchsorted(panel.dates, np.datetime64("2026-08-17")))
    if panel.dates[first] != np.datetime64("2026-08-17") or panel.dates[
        -1
    ] != np.datetime64("2026-09-30"):
        raise ValueError("the fixed full holdout calendar is required")
    path = Path(output)
    if path.exists():
        raise FileExistsError("a completed common-clock comparison already exists")
    grids = {name: common_clock(values, dataset) for name, values in forecasts.items()}
    prices = replay.control_prices(panel, cubes)
    spy = panel.adj_close[:, panel.tickers.index("SPY")]
    result = {
        "status": "conditional_common_clock_holdout",
        "adoption_eligible": False,
        "start": "2026-08-17",
        "end": "2026-09-30",
        "clock": 9,
        "initial_nav": 1,
        "source": source_identity(),
        "comparison_source_sha256": sha256(__file__),
        "forecast_evidence": evidence,
        "missing_data": dataset["diagnostics"],
        "costs": [],
    }
    for cost in (0, 10, 25):
        accounts = {
            name: replay.learned_account(panel, dataset, values, first, cost)
            for name, values in grids.items()
        }
        benchmarks = {
            name: replay.benchmark_account(panel, first, cost, name)
            for name in ("SPY", "QQQ")
        }
        controls = {
            f"control_phase_{phase}": replay.control_account(
                panel, grades, eligible, prices, first, cost, phase
            )
            for phase in range(20)
        }
        references = {**benchmarks, **controls}
        row = {
            "cost_bps": cost,
            "methods": {
                name: replay.score(account, references, spy)
                for name, account in accounts.items()
            },
            "references": {
                name: replay.score(account, {}, spy)
                for name, account in references.items()
            },
            "curves": {
                name: {
                    key: account[key].tolist()
                    for key in ("nav", "cash", "exposure", "turnover", "fees")
                }
                for name, account in {**accounts, **references}.items()
            },
        }
        result["costs"].append(row)
        write_json(path.with_suffix(".progress.json"), result)
        print(
            json.dumps(
                {
                    "cost_bps": cost,
                    "methods": {
                        name: value["windows"][0]
                        for name, value in row["methods"].items()
                    },
                },
                allow_nan=False,
            ),
            flush=True,
        )
    write_json(path, result)
    write_json(
        path.with_suffix(".proof.json"),
        {
            "artifact_sha256": sha256(path),
            "source": source_identity(),
            "comparison_source_sha256": sha256(__file__),
        },
    )


# Require original inputs and all three forecast artifacts for the comparison.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "snapshot",
        "provenance",
        "cubes",
        "prepared",
        "boosting",
        "ridge",
        "chronos",
        "chronos-receipt",
        "output",
    ):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    panel, grades, eligible, cubes, dataset = inputs(
        args.snapshot, args.provenance, args.cubes, args.prepared
    )
    forecasts, evidence = {}, {}
    for method in ("boosting", "ridge"):
        forecasts[method], evidence[method] = learned_forecasts(
            getattr(args, method), dataset, method
        )
    forecasts["chronos"], evidence["chronos"] = pretrained_forecasts(
        args.chronos, dataset, args.chronos_receipt
    )
    compare(panel, grades, eligible, cubes, dataset, forecasts, evidence, args.output)


if __name__ == "__main__":
    main()
