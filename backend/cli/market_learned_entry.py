"""Explicit-path, read-only fit/evaluate runner for learned entry and risk sizing."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from backend.market import (
    learned_entry_data,
    learned_entry_evaluation,
    learned_entry_models,
)
from backend.market.learned_entry_policy import POLICY
from backend.market.open_source_portfolio import load_snapshot

SNAPSHOT_SHA256 = "8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58"


# Stream large artifact hashes without keeping an additional full data copy in memory.
def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while data := handle.read(1024 * 1024):
            value.update(data)
    return value.hexdigest()


# Atomically publish evidence only after all referenced arrays exist and are hashed.
def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    os.replace(temporary, path)


# Prepare causal arrays or verify their original input and feature identity.
def inputs(snapshot, provenance, cubes_path, output):
    if sha256(snapshot) != SNAPSHOT_SHA256:
        raise ValueError("this preregistration requires the original frozen snapshot")
    panel, grades, eligible, source = load_snapshot(snapshot, provenance)
    cubes, cube_evidence = learned_entry_evaluation.read_cubes(
        cubes_path, panel.tickers
    )
    identity = {
        "snapshot_sha256": sha256(snapshot),
        "provenance_sha256": sha256(provenance),
        "cubes": cube_evidence,
        "feature_source_sha256": sha256(learned_entry_data.__file__),
    }
    archive = output / "prepared.npz"
    receipt_path = output / "prepared.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if (
            receipt["identity"] != identity
            or sha256(archive) != receipt["artifact_sha256"]
        ):
            raise ValueError(
                "prepared data differs from original input or feature identity"
            )
        with np.load(archive, allow_pickle=False) as saved:
            dataset = {name: saved[name] for name in saved.files}
        dataset["feature_names"] = tuple(dataset["feature_names"].tolist())
        dataset["tickers"] = tuple(dataset["tickers"].tolist())
        dataset["diagnostics"] = receipt["diagnostics"]
    else:
        dataset = learned_entry_data.prepare(panel, grades, eligible, cubes)
        temporary = archive.with_suffix(".tmp")
        with temporary.open("wb") as handle:
            np.savez(
                handle,
                **{
                    key: value for key, value in dataset.items() if key != "diagnostics"
                },
            )
        os.replace(temporary, archive)
        write_json(
            receipt_path,
            {
                "identity": identity,
                "artifact_sha256": sha256(archive),
                "diagnostics": dataset["diagnostics"],
            },
        )
    dataset["provenance"] = {**identity, "snapshot_contract": source}
    dataset["training_symbols"] = np.array(
        [name not in ("SPY", "QQQ") for name in panel.tickers]
    )
    return panel, grades, eligible, cubes, dataset


# Pin the source revision and executable files used by the research artifacts.
def source_identity():
    import subprocess

    from backend.market import learned_entry_policy

    root = Path(__file__).resolve().parents[2]
    files = [
        Path(__file__),
        Path(learned_entry_data.__file__),
        Path(learned_entry_evaluation.__file__),
        Path(learned_entry_models.__file__),
        Path(learned_entry_policy.__file__),
        root / "docs/research/learned-entry-risk-plan-2026-10-02.md",
        root / "docs/research/learned-linear-plan-2026-10-02.md",
        root / "docs/research/learned-entry-comparison-details-2026-10-02.md",
    ]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "source_revision": os.environ.get(
            "ANIOS_RESEARCH_SOURCE_REVISION",
            revision.stdout.strip() if revision.returncode == 0 else "unavailable",
        ),
        "files": {str(path.relative_to(root)): sha256(path) for path in files},
    }


# Fit the fixed method once and publish a hashed, pickle-free forecast grid.
def fit(dataset, output, method):
    method_dir = output / method
    predictions, manifest = learned_entry_models.walk_forward(
        dataset, method_dir, method
    )
    archive = method_dir / "predictions.npz"
    temporary = archive.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        np.savez(handle, predictions=predictions, dates=dataset["dates"])
    os.replace(temporary, archive)
    write_json(
        method_dir / "complete.json",
        {
            "status": "fitted",
            "artifact_sha256": sha256(archive),
            "source": source_identity(),
            "manifest": manifest,
            "prediction_array_sha256": learned_entry_models._array_hash(predictions),
        },
    )


# Evaluate all fixed costs and control phases without refitting or selecting a winner.
def evaluate(panel, grades, eligible, cubes, dataset, output, method):
    method_dir = output / method
    receipt = json.loads((method_dir / "complete.json").read_text())
    archive = method_dir / "predictions.npz"
    if (
        sha256(archive) != receipt["artifact_sha256"]
        or receipt["source"] != source_identity()
    ):
        raise ValueError("forecast artifact or evaluated source identity changed")
    with np.load(archive, allow_pickle=False) as saved:
        predictions = saved["predictions"]
        if not np.array_equal(saved["dates"], panel.dates):
            raise ValueError("forecast source calendar changed")
    x, y, valid, dates, features = learned_entry_models._validate(dataset)
    identity = learned_entry_models._identity(
        dataset, x, y, valid, dates, features, method
    )
    if (
        json.loads(json.dumps(identity)) != receipt["manifest"]["identity"]
        or predictions.shape != dataset["y"].shape
        or np.isinf(predictions).any()
        or np.isfinite(predictions[~valid]).any()
        or learned_entry_models._array_hash(predictions)
        != receipt["prediction_array_sha256"]
    ):
        raise ValueError("forecast grid or fitted input/method identity changed")
    available = np.isfinite(predictions).all(axis=-1).any(axis=(1, 2))
    if not available.any():
        raise ValueError("no mature three-head fit; evaluation unavailable")
    first = int(np.flatnonzero(available)[0])
    control_prices = learned_entry_evaluation.control_prices(panel, cubes)
    result = {
        "policy": POLICY,
        "method": method,
        "status": "conditional_research",
        "adoption_eligible": False,
        "source": source_identity(),
        "forecast_sha256": receipt["artifact_sha256"],
        "data": dataset["provenance"],
        "diagnostics": dataset["diagnostics"],
        "common_start": str(panel.dates[first]),
        "common_end": str(panel.dates[-1]),
        "limitations": [
            "current-vintage grades/membership, not exact historical live policy",
            "raw SIP next-open/auction proxies, not broker fill evidence",
            "early-close and unavailable cube opportunities retained as missing",
            "fractional NAV1 ledger, not production whole-share execution",
            "price-only; historical fundamentals and earnings tone unavailable",
            "benchmark entry at session open, candidate after completed first bar",
            "control is the fixed price/grade component; historical overlays absent",
        ],
        "costs": [],
    }
    spy = panel.adj_close[:, panel.tickers.index("SPY")]
    for cost in (0, 10, 25):
        references = {
            name: learned_entry_evaluation.benchmark_account(panel, first, cost, name)
            for name in ("SPY", "QQQ")
        }
        candidate = learned_entry_evaluation.learned_account(
            panel, dataset, predictions, first, cost
        )
        controls = [
            learned_entry_evaluation.control_account(
                panel, grades, eligible, control_prices, first, cost, phase
            )
            for phase in range(20)
        ]
        comparisons = {
            **references,
            **{f"control_phase_{i}": account for i, account in enumerate(controls)},
        }
        curves = {"learned": candidate, **comparisons}
        row = {
            "cost_bps": cost,
            "learned": learned_entry_evaluation.score(candidate, comparisons, spy),
            "benchmarks": {
                name: learned_entry_evaluation.score(account, {}, spy)
                for name, account in references.items()
            },
            "controls": [
                learned_entry_evaluation.score(account, references, spy)
                for account in controls
            ],
            "curves": {
                name: {
                    key: account[key].tolist()
                    for key in ("nav", "cash", "exposure", "turnover", "fees")
                }
                for name, account in curves.items()
            },
        }
        result["costs"].append(row)
        write_json(method_dir / "evaluation-progress.json", result)
        print(
            json.dumps(
                {
                    "status": "evaluated_cost",
                    "method": method,
                    "cost_bps": cost,
                    "learned": row["learned"]["windows"][0],
                },
                allow_nan=False,
            ),
            flush=True,
        )
    write_json(method_dir / "evaluation.json", result)
    write_json(
        method_dir / "evaluation-proof.json",
        {
            "report_sha256": sha256(method_dir / "evaluation.json"),
            "source": source_identity(),
            "forecast_sha256": receipt["artifact_sha256"],
        },
    )


# Accept only explicit source and output paths for a bounded research stage.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "provenance", "cubes", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--method", choices=("boosting", "ridge"), required=True)
    parser.add_argument(
        "--stage", choices=("prepare", "fit", "evaluate"), required=True
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    panel, grades, eligible, cubes, dataset = inputs(
        args.snapshot, args.provenance, args.cubes, args.output
    )
    print(
        json.dumps(
            {"status": "prepared", "method": args.method, **dataset["diagnostics"]}
        ),
        flush=True,
    )
    if args.stage == "fit":
        fit(dataset, args.output, args.method)
    elif args.stage == "evaluate":
        evaluate(panel, grades, eligible, cubes, dataset, args.output, args.method)


if __name__ == "__main__":
    main()
