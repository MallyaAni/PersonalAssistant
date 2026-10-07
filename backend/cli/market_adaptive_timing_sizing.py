"""Reuse saved forecasts and controls for the fixed adaptive funded sizing study.

This runner fits no return or timing model and recomputes no saved account.
Only growth/gate and growth/adaptive books are new. Original grades, universe,
cash constraints, missing opportunities and all reset phases remain explicit.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from backend.cli import market_normalized_continuation as normalized
from backend.cli import market_sequential_execution as primary
from backend.cli import market_sequential_first_available as saved
from backend.cli.market_learned_entry import sha256, write_json
from backend.market import learned_entry_models as original
from backend.market import sequential_execution_replay as replay

POLICY = "adaptive-timing-sizing/1-research"
NORMALIZED_REPORT_SHA = (
    "f11a413568e7d4f9b78633d842299426681e569c7d482bbcde5f275af5109646"
)
NORMALIZED_MANIFEST_SHA = (
    "c1b6efe83ffa23fd64ffc6af9ae60966d3dbe1c660147910a81e5402f7b77124"
)
NORMALIZED_FORECAST_SHA = (
    "81f88366f28cb29343fd1f85f3e757258abb07c4b934d9e7571884d06fb2e71b"
)
DAILY_FORECAST_SHA = "4de8c9521bb1f7eaf3047c6c45534ef172dbf02b83d087e914cb2d124e8f712d"
DAILY_FIT_SHA = "726c272444e60c748eb2254e5daa33f7a2b6cbc3cc5d694041c8144c515ae42b"
DAILY_INPUT_SHA = "5d556a2fc4d2e4e52121e0039e11f2cfc07eb5d5f53acbb3a6240f5fcf2d171a"
OLD_HOOKS = {
    "backend/market/learned_execution_timing.py": (
        "1795cfa7f1aa4e70f550ddf821e3b46a557f890edab80ef971698281cad43557"
    ),
    "backend/market/sequential_execution_replay.py": (
        "b69cb3310992f33ea7c5404043c2a72ab8f57de51d16197342bc5ce093a2b1d9"
    ),
}
SIMULATOR = "backend/agents/trading/desk/simulate.py"
OLD_SIMULATOR_SHA = "5f96e77c70f26b5fcd2ac1e8241e8ca20c3f3d67fd8acb63748e52f9aa1b5cf6"
BOOK_AST_SHA = "7cc1d211747ddae23f20a97caaf74d9b01dee3098d18f8237ddd9db016637c79"
CALENDAR_FILE = "backend/market/data/nyse_historical_sessions.json"
OLD_CALENDAR_SHA = "8d92cab790021f8fac3211bffa4f928559461515de171b7053578411716f36c9"
EXPANDED_CALENDAR_SHA = (
    "5660668dc3b2f29684694de2dcbd66af2eaa69e83e6dd2d2c1e402cd01b6ffa6"
)
ARMS = ("equal_gate", "equal_adaptive", "growth_gate", "growth_adaptive")
NEW_ARMS = {"growth_gate": "control", "growth_adaptive": "candidate"}
WINDOW_NAMES = {"2016-20": "2018-20", "frozen_holdout": "reused_recent"}


# Refuse a changed evidence boundary rather than silently selecting another source.
def require(condition, reason):
    if not condition:
        raise ValueError(reason)


# Authenticate immutable ordinary JSON before parsing its contents.
def authenticated_json(path, digest):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Regular evidence file required")
    require(sha256(path) == digest, f"Original evidence SHA required: {path.name}")
    return json.loads(path.read_text())


# Pin the actual funded book implementation independently of unused simulator hooks.
def book_ast_hash(path):
    tree = ast.parse(Path(path).read_text())
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "_Book"
    ]
    require(len(classes) == 1, "Exact funded book class required")
    return hashlib.sha256(
        ast.dump(classes[0], include_attributes=False).encode()
    ).hexdigest()


# Accept only declared old hook lineage and the byte-equivalent funded book class.
def historical_source(files, current, root):
    require(
        isinstance(files, dict) and set(files) == set(current),
        "Historical source file set changed",
    )
    for name, digest in files.items():
        if name in OLD_HOOKS:
            require(digest == OLD_HOOKS[name], "Unknown historical target hook")
        elif name == CALENDAR_FILE:
            # Only 2015 was added; evaluated 2018+ support is separately pinned.
            require(
                digest == OLD_CALENDAR_SHA and current[name] == EXPANDED_CALENDAR_SHA,
                "Unreviewed historical calendar transition",
            )
        elif name == SIMULATOR:
            require(
                digest == OLD_SIMULATOR_SHA
                and book_ast_hash(Path(root) / name) == BOOK_AST_SHA,
                "Actual funded book changed from saved control",
            )
        else:
            require(
                digest == current[name], f"Unreviewed historical source change: {name}"
            )


# Authenticate all sixty original gate accounts and the common saved ETF references.
def load_primary(panel, dataset, report_path, proof_path):
    report = authenticated_json(report_path, saved.PRIMARY_SHA256)
    proof = json.loads(Path(proof_path).read_text())
    require(
        proof["report_sha256"] == saved.PRIMARY_SHA256
        and proof["identity"] == report["identity"],
        "Primary proof identity changed",
    )
    first = primary.comparison_first(panel)
    dates = panel.dates[first - 1 :]
    current = primary.source_identity()
    historical_source(
        report["identity"]["source"]["files"],
        current["files"],
        Path(__file__).resolve().parents[2],
    )
    require(
        report["identity"]["data"] == dataset["provenance"]
        and report["dates"] == dates.astype(str).tolist(),
        "Primary original input/calendar changed",
    )
    require(
        report["identity"]["baseline_sha256"] == primary.BASELINE_SHA256,
        "Primary benchmark receipt changed",
    )
    schedule = [(cost, phase) for cost in primary.COSTS for phase in range(20)]
    require(
        report["status"] == "complete_reused_conditional_research"
        and report["adoption_eligible"] is False
        and [(row["cost_bps"], row["phase"]) for row in report["phases"]] == schedule,
        "Complete original sixty phase pairs required",
    )
    references = {
        cost: {
            name: primary._reference(
                panel,
                first,
                report["benchmarks"][str(cost)][name]["curves"],
                name,
                cost,
            )
            for name in ("SPY", "QQQ")
        }
        for cost in primary.COSTS
    }
    controls = {
        (row["cost_bps"], row["phase"]): saved._saved_account(row["control"], dates)
        for row in report["phases"]
    }
    return report, controls, references


# Authenticate saved timing forecasts against their causal preparation and report.
def load_timing(directory, panel, dataset):
    directory = Path(directory)
    report = authenticated_json(
        directory / "normalized-evaluation.json", NORMALIZED_REPORT_SHA
    )
    proof = json.loads((directory / "normalized-evaluation-proof.json").read_text())
    require(
        proof["report_sha256"] == NORMALIZED_REPORT_SHA
        and proof["identity"] == report["identity"],
        "Normalized report proof changed",
    )
    manifest = authenticated_json(
        directory / "models/manifest.json", NORMALIZED_MANIFEST_SHA
    )
    historical_source(
        report["identity"]["source"]["files"],
        normalized.source_identity()["files"],
        Path(__file__).resolve().parents[2],
    )
    require(
        manifest["identity_sha256"] == original._json_hash(manifest["identity"])
        and report["identity"]["model_identity"] == manifest["identity_sha256"],
        "Normalized model identity changed",
    )
    require(
        manifest["identity"]["source_provenance"] == dataset["provenance"],
        "Normalized input provenance changed",
    )
    for key in ("X", "y", "valid", "dates"):
        require(
            manifest["identity"]["arrays"][key] == original._array_hash(dataset[key]),
            f"Normalized prepared array changed: {key}",
        )
    forecast = manifest["forecast"]
    require(
        forecast["file"] == "predictions.npz"
        and forecast["sha256"]
        == NORMALIZED_FORECAST_SHA
        == report["identity"]["forecast_sha256"],
        "Original normalized forecast receipt changed",
    )
    path = directory / "models/predictions.npz"
    require(
        sha256(path) == NORMALIZED_FORECAST_SHA, "Normalized forecast bytes changed"
    )
    with np.load(path, allow_pickle=False) as archive:
        require(
            set(archive.files) == {"dates", "predictions"},
            "Normalized forecast keys changed",
        )
        dates, predictions = archive["dates"], archive["predictions"]
    require(
        dates.dtype == np.dtype("datetime64[D]") and np.array_equal(dates, panel.dates),
        "Normalized forecast calendar changed",
    )
    require(
        predictions.dtype == np.dtype("float32")
        and predictions.shape == (*np.shape(dataset["valid"]), 2)
        and not np.isinf(predictions).any(),
        "Normalized forecast representation changed",
    )
    for key, array in (("dates", dates), ("predictions", predictions)):
        require(
            forecast["arrays"][key] == original._array_hash(array),
            "Normalized forecast array SHA changed",
        )
    first = primary.comparison_first(panel)
    scored = panel.dates[first - 1 :]
    schedule = [(cost, phase) for cost in primary.COSTS for phase in range(20)]
    require(
        report["status"] == "complete_conditional_research"
        and report["adoption_eligible"] is False
        and report["identity"]["primary_sha256"] == saved.PRIMARY_SHA256
        and report["identity"]["dates"] == scored.astype(str).tolist()
        and report["identity"]["data"] == dataset["provenance"]
        and [(row["cost_bps"], row["phase"]) for row in report["phases"]] == schedule,
        "Complete matched normalized accounts required",
    )
    controls = {
        (row["cost_bps"], row["phase"]): saved._saved_account(row["candidate"], scored)
        for row in report["phases"]
    }
    return predictions, manifest, controls


# Authenticate completed-close forecasts without fitting or loading model objects.
def load_daily(directory, panel, dataset):
    directory = Path(directory)
    inputs = authenticated_json(directory / "inputs.json", DAILY_INPUT_SHA)
    fit = authenticated_json(directory / "fit.json", DAILY_FIT_SHA)
    original_inputs = inputs["original_inputs"]
    require(
        original_inputs["snapshot_sha256"] == dataset["provenance"]["snapshot_sha256"]
        and original_inputs["provenance_sha256"]
        == dataset["provenance"]["provenance_sha256"]
        and original_inputs["snapshot_provenance"]
        == dataset["provenance"]["snapshot_contract"],
        "Daily model original input lineage changed",
    )
    require(
        original_inputs["symbols"] == list(panel.tickers)
        and fit["identity"]["symbols"] == list(panel.tickers)
        and fit["identity"]["provenance"] == inputs,
        "Daily model symbol identity changed",
    )
    require(
        fit["identity_sha256"] == original._json_hash(fit["identity"])
        and fit["identity"]["policy"] == "learned-held-b-forecast/1"
        and fit["identity"]["label_end"] == 11
        and fit["identity"]["holdout_end_before"] == "2026-08-17",
        "Daily forecast clock contract changed",
    )
    path = directory / "forecasts.npz"
    require(
        fit["artifact_hashes"]["forecasts.npz"] == DAILY_FORECAST_SHA == sha256(path),
        "Daily forecast bytes changed",
    )
    with np.load(path, allow_pickle=False) as archive:
        require(
            set(archive.files) == {"dates", "relative", "spy"},
            "Daily forecast keys changed",
        )
        dates, relative, spy = archive["dates"], archive["relative"], archive["spy"]
    require(
        dates.dtype == np.dtype("datetime64[D]")
        and np.array_equal(dates, panel.dates)
        and original_inputs["arrays_sha256"]["dates"] == original._array_hash(dates),
        "Daily forecast calendar changed",
    )
    require(
        relative.dtype == np.dtype("float64")
        and relative.shape == panel.adj_close.shape
        and spy.dtype == np.dtype("float64")
        and spy.shape == panel.dates.shape
        and not np.isinf(relative).any()
        and not np.isinf(spy).any(),
        "Daily forecast representation changed",
    )
    require(
        original._array_hash(relative) == fit["relative_forecast_sha256"]
        and original._array_hash(spy) == fit["spy_forecast_sha256"],
        "Daily forecast array SHA changed",
    )
    return (
        relative,
        spy,
        {
            "forecast_sha256": DAILY_FORECAST_SHA,
            "fit_sha256": DAILY_FIT_SHA,
            "inputs_sha256": DAILY_INPUT_SHA,
            "identity_sha256": fit["identity_sha256"],
        },
    )


# Bind each allocation to the exact preceding completed-close forecast row.
def target_provider(panel, relative, market):
    dates = np.asarray(panel.dates)
    positions = {str(value): index for index, value in enumerate(dates)}
    benchmark_indices = tuple(panel.tickers.index(name) for name in ("SPY", "QQQ"))

    # Produce a dated funded plan without exposing any current or future session prices.
    def provide(
        *, history, grades, eligible, current_weights, cash_weight, cost_bps, as_of
    ):
        from backend.market.adaptive_growth_policy import allocate

        day = positions.get(str(as_of))
        require(
            day is not None and str(np.datetime64(as_of, "D")) == str(as_of),
            "Exact completed-close as_of required",
        )
        require(
            np.shape(history) == (day + 1, len(panel.tickers))
            and np.array_equal(
                np.asarray(history), panel.adj_close[: day + 1], equal_nan=True
            ),
            "Allocation requires the exact causal history prefix",
        )
        means = relative[day] + market[day]
        weights, receipt = allocate(
            history,
            grades,
            eligible,
            means,
            current_weights,
            cash_weight,
            cost_bps,
            benchmark_indices,
        )
        receipt = dict(receipt)
        require(
            receipt.get("status") in ("optimized", "unavailable", "protected"),
            "Explicit allocation status required",
        )
        receipt.update(
            as_of=str(dates[day]),
            forecast_as_of=str(dates[day]),
            forecast_row_sha256=original._array_hash(means[None, :]),
            forecast_horizon_sessions=10,
            scheduled_reset_sessions=20,
        )
        return weights, receipt

    return provide


# Pin the new source boundary separately from the authenticated saved control lineage.
def source_identity(args, *, whole_tree=True):
    source = primary.source_identity()
    root = Path(__file__).resolve().parents[2]
    for name in (
        "backend/cli/market_adaptive_timing_sizing.py",
        "backend/market/adaptive_growth_policy.py",
        "docs/research/adaptive-timing-sizing-plan-2026-10-03.md",
    ):
        source["files"][name] = sha256(root / name)
    if args.source_manifest is not None and whole_tree:
        from backend.market.retention_study import authenticate_source

        source["whole_tree"] = authenticate_source(
            args.source_revision, args.source_manifest
        )
    return source


# Label reused windows accurately while preserving the shared score arithmetic.
def named_score(score, account):
    for row in score["windows"]:
        row["window"] = WINDOW_NAMES.get(row["window"], row["window"])
        if row.get("status") == "measured":
            dates = account["dates"][1:]
            mask = (dates >= np.datetime64(row["start"])) & (
                dates <= np.datetime64(row["end"])
            )
            row["gross_traded_weight_per_year"] = float(
                np.sum(account["turnover"][1:][mask]) * 252 / row["sessions"]
            )
    return score


# Persist one full trace once and authenticate it rather than rewriting prior accounts.
def publish_account(output, key, account, references, spy):
    evidence = primary.account_evidence(account, references, spy)
    evidence["score"] = named_score(evidence["score"], account)
    evidence["allocation_trace"] = account.get("allocation_trace", [])
    path = output / f"{key}.json"
    require(not path.exists(), "Completed account cannot be overwritten")
    write_json(path, evidence)
    return {
        "file": path.name,
        "sha256": sha256(path),
        "score": evidence["score"],
        "counts": evidence["counts"],
        "allocation_statuses": dict(
            Counter(row["receipt"]["status"] for row in evidence["allocation_trace"])
        ),
    }


# Summarize every phase/window against all other arms and both funded ETF accounts.
def summarize(rows):
    require(
        [(row["cost_bps"], row["phase"]) for row in rows]
        == [(cost, phase) for cost in primary.COSTS for phase in range(20)],
        "All sixty ordered phase rows required",
    )
    result = []
    keys = (
        "total_net_gain",
        "cagr",
        "max_drawdown_loss",
        "sharpe",
        "gross_traded_weight_per_year",
        "fees_initial_nav_units",
    )
    for cost in primary.COSTS:
        phases = [row for row in rows if row["cost_bps"] == cost]
        windows = []
        for position, window in enumerate(
            ("all", "2018-20", "2021-26", "reused_recent")
        ):
            arms = {}
            for arm in ARMS:
                metrics = [row["scores"][arm]["windows"][position] for row in phases]
                require(
                    all(
                        item["status"] == "measured" and item["window"] == window
                        for item in metrics
                    ),
                    "Unavailable window cannot be dropped from summary",
                )
                comparisons = {}
                for other in (*ARMS, "SPY", "QQQ"):
                    if other == arm:
                        continue
                    differences = np.array(
                        [
                            row["scores"][arm]["windows"][position]["total_net_gain"]
                            - row["scores"][other]["windows"][position][
                                "total_net_gain"
                            ]
                            for row in phases
                        ]
                    )
                    comparisons[other] = {
                        "median_gain_difference": float(np.median(differences)),
                        "positive_phases": int((differences > 0).sum()),
                        "minimum": float(differences.min()),
                        "maximum": float(differences.max()),
                    }
                arms[arm] = {
                    "median_metrics": {
                        key: float(np.median([item[key] for item in metrics]))
                        if all(item[key] is not None for item in metrics)
                        else None
                        for key in keys
                    },
                    "paired_gain": comparisons,
                }
            windows.append({"window": window, "arms": arms})
        result.append({"cost_bps": cost, "phases": 20, "windows": windows})
    return result


# Compute only the two new growth books while reusing every saved control account.
def evaluate(
    args,
    loaded,
    forecasts,
    relative,
    market,
    primary_report,
    equal_gate,
    equal_adaptive,
    etfs,
    daily_receipt,
    timing_manifest,
):
    panel, grades, eligible, cubes, dataset = loaded
    first = primary.comparison_first(panel)
    opens = primary.session_opens(panel, cubes)
    supported = primary.execution_support(panel, first)
    require(
        original._array_hash(opens) == primary_report["identity"]["session_open_sha256"]
        and original._array_hash(supported)
        == primary_report["identity"]["supported_sessions_sha256"],
        "Shared execution opportunities changed",
    )
    identity = {
        "source": source_identity(args),
        "data": dataset["provenance"],
        "primary_sha256": saved.PRIMARY_SHA256,
        "normalized_report_sha256": NORMALIZED_REPORT_SHA,
        "normalized_manifest_sha256": NORMALIZED_MANIFEST_SHA,
        "timing_forecast_sha256": NORMALIZED_FORECAST_SHA,
        "timing_identity": timing_manifest["identity_sha256"],
        "daily_forecasts": daily_receipt,
        "session_open_sha256": original._array_hash(opens),
        "supported_sessions_sha256": original._array_hash(supported),
        "dates": panel.dates[first - 1 :].astype(str).tolist(),
        "cost_bps": list(primary.COSTS),
        "phases": list(range(20)),
        "arms": list(ARMS),
        "new_accounts": 120,
    }
    output = Path(args.output)
    require(
        not output.exists(),
        "Fresh private output directory required; no account restart",
    )
    output.mkdir(parents=True)
    write_json(output / "identity.json", identity)
    provider = target_provider(panel, relative, market)
    spy = panel.adj_close[:, panel.tickers.index("SPY")]
    rows = []
    for cost in primary.COSTS:
        for phase in range(20):
            accounts = {
                "equal_gate": equal_gate[(cost, phase)],
                "equal_adaptive": equal_adaptive[(cost, phase)],
            }
            for arm, method in NEW_ARMS.items():
                accounts[arm] = replay.account(
                    panel,
                    grades,
                    eligible,
                    dataset,
                    forecasts,
                    opens,
                    first,
                    cost,
                    phase,
                    method=method,
                    supported_days=supported,
                    target_provider=provider,
                )
                accounts[arm]["policy"] = f"{POLICY}/{arm}"
            references = {**accounts, **etfs[cost]}
            records = {}
            scores = {}
            for arm, account in references.items():
                others = {
                    name: value for name, value in references.items() if name != arm
                }
                if arm in NEW_ARMS:
                    records[arm] = publish_account(
                        output, f"{arm}-{cost}-{phase}", account, others, spy
                    )
                    scores[arm] = records[arm]["score"]
                else:
                    scores[arm] = named_score(
                        primary.scoring.score(account, others, spy), account
                    )
            row = {
                "cost_bps": cost,
                "phase": phase,
                "accounts": records,
                "scores": scores,
            }
            row_path = output / f"phase-{cost}-{phase}.json"
            write_json(row_path, row)
            rows.append(row)
            require(
                source_identity(args, whole_tree=False)
                == {
                    key: value
                    for key, value in identity["source"].items()
                    if key != "whole_tree"
                },
                "Source changed during new account evaluation",
            )
            write_json(
                output / "progress.json",
                {
                    "identity_sha256": original._json_hash(identity),
                    "phase_rows": len(rows),
                    "new_accounts": len(rows) * 2,
                    "last_phase": row_path.name,
                    "last_phase_sha256": sha256(row_path),
                },
            )
            print(
                json.dumps(
                    {"phase": phase, "cost_bps": cost, "new_accounts": len(rows) * 2}
                ),
                flush=True,
            )
    report = {
        "policy": POLICY,
        "identity": identity,
        "status": "complete_reused_conditional_research",
        "adoption_eligible": False,
        "runtime": primary.runtime_identity(),
        "summary": summarize(rows),
        "phases": [
            {
                "cost_bps": row["cost_bps"],
                "phase": row["phase"],
                "file": f"phase-{row['cost_bps']}-{row['phase']}.json",
                "sha256": sha256(
                    output / f"phase-{row['cost_bps']}-{row['phase']}.json"
                ),
            }
            for row in rows
        ],
        "limitations": [
            "Current-vintage grades/universe; not original historical publications.",
            "Reused data and recent window; no untouched holdout claim.",
            "Ten-session growth approximation versus twenty-session target resets.",
            "Missing/early closes retained; next-open proxies not broker fills.",
            "Overlapping phase accounts are not independent evidence.",
            "No live-policy promotion from these component results.",
        ],
    }
    require(
        source_identity(args) == identity["source"],
        "Source changed before report completion",
    )
    write_json(output / "evaluation.json", report)
    write_json(
        output / "evaluation-proof.json",
        {"report_sha256": sha256(output / "evaluation.json"), "identity": identity},
    )
    return report


# Require explicit read-only evidence paths before creating any new account output.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "snapshot",
        "provenance",
        "cubes",
        "prepared",
        "normalized",
        "daily",
        "primary",
        "primary-proof",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--source-revision")
    args = parser.parse_args()
    require(
        args.source_manifest is None or args.source_revision is not None,
        "Manifest requires an exact source revision",
    )
    loaded = primary.load_inputs(args)
    panel, _, _, _, dataset = loaded
    primary_report, equal_gate, etfs = load_primary(
        panel, dataset, args.primary, args.primary_proof
    )
    predictions, manifest, equal_adaptive = load_timing(args.normalized, panel, dataset)
    relative, market, daily_receipt = load_daily(args.daily, panel, dataset)
    evaluate(
        args,
        loaded,
        predictions,
        relative,
        market,
        primary_report,
        equal_gate,
        equal_adaptive,
        etfs,
        daily_receipt,
        manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
