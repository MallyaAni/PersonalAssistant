"""Export and evaluate the registered offline filing-expectations experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

from backend.market import filing_expectations as study
from backend.market import fundamental_source_store as sources
from backend.market.panel import build_panel
from backend.market.store import MarketStore


# Serialize strict JSON exclusively and verify the persisted bytes immediately.
def write_json(path, value):
    body = (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    with Path(path).open("xb") as handle:
        handle.write(body)
    if Path(path).read_bytes() != body:
        raise ValueError("research output readback differs")
    return hashlib.sha256(body).hexdigest()


# Bind the research output to the actual checkout, including uncommitted code hashes.
def provenance():
    root = Path(__file__).resolve().parents[2]
    names = (
        "backend/market/filing_expectations.py",
        "backend/cli/market_filing_expectations.py",
        "backend/market/qualified_fundamentals.py",
        "backend/market/fundamental_period_sources.py",
        "backend/market/fundamental_unit_sources.py",
        "backend/market/fundamental_source_store.py",
        study.PLAN,
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    return {
        "revision": revision,
        "sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in names
        },
    }


# Read only the declared original-byte archives and build first-disclosure events.
def export(args):
    root = Path(args.sources)
    if not (root / sources.KIND).is_dir():
        raise ValueError("original-byte source archives required; no legacy fallback")
    tickers = sorted(
        {path.stem for path in (root / sources.KIND).glob("asof=*/*.parquet")}
    )
    events, inventory, rejected = [], [], Counter()
    store = MarketStore(root)
    for ticker in tickers:
        stored = sources.load(store, ticker, args.asof)
        if stored is None:
            rejected["missing_source_before_archive_cutoff"] += 1
            continue
        rows, failures = study.source_events(ticker, stored.source, args.asof)
        events.extend(rows)
        rejected.update(failures)
        inventory.append(
            {
                "ticker": ticker,
                "cik": stored.source.cik,
                "sha256": stored.source.sha256,
                "asof": str(stored.asof),
                "captured_at": stored.captured_at.isoformat(),
                "events": len(rows),
                "rejected": failures,
            }
        )
        print(f"{ticker}: {len(rows)} eligible filing events", flush=True)
    events.sort(key=lambda row: (row["feature_date"], row["ticker"], row["period_end"]))
    study.validate_events(events)
    output = {
        "schema": "filing-expectations-events/1",
        "features": list(study.FEATURES),
        "asof": str(args.asof),
        "source_inventory": inventory,
        "rejected": dict(rejected),
        "events": events,
        "historical_authenticity_verified": False,
        "provenance": provenance(),
    }
    digest = write_json(args.out, output)
    print(
        json.dumps({"events": len(events), "issuers": len(inventory), "sha256": digest})
    )


# Load the exact declared dataset and refuse changed bytes or feature contracts.
def load_events(path, digest):
    body = Path(path).read_bytes()
    if hashlib.sha256(body).hexdigest() != digest:
        raise ValueError("event dataset hash mismatch")
    dataset = json.loads(body)
    if dataset["schema"] != "filing-expectations-events/1" or dataset[
        "features"
    ] != list(study.FEATURES):
        raise ValueError("unsupported event feature contract")
    study.validate_events(dataset["events"])
    return dataset


# Run the fixed learners and save predictions, models and gross diagnostics.
def evaluate(args):
    dataset = load_events(args.events, args.sha256)
    out = Path(args.out)
    out.mkdir(parents=False, exist_ok=False)
    events = dataset["events"]
    predictions, fits = study.walk_forward(events)
    summary = {
        "plan": study.PLAN,
        "events_sha256": args.sha256,
        "provenance": provenance(),
        "parameters": study.LGBM_PARAMS,
        "models": study.summarize(events, predictions),
        "source_issuers": len(dataset["source_inventory"]),
        "eligible_events": len(events),
        "source_rejections": dataset["rejected"],
        "live_promotion_authorized": False,
        "historical_authenticity_verified": False,
    }
    retained = [
        {
            "ticker": row["ticker"],
            "period_end": row["period_end"],
            "feature_date": row["feature_date"],
            "available": row["available"],
            "target": row["target"],
            "baseline": row["baseline"],
            "predictions": {
                name: float(values[i]) if np.isfinite(values[i]) else None
                for name, values in predictions.items()
            },
        }
        for i, row in enumerate(events)
    ]
    if args.market:
        market = MarketStore(args.market)
        tickers = sorted({row["ticker"] for row in events} | {"SPY", "QQQ"})
        asof = date.fromisoformat(dataset["asof"])
        panel = build_panel(market, tickers, "SPY", {}, asof=asof)
        # A vendor partition can contain later rows; preserve the evaluation cutoff.
        keep = panel.dates <= np.datetime64(asof)
        from dataclasses import replace

        panel = replace(
            panel,
            **{
                name: getattr(panel, name)[keep]
                for name in (
                    "dates",
                    "open",
                    "high",
                    "low",
                    "close",
                    "adj_close",
                    "volume",
                )
            },
        )
        returns = study.event_returns(events, panel)
        summary["returns"] = study.return_diagnostics(events, predictions, returns)
        for row, reading in zip(retained, returns, strict=True):
            row["gross_returns"] = reading
        summary["price_partitions"] = {
            ticker: str(market._latest_of_kind("bars", ticker, asof))
            for ticker in tickers
        }
    summary["predictions_sha256"] = write_json(out / "predictions.json", retained)
    summary["fits_sha256"] = write_json(out / "fits.json", fits)
    summary["summary_sha256_note"] = "summary hash is printed after exclusive write"
    digest = write_json(out / "summary.json", summary)
    print(json.dumps({"summary_sha256": digest, "models": summary["models"]}, indent=2))


# Expose explicit offline input/output paths without any deployment or trading mode.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("export")
    build.add_argument("--sources", required=True)
    build.add_argument("--asof", required=True, type=date.fromisoformat)
    build.add_argument("--out", required=True)
    score = commands.add_parser("evaluate")
    score.add_argument("--events", required=True)
    score.add_argument("--sha256", required=True)
    score.add_argument("--market")
    score.add_argument("--out", required=True)
    args = parser.parse_args()
    (export if args.command == "export" else evaluate)(args)


if __name__ == "__main__":
    main()
