"""Fit one declared arithmetic bridge and compare nine new funded daily books.

Only authenticated, supplied original artifacts are accepted. This research CLI
has no provider, production account, order or deployment path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from backend.market import allocation_controls, retention_inputs
from backend.market.allocation_evaluation import metrics

POLICY = "daily-arithmetic-bridge/1-research"
AS_OF = "2026-09-30T16:00:00-04:00"
COSTS = (0, 10, 25)
ARMS = ("calibrated", "mean", "equal")
ORIGINAL = {
    "inputs.json": "5d556a2fc4d2e4e52121e0039e11f2cfc07eb5d5f53acbb3a6240f5fcf2d171a",
    "fit.json": "726c272444e60c748eb2254e5daa33f7a2b6cbc3cc5d694041c8144c515ae42b",
    "prepared.npz": "67dd974e0cd3c8d5a24859931c4c5e61d5d40def008d688c160bd1d08ddc56eb",
    "forecasts.npz": "4de8c9521bb1f7eaf3047c6c45534ef172dbf02b83d087e914cb2d124e8f712d",
}
WINDOWS = {
    "all": ("2018-02-01", "2026-09-30"),
    "2018_2020": ("2018-02-01", "2020-12-31"),
    "2021_2026": ("2021-01-01", "2026-09-30"),
    "reused_2026_08_17_09_30": ("2026-08-17", "2026-09-30"),
}


# Stop at the first unsupported source, clock or persistence boundary.
def require(condition, message):
    if not condition:
        raise ValueError(message)


# Authenticate bytes before parsing and after the completed experiment.
def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


# Read numeric archives without executing pickled data or loading a fitted model.
def arrays(path):
    with np.load(path, allow_pickle=False) as bundle:
        return {name: bundle[name].copy() for name in bundle.files}


# Write new evidence atomically without overwriting an existing checkpoint.
def write_json(path, value):
    require(not path.exists(), "Existing evidence must not be overwritten")
    temporary = path.with_suffix(path.suffix + ".tmp")
    require(not temporary.exists(), "Incomplete prior evidence must be preserved")
    temporary.write_text(
        json.dumps(readable_value(value), sort_keys=True, allow_nan=False) + "\n"
    )
    os.replace(temporary, path)


# Retain missing numeric evidence as null while refusing infinities and opaque objects.
def readable_value(value):
    if isinstance(value, np.ndarray):
        return readable_value(value.tolist())
    if isinstance(value, np.generic):
        return readable_value(value.item())
    if isinstance(value, dict):
        require(
            all(isinstance(key, str) for key in value), "String receipt keys required"
        )
        return {key: readable_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [readable_value(item) for item in value]
    if isinstance(value, float):
        require(not np.isinf(value), "Infinite receipt value is invalid")
        return None if np.isnan(value) else value
    require(
        value is None or isinstance(value, (str, bool, int)),
        "Unsupported receipt value",
    )
    return value


# Verify every mounted source file against the caller's exact committed manifest.
def source_identity(args):
    root = Path(__file__).resolve().parents[2]
    require(
        digest(args.source_manifest) == args.manifest_sha256, "Source manifest bytes"
    )
    manifest = json.loads(args.source_manifest.read_bytes())
    require(manifest["git_commit"] == args.source_revision, "Source revision")
    for name, expected in manifest["files"].items():
        path = root / name
        require(path.resolve().is_relative_to(root.resolve()), "Source path boundary")
        require(digest(path) == expected, "Mounted source differs: " + name)
    return {
        "revision": args.source_revision,
        "manifest_sha256": args.manifest_sha256,
        "files": len(manifest["files"]),
    }


# Restore only the immutable original daily study and its certified assembly.
def load_inputs(args):
    anchors = {
        args.snapshot: (
            "8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58"
        ),
        args.provenance: (
            "529f59d10ca0b612b050a0eddd21b2fd7eee316346004130d035cdac4dbd9844"
        ),
        args.original_proof: (
            "d855eea0eb910748f01142a3b44f027079f1665afd9570d95c0d0f1a879a238f"
        ),
        **{args.daily / name: value for name, value in ORIGINAL.items()},
    }
    for path, expected in anchors.items():
        require(digest(path) == expected, "Original artifact differs: " + str(path))
    require(
        json.loads(args.original_proof.read_bytes())["ok"] is True, "Original proof"
    )
    panel, grades, eligible, assembled = retention_inputs.load(
        args.snapshot, args.provenance, args.daily_dir
    )
    original = json.loads((args.daily / "inputs.json").read_bytes())["original_inputs"]
    for key in ("arrays_sha256", "grades_sha256", "eligible_sha256", "symbols"):
        require(assembled[key] == original[key], "Original daily assembly: " + key)
    for name in panel.tickers:
        require(
            assembled["daily_sources"][name]["sha256"]
            == original["daily_sources"][name]["sha256"],
            "Original parquet bytes: " + name,
        )
    forecasts = arrays(args.daily / "forecasts.npz")
    require(np.array_equal(forecasts["dates"], panel.dates), "Original forecast dates")
    require(
        len(panel.tickers) == 96 and panel.dates[-1] == np.datetime64("2026-09-30"),
        "Original fixed cohort and end date",
    )
    return panel, grades, eligible, forecasts, assembled, anchors


# Score contiguous carried windows against references on exactly identical dates.
def score(account, references):
    dates, nav = account["dates"], account["nav"]
    require(
        len(nav) == len(dates) and np.isfinite(nav).all() and (nav > 0).all(),
        "Complete positive account marks required",
    )
    for reference in references.values():
        require(np.array_equal(reference["dates"], dates), "Common reference dates")
    returns = nav[1:] / nav[:-1] - 1
    windows = []
    for name, (start, end) in WINDOWS.items():
        keep = (dates[1:] >= np.datetime64(start)) & (dates[1:] <= np.datetime64(end))
        if not keep.any():
            windows.append({"window": name, "status": "unavailable", "sessions": 0})
            continue
        measurement = metrics(returns[keep])
        reference_gains = {
            label: metrics((ref["nav"][1:] / ref["nav"][:-1] - 1)[keep])["total"]
            for label, ref in references.items()
        }
        windows.append(
            {
                "window": name,
                "status": "measured",
                "start": str(dates[1:][keep][0]),
                "end": str(dates[1:][keep][-1]),
                "sessions": int(keep.sum()),
                "total_net_gain": measurement["total"],
                "cagr": measurement["annual"],
                "max_drawdown_loss": measurement["drawdown"],
                "sharpe": measurement["sharpe"],
                "excess_gain": {
                    label: measurement["total"] - gain
                    for label, gain in reference_gains.items()
                },
                "average_exposure": float(account["exposure"][1:][keep].mean()),
                "gross_trading_per_year": float(
                    account["turnover"][1:][keep].sum() * 252 / keep.sum()
                ),
                "fees_initial_nav_units": float(account["fees"][1:][keep].sum()),
            }
        )
    rolling = {}
    if len(returns) >= 252:
        own = nav[252:] / nav[:-252]
        for label, ref in references.items():
            other = ref["nav"][252:] / ref["nav"][:-252]
            rolling[label] = {
                "windows": len(own),
                "win_rate": float(np.mean(own > other)),
            }
    return {
        "windows": windows,
        "rolling_252": rolling,
        "counts": account.get("counts", {}),
        "stocks": account.get("stocks", {}),
    }


# Save numeric account state separately from readable plans and trade receipts.
def save_account(output, name, account, measured):
    numeric = {
        key: value for key, value in account.items() if isinstance(value, np.ndarray)
    }
    readable = {key: value for key, value in account.items() if key not in numeric}
    if "prices" in readable:
        prices = readable.pop("prices")
        require(set(prices) == {"open", "close"}, "Declared account price fields")
        for key, value in prices.items():
            require(isinstance(value, np.ndarray), "Numeric account prices required")
            numeric["prices_" + key] = value
        readable["prices"] = {key: "prices_" + key for key in prices}
    path = output / (name + ".npz")
    require(not path.exists(), "Existing account must not be overwritten")
    np.savez_compressed(path, **numeric)
    receipt_path = output / (name + ".json")
    write_json(receipt_path, {"account": readable, "score": measured})
    return {
        "arrays_file": path.name,
        "arrays_sha256": digest(path),
        "receipt_file": receipt_path.name,
        "receipt_sha256": digest(receipt_path),
        "score": measured,
    }


# Fit the single frozen bridge once and create only the nine declared new books.
def evaluate(args, loaded, source):
    from backend.market import daily_arithmetic_bridge, daily_bridge_replay

    panel, grades, eligible, forecasts, assembled, anchors = loaded
    root = Path(__file__).resolve().parents[2]
    require(not args.output.exists(), "Fresh private output required; no restart")
    for protected in (root, args.daily, args.daily_dir, args.snapshot.parent):
        require(
            not args.output.resolve().is_relative_to(protected.resolve()),
            "Output must be outside original/source trees",
        )
    opens = allocation_controls.adjusted_open(panel.open, panel.close, panel.adj_close)
    bridge = daily_arithmetic_bridge.walk_forward(
        panel.dates,
        panel.tickers,
        opens,
        grades,
        eligible,
        forecasts["relative"] + forecasts["spy"][:, None],
        panel.dates,
        data_as_of=AS_OF,
    )
    first_date = bridge.manifest["first_score_date"]
    require(first_date is not None, "No causal mature bridge start available")
    first = int(np.flatnonzero(panel.dates == np.datetime64(first_date))[0])
    require(
        first >= 252 and first < len(panel.dates) - 1, "Supported causal account anchor"
    )
    args.output.mkdir(parents=True)
    identity = {
        "policy": POLICY,
        "source": source,
        "as_of": AS_OF,
        "original_artifacts": ORIGINAL,
        "original_input": assembled,
        "original_proof_sha256": digest(args.original_proof),
        "common_anchor": str(panel.dates[first]),
        "first_fill_session": str(panel.dates[first + 1]),
        "excluded_warmup_decision_sessions": int(
            (
                (panel.dates >= np.datetime64("2018-02-01"))
                & (panel.dates < panel.dates[first])
            ).sum()
        ),
        "cost_bps": list(COSTS),
        "arms": list(ARMS),
        "new_stock_accounts": 9,
        "execution": "frozen_previous_close_quantities_next_official_open_proxy",
        "selection": "current_vintage_reconstruction_not_historical_publication",
        "adoption_eligible": False,
    }
    write_json(args.output / "identity.json", identity)
    write_json(args.output / "bridge-fit.json", bridge.manifest)
    np.savez_compressed(
        args.output / "bridge.npz",
        calibrated=bridge.calibrated,
        past_mean=bridge.past_mean,
        labels=bridge.labels,
        label_end_dates=bridge.label_end_dates,
        score_mask=bridge.score_mask,
        dates=panel.dates,
        symbols=np.asarray(panel.tickers),
    )
    rows = []
    for cost in COSTS:
        accounts = {
            method: daily_bridge_replay.run_account(
                panel,
                grades,
                eligible,
                bridge.past_mean if method == "mean" else bridge.calibrated,
                method=method,
                cost_bps=cost,
                first=first,
            )
            for method in ARMS
        }
        accounts.update(
            {
                name: daily_bridge_replay.benchmark_account(
                    panel, ticker=name, cost_bps=cost, first=first
                )
                for name in ("SPY", "QQQ")
            }
        )
        records = {}
        for name, account in accounts.items():
            measured = score(
                account,
                {label: value for label, value in accounts.items() if label != name},
            )
            records[name] = save_account(
                args.output, f"{name}-{cost}", account, measured
            )
        rows.append({"cost_bps": cost, "accounts": records})
        print(
            json.dumps({"cost_bps": cost, "completed_stock_books": len(rows) * 3}),
            flush=True,
        )
    for path, expected in anchors.items():
        require(digest(path) == expected, "Original evidence changed during evaluation")
    require(source_identity(args) == source, "Source changed during evaluation")
    report = {
        "identity": identity,
        "status": "complete_reused_daily_component_not_adopted",
        "bridge_file": "bridge.npz",
        "bridge_sha256": digest(args.output / "bridge.npz"),
        "fit_file": "bridge-fit.json",
        "fit_sha256": digest(args.output / "bridge-fit.json"),
        "rows": rows,
        "adoption_eligible": False,
        "runtime": {
            "numpy": np.__version__,
            "image_id": os.environ.get("EXPECTED_IMAGE_ID"),
        },
        "limitations": [
            "Reused/current-vintage grades and universe; not an untouched holdout.",
            "Official daily opens are proxies, not broker or selected intraday fills.",
            "Daily equal target rule is not full live-policy/FOMC reconstruction.",
            "One-session log covariance approximates arithmetic conditional risk.",
            "No live adoption from these component accounts alone.",
        ],
    }
    write_json(args.output / "evaluation.json", report)
    print(
        json.dumps(
            {"complete": True, "report_sha256": digest(args.output / "evaluation.json")}
        ),
        flush=True,
    )
    return report


# Parse explicit supplied sources without discovering or writing production paths.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "snapshot",
        "provenance",
        "daily-dir",
        "daily",
        "original-proof",
        "source-manifest",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("source-revision", "manifest-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Fresh private output required; no restart")
    source = source_identity(args)
    evaluate(args, load_inputs(args), source)


if __name__ == "__main__":
    main()
