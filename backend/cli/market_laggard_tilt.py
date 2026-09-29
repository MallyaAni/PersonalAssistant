"""Run the frozen partial-laggard comparison on explicitly trusted cached inputs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import pickle
import subprocess
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import point_in_time, policy_v4, simulate
from backend.cli.market_filing_expectations import write_json
from backend.cli.market_pit_scorecard import window_stats
from backend.market import (
    benchmarks,
    filing_expectations,
    laggard_tilt,
    profit_taking,
    stage3_io,
    stage3_overlay,
)
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot
from backend.market.session_anatomy import json_ready

CACHE_SHA256 = "dbe55808a0be2ea01932f5212da28cf72dffffa0fe3ea8b097727b304f8a8b91"
FORECAST_SHA256 = "c89f17f7f7e68639f30c05537daf7eeb55afb7a311290d315f1d34201cec2ff2"
WINDOWS = {
    "2018-2023": ("2018-01-01", "2024-01-01"),
    "2024-2026": ("2024-01-01", None),
    "all": (None, None),
}


class FrozenIndexes:
    """Compatibility with the completed study's public-data-only cache wrapper."""

    # Serve the already captured benchmark histories, never a newer store partition.
    def read(self, symbol, asof=None):
        return self.histories.get(symbol)


class CacheReader(pickle.Unpickler):
    """Only for the explicitly trusted, hash-pinned cache created by this workspace."""

    # Reuse data without importing the failed experiment's learner or simulator hooks.
    def find_class(self, module, name):
        if (module, name) == ("backend.market.daily_action_study", "FrozenIndexes"):
            return FrozenIndexes
        return super().find_class(module, name)


# Authenticate the specifically registered local cache before any pickle operation.
def load_cache(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CACHE_SHA256:
        raise ValueError("trusted public cache hash mismatch")
    bundle = CacheReader(io.BytesIO(raw)).load()
    if set(bundle) != {"report", "membership", "indexes", "spy", "qqq"}:
        raise ValueError("unexpected public cache schema")
    return bundle


# Save the complete observed journal exclusively in compressed form and verify readback.
def save_journal(path, snapshot):
    body = json.dumps(snapshot, allow_nan=False, separators=(",", ":")).encode()
    with gzip.open(path, "xb") as handle:
        handle.write(body)
    with gzip.open(path, "rb") as handle:
        if handle.read() != body:
            raise ValueError("journal readback differs")
    return hashlib.sha256(body).hexdigest()


# Retain annual and causal-regime diagnostics on this account's actual return intervals.
def diagnostics(dates, returns, regime):
    years = sorted(set(str(day)[:4] for day in dates))
    annual = {
        year: window_stats(
            returns[np.array([str(day).startswith(year) for day in dates])]
        )
        for year in years
    }
    by_regime = {}
    for name in sorted(set(regime)):
        keep = (regime == name) & np.isfinite(returns)
        by_regime[name] = {
            "sessions": int(keep.sum()),
            "mean_daily_bp": float(returns[keep].mean() * 1e4) if keep.any() else None,
        }
    return {"annual": annual, "causal_regimes": by_regime}


# Run a funded stock account and independently reconstruct every closing mark.
def stock_account(bundle, grid, label, offset, cost, out, revision):
    report, mask = bundle["report"], bundle["membership"]
    panel = report.panel
    allocator = (
        policy_v4.allocator(mask)
        if label == "v4"
        else laggard_tilt.Allocator(mask, grid, label == "placebo")
    )
    opens = simulate.adjusted_open(panel)
    journal = ResearchJournal(
        panel.dates,
        panel.tickers,
        opens,
        panel.adj_close,
        run_id=f"laggard-tilt-{label}-{offset}-{cost}",
        account_id="synthetic-research",
        policy_id=label,
        cost_bps=cost,
        provenance={
            "source_revision": revision,
            "cache_sha256": CACHE_SHA256,
            "forecast_sha256": FORECAST_SHA256,
        },
    )
    result = simulate.run(
        report,
        since=panel.dates[offset].astype(object),
        cost_bps=cost,
        allocator=allocator,
        journal=journal,
        **profit_taking.control_options(panel),
    )
    snapshot = journal.snapshot()
    verified = verify_snapshot(snapshot)
    if not verified["ok"]:
        raise ValueError(f"account reconciliation failed: {verified['errors']}")
    marks = verified["marks"]
    nav = np.asarray([row["nav"] for row in marks])
    replay_returns = np.r_[np.nan, nav[1:] / nav[:-1] - 1]
    np.testing.assert_allclose(result.returns, replay_returns, atol=1e-10, rtol=1e-10)
    digest = save_journal(out / f"journal-{label}-{offset}-{cost}.json.gz", snapshot)
    turnover = np.diff(np.asarray([row["traded"] for row in marks])) / nav[:-1]
    metadata = {
        "journal_sha256_uncompressed": digest,
        "reconciled_marks": len(marks),
        "mean_closing_stock_exposure": float(np.nanmean(result.invested)),
        "annualized_gross_turnover": float(turnover.mean() * 252),
        "recorded_fill_batches": sum(
            row["type"] == "fill_batch" for row in snapshot["events"]
        ),
    }
    if label != "v4":
        metadata["allocator"] = {
            "calls": allocator.calls,
            "changed": allocator.changed,
            "sum_target_reduction": allocator.shifted,
            "max_target_cash_difference": allocator.max_cash_difference,
        }
    return result.dates, result.returns, metadata


# Aggregate every offset rather than choosing a favourable reset phase.
def summarize(accounts):
    rows = []
    for cost in (10, 25):
        for window, bounds in WINDOWS.items():
            for label in ("v4", "sequence", "placebo", "SPY", "QQQ"):
                curves = [
                    row
                    for row in accounts
                    if row["cost_bps"] == cost and row["label"] == label
                ]
                stats, wins, differences = [], 0, []
                for curve in curves:
                    dates = np.asarray(curve["dates"], dtype="datetime64[D]")
                    keep = point_in_time.window(dates, *bounds)
                    values = np.asarray(curve["returns"], dtype=float)
                    stats.append(window_stats(values[keep]))
                    control = next(
                        row
                        for row in accounts
                        if row["cost_bps"] == cost
                        and row["label"] == "v4"
                        and row["offset"] == curve["offset"]
                    )
                    baseline = np.asarray(control["returns"], dtype=float)
                    np.testing.assert_array_equal(
                        dates, np.asarray(control["dates"], dtype="datetime64[D]")
                    )
                    wins += int(
                        stats[-1]["cagr"] > window_stats(baseline[keep])["cagr"]
                    )
                    differences.append(
                        float(np.nanmean(values[keep] - baseline[keep]) * 1e4)
                    )
                rows.append(
                    {
                        "cost_bps": cost,
                        "window": window,
                        "label": label,
                        "median_cagr": float(np.median([row["cagr"] for row in stats])),
                        "median_drawdown": float(
                            np.median([row["drawdown"] for row in stats])
                        ),
                        "offsets_above_v4": wins,
                        "median_paired_daily_bp": float(np.median(differences)),
                    }
                )
    return rows


# Apply the predeclared advancement screens; passing never authorises promotion.
def verdict(rows, accounts):
    chosen = {
        (row["window"], row["label"]): row for row in rows if row["cost_bps"] == 25
    }
    early, later = chosen["2018-2023", "sequence"], chosen["2024-2026", "sequence"]
    baseline = chosen["2018-2023", "v4"]
    sequence = next(
        row
        for row in accounts
        if row["label"] == "sequence" and row["offset"] == 10 and row["cost_bps"] == 25
    )
    control = next(
        row
        for row in accounts
        if row["label"] == "v4" and row["offset"] == 10 and row["cost_bps"] == 25
    )
    dates = np.asarray(sequence["dates"], dtype="datetime64[D]")
    diff = np.asarray(sequence["returns"], dtype=float) - np.asarray(
        control["returns"], dtype=float
    )
    keep = point_in_time.window(dates, *WINDOWS["2018-2023"]) & np.isfinite(diff)
    interval = filing_expectations.benefit_interval(dates[keep], diff[keep])
    checks = {
        "cagr_gain_at_least_one_point": early["median_cagr"] - baseline["median_cagr"]
        >= 0.01,
        "at_least_16_offsets": early["offsets_above_v4"] >= 16,
        "recent_nonnegative": later["median_paired_daily_bp"] >= 0,
        "positive_bootstrap_lower": interval[0] is not None and interval[0] > 0,
    }
    for window in ("2018-2023", "2024-2026"):
        candidate = chosen[window, "sequence"]
        checks[f"{window}_drawdown"] = (
            candidate["median_drawdown"]
            >= chosen[window, "v4"]["median_drawdown"] - 0.01
        )
        checks[f"{window}_beats_placebo"] = (
            candidate["median_cagr"] > chosen[window, "placebo"]["median_cagr"]
        )
    return {
        "label": "RESEARCH_PROMISING_NOT_PROMOTION"
        if all(checks.values())
        else "DO_NOT_ADVANCE",
        "checks": checks,
        "representative_offset": 10,
        "paired_daily_return_benefit_95pct": interval,
        "live_promotion_authorized": False,
    }


# Run the registered grid from clean code and save each account as it completes.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trusted-cache", required=True)
    parser.add_argument("--forecast", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if subprocess.check_output(["git", "status", "--porcelain"], text=True):
        parser.error("commit the research code before running")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if hashlib.sha256(Path(args.forecast).read_bytes()).hexdigest() != FORECAST_SHA256:
        parser.error("registered sequence forecast hash mismatch")
    bundle = load_cache(args.trusted_cache)
    report = bundle["report"]
    forecast = stage3_io.load_forecast(args.forecast)
    aligned = stage3_overlay.align(forecast, report.panel)
    regime = laggard_tilt.regimes(bundle["spy"])
    out = Path(args.out)
    out.mkdir(parents=False, exist_ok=False)
    accounts = []
    for cost in (10, 25):
        for offset in range(20):
            for label in ("v4", "sequence", "placebo", "SPY", "QQQ"):
                if label in ("SPY", "QQQ"):
                    dates = report.panel.dates[offset:]
                    series = benchmarks.load_benchmark(
                        bundle["indexes"], label, dates, cost_bps=cost
                    )
                    if not series.available:
                        raise ValueError(series.reason)
                    returns, metadata = series.daily, {"funded_buy_and_hold": True}
                else:
                    dates, returns, metadata = stock_account(
                        bundle, aligned.grid, label, offset, cost, out, revision
                    )
                row = {
                    "label": label,
                    "cost_bps": cost,
                    "offset": offset,
                    "dates": [str(day) for day in dates],
                    "returns": returns.tolist(),
                    "metadata": metadata,
                    **diagnostics(dates, returns, regime[offset:]),
                }
                accounts.append(row)
                write_json(out / f"curve-{label}-{offset}-{cost}.json", json_ready(row))
                print(
                    f"{cost} bp offset {offset} {label}: saved and verified", flush=True
                )
    rows = summarize(accounts)
    output = {
        "plan": laggard_tilt.PLAN,
        "source_revision": revision,
        "cache_sha256": CACHE_SHA256,
        "forecast_sha256": FORECAST_SHA256,
        "rows": rows,
        "verdict": verdict(rows, accounts),
        "stock_accounts_reconciled": 120,
        "funded_index_accounts": 80,
        "historical_availability_verified": False,
    }
    write_json(out / "summary.json", json_ready(output))
    print(json.dumps(output["verdict"], indent=2))


if __name__ == "__main__":
    main()
