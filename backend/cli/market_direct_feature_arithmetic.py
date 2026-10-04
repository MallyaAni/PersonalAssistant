"""Fit one independent-support daily head and compare six new funded books."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from backend.cli import market_direct_error_band as old

saved = old.saved
POLICY = "direct-feature-arithmetic/1-research"
BAND_SOURCE = "0e563ccb9756814c7493aa777e61b28ed8a2eb0b"
BAND_REPORT = "98d29a64cfb2703fb79c06b76a1d1cc74307ea1d86dcb1650981778cd935f3c0"
BAND_PROOF = "ea673e3e4555ac853eafd6c713b61739d54872928b2f9cde4361cfa2f3cc7b09"


# Authenticate the last three controls and retain their original recorded scores.
def load_band(args, anchors, controls, records):
    saved.require(saved.digest(args.band_proof) == BAND_PROOF, "Band proof bytes")
    anchors[args.band_proof] = BAND_PROOF
    proof = json.loads(args.band_proof.read_bytes())
    saved.require(
        proof["ok"] is True
        and proof["source_revision"] == BAND_SOURCE
        and proof["report_sha256"] == BAND_REPORT
        and proof["new_stock_accounts"] == 3
        and proof["reused_control_accounts"] == 18,
        "Exact completed band proof required",
    )
    path = old.direct.checked_file(
        args.band_study, "evaluation.json", BAND_REPORT, anchors
    )
    report = json.loads(path.read_bytes())
    saved.require(
        report["status"] == "complete_error_band_daily_component_not_adopted"
        and report["adoption_eligible"] is False
        and report["controls_scores_are_original"] is True
        and report["identity"]["source"]["revision"] == BAND_SOURCE
        and report["identity"]["common_anchor"] == "2020-03-02"
        and [row["cost_bps"] for row in report["rows"]] == list(saved.COSTS),
        "Complete saved band cost/source grid",
    )
    for row in report["rows"]:
        cost, record = row["cost_bps"], row["error_band"]
        saved.require(
            row["reused_controls"] == records[cost],
            "Exact eighteen old control records",
        )
        key = f"error-band-{cost}"
        saved.require(
            record["arrays_file"] == key + ".npz"
            and record["receipt_file"] == key + ".json"
            and proof["book_artifacts"][key]
            == {"arrays": record["arrays_sha256"], "receipt": record["receipt_sha256"]},
            "Proof-linked band book names",
        )
        numeric_path = old.direct.checked_file(
            args.band_study, record["arrays_file"], record["arrays_sha256"], anchors
        )
        receipt_path = old.direct.checked_file(
            args.band_study, record["receipt_file"], record["receipt_sha256"], anchors
        )
        numeric, receipt = (
            saved.arrays(numeric_path),
            json.loads(receipt_path.read_bytes()),
        )
        saved.require(
            not (numeric.keys() & receipt["account"].keys())
            and receipt["score"] == record["score"],
            "Separated old band state and exact score",
        )
        controls[cost]["old_band"] = {**receipt["account"], **numeric}
        records[cost]["old_band"] = record


# Preserve input trees and run only the six registered new accounts from one fit.
def evaluate(args, loaded, source):
    from backend.market import daily_bridge_replay, direct_feature_arithmetic

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
        args.direct_study,
        args.direct_proof.parent,
        args.band_study,
        args.band_proof.parent,
    ):
        saved.require(
            not args.output.resolve().is_relative_to(protected.resolve()),
            "Output outside original/source/proof trees",
        )
    bridge, controls, records = old.direct.load_controls(args, panel, anchors)
    old.load_direct(args, panel, anchors, controls, records)
    load_band(args, anchors, controls, records)
    first = int(np.flatnonzero(panel.dates == np.datetime64("2020-03-02"))[0])
    for books in controls.values():
        saved.require(
            set(books)
            == {"direct", "old_band", "calibrated", "mean", "equal", "SPY", "QQQ"},
            "All21 saved controls",
        )
        for account in books.values():
            saved.require(
                np.array_equal(account["dates"], panel.dates[first:]),
                "Unchanged common control anchor",
            )
    prepared = saved.arrays(args.daily / "prepared.npz")
    prepared.update(
        symbols=tuple(panel.tickers),
        feature_names=json.loads((args.daily / "fit.json").read_bytes())["identity"][
            "features"
        ],
        absolute_forecasts=original["relative"] + original["spy"][:, None],
    )
    saved.require(
        np.array_equal(prepared["dates"], panel.dates), "Exact original feature dates"
    )
    forecast = direct_feature_arithmetic.walk_forward(
        prepared, bridge, grades, eligible
    )
    old.direct.validate_models(forecast.models, forecast.manifest)
    bands = direct_feature_arithmetic.calibrate(forecast, bridge)
    args.output.mkdir(parents=True)
    model_files = old.direct.save_models(args.output, forecast.models)
    saved.write_json(
        args.output / "feature-fit.json",
        {"forecast_manifest": forecast.manifest, "model_files": model_files},
    )
    saved.write_json(args.output / "calibration.json", bands.manifest)
    np.savez_compressed(
        args.output / "feature-forecasts.npz",
        forecasts=forecast.forecasts,
        radii=bands.radii,
        score_mask=forecast.score_mask,
        dates=panel.dates,
        symbols=np.asarray(panel.tickers),
    )
    identity = {
        "policy": POLICY,
        "source": source,
        "as_of": saved.AS_OF,
        "original_artifacts": saved.ORIGINAL,
        "original_input": assembled,
        "bridge_report_sha256": old.direct.BRIDGE_REPORT,
        "bridge_proof_sha256": old.direct.BRIDGE_PROOF,
        "direct_report_sha256": old.DIRECT_REPORT,
        "direct_proof_sha256": old.DIRECT_PROOF,
        "band_report_sha256": BAND_REPORT,
        "band_proof_sha256": BAND_PROOF,
        "common_anchor": str(panel.dates[first]),
        "first_fill_session": str(panel.dates[first + 1]),
        "cost_bps": list(saved.COSTS),
        "new_stock_accounts": 6,
        "reused_control_accounts": 21,
        "execution": "frozen_previous_close_quantities_next_official_open_proxy",
        "selection": "current_vintage_reconstruction_not_historical_publication",
        "adoption_eligible": False,
    }
    saved.write_json(args.output / "identity.json", identity)
    rows = []
    for cost in saved.COSTS:
        accounts = {}
        for name, radii in (("feature_raw", None), ("feature_band", bands.radii)):
            account = daily_bridge_replay.run_account(
                panel,
                grades,
                eligible,
                forecast.forecasts,
                method="calibrated",
                cost_bps=cost,
                first=first,
                radii=radii,
            )
            accounts[name] = saved.save_account(
                args.output,
                f"{name}-{cost}",
                account,
                saved.score(account, controls[cost]),
            )
            print(json.dumps({"cost_bps": cost, "new_book": name}), flush=True)
        rows.append(
            {"cost_bps": cost, "accounts": accounts, "reused_controls": records[cost]}
        )
    for path, expected in anchors.items():
        saved.require(saved.digest(path) == expected, "Original evidence preserved")
    saved.require(saved.source_identity(args) == source, "Exact mounted source")
    report = {
        "identity": identity,
        "status": "complete_independent_feature_component_not_adopted",
        "fit_file": "feature-fit.json",
        "fit_sha256": saved.digest(args.output / "feature-fit.json"),
        "forecast_file": "feature-forecasts.npz",
        "forecast_sha256": saved.digest(args.output / "feature-forecasts.npz"),
        "calibration_file": "calibration.json",
        "calibration_sha256": saved.digest(args.output / "calibration.json"),
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


# Parse exact supplied evidence and one fresh private research destination.
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
        "direct-study",
        "direct-proof",
        "band-study",
        "band-proof",
        "source-manifest",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("source-revision", "manifest-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    saved.require(not args.output.exists(), "Fresh private output; no restart")
    evaluate(args, saved.load_inputs(args), saved.source_identity(args))


if __name__ == "__main__":
    main()
