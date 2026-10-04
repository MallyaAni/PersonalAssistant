"""Fit one direct daily head and create three new books with saved controls.

Original models, bridge fits and completed control accounts are never rerun.
All supplied evidence is authenticated before use; output is private research.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from backend.cli import market_daily_arithmetic_bridge as saved
from backend.market.daily_arithmetic_bridge import BridgeForecasts

POLICY = "direct-daily-arithmetic/1-research"
BRIDGE_REPORT = "1e3dc8fc1e74049e7945f198d0b18ab5fcffebed3f6a077c1b85fa42fe15f9df"
BRIDGE_PROOF = "cf4132bd2e51c3a6420eac17dd121ce6fb09637bc79d2cac899a5f2373d502c2"
CONTROL_SOURCE = "d339aebea05d28a034ff89a78c36791ecf400fef"
CONTROL_NAMES = ("calibrated", "mean", "equal", "SPY", "QQQ")


# Refuse a substituted artifact or a path outside its supplied read-only tree.
def checked_file(root, name, expected, anchors):
    path = root / name
    saved.require(
        path.resolve().is_relative_to(root.resolve()), "Saved artifact path boundary"
    )
    saved.require(saved.digest(path) == expected, "Saved bytes differ: " + name)
    anchors[path] = expected
    return path


# Restore authenticated bridge rows and complete controls without invoking producers.
def load_controls(args, panel, anchors):
    saved.require(saved.digest(args.bridge_proof) == BRIDGE_PROOF, "Bridge proof")
    anchors[args.bridge_proof] = BRIDGE_PROOF
    proof = json.loads(args.bridge_proof.read_bytes())
    saved.require(
        proof["ok"] is True
        and proof["source_revision"] == CONTROL_SOURCE
        and proof["report_sha256"] == BRIDGE_REPORT,
        "Completed exact bridge proof required",
    )
    report_path = checked_file(
        args.bridge_study, "evaluation.json", BRIDGE_REPORT, anchors
    )
    report = json.loads(report_path.read_bytes())
    saved.require(
        report["adoption_eligible"] is False
        and report["identity"]["source"]["revision"] == CONTROL_SOURCE
        and report["identity"]["common_anchor"] == "2020-03-02"
        and [row["cost_bps"] for row in report["rows"]] == list(saved.COSTS),
        "Fixed component identity and complete cost grid",
    )
    fit_path = checked_file(
        args.bridge_study, report["fit_file"], report["fit_sha256"], anchors
    )
    numeric_path = checked_file(
        args.bridge_study, report["bridge_file"], report["bridge_sha256"], anchors
    )
    numeric, fit = saved.arrays(numeric_path), json.loads(fit_path.read_bytes())
    saved.require(
        np.array_equal(numeric["dates"], panel.dates)
        and tuple(numeric["symbols"]) == tuple(panel.tickers),
        "Exact bridge calendar and stock identities",
    )
    bridge = BridgeForecasts(
        **{
            name: numeric[name]
            for name in (
                "calibrated",
                "past_mean",
                "labels",
                "label_end_dates",
                "score_mask",
            )
        },
        manifest=fit,
    )
    controls, records = {}, {}
    for row in report["rows"]:
        cost = row["cost_bps"]
        saved.require(
            set(row["accounts"]) == set(CONTROL_NAMES), "Complete saved control grid"
        )
        controls[cost], records[cost] = {}, row["accounts"]
        for name, record in row["accounts"].items():
            key = f"{name}-{cost}"
            saved.require(
                record["arrays_file"] == key + ".npz"
                and record["receipt_file"] == key + ".json"
                and proof["book_artifacts"][key]
                == {
                    "arrays": record["arrays_sha256"],
                    "receipt": record["receipt_sha256"],
                },
                "Proof-linked canonical control filenames",
            )
            numeric_path = checked_file(
                args.bridge_study,
                record["arrays_file"],
                record["arrays_sha256"],
                anchors,
            )
            receipt_path = checked_file(
                args.bridge_study,
                record["receipt_file"],
                record["receipt_sha256"],
                anchors,
            )
            numeric, receipt = (
                saved.arrays(numeric_path),
                json.loads(receipt_path.read_bytes()),
            )
            saved.require(
                not (numeric.keys() & receipt["account"].keys()),
                "Separate numeric and readable control state",
            )
            saved.require(
                receipt["score"] == record["score"], "Original control score identity"
            )
            controls[cost][name] = {**receipt["account"], **numeric}
    return bridge, controls, records


# Match every available or unavailable model to its recorded monthly status.
def validate_models(models, manifest):
    from backend.market.direct_daily_arithmetic import model_identity

    receipts = manifest["months"]
    saved.require(
        list(models) == [item["month"] for item in receipts],
        "Complete ordered model receipt schedule",
    )
    for receipt in receipts:
        head = models[receipt["month"]]
        if head is None:
            saved.require(
                receipt["status"]
                in (
                    "insufficient_training_days",
                    "fit_clock_unavailable",
                    "no_observed_training_features",
                ),
                "Unavailable model must have an explicit unavailable receipt",
            )
        else:
            saved.require(
                receipt["status"] == "fitted"
                and receipt["model"] == model_identity(head),
                "Exact fitted model and numeric receipt identity",
            )


# Save fitted numeric trees while retaining unavailable months only in receipts.
def save_models(output, models):
    records = {}
    for month, head in models.items():
        saved.require(
            str(np.datetime64(month, "M")) == month, "Canonical model month"
        )
        if head is None:
            continue
        estimator = head.estimator
        numeric = {
            "columns": np.asarray(head.columns),
            "baseline": np.asarray(estimator._baseline_prediction),
            "features": np.asarray(estimator.n_features_in_),
            "iterations": np.asarray(estimator.n_iter_),
        }
        saved.require(
            len(estimator._predictors) == 64 and estimator.n_iter_ == 64,
            "Exact registered iteration count",
        )
        for stage, trees in enumerate(estimator._predictors):
            saved.require(len(trees) == 1, "One arithmetic regression output")
            tree = trees[0]
            saved.require(
                not tree.nodes["is_categorical"].any(), "Numeric original features"
            )
            numeric[f"nodes_{stage}"] = tree.nodes
            numeric[f"raw_categories_{stage}"] = tree.raw_left_cat_bitsets
            numeric[f"binned_categories_{stage}"] = tree.binned_left_cat_bitsets
        path = output / f"model-{month}.npz"
        saved.require(not path.exists(), "Fresh model evidence required")
        np.savez_compressed(path, **numeric)
        records[month] = {"file": path.name, "sha256": saved.digest(path)}
    return records


# Fit the registered direct head once and simulate only its three new funded books.
def evaluate(args, loaded, source):
    from backend.market import daily_bridge_replay, direct_daily_arithmetic

    panel, grades, eligible, original, assembled, anchors = loaded
    saved.require(not args.output.exists(), "Fresh private output; no restart")
    root = Path(__file__).resolve().parents[2]
    for protected in (
        root,
        args.daily,
        args.daily_dir,
        args.snapshot.parent,
        args.bridge_study,
        args.bridge_proof.parent,
    ):
        saved.require(
            not args.output.resolve().is_relative_to(protected.resolve()),
            "Output outside original/source/proof trees",
        )
    bridge, controls, control_records = load_controls(args, panel, anchors)
    prepared = saved.arrays(args.daily / "prepared.npz")
    prepared.update(
        symbols=tuple(panel.tickers),
        feature_names=json.loads((args.daily / "fit.json").read_bytes())["identity"][
            "features"
        ],
        absolute_forecasts=original["relative"] + original["spy"][:, None],
    )
    saved.require(
        np.array_equal(prepared["dates"], panel.dates), "Original feature dates"
    )
    first = int(
        np.flatnonzero(panel.dates == np.datetime64("2020-03-02"))[0]
    )
    for books in controls.values():
        for account in books.values():
            saved.require(
                np.array_equal(account["dates"], panel.dates[first:]),
                "Unchanged common control anchor",
            )
    direct = direct_daily_arithmetic.walk_forward(prepared, bridge)
    validate_models(direct.models, direct.manifest)
    args.output.mkdir(parents=True)
    model_records = save_models(args.output, direct.models)
    saved.write_json(
        args.output / "direct-fit.json",
        {"forecast_manifest": direct.manifest, "models": model_records},
    )
    np.savez_compressed(
        args.output / "direct-forecasts.npz",
        forecasts=direct.forecasts,
        dates=panel.dates,
        symbols=np.asarray(panel.tickers),
        score_mask=bridge.score_mask,
    )
    identity = {
        "policy": POLICY,
        "source": source,
        "as_of": saved.AS_OF,
        "original_artifacts": saved.ORIGINAL,
        "original_input": assembled,
        "bridge_report_sha256": BRIDGE_REPORT,
        "bridge_proof_sha256": BRIDGE_PROOF,
        "control_source_revision": CONTROL_SOURCE,
        "common_anchor": str(panel.dates[first]),
        "first_fill_session": str(panel.dates[first + 1]),
        "cost_bps": list(saved.COSTS),
        "new_stock_accounts": 3,
        "reused_control_accounts": 15,
        "execution": "frozen_previous_close_quantities_next_official_open_proxy",
        "selection": "current_vintage_reconstruction_not_historical_publication",
        "adoption_eligible": False,
    }
    saved.write_json(args.output / "identity.json", identity)
    rows = []
    for cost in saved.COSTS:
        account = daily_bridge_replay.run_account(
            panel,
            grades,
            eligible,
            direct.forecasts,
            method="calibrated",
            cost_bps=cost,
            first=first,
        )
        record = saved.save_account(
            args.output,
            f"direct-{cost}",
            account,
            saved.score(account, controls[cost]),
        )
        rows.append(
            {
                "cost_bps": cost,
                "direct": record,
                "reused_controls": control_records[cost],
            }
        )
        print(json.dumps({"cost_bps": cost, "new_direct_books": len(rows)}), flush=True)
    for path, expected in anchors.items():
        saved.require(saved.digest(path) == expected, "Original evidence preserved")
    saved.require(saved.source_identity(args) == source, "Exact mounted source")
    report = {
        "identity": identity,
        "status": "complete_direct_daily_component_not_adopted",
        "fit_file": "direct-fit.json",
        "fit_sha256": saved.digest(args.output / "direct-fit.json"),
        "forecast_file": "direct-forecasts.npz",
        "forecast_sha256": saved.digest(args.output / "direct-forecasts.npz"),
        "rows": rows,
        "controls_scores_are_original": True,
        "adoption_eligible": False,
        "runtime": {
            "numpy": np.__version__,
            "image_id": os.environ.get("EXPECTED_IMAGE_ID"),
        },
    }
    saved.write_json(args.output / "evaluation.json", report)
    print(
        json.dumps(
            {
                "complete": True,
                "report_sha256": saved.digest(args.output / "evaluation.json"),
            }
        ),
        flush=True,
    )
    return report


# Parse supplied immutable evidence and one fresh private result destination.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "snapshot",
        "provenance",
        "daily-dir",
        "daily",
        "original-proof",
        "bridge-study",
        "bridge-proof",
        "source-manifest",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("source-revision", "manifest-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    saved.require(not args.output.exists(), "Fresh private output; no restart")
    source = saved.source_identity(args)
    evaluate(args, saved.load_inputs(args), source)


if __name__ == "__main__":
    main()
