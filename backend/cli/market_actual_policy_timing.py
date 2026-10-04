"""Run the frozen real-policy timing study without fitting or promoting a model.

All300 declared accounts are new:180 policy books and120 matched whole-share
ETF controls. Earlier studies supply authenticated input receipts only.
"""

import argparse
import gzip
import json
from datetime import date, datetime
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import intraday_orders
from backend.cli import market_probabilistic_execution as forecasts
from backend.cli import market_probabilistic_funded_timing as saved
from backend.cli.market_learned_entry import sha256, write_json
from backend.cli.market_sequential_execution import runtime_identity
from backend.market import calendar
from backend.market.allocation_evaluation import metrics
from backend.market.learned_entry_evaluation import read_cubes
from backend.market.live_execution_inputs import prepare, review_action_export
from backend.market.live_policy_features import FeatureCache
from backend.market.live_policy_replay import plain, run_account, run_benchmark
from backend.market.live_probability_timing import build_reader
from backend.market.panel import Panel
from backend.market.retention_study import authenticate_source

POLICY = "actual-policy-timing/1-research"
PROTOCOL = "docs/research/actual-policy-timing-plan-2026-10-04.md"
PROTOCOL_SHA = "8bb0b528f56dd4f43e72823e4efa8eee71631e90b6d84831c881247a70cbabcc"
SNAPSHOT_SHA = "8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58"
PROVENANCE_SHA = "529f59d10ca0b612b050a0eddd21b2fd7eee316346004130d035cdac4dbd9844"
ACTIONS_SHA = "0e05a397f3719c61688e2eb79355eb5111961c05f31916db8a16ab6ff01dbcca"
# This exact export misclassifies the Sandisk distribution as a WDC share split.
REJECTED_ACTIONS_SHA = (
    "0e05a397f3719c61688e2eb79355eb5111961c05f31916db8a16ab6ff01dbcca"
)
INPUT_RECEIPT_SHA = "9a367843ab2f529ba5123997967e435ae41481be5692314501e71f3aaad7be29"
ARMS = ("rule", "boosting", "ridge")
BENCHMARKS = ("SPY", "QQQ")
COSTS = (0, 10, 25)
WINDOWS = (
    ("full", "2018-02-01", "2026-10-01"),
    ("2018-20", "2018-02-01", "2021-01-01"),
    ("2021-26", "2021-01-01", "2026-10-01"),
    ("reused_recent", "2026-08-17", "2026-10-01"),
)


# Refuse a changed source contract rather than choose another usable study window.
def require(condition, message):
    if not condition:
        raise ValueError(message)


# Enumerate every predeclared start, cost and method without outcome-dependent choices.
def account_grid(dates):
    dates = np.asarray(dates)
    require(
        dates.dtype == np.dtype("datetime64[D]")
        and len(dates) > 21
        and not np.isnat(dates).any()
        and np.all(dates[1:] > dates[:-1]),
        "Ordered original daily sessions required",
    )
    first = np.flatnonzero(dates == np.datetime64("2018-02-01"))
    final = np.flatnonzero(dates == np.datetime64("2026-09-30"))
    require(len(first) == len(final) == 1 and first[0] > 0, "Fixed endpoints required")
    require(first[0] + 19 < final[0], "Twenty complete starts required")
    rows = []
    for cost in COSTS:
        for start in range(20):
            for arm in (*ARMS, *BENCHMARKS):
                index = int(first[0]) + start
                rows.append(
                    {
                        "arm": arm,
                        "cost_bps": cost,
                        "start": start,
                        "first": index,
                        "last": int(final[0]),
                        "first_session": str(dates[index]),
                        "id": f"{arm}-{cost}-{start}",
                    }
                )
    return rows


# Authenticate the complete mounted tree and the frozen comparison specification.
def source_identity(args):
    root = Path(__file__).resolve().parents[2]
    require(sha256(root / PROTOCOL) == PROTOCOL_SHA, "Frozen protocol differs")
    identity = authenticate_source(args.source_revision, args.source_manifest)
    manifest = json.loads(Path(args.source_manifest).read_text())
    for name in (
        "backend/cli/market_actual_policy_timing.py",
        "backend/cli/market_daily.py",
        "backend/market/live_policy_replay.py",
        "backend/market/live_policy_report.py",
        "backend/market/live_policy_features.py",
        "backend/market/live_probability_timing.py",
        "backend/market/live_execution_inputs.py",
        "backend/market/replay_broker.py",
        PROTOCOL,
    ):
        require(
            manifest["files"].get(name) == sha256(root / name),
            "Actual-policy dependency missing from source identity",
        )
    require(identity["files"] >= 2300, "Whole checkout manifest required")
    return identity


# Refuse known invalid actions before loading original arrays or predictive models.
def load_inputs(args):
    require(
        ACTIONS_SHA != REJECTED_ACTIONS_SHA,
        "Known incorrect stock-distribution export; reviewed replacement required",
    )
    forecasts.evidence(args.snapshot, SNAPSHOT_SHA)
    forecasts.evidence(args.provenance, PROVENANCE_SHA)
    actions = forecasts.evidence(args.actions, ACTIONS_SHA, json_file=True)
    original = forecasts.evidence(args.input_receipt, INPUT_RECEIPT_SHA, json_file=True)
    require(
        original["adoption_eligible"] is False, "Original research receipt required"
    )
    with np.load(args.snapshot, allow_pickle=False) as archive:
        names = tuple(archive["symbols"].tolist())
        dates = archive["dates"].astype("datetime64[D]")
        panel = Panel(
            dates,
            names,
            *(
                archive[field]
                for field in ("open", "high", "low", "close", "adj_close", "volume")
            ),
            {},
            "SPY",
        )
        grades, eligible = archive["grades"], archive["eligible"]
    require(len(names) == 96 and len(dates) == 2953, "Original complete panel required")
    cubes, cube_receipts = read_cubes(args.cubes, names)
    require(
        cube_receipts == original["identity"]["data"]["cubes"],
        "Original raw cube bytes or exclusions differ",
    )
    require(
        actions["snapshot_sha256"] == SNAPSHOT_SHA
        and actions["provenance_sha256"] == PROVENANCE_SHA,
        "Actions belong to another daily archive",
    )
    raw = prepare(
        panel,
        grades,
        eligible,
        cubes,
        actions["actions"],
        basis_as_of=actions["basis_as_of"],
        complete_through=actions["complete_through"],
        dividend_price_basis="split_adjusted_archive_share_dollars",
        provenance={
            "snapshot_sha256": SNAPSHOT_SHA,
            "provenance_sha256": PROVENANCE_SHA,
            "actions_sha256": ACTIONS_SHA,
            "cubes": cube_receipts,
        },
    )
    diagnostic, _ = saved.diagnostic_evidence(args.diagnostic, args.probability_proof)
    loaded = forecasts.load_inputs(args.prepared, args.moments, args.fit_proof)
    require(
        np.array_equal(loaded[0], dates) and loaded[1] == names,
        "Original forecast and actual policy grids differ",
    )
    providers = {
        name: saved.distribution_provider(args.diagnostic, name, diagnostic, loaded)
        for name in saved.METHODS
    }
    paths = [
        args.snapshot,
        args.provenance,
        args.actions,
        args.input_receipt,
        args.prepared,
        args.fit_proof,
        args.probability_proof,
        args.moments / "predictions.npz",
        args.moments / "complete.json",
        args.diagnostic / "report.json",
    ]
    for name in saved.METHODS:
        paths.extend(
            (
                args.diagnostic / f"{name}.npz",
                args.diagnostic / f"{name}-calibration.json",
            )
        )
    source_files = {str(path): sha256(path) for path in paths}
    for name, receipt in cube_receipts.items():
        path = args.cubes / f"{name}.npz"
        if receipt["status"] == "original":
            require(
                path.is_file() and not path.is_symlink(), "Regular raw cube required"
            )
            source_files[str(path)] = receipt["sha256"]
        else:
            require(not path.exists(), "Originally missing cube must remain missing")
            source_files[str(path)] = None
    return panel, raw, cubes, providers, source_files


# Measure one fixed window without removing or filling any missing wealth observation.
def account_score(result, lower, upper):
    rows = result["sessions"]
    positions = [
        i
        for i, row in enumerate(rows)
        if not row["initial"] and lower <= row["session"] < upper
    ]
    if not positions:
        return {"status": "no_sessions", "sessions": 0, "total_gain": None}
    selected = rows[max(0, positions[0] - 1) : positions[-1] + 1]
    values = np.array(
        [np.nan if row["nav"] is None else row["nav"] for row in selected]
    )
    complete = bool(np.isfinite(values).all() and (values > 0).all())
    require(not np.any(values[np.isfinite(values)] < 0), "Negative unlevered wealth")
    endpoints = bool(
        np.isfinite(values[[0, -1]]).all() and values[0] > 0 and values[-1] >= 0
    )
    gain = float(values[-1] / values[0] - 1) if endpoints else None
    price_values = [selected[0]["price_nav"], selected[-1]["price_nav"]]
    price_gain = (
        price_values[-1] / price_values[0] - 1
        if all(value is not None and np.isfinite(value) for value in price_values)
        and price_values[0] > 0
        and price_values[-1] >= 0
        else None
    )
    zero_wealth = bool(np.isfinite(values).all() and np.any(values == 0))
    risk = metrics(values[1:] / values[:-1] - 1) if complete else {}
    if zero_wealth and values[0] > 0:
        risk = {
            "annual": -1.0 if values[-1] == 0 else None,
            "drawdown": float(np.max(1 - values / np.maximum.accumulate(values))),
        }
    fills = [
        row
        for row in result["fills"]
        if lower
        <= datetime.fromisoformat(row["at"])
        .astimezone(calendar.NEW_YORK)
        .date()
        .isoformat()
        < upper
    ]
    refused = [
        row
        for row in result.get("attempts", [])
        if row["accepted"] is False
        and lower
        <= datetime.fromisoformat(row["at"])
        .astimezone(calendar.NEW_YORK)
        .date()
        .isoformat()
        < upper
    ]
    executed = {}
    for row in result["fills"]:
        if (
            datetime.fromisoformat(row["at"])
            .astimezone(calendar.NEW_YORK)
            .date()
            .isoformat()
            >= upper
        ):
            continue
        executed[row["client_order_id"]] = (
            executed.get(row["client_order_id"], 0) + row["filled_qty"]
        )
    remaining_by_symbol = {}
    unexecuted = 0
    for row in result.get("intents", []):
        expected = row.get("execute_on")
        if expected is None:
            following = intraday_orders.next_session(date.fromisoformat(row["session"]))
            expected = following.isoformat() if following is not None else None
        if expected is not None and lower <= expected < upper:
            remaining = max(0, row["qty"] - executed.get(row["client_order_id"], 0))
            unexecuted += remaining > 0
            remaining_by_symbol[row["symbol"]] = (
                remaining_by_symbol.get(row["symbol"], 0) + remaining
            )
    notional = sum(row["filled_qty"] * (row["price"] or 0) for row in fills)
    prior = {
        row["session"]: previous["nav"]
        for previous, row in zip(selected[:-1], selected[1:], strict=True)
    }
    turnover = 0.0
    for row in fills:
        day = (
            datetime.fromisoformat(row["at"])
            .astimezone(calendar.NEW_YORK)
            .date()
            .isoformat()
        )
        denominator = prior.get(day)
        if not denominator or not np.isfinite(denominator) or denominator <= 0:
            turnover = None
            break
        turnover += row["filled_qty"] * (row["price"] or 0) / denominator
    exposure = [
        (row["price_nav"] - row["cash"]) / row["nav"]
        for row in selected[1:]
        if row["nav"] is not None and row["nav"] > 0 and row["price_nav"] is not None
    ]
    return plain(
        {
            "status": (
                "complete"
                if complete
                else "zero_wealth"
                if zero_wealth
                else "missing_wealth_observations"
            ),
            "sessions": len(positions),
            "missing_nav_marks": int((~np.isfinite(values)).sum()),
            "total_gain": gain,
            "price_component_gain": price_gain,
            "ending_dividend_receivable": selected[-1].get("dividend_receivable"),
            "cagr": risk.get("annual"),
            "drawdown_positive_loss": risk.get("drawdown"),
            "sharpe": risk.get("sharpe"),
            "fees": sum(row["fee"] for row in fills),
            "missed_fill_quantity": sum(
                row["requested_qty"] - row["filled_qty"] for row in fills
            ),
            "refused_attempt_quantity": sum(row["qty"] for row in refused),
            "refused_attempts": len(refused),
            "refused_unique_intents": len({row["client_order_id"] for row in refused}),
            "unexecuted_original_intents": unexecuted,
            "remaining_original_qty_by_symbol": remaining_by_symbol,
            "quantity_basis": (
                "order_share_units_not_capital;refusal_retries_counted_as_attempts"
            ),
            "realized_notional": notional,
            "realized_turnover": turnover,
            "mean_end_session_exposure": float(np.mean(exposure)) if complete else None,
            "benchmark_reference_available": result.get("entry", {}).get("status")
            == "filled_opening_proxy"
            if "entry" in result
            else None,
        }
    )


# Write one new immutable compressed account before publishing its hash in progress.
def archive_account(path, result):
    with (
        Path(path).open("xb") as handle,
        gzip.GzipFile(filename="", fileobj=handle, mode="wb", mtime=0) as archive,
    ):
        archive.write(
            json.dumps(
                plain(result), sort_keys=True, allow_nan=False, separators=(",", ":")
            ).encode()
        )
    return sha256(path)


# Retain every start and missing comparison instead of selecting the strongest outcome.
def comparison_summary(rows):
    indexed = {(row["arm"], row["cost_bps"], row["start"]): row for row in rows}
    summary = []
    for method in ARMS[1:]:
        for cost in COSTS:
            for window, _, _ in WINDOWS:
                pairs = []
                for start in range(20):
                    candidate = indexed[(method, cost, start)]["scores"][window]
                    control = indexed[("rule", cost, start)]["scores"][window]
                    pair = {
                        "start": start,
                        "candidate_status": candidate["status"],
                        "rule_status": control["status"],
                        "gain_difference": None,
                        "benchmark_excess": {},
                    }
                    if (
                        candidate["total_gain"] is not None
                        and control["total_gain"] is not None
                    ):
                        pair["gain_difference"] = (
                            candidate["total_gain"] - control["total_gain"]
                        )
                    for benchmark in BENCHMARKS:
                        other = indexed[(benchmark, cost, start)]["scores"][window]
                        pair["benchmark_excess"][benchmark] = (
                            candidate["total_gain"] - other["total_gain"]
                            if candidate["total_gain"] is not None
                            and other["total_gain"] is not None
                            and other.get("benchmark_reference_available") is True
                            else None
                        )
                    pairs.append(pair)
                gains = [
                    row["gain_difference"]
                    for row in pairs
                    if row["gain_difference"] is not None
                ]
                summary.append(
                    {
                        "method": method,
                        "cost_bps": cost,
                        "window": window,
                        "starts": 20,
                        "endpoint_pairs": len(gains),
                        "complete_risk_pairs": sum(
                            row["candidate_status"] == row["rule_status"] == "complete"
                            for row in pairs
                        ),
                        "median_gain_difference": float(np.median(gains))
                        if gains
                        else None,
                        "minimum": min(gains) if gains else None,
                        "maximum": max(gains) if gains else None,
                        "count_better": sum(value > 0 for value in gains),
                        "pairs": pairs,
                    }
                )
    return summary


# Recheck original file bytes after the run without fitting or resimulating anything.
def check_original_files(files):
    for filename, expected in files.items():
        path = Path(filename)
        if expected is None:
            require(
                not path.exists() and not path.is_symlink(),
                "Originally absent input appeared during evaluation",
            )
            continue
        require(
            path.is_file() and not path.is_symlink() and sha256(path) == expected,
            f"Original evidence changed: {path.name}",
        )


# Review source-bound actions without restoring predictors or creating accounts.
def review_inputs(args):
    output = Path(args.output)
    require(not output.exists(), "Fresh output required; never restart or overwrite")
    source = source_identity(args)
    paths = (Path(args.actions), Path(args.action_review))
    require(
        all(path.is_file() and not path.is_symlink() for path in paths),
        "Regular original action and review files required",
    )
    original_bytes, review_bytes = (path.read_bytes() for path in paths)
    require(sha256(paths[0]) == ACTIONS_SHA, "Fixed original action bytes required")
    result = review_action_export(original_bytes, review_bytes)
    require(
        dict(result["scope"])
        == {"first_session": "2018-02-01", "last_session": "2026-09-30"},
        "Fixed study action review scope required",
    )
    files = {
        str(paths[0]): result["original_actions_sha256"],
        str(paths[1]): result["review_sha256"],
    }
    check_original_files(files)
    require(source_identity(args) == source, "Mounted source changed during review")
    output.mkdir(parents=True, exist_ok=False)
    write_json(
        output / "action-review.json",
        plain(
            {
                **result,
                "source": source,
                "original_files": files,
                "accounts_created": 0,
                "models_restored": 0,
                "models_fitted": 0,
                "policy_returns_scored": 0,
            }
        ),
    )


# Run the fixed study or an input-only preflight in a fresh private folder.
def evaluate(args):
    output = Path(args.output)
    require(not output.exists(), "Fresh output required; never restart or overwrite")
    source = source_identity(args)
    panel, raw, cubes, providers, files = load_inputs(args)
    grid = account_grid(panel.dates)
    check_original_files(files)
    output.mkdir(parents=True, exist_ok=False)
    identity = {
        "policy": POLICY,
        "protocol_sha256": PROTOCOL_SHA,
        "source": source,
        "runtime": runtime_identity(),
        "original_files": files,
        "accounts": grid,
        "raw_input_provenance": dict(raw.provenance),
        "restored_models": {
            name: item.verification for name, item in providers.items()
        },
        "availability": (
            "current_vintage_grades_universe_and_history_not_exact_live_reconstruction"
        ),
        "sizing": "unchanged_actual_graded_equal_weight_5",
        "holding_exits": "unchanged_grade_reset_FOMC_paths",
        "dividends": "unspendable_receivables_unknown_payment_dates_no_reinvestment",
        "fills": (
            "conditional_original_raw_SIP_proxy_not_proven_broker_or_midpoint_fills"
        ),
        "models_fitted": 0,
        "adoption_eligible": False,
    }
    write_json(output / "identity.json", plain(identity))
    if args.preflight:
        write_json(
            output / "preflight.json",
            {
                "status": "inputs_verified_not_scored",
                "accounts_created": 0,
                "declared_accounts": len(grid),
            },
        )
        return
    cache = FeatureCache(source["manifest_sha256"])
    accounts = output / "accounts"
    accounts.mkdir()
    rows = []
    for spec in grid:
        root = output / "state" / spec["id"]
        arguments = (panel, raw, root, spec["first"], spec["last"], spec["cost_bps"])
        if spec["arm"] in BENCHMARKS:
            result = run_benchmark(*arguments, spec["arm"])
        else:
            method = spec["arm"]
            completed_sessions = 0

            # Publish progress from completed nights without supplying future labels.
            def publish_session(
                row, account_id=spec["id"], final_date=str(panel.dates[spec["last"]])
            ):
                nonlocal completed_sessions
                completed_sessions += 1
                if (
                    completed_sessions == 1
                    or completed_sessions % 20 == 0
                    or row["session"] == final_date
                ):
                    write_json(
                        output / "active-account.json",
                        {
                            "status": "running",
                            "account": account_id,
                            "completed_accounts": len(rows),
                            "completed_sessions": completed_sessions,
                            "historical_session": row["session"],
                            "written_at": datetime.now(calendar.NEW_YORK).isoformat(),
                        },
                    )

            result = run_account(
                panel,
                raw,
                cubes,
                root,
                spec["first"],
                spec["last"],
                spec["cost_bps"],
                feature_reader=cache,
                reader_builder=build_reader if method != "rule" else None,
                provider=providers[method].provider if method != "rule" else None,
                on_session=publish_session,
            )
        result["comparison_account"] = spec
        path = accounts / (spec["id"] + ".json.gz")
        digest = archive_account(path, result)
        scores = {
            name: account_score(result, lower, upper) for name, lower, upper in WINDOWS
        }
        rows.append(
            {
                **spec,
                "file": str(path.relative_to(output)),
                "sha256": digest,
                "scores": scores,
                "fill_records": len(result["fills"]),
                "intents": len(result.get("intents", [])),
                "forecast_decisions": len(result.get("forecast_decisions", [])),
            }
        )
        write_json(
            output / "progress.json",
            {
                "status": "running",
                "completed": len(rows),
                "declared": len(grid),
                "accounts": rows,
                "cache": cache.receipt(),
            },
        )
        print(
            json.dumps(
                {"completed": len(rows), "account": spec["id"], "sha256": digest}
            ),
            flush=True,
        )
    check_original_files(files)
    require(source_identity(args) == source, "Mounted source changed during evaluation")
    write_json(
        output / "active-account.json",
        {
            "status": "complete_pending_independent_verification",
            "completed_accounts": len(rows),
            "declared_accounts": len(grid),
        },
    )
    write_json(
        output / "progress.json",
        {
            "status": "complete_pending_independent_verification",
            "completed": len(rows),
            "declared": len(grid),
            "accounts": rows,
            "cache": cache.receipt(),
        },
    )
    write_json(
        output / "report.json",
        {
            "status": "complete_pending_independent_verification",
            "policy": POLICY,
            "identity_sha256": sha256(output / "identity.json"),
            "accounts": rows,
            "summary": comparison_summary(rows),
            "cache": cache.receipt(),
            "adoption_eligible": False,
        },
    )


# Accept only explicit immutable research paths and the complete fixed study contract.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = (
        "snapshot",
        "provenance",
        "cubes",
        "actions",
        "input-receipt",
        "prepared",
        "moments",
        "fit-proof",
        "diagnostic",
        "probability-proof",
        "source-manifest",
        "output",
    )
    for name in names:
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--source-revision")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--action-review", type=Path)
    parser.add_argument("--review-actions-only", action="store_true")
    args = parser.parse_args()
    required = (
        ("actions", "action-review", "source-manifest", "output")
        if args.review_actions_only
        else names
    )
    for name in (*required, "source-revision"):
        if getattr(args, name.replace("-", "_")) is None:
            parser.error("--" + name + " is required")
    if args.review_actions_only:
        if args.preflight:
            parser.error("Action review and model preflight are separate modes")
        review_inputs(args)
    else:
        if args.action_review is not None:
            parser.error("Action review is not an executable economic source")
        evaluate(args)


if __name__ == "__main__":
    main()
