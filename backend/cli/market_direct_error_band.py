"""Create three error-band books from authenticated saved direct predictions.

No original model fitting, estimator scoring or completed account replay occurs.
All original inputs and eighteen controls remain supplied read-only evidence.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from backend.cli import market_direct_daily_arithmetic as direct

saved = direct.saved
POLICY = "direct-error-band/1-research"
DIRECT_SOURCE = "e093cd51b9207899bfee6c46f4f578b1e7fd1d97"
DIRECT_REPORT = "764e8e6489325bf84d515ae2acc000bdebe41a2b539e59df1dce274950e8fc0a"
DIRECT_PROOF = "8c8bbe09871d4e1ae3a87ecf306d135f80c330a111edee4bb1664d3b2ecb7017"


# Authenticate original direct forecasts and all three proof-linked saved books.
def load_direct(args, panel, anchors, controls, records):
    saved.require(saved.digest(args.direct_proof) == DIRECT_PROOF, "Direct proof")
    anchors[args.direct_proof] = DIRECT_PROOF
    proof = json.loads(args.direct_proof.read_bytes())
    saved.require(
        proof["ok"] is True
        and proof["source_revision"] == DIRECT_SOURCE
        and proof["report_sha256"] == DIRECT_REPORT
        and proof["new_stock_accounts"] == 3
        and proof["reused_control_accounts"] == 15,
        "Exact completed direct proof required",
    )
    report_path = direct.checked_file(
        args.direct_study, "evaluation.json", DIRECT_REPORT, anchors
    )
    report = json.loads(report_path.read_bytes())
    saved.require(
        report["status"] == "complete_direct_daily_component_not_adopted"
        and report["adoption_eligible"] is False
        and report["controls_scores_are_original"] is True
        and report["identity"]["source"]["revision"] == DIRECT_SOURCE
        and report["identity"]["common_anchor"] == "2020-03-02"
        and [row["cost_bps"] for row in report["rows"]] == list(saved.COSTS),
        "Exact completed direct component and cost grid",
    )
    for field in ("fit", "forecast"):
        saved.require(
            proof[field + "_sha256"] == report[field + "_sha256"],
            "Proof-linked direct " + field,
        )
    numeric_path = direct.checked_file(
        args.direct_study, report["forecast_file"], report["forecast_sha256"], anchors
    )
    fit_path = direct.checked_file(
        args.direct_study, report["fit_file"], report["fit_sha256"], anchors
    )
    saved.require(
        numeric_path.name == "direct-forecasts.npz"
        and fit_path.name == "direct-fit.json",
        "Canonical direct forecast files",
    )
    numeric = saved.arrays(numeric_path)
    fitted = json.loads(fit_path.read_bytes())
    saved.require(
        set(numeric) == {"forecasts", "dates", "symbols", "score_mask"}
        and np.array_equal(numeric["dates"], panel.dates)
        and tuple(numeric["symbols"]) == tuple(panel.tickers),
        "Exact direct date and symbol denominator",
    )
    for row in report["rows"]:
        cost, record = row["cost_bps"], row["direct"]
        saved.require(
            row["reused_controls"] == records[cost],
            "Unchanged original fifteen control records",
        )
        saved.require(
            record["arrays_file"] == f"direct-{cost}.npz"
            and record["receipt_file"] == f"direct-{cost}.json",
            "Canonical direct control book files",
        )
        numeric_path = direct.checked_file(
            args.direct_study, record["arrays_file"], record["arrays_sha256"], anchors
        )
        receipt_path = direct.checked_file(
            args.direct_study, record["receipt_file"], record["receipt_sha256"], anchors
        )
        account, receipt = (
            saved.arrays(numeric_path),
            json.loads(receipt_path.read_bytes()),
        )
        saved.require(
            not (account.keys() & receipt["account"].keys())
            and receipt["score"] == record["score"],
            "Separated direct control arrays and exact recorded scores",
        )
        controls[cost]["direct"] = {**receipt["account"], **account}
        records[cost]["direct"] = record
    return numeric, fitted["forecast_manifest"]


# Preserve existing input trees while creating only the registered new accounts.
def evaluate(args, loaded, source):
    from backend.market import daily_bridge_replay, direct_error_band

    panel, grades, eligible, _, assembled, anchors = loaded
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
    ):
        saved.require(
            not args.output.resolve().is_relative_to(protected.resolve()),
            "Output outside original/source/proof trees",
        )
    bridge, controls, records = direct.load_controls(args, panel, anchors)
    numeric, direct_manifest = load_direct(args, panel, anchors, controls, records)
    first = int(np.flatnonzero(panel.dates == np.datetime64("2020-03-02"))[0])
    for books in controls.values():
        for account in books.values():
            saved.require(
                np.array_equal(account["dates"], panel.dates[first:]),
                "Unchanged common control anchor",
            )
    bands = direct_error_band.calibrate(
        numeric["dates"],
        numeric["symbols"],
        numeric["forecasts"],
        direct_manifest,
        bridge,
    )
    args.output.mkdir(parents=True)
    saved.write_json(args.output / "calibration.json", bands.manifest)
    np.savez_compressed(
        args.output / "bands.npz",
        radii=bands.radii,
        forecasts=numeric["forecasts"],
        dates=numeric["dates"],
        symbols=numeric["symbols"],
        score_mask=numeric["score_mask"],
    )
    identity = {
        "policy": POLICY,
        "source": source,
        "as_of": saved.AS_OF,
        "original_artifacts": saved.ORIGINAL,
        "original_input": assembled,
        "bridge_report_sha256": direct.BRIDGE_REPORT,
        "bridge_proof_sha256": direct.BRIDGE_PROOF,
        "direct_report_sha256": DIRECT_REPORT,
        "direct_proof_sha256": DIRECT_PROOF,
        "direct_source_revision": DIRECT_SOURCE,
        "common_anchor": str(panel.dates[first]),
        "first_fill_session": str(panel.dates[first + 1]),
        "cost_bps": list(saved.COSTS),
        "new_stock_accounts": 3,
        "reused_control_accounts": 18,
        "execution": "frozen_previous_close_quantities_next_official_open_proxy",
        "selection": "current_vintage_reconstruction_not_historical_publication",
        "radius_is_fee": False,
        "adoption_eligible": False,
    }
    saved.write_json(args.output / "identity.json", identity)
    rows = []
    for cost in saved.COSTS:
        account = daily_bridge_replay.run_account(
            panel,
            grades,
            eligible,
            numeric["forecasts"],
            method="calibrated",
            cost_bps=cost,
            first=first,
            radii=bands.radii,
        )
        record = saved.save_account(
            args.output,
            f"error-band-{cost}",
            account,
            saved.score(account, controls[cost]),
        )
        rows.append(
            {"cost_bps": cost, "error_band": record, "reused_controls": records[cost]}
        )
        print(
            json.dumps({"cost_bps": cost, "new_error_band_books": len(rows)}),
            flush=True,
        )
    for path, expected in anchors.items():
        saved.require(saved.digest(path) == expected, "Original evidence preserved")
    saved.require(saved.source_identity(args) == source, "Exact mounted source")
    report = {
        "identity": identity,
        "status": "complete_error_band_daily_component_not_adopted",
        "calibration_file": "calibration.json",
        "calibration_sha256": saved.digest(args.output / "calibration.json"),
        "numeric_file": "bands.npz",
        "numeric_sha256": saved.digest(args.output / "bands.npz"),
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


# Parse exact supplied artifacts and a fresh output without accessing production.
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
