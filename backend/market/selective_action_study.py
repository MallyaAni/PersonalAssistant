"""Registered selective action-value experiment, entirely outside live trading."""

from __future__ import annotations

import hashlib
import json
import pickle
import time
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import point_in_time, policy_v4, simulate
from backend.cli.market_profit_taking import default_desk
from backend.market import daily_action_model, membership, profit_taking
from backend.market.daily_action_study import (
    COSTS,
    OFFSETS,
    FrozenIndexes,
    account_summary,
    index_account,
    index_prices,
    paired,
    regime_labels,
    save_json,
)
from backend.market.research_journal import ResearchJournal, _new_directory
from backend.market.research_journal_replay import verify_snapshot

PLAN = "docs/research/selective-actions-plan-2026-09-29.md"
HORIZON = 20
ARMS = ("original_v4", "momentum", "mean", "ridge", "tree")


# Hash a local artifact without retaining another large copy of its bytes.
def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# Freeze existing public research inputs once, with no provider or account requests.
def prepare_inputs(store, membership_path, output, *, source_revision):
    output = _new_directory(output)
    report = default_desk(store)
    restricted, mask = point_in_time.point_in_time(report, membership_path)
    indexes = FrozenIndexes(store)
    panel = restricted.panel
    _, spy = index_prices(indexes, "SPY", panel.dates)
    _, qqq = index_prices(indexes, "QQQ", panel.dates)
    np.testing.assert_array_equal(spy, panel.adj_close[:, panel.index(panel.benchmark)])
    missing = sorted(
        {row.ticker for row in membership.load_history(membership_path)}
        - set(panel.tickers)
    )
    bundle = {
        "report": restricted,
        "membership": mask,
        "indexes": indexes,
        "spy": spy,
        "qqq": qqq,
    }
    cache = output / "public-inputs.pickle"
    with cache.open("xb") as stream:
        pickle.dump(bundle, stream, protocol=pickle.HIGHEST_PROTOCOL)
    receipt = {
        "schema": "selective-public-inputs/1",
        "source_revision": source_revision,
        "cache_sha256": file_hash(cache),
        "membership_sha256": file_hash(membership_path),
        "start": str(panel.dates[0]),
        "end": str(panel.dates[-1]),
        "tickers": panel.tickers,
        "missing_historical_members": missing,
        "historical_availability_verified": False,
        "test_status": "reused historical development data, not pristine test",
        "cache_warning": (
            "Trusted local public report only; hash is integrity, not trust."
        ),
    }
    save_json(output / "inputs.json", receipt)
    print(json.dumps(receipt), flush=True)
    return bundle, receipt


# Authenticate explicitly trusted local cache bytes before any pickle deserialization.
def load_inputs(path, expected_sha256):
    path = Path(path)
    raw = path.read_bytes()
    if len(expected_sha256) != 64 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Trusted input cache SHA-256 mismatch")
    bundle = pickle.loads(raw)
    if not isinstance(bundle, dict) or set(bundle) != {
        "report",
        "membership",
        "indexes",
        "spy",
        "qqq",
    }:
        raise ValueError("Invalid selective input cache schema")
    return bundle


# Observe ordinary teacher opportunities without changing its plan or account state.
class TeacherCollector:
    # Retain only the checkpoint needed by the current close and actual opportunities.
    def __init__(self, daily_data):
        self.daily_data = daily_data
        self.latest = None
        self.opportunities = []

    # Receive state before the simulator consumes resets, retries or event transitions.
    def capture(self, checkpoint):
        self.latest = checkpoint

    # Enumerate alternatives using only the current ordinary close and current features.
    def __call__(self, context):
        from backend.market.selective_action_execution import candidates

        if context.t - context.last_rebalance not in (0, 5, 10, 15):
            return None
        choices = candidates(context, self.daily_data.features[context.t])
        if choices:
            if self.latest is None or self.latest.t != context.t:
                raise ValueError("Teacher checkpoint does not precede this decision")
            self.opportunities.append((self.latest, context, choices))
        return None


# Reconcile all teacher marks independently of simulator completion.
def verify_account(result, journal):
    proof = verify_snapshot(journal.snapshot())
    if not proof["ok"]:
        raise ValueError(f"Unreconciled teacher journal: {proof['errors']}")
    np.testing.assert_allclose(
        [row["nav"] for row in proof["marks"]],
        result.equity,
        rtol=1e-10,
        atol=1e-12,
    )
    np.testing.assert_allclose(proof["total_traded"], result.traded, rtol=1e-10)
    return proof


# Price one-action forks with the same stateful planner and retain every present row.
def generate_labels(report, mask, daily_data, output, *, prepared, options):
    from backend.market.selective_action_execution import ForcedAction
    from backend.market.selective_action_model import STATE_FEATURE_NAMES, ActionData

    output = _new_directory(output)
    panel = report.panel
    start = int(np.searchsorted(panel.dates, np.datetime64("2016-01-01")))
    since = panel.dates[start].astype(object)
    allocator = policy_v4.allocator(mask)
    collector = TeacherCollector(daily_data)
    journal = ResearchJournal(
        panel.dates,
        panel.tickers,
        simulate.adjusted_open(panel),
        panel.adj_close,
        run_id="selective-actions/1",
        account_id="teacher-2016",
        policy_id="unchanged-v4",
        cost_bps=25.0,
        provenance={"specification": PLAN, "teacher_only": True},
    )
    teacher = simulate.run(
        report,
        since=since,
        allocator=allocator,
        cost_bps=25.0,
        research_capture=collector.capture,
        research_hook=collector,
        research_prepared=prepared,
        journal=journal,
        **options,
    )
    verify_account(teacher, journal)
    journal.archive(output / "teacher-journal")
    np.savez_compressed(
        output / "teacher-curve.npz", dates=teacher.dates, equity=teacher.equity
    )
    dates, features, labels, endpoints, actions, evidence = [], [], [], [], [], []
    baseline_checks, prefix_checks = [], []
    sampled_years = set()
    began = time.monotonic()
    progress_path = output / "progress.jsonl"
    with progress_path.open("x") as progress:
        for number, (checkpoint, context, choices) in enumerate(
            collector.opportunities
        ):
            t = context.t
            stop = t + HORIZON
            mature = stop < len(panel.dates)
            baseline_nav = None
            if mature:
                base = simulate.run(
                    report,
                    allocator=allocator,
                    cost_bps=25.0,
                    research_resume=checkpoint,
                    research_stop=stop,
                    research_prepared=prepared,
                    **options,
                )
                np.testing.assert_array_equal(base.dates, panel.dates[t : stop + 1])
                np.testing.assert_allclose(
                    base.equity,
                    teacher.equity[t - start : stop - start + 1],
                    rtol=1e-12,
                    atol=1e-12,
                )
                baseline_nav = float(base.equity[-1])
                baseline_checks.append({"t": t, "stop": stop, "nav": baseline_nav})
            for candidate in choices:
                action_nav = None
                if mature:
                    fork = simulate.run(
                        report,
                        allocator=allocator,
                        cost_bps=25.0,
                        research_resume=checkpoint,
                        research_stop=stop,
                        research_prepared=prepared,
                        research_hook=ForcedAction(t, candidate),
                        **options,
                    )
                    np.testing.assert_array_equal(fork.dates, panel.dates[t : stop + 1])
                    action_nav = float(fork.equity[-1])
                    label = (action_nav - baseline_nav) / context.nav
                    if not np.isfinite(label):
                        raise ValueError(
                            "A completed counterfactual label is nonfinite"
                        )
                    year = str(panel.dates[t].astype("datetime64[Y]"))
                    if year not in sampled_years:
                        full = simulate.run(
                            report,
                            since=since,
                            allocator=allocator,
                            cost_bps=25.0,
                            research_stop=stop,
                            research_prepared=prepared,
                            research_hook=ForcedAction(t, candidate),
                            **options,
                        )
                        np.testing.assert_allclose(
                            full.equity[t - start :],
                            fork.equity,
                            rtol=1e-12,
                            atol=1e-12,
                        )
                        prefix_checks.append(
                            {
                                "t": t,
                                "symbol": candidate.symbol,
                                "action": candidate.action,
                            }
                        )
                        sampled_years.add(year)
                else:
                    label = np.nan
                dates.append(panel.dates[t])
                features.append(candidate.features)
                labels.append(label)
                endpoints.append(
                    panel.dates[stop] if mature else np.datetime64("NaT", "D")
                )
                actions.append(candidate.action)
                evidence.append(
                    {
                        "row": len(labels) - 1,
                        "t": t,
                        "symbol": candidate.symbol,
                        "action": candidate.action,
                        "units": float(candidate.units),
                        "incumbent_units": float(
                            context.incumbent_units[candidate.index]
                        ),
                        "held_units": float(context.held_units[candidate.index]),
                        "nav": float(context.nav),
                        "cash": float(context.cash),
                        "last_rebalance": int(context.last_rebalance),
                        "next_rebalance": int(context.next_rebalance),
                        "baseline_endpoint_nav": baseline_nav,
                        "action_endpoint_nav": action_nav,
                        "label": float(label) if mature else None,
                    }
                )
            progress.write(
                json.dumps(
                    {
                        "opportunity": number,
                        "session": str(panel.dates[t]),
                        "rows": len(labels),
                    }
                )
                + "\n"
            )
            progress.flush()
            if number % 25 == 0 or number + 1 == len(collector.opportunities):
                print(
                    f"Selective labels {number + 1}/{len(collector.opportunities)}: "
                    f"{len(labels)} rows, {time.monotonic() - began:.1f}s",
                    flush=True,
                )
    if not labels:
        raise ValueError("No selective action opportunities in the teacher account")
    data = ActionData(
        dates=np.asarray(dates, dtype="datetime64[D]"),
        features=np.asarray(features, dtype=float),
        labels=np.asarray(labels, dtype=float),
        label_end=np.asarray(endpoints, dtype="datetime64[D]"),
        actions=np.asarray(actions),
        feature_names=daily_data.feature_names + STATE_FEATURE_NAMES,
    )
    np.savez_compressed(
        output / "action-data.npz",
        dates=data.dates,
        features=data.features,
        labels=data.labels,
        label_end=data.label_end,
        actions=data.actions,
        feature_names=np.asarray(data.feature_names),
    )
    save_json(output / "label-evidence.json", evidence)
    save_json(
        output / "fork-checks.json",
        {"baseline": baseline_checks, "full_prefix": prefix_checks},
    )
    return data


# Apply the preregistered paired screens without treating a research pass as deployment.
def verdict(runs):
    result = {}
    selected = [row for row in runs if row["cost_bps"] == 25]
    if sorted(row["offset"] for row in selected) != list(OFFSETS):
        raise ValueError("Verdict requires exactly four registered 25 bp offsets")
    for name in ("ridge", "tree"):
        checks = {}
        for control in ("original_v4", "momentum"):
            gains = [
                r["accounts"][name]["all"]["cagr"]
                - r["accounts"][control]["all"]["cagr"]
                for r in selected
            ]
            drawdowns = [
                r["accounts"][name]["all"]["drawdown"]
                - r["accounts"][control]["all"]["drawdown"]
                for r in selected
            ]
            zero = next(row for row in selected if row["offset"] == 0)
            pair = zero["paired"][name][control]
            median_gain = float(
                np.median([r["accounts"][name]["all"]["cagr"] for r in selected])
                - np.median([r["accounts"][control]["all"]["cagr"] for r in selected])
            )
            checks[control] = {
                "median_cagr_gain": median_gain,
                "offsets_above": sum(g > 0 for g in gains),
                "worst_drawdown_gap": min(drawdowns),
                **pair,
                "passes": bool(
                    median_gain >= 0.01
                    and pair["hac_t"] >= 2
                    and min(drawdowns) >= -0.03
                    and pair["recent_mean_daily_bp"] is not None
                    and pair["recent_mean_daily_bp"] >= 0
                    and sum(g > 0 for g in gains) >= 3
                ),
            }
        result[name] = {
            "status": "RESEARCH_PASS_ONLY"
            if all(row["passes"] for row in checks.values())
            else "DO_NOT_PROMOTE",
            "checks": checks,
        }
    return result


# Describe selected-state extrapolation without changing the frozen action policy.
def selected_state_shift(data, selections):
    windows = {}
    outside, outside_state, unseen_actions = 0, 0, 0
    for selection in selections:
        day = np.datetime64(selection["session"], "D")
        year = str(day.astype("datetime64[Y]"))
        if year not in windows:
            boundary = np.datetime64(f"{year}-01-01")
            rows = (
                (data.dates >= np.datetime64("2016-01-01"))
                & (data.dates < boundary)
                & np.isfinite(data.labels)
                & ~np.isnat(data.label_end)
                & (data.label_end < boundary)
            )
            if not rows.any():
                raise ValueError("No teacher training support for a selected action")
            windows[year] = (
                data.features[rows].min(axis=0),
                data.features[rows].max(axis=0),
                set(data.actions[rows]),
            )
        low, high, actions = windows[year]
        features = np.asarray(selection["features"], dtype=float)
        if features.shape != low.shape or not np.isfinite(features).all():
            raise ValueError("Selected action features cannot be audited")
        shifted = (features < low - 1e-12) | (features > high + 1e-12)
        outside += int(shifted.any())
        outside_state += int(shifted[22:].any())
        unseen_actions += int(selection["action"] not in actions)
    return {
        "selected_actions": len(selections),
        "outside_any_training_feature_range": outside,
        "outside_account_action_feature_range": outside_state,
        "action_absent_from_training": unseen_actions,
        "scope": (
            "Selected actions only, compared with that year's matured teacher refit "
            "rows. Inside marginal ranges does not prove joint-state or policy support."
        ),
    }


# Train on exact teacher counterfactuals and evaluate seven continuous funded accounts.
def run(bundle, output, *, source_revision, input_receipt):
    from backend.market import selective_action_execution as execution
    from backend.market import selective_action_model as model

    output = _new_directory(output)
    report, mask, indexes = bundle["report"], bundle["membership"], bundle["indexes"]
    save_json(
        output / "protocol.json",
        {
            "source_revision": source_revision,
            "plan": PLAN,
            "plan_sha256": file_hash(PLAN),
            "plan_text": Path(PLAN).read_text(),
        },
    )
    panel = report.panel
    options = profit_taking.control_options(panel)
    prepared = simulate.prepare_research(report, **options)
    daily_data = daily_action_model.build_dataset(
        panel, mask, report.graded.grades, bundle["qqq"]
    )
    save_json(
        output / "inputs.json",
        {
            **input_receipt,
            "execution_source_revision": source_revision,
            "specification": PLAN,
            "feature_names": daily_data.feature_names,
        },
    )
    np.savez_compressed(
        output / "inputs.npz",
        dates=panel.dates,
        tickers=panel.tickers,
        features=daily_data.features,
        membership=mask,
        grades=report.graded.grades,
        open=panel.open,
        high=panel.high,
        low=panel.low,
        close=panel.close,
        adj_close=panel.adj_close,
        volume=panel.volume,
        qqq=bundle["qqq"],
        spy=bundle["spy"],
    )
    data = generate_labels(
        report, mask, daily_data, output / "labels", prepared=prepared, options=options
    )
    trained = model.train(data, output / "training")
    first = int(np.searchsorted(panel.dates, np.datetime64("2019-01-01")))
    if first + max(OFFSETS) >= len(panel.dates) - 1:
        raise ValueError("Insufficient registered outer history")
    regimes = regime_labels(bundle["spy"])
    runs = []
    for cost in COSTS:
        for offset in OFFSETS:
            start = first + offset
            dates = panel.dates[start:]
            curves, accounts = {}, {}
            for name in ARMS:
                priced = execution.price(
                    report,
                    mask,
                    daily_data,
                    trained,
                    panel.dates[start].astype(object),
                    cost,
                    family=name,
                    research_prepared=prepared,
                )
                np.testing.assert_array_equal(priced.result.dates, dates)
                daily = np.asarray(priced.result.returns, dtype=float)
                accounts[name] = account_summary(dates, daily, regimes[start:])
                # Keep detailed daily evidence outside the bounded result summary.
                save_json(
                    output / f"execution-{cost:g}-{offset}-{name}.json",
                    priced.diagnostics,
                )
                accounts[name]["execution"] = {
                    key: value
                    for key, value in priced.diagnostics.items()
                    if key not in ("daily", "decisions", "predictions")
                }
                accounts[name]["teacher_state_support"] = selected_state_shift(
                    data, priced.diagnostics.get("selected_interventions", [])
                )
                curves[name] = daily
                priced.journal.archive(output / f"journal-{cost:g}-{offset}-{name}")
                print(
                    f"Selective account {cost:g}bp offset {offset} {name}: "
                    f"CAGR {accounts[name]['all']['cagr']:.3%}",
                    flush=True,
                )
            for symbol in ("SPY", "QQQ"):
                index, journal = index_account(
                    indexes, symbol, dates, cost, run_id="selective-actions/1"
                )
                curves[symbol] = index.daily
                accounts[symbol] = account_summary(dates, index.daily, regimes[start:])
                journal.archive(output / f"journal-{cost:g}-{offset}-{symbol}")
            comparisons = {
                name: {
                    control: paired(dates, curves[name], curves[control])
                    for control in ("original_v4", "momentum", "mean", "SPY", "QQQ")
                    if name != control
                }
                for name in ("momentum", "mean", "ridge", "tree")
            }
            runs.append(
                {
                    "cost_bps": cost,
                    "offset": offset,
                    "accounts": accounts,
                    "paired": comparisons,
                }
            )
            np.savez_compressed(
                output / f"curves-{cost:g}-{offset}.npz", dates=dates, **curves
            )
            save_json(output / f"result-{cost:g}-{offset}.json", runs[-1])
    scores = {}
    for name in ("mean", "ridge", "tree"):
        predictions = trained.predictions[name]
        keep = np.isfinite(data.labels) & np.isfinite(predictions)
        mse = float(np.mean((predictions[keep] - data.labels[keep]) ** 2))
        mean_mse = float(
            np.mean((trained.predictions["mean"][keep] - data.labels[keep]) ** 2)
        )
        scores[name] = {
            "rows": int(keep.sum()),
            "mse": mse,
            "skill_vs_action_mean": 1 - mse / mean_mse if mean_mse > 0 else None,
        }
    summary = {
        "source_revision": source_revision,
        "action_value_scores": scores,
        "runs": runs,
        "verdict": verdict(runs),
        "promoted": False,
        "deployed": False,
    }
    save_json(output / "summary.json", summary)
    return summary
