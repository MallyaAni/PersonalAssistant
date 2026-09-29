"""Bounded /4 ablation using existing selection forecasts; never places orders."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk, point_in_time, policy_v4, simulate
from backend.cli.market_pit_scorecard import window_stats
from backend.market import (
    benchmarks,
    candidate_stats,
    profit_taking,
    stage3_io,
    universe,
)
from backend.market import stage3_overlay as so
from backend.market.midcycle_ew import Ledger, diagnostics
from backend.market.session_anatomy import json_ready
from backend.market.store import MarketStore

PLAN = "docs/research/target-consistency-2026-09-29.md"
ASOF = date(2026, 9, 28)
ARMS = ("base", "base_gate", "ml", "ml_gate", "equal_weight")
PAIRS = (
    ("base_gate", "base"),
    ("ml", "base"),
    ("ml_gate", "base_gate"),
    ("ml_gate", "ml"),
    ("ml_gate", "base"),
    ("base", "SPY"),
    ("base", "QQQ"),
    ("ml_gate", "SPY"),
    ("ml_gate", "QQQ"),
    ("ml_gate", "equal_weight"),
)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for part in iter(lambda: handle.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def lagged_trend(prices):
    """Descriptive prior-session SPY trend; unknown until 200 valid closes."""
    prices = np.asarray(prices, dtype=float)
    out = np.full(len(prices), "unknown", dtype="U7")
    for t in range(200, len(prices)):
        past = prices[t - 200 : t]
        if np.isfinite(past).all() and (past > 0).all():
            out[t] = "up" if past[-1] >= past.mean() else "down"
    return out


def price(report, mask, grid, arm, offset, cost, spans):
    """One funded account through the existing simulator, not a new ledger."""
    options = profit_taking.control_options(report.panel)
    ledger = Ledger()
    ledger.exposure = options.get("event_exposure")
    overlay = so.Overlay(mask, grid) if arm.startswith("ml") else None
    allocator = (
        overlay.allocator
        if overlay
        else point_in_time.equal_weight_allocator(mask)
        if arm == "equal_weight"
        else policy_v4.allocator(mask)
    )
    if arm.endswith("_gate"):
        options["midcycle_target_gate"] = True
    result = simulate.run(
        report,
        since=report.panel.dates[offset].astype(object),
        cost_bps=cost,
        allocator=allocator,
        journal=ledger,
        **options,
    )
    if not np.isfinite(result.returns[1:]).all():
        raise ValueError(f"{arm}: missing evaluated return")
    stats = {w: diagnostics(ledger, start, end) for w, (start, end) in spans.items()}
    dropped = (
        so._held_after_drop(overlay, ledger, report.panel.adj_close) if overlay else {}
    )
    return result.dates, result.returns, stats, dropped


def paired(diff):
    diff = np.asarray(diff, dtype=float)
    if not np.isfinite(diff).all():
        raise ValueError("missing paired outcome")
    return {
        "sessions": len(diff),
        "bp_per_session": float(diff.mean() * 1e4) if len(diff) else None,
        "hac_t": candidate_stats.hac_t(diff, 20) if len(diff) > 2 else None,
    }


def run(  # noqa: C901 - explicit fixed accounts, offsets and reporting windows
    report, mask, forecast, store, *, offsets=20, costs=(10.0, 25.0)
):
    if (
        not 1 <= offsets <= 20
        or not costs
        or any(c < 0 or not np.isfinite(c) for c in costs)
    ):
        raise ValueError("invalid offsets or costs")
    aligned = so.align(forecast, report.panel)
    if aligned.first is None:
        raise ValueError("no forecast on the report calendar")
    first = aligned.first
    spans = {
        "model": (first, date(2024, 1, 1)),
        "recent": (date(2024, 1, 1), None),
        "all": (first, None),
    }
    spans.update(
        {
            str(y): (max(first, date(y, 1, 1)), date(y + 1, 1, 1))
            for y in range(first.year, ASOF.year + 1)
        }
    )
    panel = report.panel
    trend = lagged_trend(panel.adj_close[:, panel.index("SPY")])
    payload = {
        "study": "target-consistency/1",
        "plan": PLAN,
        "asof": str(ASOF),
        "offsets": offsets,
        "costs_bps": list(costs),
        "policy": policy_v4.POLICY_VERSION,
        "selection_model_fits": 0,
        "desk_reconstruction": "unchanged expectations-gap historical fitting",
        "interpretation": "retrospective ablation; previously examined dates",
        "adoption_eligible": False,
        "rows": [],
        "paired": [],
        "regimes": [],
        "daily_at_middle_offset": [],
        "dropped": [],
        "windows": {k: [str(a), str(b) if b else None] for k, (a, b) in spans.items()},
    }
    for cost in costs:
        for offset in range(offsets):
            runs, stats, dates = {}, {}, None
            for arm in ARMS:
                own_dates, daily, diag, dropped = price(
                    report, mask, aligned.grid, arm, offset, cost, spans
                )
                if dates is not None and not np.array_equal(dates, own_dates):
                    raise ValueError("account calendar mismatch")
                dates = own_dates
                runs[arm], stats[arm] = daily, diag
                if offset == offsets // 2 and dropped:
                    values = np.array(list(dropped.values()))
                    payload["dropped"].append(
                        {
                            "arm": arm,
                            "cost_bps": cost,
                            "mean_weight": float(values.mean()),
                            "held_share": float((values > 0).mean()),
                            "sessions": len(values),
                        }
                    )
            for symbol in ("SPY", "QQQ"):
                benchmark = benchmarks.load_benchmark(
                    store, symbol, dates, cost_bps=cost, asof=ASOF
                )
                if not benchmark.available:
                    raise ValueError(benchmark.reason)
                runs[symbol] = benchmark.daily
            # All accounts have the same single initial mark, not an earned return.
            for arm, daily in runs.items():
                if not np.isfinite(daily[1:]).all() or (daily[1:] <= -1).any():
                    raise ValueError(f"invalid account outcomes: {arm}")
            for window, (start, end) in spans.items():
                keep = point_in_time.window(dates, start, end)
                keep[0] = False
                for arm, daily in runs.items():
                    row = {
                        "arm": arm,
                        "cost_bps": cost,
                        "offset": offset,
                        "window": window,
                        **window_stats(daily[keep]),
                        "growth_factor": float(np.prod(1 + daily[keep])),
                    }
                    for key in (
                        "cash_share",
                        "midcycle_turnover",
                        "rebalance_turnover",
                    ):
                        row[key] = stats.get(arm, {}).get(window, {}).get(key)
                    payload["rows"].append(row)
                # Preserve every offset's paired effect, not just the best one.
                for left, right in PAIRS:
                    payload["paired"].append(
                        {
                            "left": left,
                            "right": right,
                            "cost_bps": cost,
                            "offset": offset,
                            "window": window,
                            **paired((runs[left] - runs[right])[keep]),
                        }
                    )
                interaction = (runs["ml_gate"] - runs["base_gate"]) - (
                    runs["ml"] - runs["base"]
                )
                payload["paired"].append(
                    {
                        "left": "interaction",
                        "right": "zero",
                        "cost_bps": cost,
                        "offset": offset,
                        "window": window,
                        **paired(interaction[keep]),
                    }
                )
            if offset == offsets // 2:
                payload["daily_at_middle_offset"].append(
                    {
                        "cost_bps": cost,
                        "offset": offset,
                        "dates": dates.astype(str).tolist(),
                        "returns": {k: v.tolist() for k, v in runs.items()},
                    }
                )
                regimes = trend[np.searchsorted(panel.dates, dates)]
                for label in ("up", "down", "unknown"):
                    keep = (regimes == label) & (dates >= np.datetime64(first))
                    keep[0] = False
                    for arm, daily in runs.items():
                        payload["regimes"].append(
                            {
                                "regime": label,
                                "arm": arm,
                                "cost_bps": cost,
                                "sessions": int(keep.sum()),
                                "mean_daily_bp": float(daily[keep].mean() * 1e4)
                                if keep.any()
                                else None,
                            }
                        )
            print(
                f"finished cost={cost:g} offset={offset}: five accounts + SPY/QQQ",
                flush=True,
            )
    payload["economic_check"] = economic_check(payload)
    return payload


def economic_check(payload):
    """Existing floor; even a pass is not permission to adopt a post-hoc idea."""
    middle = payload["offsets"] // 2
    pairs = payload["paired"]
    primary = [p for p in pairs if p["left"] == "ml_gate" and p["right"] == "base_gate"]
    floors = [p for p in primary if p["offset"] == middle and p["window"] == "model"]
    passes = bool(floors) and all(
        p["bp_per_session"] is not None
        and p["bp_per_session"] >= 2
        and p["hac_t"] is not None
        and p["hac_t"] >= 2
        for p in floors
    )
    high = max(payload["costs_bps"])
    # Offset wins are based on compounded wealth, not arithmetic mean return.
    rows = [
        r for r in payload["rows"] if r["window"] == "model" and r["cost_bps"] == high
    ]
    by = {(r["arm"], r["offset"]): r for r in rows}
    wins = sum(
        by["ml_gate", k]["growth_factor"] > by["base_gate", k]["growth_factor"]
        for k in range(payload["offsets"])
    )
    dd = {
        arm: float(
            np.median([by[arm, k]["drawdown"] for k in range(payload["offsets"])])
        )
        for arm in ("ml_gate", "base_gate")
    }
    recent = [
        p
        for p in primary
        if p["offset"] == middle and p["window"] == "recent" and p["cost_bps"] == high
    ]
    complete = payload["offsets"] == 20 and set(payload["costs_bps"]) == {10.0, 25.0}
    passed = (
        complete
        and passes
        and wins >= 15
        and dd["ml_gate"] - dd["base_gate"] >= -0.03
        and len(recent) == 1
        and recent[0]["bp_per_session"] is not None
        and recent[0]["bp_per_session"] >= 0
    )
    return {
        "status": "FURTHER_EVALUATION_ONLY" if passed else "DO_NOT_PROMOTE",
        "complete_registered_geometry": complete,
        "floors": floors,
        "offsets_above_control": wins,
        "drawdown_gap_points": 100 * (dd["ml_gate"] - dd["base_gate"]),
        "recent": recent,
        "adoption_eligible": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    forecast = stage3_io.load_forecast(args.forecast)
    if forecast.kind != "s1" or forecast.family != "seq":
        raise ValueError("this ablation requires the existing S1 sequence ensemble")
    print("building the 2026-09-28 desk report from stored inputs", flush=True)
    store = MarketStore(args.root)
    report = desk.run(store, ASOF, inputs=(desk.EXPECTATIONS_GAP,))
    if desk.EXPECTATIONS_GAP not in report.inputs:
        raise ValueError(
            "expected desk inputs unavailable; refusing plain-rule fallback"
        )
    restricted, mask = point_in_time.point_in_time(report)
    payload = run(restricted, mask, forecast, store)
    payload["identity"] = {
        "code": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "forecast_sha256": sha256(args.forecast),
        "plan_sha256": sha256(PLAN),
        "membership_sha256": sha256(universe.MEMBERSHIP_HISTORY_PATH),
        "report_arrays": {
            k: hashlib.sha256(np.asarray(v).tobytes()).hexdigest()
            for k, v in {
                "dates": report.panel.dates,
                "open": report.panel.open,
                "close": report.panel.adj_close,
                "grades": report.graded.grades,
                "membership": mask,
            }.items()
        },
        "tickers": list(report.panel.tickers),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump(json_ready(payload), handle, indent=2, allow_nan=False)
    print(json.dumps(json_ready(payload["economic_check"]), indent=2), flush=True)
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
