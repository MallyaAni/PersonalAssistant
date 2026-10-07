"""One post-result first-available ablation on the original funded execution book."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from backend.cli import market_sequential_execution as primary_cli
from backend.cli.market_learned_entry import sha256, write_json
from backend.market import learned_entry_models as original
from backend.market.learned_execution_timing import replay_account

PRIMARY_SHA256 = "2a8276f0c5e677292a600c260e87016d39029ee33359cdfae9c228c70fe22f11"
POLICY = "first-available-completed-quote/1"
PROTOCOL_NAME = "docs/research/sequential-first-available-plan-2026-10-03.md"
PROTOCOL_PATH = Path(__file__).resolve().parents[2] / PROTOCOL_NAME
CLI_NAME = "backend/cli/market_sequential_first_available.py"
REPORT_NAME = "first-available-evaluation"


# Act at the first observed valid quote, locking execution before outcome inspection.
def account(
    panel, grades, eligible, dataset, first, cost_bps, offset, *, supported_days=None
):
    if supported_days is None:
        supported_days = primary_cli.execution_support(panel, first)

    # Select solely from pending intents and presently observed positive quote validity.
    def choose(
        day, clock, delta, known, pending, observed, nav, budget, cost, final, counts
    ):
        notional = np.maximum(delta, 0) * np.where(pending & known, observed, 0)
        if float(notional.sum()) * (1 + cost / 1e4) > budget:
            counts["cash_limited_decisions"] += int(
                (pending & known & (delta > 0)).sum()
            )
        return pending & known

    # Read the honest subsequent open only after the shared ledger locks the attempt.
    def prices(day, clock, final):
        return dataset["next_open"][day, clock]

    result = replay_account(
        panel,
        grades,
        eligible,
        dataset,
        first,
        cost_bps,
        offset,
        choose,
        prices,
        24,
        supported_days=supported_days,
        record_intents=True,
        decision_counts={"cash_limited_decisions": 0, "unsupported_plan_sessions": 0},
    )
    result["policy"] = POLICY
    return result


# Pin unchanged source plus this separately registered interpretability control.
def source_identity():
    pinned = primary_cli.source_identity()
    pinned["files"].update(
        {CLI_NAME: sha256(Path(__file__)), PROTOCOL_NAME: sha256(PROTOCOL_PATH)}
    )
    return pinned


# Recover original funded curves and traces without invoking an account or model replay.
def _saved_account(saved, dates):
    account = {
        key: np.asarray(saved["curves"][key], dtype=np.float64)
        for key in primary_cli.CURVES
    }
    if any(
        value.shape != dates.shape or not np.isfinite(value).all()
        for value in account.values()
    ):
        raise ValueError("Primary saved curve dimensions or finite values changed")
    if (
        account["nav"][0] != 1
        or (account["nav"] <= 0).any()
        or (account["cash"] < -1e-8).any()
        or (account["cash"] > account["nav"] + 1e-8).any()
    ):
        raise ValueError("Primary curve NAV1 or funded cash invariant changed")
    if (account["fees"] < 0).any() or (account["turnover"] < 0).any():
        raise ValueError("Primary cost curve sign changed")
    account.update(
        dates=dates,
        counts=saved["counts"],
        stocks=saved["stocks"],
        intent_trace=saved["intent_trace"],
    )
    if len(account["intent_trace"]) != account["counts"]["intents"]:
        raise ValueError("Primary intent denominator changed")
    gain = sum(
        stock["net_gain_initial_nav_units"] for stock in account["stocks"].values()
    )
    if not np.isclose(gain, account["nav"][-1] - 1, atol=1e-8, rtol=0):
        raise ValueError("Primary stock wealth does not reconcile")
    return account


# Authenticate the primary evidence, unchanged inputs and all26 original source hashes.
def load_primary(panel, dataset, primary, primary_proof):
    if sha256(primary) != PRIMARY_SHA256:
        raise ValueError("Original primary report SHA required")
    report = json.loads(Path(primary).read_text())
    proof = json.loads(Path(primary_proof).read_text())
    if (
        proof["report_sha256"] != PRIMARY_SHA256
        or proof["identity"] != report["identity"]
    ):
        raise ValueError("Primary proof does not authenticate original report")
    first = primary_cli.comparison_first(panel)
    dates = panel.dates[first - 1 :].copy()
    source = primary_cli.source_identity()
    if report["identity"]["source"]["files"] != source["files"]:
        raise ValueError("Original source files changed; no matched ablation")
    if (
        report["identity"]["data"] != dataset["provenance"]
        or report["dates"] != dates.astype(str).tolist()
    ):
        raise ValueError("Primary input provenance or calendar changed")
    if report["identity"]["baseline_sha256"] != primary_cli.BASELINE_SHA256:
        raise ValueError("Primary ETF reference provenance changed")
    expected = [(cost, phase) for cost in primary_cli.COSTS for phase in range(20)]
    if (
        report["status"] != "complete_reused_conditional_research"
        or report["adoption_eligible"] is not False
        or [(row["cost_bps"], row["phase"]) for row in report["phases"]] != expected
    ):
        raise ValueError("Complete original60 phase pairs required")
    etfs = {
        cost: {
            name: primary_cli._reference(
                panel,
                first,
                report["benchmarks"][str(cost)][name]["curves"],
                name,
                cost,
            )
            for name in ("SPY", "QQQ")
        }
        for cost in primary_cli.COSTS
    }
    comparisons = {
        (row["cost_bps"], row["phase"]): {
            "candidate": _saved_account(row["candidate"], dates),
            "control": _saved_account(row["control"], dates),
            **etfs[row["cost_bps"]],
        }
        for row in report["phases"]
    }
    return report, comparisons


# Publish a complete private evidence payload and its authenticated identity receipt.
def _save_report(output, name, report):
    path = output / f"{name}.json"
    write_json(path, report)
    write_json(
        output / f"{name}-proof.json",
        {"report_sha256": sha256(path), "identity": report["identity"]},
    )


# Authenticate ordered completed phases before resuming or returning existing evidence.
def _read_report(output, name, identity, *, complete=False):
    path = output / f"{name}.json"
    if not path.exists():
        return None
    proof = json.loads((output / f"{name}-proof.json").read_text())
    report = json.loads(path.read_text())
    expected = [(cost, phase) for cost in primary_cli.COSTS for phase in range(20)]
    actual = [(row["cost_bps"], row["phase"]) for row in report["phases"]]
    if (
        sha256(path) != proof["report_sha256"]
        or proof["identity"] != identity
        or report["identity"] != identity
        or actual != expected[: len(actual)]
    ):
        raise ValueError("Saved ablation evidence or source identity changed")
    if complete and (
        actual != expected
        or report["status"] != "complete_post_result_interpretability"
        or report["adoption_eligible"] is not False
    ):
        raise ValueError("Incomplete ablation report cannot suppress evaluation")
    return report


# Summarize all phases against both original books without selecting winners.
def _summary(rows):
    result = []
    for cost in primary_cli.COSTS:
        phases = [row for row in rows if row["cost_bps"] == cost]
        if len(phases) != 20:
            raise ValueError("All20 phases required")
        comparisons = {}
        for name in ("candidate", "control"):
            gains = np.array(
                [row["paired_gain_initial_nav_units"][name] for row in phases]
            )
            comparisons[name] = {
                "positive_phases": int((gains > 0).sum()),
                "median": float(np.median(gains)),
                "minimum": float(gains.min()),
                "maximum": float(gains.max()),
            }
        result.append(
            {
                "cost_bps": cost,
                "phases": 20,
                "paired_gain_initial_nav_units": comparisons,
            }
        )
    return result


# Evaluate only the sixty new first-available books against authenticated saved curves.
def evaluate(panel, grades, eligible, cubes, dataset, output, primary, primary_proof):
    primary_report, comparisons = load_primary(panel, dataset, primary, primary_proof)
    first = primary_cli.comparison_first(panel)
    supported = primary_cli.execution_support(panel, first)
    if (
        original._array_hash(supported)
        != primary_report["identity"]["supported_sessions_sha256"]
        or original._array_hash(primary_cli.session_opens(panel, cubes))
        != primary_report["identity"]["session_open_sha256"]
    ):
        raise ValueError("Primary cube units or supported-session identity changed")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    identity = {
        "source": source_identity(),
        "primary_report_sha256": sha256(primary),
        "primary_proof_sha256": sha256(primary_proof),
        "primary_identity": primary_report["identity"],
        "data": dataset["provenance"],
        "cost_bps": list(primary_cli.COSTS),
        "phases": list(range(20)),
        "common_start": str(primary_cli.START),
        "common_end": str(primary_cli.END),
    }
    existing = _read_report(output, REPORT_NAME, identity, complete=True)
    if existing is not None:
        return existing
    report = _read_report(output, REPORT_NAME + "-progress", identity) or {
        "identity": identity,
        "phases": [],
        "policy": POLICY,
        "adoption_eligible": False,
        "status": "post_result_interpretability",
        "runtime": primary_cli.runtime_identity(),
        "dates": panel.dates[first - 1 :].astype(str).tolist(),
        "limitations": [
            "Post-result exploratory ablation; not preregistered primary evidence.",
            "Original grades, allocation, supported sessions and funding unchanged.",
            "Only first-available books replayed; original curves reused.",
            "FractionalNAV1 next-open proxies; broker/midpoint fills are unproven.",
            "All reset phases overlap; they are not independent samples.",
            "No live adoption from this reused diagnostic.",
        ],
    }
    completed = len(report["phases"])
    spy = panel.adj_close[:, panel.tickers.index("SPY")]
    for index, (cost, phase) in enumerate(
        (c, p) for c in primary_cli.COSTS for p in range(20)
    ):
        if index < completed:
            continue
        result = account(
            panel,
            grades,
            eligible,
            dataset,
            first,
            cost,
            phase,
            supported_days=supported,
        )
        refs = comparisons[(cost, phase)]
        row = {
            "cost_bps": cost,
            "phase": phase,
            "first_available": primary_cli.account_evidence(result, refs, spy),
            "paired_gain_initial_nav_units": {
                name: float(result["nav"][-1] - refs[name]["nav"][-1])
                for name in ("candidate", "control")
            },
        }
        report["phases"].append(row)
        if source_identity() != identity["source"]:
            raise ValueError("Ablation source changed during evaluation")
        _save_report(output, REPORT_NAME + "-progress", report)
        print(
            json.dumps(
                {
                    "status": "first_available_phase",
                    "cost_bps": cost,
                    "phase": phase,
                    "paired_gain_initial_nav_units": row[
                        "paired_gain_initial_nav_units"
                    ],
                }
            ),
            flush=True,
        )
    report.update(
        status="complete_post_result_interpretability",
        phase_summary=_summary(report["phases"]),
    )
    _save_report(output, REPORT_NAME, report)
    return report


# Require original private inputs and primary proof for this single no-fit ablation.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "snapshot",
        "provenance",
        "cubes",
        "prepared",
        "output",
        "primary",
        "primary-proof",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    panel, grades, eligible, cubes, dataset = primary_cli.load_inputs(args)
    evaluate(
        panel,
        grades,
        eligible,
        cubes,
        dataset,
        args.output,
        args.primary,
        args.primary_proof,
    )


if __name__ == "__main__":
    main()
