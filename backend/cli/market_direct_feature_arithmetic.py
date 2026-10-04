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
FEATURE_SOURCE = "de7a0059ceaa4ff0c4d6bccd360061f34db1c64d"
FEATURE_REPORT = "491d90d52414ef6af25d7bf0c60dc4a84c042993fbaa47052d0280a2e7425929"
FEATURE_PROOF = "87ecc525f2fe0642cd5d558fd79ccc05741fd97bd178f7b5f7d6306bbae3f60d"


# Restore six authenticated feature controls without recomputing their old scores.
def load_feature(args, anchors, controls, records):
    saved.require(
        args.feature_study is not None and args.feature_proof is not None,
        "Held-B evaluation requires the completed feature study and proof",
    )
    saved.require(
        saved.digest(args.feature_proof) == FEATURE_PROOF, "Feature proof bytes"
    )
    anchors[args.feature_proof] = FEATURE_PROOF
    proof = json.loads(args.feature_proof.read_bytes())
    saved.require(
        proof["ok"] is True
        and proof["source_revision"] == FEATURE_SOURCE
        and proof["report_sha256"] == FEATURE_REPORT
        and proof["new_stock_accounts"] == 6
        and proof["reused_control_accounts"] == 21,
        "Exact completed feature proof required",
    )
    path = old.direct.checked_file(
        args.feature_study, "evaluation.json", FEATURE_REPORT, anchors
    )
    report = json.loads(path.read_bytes())
    saved.require(
        report["status"] == "complete_independent_feature_component_not_adopted"
        and report["adoption_eligible"] is False
        and report["controls_scores_are_original"] is True
        and report["identity"]["source"]["revision"] == FEATURE_SOURCE
        and report["identity"]["common_anchor"] == "2020-03-02"
        and [row["cost_bps"] for row in report["rows"]] == list(saved.COSTS),
        "Complete saved feature cost/source grid",
    )
    for row in report["rows"]:
        cost = row["cost_bps"]
        saved.require(row["reused_controls"] == records[cost], "Exact21 old controls")
        saved.require(
            set(row["accounts"]) == {"feature_raw", "feature_band"},
            "Both original feature arms required",
        )
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
                "Proof-linked feature book names",
            )
            numeric_path = old.direct.checked_file(
                args.feature_study,
                record["arrays_file"],
                record["arrays_sha256"],
                anchors,
            )
            receipt_path = old.direct.checked_file(
                args.feature_study,
                record["receipt_file"],
                record["receipt_sha256"],
                anchors,
            )
            numeric, receipt = (
                saved.arrays(numeric_path),
                json.loads(receipt_path.read_bytes()),
            )
            saved.require(
                not (numeric.keys() & receipt["account"].keys())
                and receipt["score"] == record["score"],
                "Separated old feature state and exact original score",
            )
            controls[cost][name] = {**receipt["account"], **numeric}
            records[cost][name] = record


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
    hold_b = getattr(args, "hold_b", False)
    saved.require(isinstance(hold_b, bool), "Explicit boolean held-B option")
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
        *(
            (args.feature_study, args.feature_proof.parent)
            if hold_b
            and args.feature_study is not None
            and args.feature_proof is not None
            else ()
        ),
    ):
        saved.require(
            not args.output.resolve().is_relative_to(protected.resolve()),
            "Output outside original/source/proof trees",
        )
    bridge, controls, records = old.direct.load_controls(args, panel, anchors)
    old.load_direct(args, panel, anchors, controls, records)
    load_band(args, anchors, controls, records)
    if hold_b:
        load_feature(args, anchors, controls, records)
    first = int(np.flatnonzero(panel.dates == np.datetime64("2020-03-02"))[0])
    for books in controls.values():
        saved.require(
            set(books)
            == (
                {"direct", "old_band", "calibrated", "mean", "equal", "SPY", "QQQ"}
                | ({"feature_raw", "feature_band"} if hold_b else set())
            ),
            "Complete saved control grid",
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
        prepared, bridge, grades, eligible, **({"hold_b": True} if hold_b else {})
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
        "policy": "learned-held-exits/1-research" if hold_b else POLICY,
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
        "reused_control_accounts": 27 if hold_b else 21,
        "execution": "frozen_previous_close_quantities_next_official_open_proxy",
        "selection": "current_vintage_reconstruction_not_historical_publication",
        "adoption_eligible": False,
    }
    if hold_b:
        identity.update(
            hold_b=True,
            feature_report_sha256=FEATURE_REPORT,
            feature_proof_sha256=FEATURE_PROOF,
            buys="A/A+ only",
            held_B="retain_trim_exit_only_never_add_or_rebuy",
        )
    saved.write_json(args.output / "identity.json", identity)
    rows = []
    for cost in saved.COSTS:
        accounts = {}
        for name, radii in (
            ("held_raw" if hold_b else "feature_raw", None),
            ("held_band" if hold_b else "feature_band", bands.radii),
        ):
            account = daily_bridge_replay.run_account(
                panel,
                grades,
                eligible,
                forecast.forecasts,
                method="calibrated",
                cost_bps=cost,
                first=first,
                radii=radii,
                **({"hold_b": True} if hold_b else {}),
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
        "status": (
            "complete_learned_held_exits_component_not_adopted"
            if hold_b
            else "complete_independent_feature_component_not_adopted"
        ),
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
    parser.add_argument("--hold-b", action="store_true")
    for name in ("feature-study", "feature-proof"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    saved.require(not args.output.exists(), "Fresh private output; no restart")
    evaluate(args, saved.load_inputs(args), saved.source_identity(args))


if __name__ == "__main__":
    main()
