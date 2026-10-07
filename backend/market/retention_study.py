"""Fixed funded held-B comparison on authenticated original daily inputs.

This reconstructed daily component study neither submits orders nor establishes
current intraday executor parity or historical publication-time eligibility.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np

from backend.agents.trading.desk import event_risk, paper, policy_v5, simulate
from backend.market import learned_retention_models as heads
from backend.market import retention_inputs
from backend.market.allocation_evaluation import metrics
from backend.market.learned_entry_models import _array_hash, _write_json
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot
from backend.market.retention_replay import RetentionAdapter

START = np.datetime64("2018-02-01")
END = np.datetime64("2026-09-30")
SNAPSHOT_SHA256 = "8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58"
ARMS = ("incumbent", "learned", "unconditional")
COSTS = (0, 10, 25)
OFFSETS = tuple(range(20))
WINDOWS = {
    "full": (START, END),
    "2018-20": (START, np.datetime64("2020-12-31")),
    "2021-26": (np.datetime64("2021-01-01"), END),
    "reused_recent": (np.datetime64("2026-08-17"), END),
}


# Expose recorded ordinal grades without converting unknowns into a valid grade.
@dataclass(frozen=True)
class _Grades:
    grades: np.ndarray

    # Translate exactly one available grade for the shared simulator trade log.
    def letter(self, t, column):
        return {3: "A+", 2: "A", 1: "B", 0: "C"}.get(
            int(self.grades[t, column]), "unknown"
        )


# Hash retained source/artifact bytes without trusting a filename as identity.
def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# Freeze the modules and preregistration exercised by this exact research runner.
def source_hashes():
    root = Path(__file__).resolve().parents[2]
    files = (
        Path(__file__),
        Path(retention_inputs.__file__),
        Path(heads.__file__),
        Path(simulate.__file__),
        Path(paper.__file__),
        Path(policy_v5.__file__),
        Path(event_risk.__file__),
        root / "backend/market/retention_replay.py",
        root / "backend/market/learned_retention.py",
        root / "backend/market/learned_entry_models.py",
        root / "backend/market/learned_entry_data.py",
        root / "backend/agents/trading/desk/exit.py",
        root / "backend/market/allocation_controls.py",
        root / "backend/market/research_journal.py",
        root / "backend/market/research_journal_replay.py",
        root / "backend/cli/market_retention_study.py",
        root / "backend/market/allocation_evaluation.py",
        root / "backend/market/calendar.py",
        root / "backend/market/data/fomc_decisions.csv",
        root / "backend/market/data/nyse_holidays.json",
        root / "backend/market/data/nyse_early_closes.json",
        root / "backend/market/data/nyse_historical_sessions.json",
        root / "docs/research/held-b-funded-comparison-plan-2026-10-03.md",
        root / "docs/research/learned-retention-plan-2026-10-03.md",
    )
    return {str(p.relative_to(root)): file_hash(p) for p in files}


# Compare mounted bytes with the complete manifest produced from the actual Git tree.
def authenticate_source(revision, manifest_path):
    if (
        not isinstance(revision, str)
        or len(revision) != 40
        or any(c not in "0123456789abcdef" for c in revision)
    ):
        raise ValueError("Exact Git commit SHA required")
    payload = Path(manifest_path).read_bytes()
    manifest = json.loads(payload)
    if manifest.get("git_commit") != revision or not isinstance(
        manifest.get("files"), dict
    ):
        raise ValueError("Source manifest must identify the declared Git checkout")
    root = Path(__file__).resolve().parents[2]
    required = source_hashes()
    if any(manifest["files"].get(key) != value for key, value in required.items()):
        raise ValueError(
            "Required source modules or protocol differ from the Git manifest"
        )
    for name, digest in manifest["files"].items():
        path = root / name
        if (
            not isinstance(name, str)
            or Path(name).is_absolute()
            or ".." in Path(name).parts
        ):
            raise ValueError("Unsafe source manifest path")
        if not path.is_file() or path.is_symlink() or file_hash(path) != digest:
            raise ValueError(
                f"Mounted source differs from authenticated Git tree: {name}"
            )
    return {
        "git_commit": revision,
        "files": len(manifest["files"]),
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
    }


# Observe the shared adjusted-unit ledger with declared immutable source lineage.
def _journal(panel, cost, account, provenance):
    return ResearchJournal(
        panel.dates,
        panel.tickers,
        simulate.adjusted_open(panel),
        panel.adj_close,
        run_id="held-b-funded-comparison/1",
        account_id=account,
        policy_id=account.split("-")[0],
        cost_bps=cost,
        provenance=provenance,
    )


# Archive one real event history and reconcile it with the independent ledger reader.
def _archive(journal, path):
    proof = verify_snapshot(journal.snapshot())
    if not proof["ok"]:
        raise ValueError(f"Recorded account failed independent reconciliation: {proof}")
    journal.archive(path)
    return {
        "proof": proof,
        "files": {
            name: file_hash(path / name)
            for name in ("events.json", "prices.json", "manifest.json")
        },
    }


# Extract actual daily fills rather than counting intended sales as turnover.
def _flows(journal, first):
    dates = journal.snapshot()["manifest"]["sessions"]
    traded = np.zeros(len(dates) - first)
    fees = np.zeros_like(traded)
    for event in journal.snapshot()["events"]:
        if event["type"] == "fill_batch":
            row = event["session_index"] - first
            traded[row] += sum(event["notional"])
            fees[row] += sum(event["fees"])
    return traded, fees


# Make one next-open, fee-funded buy and retain its shares through the common end.
def benchmark(panel, symbol, first, cost, journal):
    prices = panel.adj_close[:, panel.index(symbol)]
    opens = simulate.adjusted_open(panel)[:, panel.index(symbol)]
    if not np.isfinite(prices[first:]).all() or not np.isfinite(opens[first:]).all():
        raise ValueError(f"Complete benchmark marks required: {symbol}")
    cash, quantity, traded = 1.0, 0.0, 0.0
    nav = np.full(len(prices) - first, np.nan)
    nav[0] = 1.0
    journal.open_account(first, cash, [quantity])
    journal.mark(first, cash, [quantity], cash, traded)
    decision = journal.decision(
        first, [None], desired_weights=[1.0], reason="buy_and_hold_cash_budget"
    )
    for t in range(first + 1, len(prices)):
        if t == first + 1:
            quantity = cash / (opens[t] * (1 + cost / 1e4))
            traded = quantity * opens[t]
            journal.adjustment(
                decision, t, "open", [quantity], "convert_opening_cash_budget_to_units"
            )
            journal.fill_batch(
                decision,
                t,
                "open",
                [quantity],
                [opens[t]],
                [0.0],
                cash,
                [quantity],
                0.0,
                cash,
                1.0,
                False,
            )
            cash = 0.0
        nav[t - first] = cash + quantity * prices[t]
        journal.mark(t, cash, [quantity], nav[t - first], traded)
    journal.finish(len(prices) - 1, cash, [quantity], traded, {})
    return nav


# Calculate comparable carried-account metrics while retaining unavailable returns.
def score(dates, nav, traded, fees, controls):
    daily = nav[1:] / nav[:-1] - 1
    scored_dates = dates[1:]
    output = {}
    for window, (begin, end) in WINDOWS.items():
        mask = (scored_dates >= begin) & (scored_dates <= end)
        values = daily[mask]
        missing = int((~np.isfinite(values)).sum())
        result = {
            "sessions": int(mask.sum()),
            "missing_returns": missing,
            "metrics": None if missing or not len(values) else metrics(values),
            "fees_nav1": float(fees[1:][mask].sum()),
            "traded_notional_nav1": float(traded[1:][mask].sum()),
            "turnover_per_year": None,
            "benchmarks": {},
        }
        if not missing and len(values):
            denominator = nav[:-1][mask]
            result["turnover_per_year"] = float(
                np.sum(traded[1:][mask] / denominator) * 252 / len(values)
            )
        for name, control in controls.items():
            other = control[1:] / control[:-1] - 1
            other = other[mask]
            if missing or not len(values) or not np.isfinite(other).all():
                result["benchmarks"][name] = {
                    "excess_total": None,
                    "rolling_252_win_rate": None,
                }
                continue
            own_total, other_total = metrics(values)["total"], metrics(other)["total"]
            own_nav = np.r_[1.0, np.cumprod(1 + values)]
            other_nav = np.r_[1.0, np.cumprod(1 + other)]
            wins = own_nav[252:] / own_nav[:-252] > other_nav[252:] / other_nav[:-252]
            result["benchmarks"][name] = {
                "excess_total": own_total - other_total,
                "rolling_252_win_rate": float(wins.mean()) if len(wins) else None,
                "rolling_windows": int(len(wins)),
                "overlapping": True,
            }
        output[window] = result
    return output


# Fit the declared heads once and persist every actual model and scored array.
def fit(panel, grades, eligible, provenance, output):
    data = heads.prepare(panel, grades, eligible, panel.dates, provenance)
    np.savez_compressed(
        output / "prepared.npz",
        **{
            key: data[key]
            for key in (
                "X",
                "relative_labels",
                "spy_labels",
                "valid",
                "spy_valid",
                "dates",
                "label_end_dates",
                "training_symbols",
            )
        },
    )
    print("authenticated preparation complete; fixed monthly fits starting", flush=True)
    forecasts = heads.walk_forward(data)
    joblib.dump(forecasts.models, output / "models.joblib", compress=3)
    np.savez_compressed(
        output / "forecasts.npz",
        dates=panel.dates,
        relative=forecasts.relative,
        spy=forecasts.spy,
    )
    receipt = {
        **forecasts.manifest,
        "artifact_hashes": {
            name: file_hash(output / name)
            for name in ("prepared.npz", "models.joblib", "forecasts.npz")
        },
        "model_format": "private_authenticated_joblib_not_untrusted_input",
    }
    _write_json(output / "fit.json", receipt)
    print("fixed monthly fits and forecast artifacts complete", flush=True)
    return forecasts


# Describe causal prior-market context without inventing a tradable regime switch.
def regime_summary(panel, first, nav, controls):
    market = panel.adj_close[:, panel.index("SPY")]
    prior_returns = market[1:] / market[:-1] - 1
    daily = nav[1:] / nav[:-1] - 1
    groups = {"above_prior_200_mean": [], "below_prior_200_mean": []}
    vols = {key: [] for key in groups}
    for index in range(1, len(nav)):
        day = first + index
        history = market[day - 200 : day]
        volatility = prior_returns[day - 64 : day - 1]
        if day < 200 or len(history) != 200 or not np.isfinite(history).all():
            continue
        if not np.isfinite(daily[index - 1]):
            continue
        key = (
            "above_prior_200_mean"
            if market[day - 1] > history.mean()
            else "below_prior_200_mean"
        )
        groups[key].append(index - 1)
        vols[key].append(float(volatility.std() * np.sqrt(252)))
    return {
        key: {
            "sessions": len(rows),
            "mean_daily_return": float(daily[rows].mean()) if rows else None,
            "mean_prior_spy_volatility": float(np.mean(vols[key])) if rows else None,
            "mean_daily_excess": {
                symbol: float((daily - (curve[1:] / curve[:-1] - 1))[rows].mean())
                if rows
                else None
                for symbol, curve in controls.items()
            },
            "compounded_regime_performance": None,
        }
        for key, rows in groups.items()
    }


# Retain every fixed paired contrast rather than selecting favorable reset phases.
def paired_results(accounts):
    lookup = {(row["arm"], row["cost_bps"], row["offset"]): row for row in accounts}
    output = []
    for cost in COSTS:
        for offset in OFFSETS:
            learned = lookup[("learned", cost, offset)]
            for control in ("incumbent", "unconditional"):
                other = lookup[(control, cost, offset)]
                for window in WINDOWS:
                    own_metrics = learned["score"][window]["metrics"]
                    other_metrics = other["score"][window]["metrics"]
                    output.append(
                        {
                            "cost_bps": cost,
                            "offset": offset,
                            "window": window,
                            "control": control,
                            "paired_total_gain": None
                            if own_metrics is None or other_metrics is None
                            else own_metrics["total"] - other_metrics["total"],
                        }
                    )
    return output


# Run the frozen three-arm cost/offset comparison without changing production state.
def run(snapshot, provenance_path, daily_dir, output, source_revision, source_manifest):
    source_identity = authenticate_source(source_revision, source_manifest)
    if file_hash(snapshot) != SNAPSHOT_SHA256:
        raise ValueError("Fixed original preregistered snapshot SHA256 required")
    output = Path(output)
    output.mkdir(exist_ok=False)
    panel, grades, eligible, inputs = retention_inputs.load(
        snapshot, provenance_path, daily_dir
    )
    if panel.dates[-1] != END or START not in panel.dates:
        raise ValueError("Original full fixed evaluation window required")
    first = int(np.searchsorted(panel.dates, START))
    provenance = {
        "source_identity": source_identity,
        "source_revision": source_revision,
        "source_sha256": source_hashes(),
        "original_inputs": inputs,
        "adoption": False,
        "selection": "reconstructed_current_vintage_not_historical_publications",
        "execution": "legacy_daily_not_current_intraday_or_broker_parity",
    }
    _write_json(output / "inputs.json", provenance)
    _write_json(
        output / "status.json", {"stage": "fitting", "source_revision": source_revision}
    )
    forecasts = fit(panel, grades, eligible, provenance, output)
    report = SimpleNamespace(panel=panel, graded=_Grades(grades))
    options = dict(
        simulate.LIVE_POLICY,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        event_exposure=event_risk.live_path(panel),
        event_lifecycle=True,
        midcycle_redeploy=True,
        redeploy_buffer=float(paper.REDEPLOY_BUFFER),
        allocator=policy_v5.allocator(eligible),
        since=str(START),
    )
    accounts, curves, benchmark_rows = [], {}, []
    (output / "journals").mkdir()
    for cost in COSTS:
        controls = {}
        for name in ("SPY", "QQQ"):
            column = panel.index(name)
            from dataclasses import replace

            single = replace(
                panel,
                tickers=(name,),
                benchmark=name,
                **{
                    field: getattr(panel, field)[:, column : column + 1]
                    for field in ("open", "high", "low", "close", "adj_close", "volume")
                },
            )
            key = f"{name}-{cost}"
            journal = _journal(single, cost, key, provenance)
            controls[name] = benchmark(single, name, first, cost, journal)
            archive = _archive(journal, output / "journals" / key)
            traded, fees = _flows(journal, first)
            curves[key] = controls[name]
            benchmark_rows.append(
                {
                    "account": key,
                    "cost_bps": cost,
                    "score": score(
                        panel.dates[first:], controls[name], traded, fees, {}
                    ),
                    "journal": archive,
                }
            )
        for offset in OFFSETS:
            for arm in ARMS:
                key = f"{arm}-{cost}-{offset}"
                adapter = (
                    None
                    if arm == "incumbent"
                    else RetentionAdapter(
                        panel.tickers,
                        eligible,
                        forecasts.relative,
                        forecasts.spy,
                        cost,
                        unconditional=arm == "unconditional",
                    )
                )
                journal = _journal(panel, cost, key, provenance)
                result = simulate.run(
                    report,
                    **options,
                    cost_bps=cost,
                    rebalance_offset=offset,
                    retention_adapter=adapter,
                    journal=journal,
                )
                archive = _archive(journal, output / "journals" / key)
                traded, fees = _flows(journal, first)
                events = [] if adapter is None else adapter.events
                _write_json(output / f"{key}-decisions.json", events)
                curves[key] = result.equity
                accounts.append(
                    {
                        "account": key,
                        "arm": arm,
                        "cost_bps": cost,
                        "offset": offset,
                        "score": score(
                            result.dates, result.equity, traded, fees, controls
                        ),
                        "prior_market_context": regime_summary(
                            panel, first, result.equity, controls
                        ),
                        "journal": archive,
                        "decisions_sha256": file_hash(output / f"{key}-decisions.json"),
                        "decision_counts": dict(
                            Counter(e.get("reason", e.get("boundary")) for e in events)
                        ),
                        "nav_sha256": _array_hash(result.equity),
                    }
                )
                _write_json(
                    output / "status.json",
                    {
                        "stage": "accounts",
                        "completed": len(accounts),
                        "last": key,
                        "source_revision": source_revision,
                    },
                )
                print(f"reconciled {key}: {len(accounts)}/180", flush=True)
    np.savez_compressed(output / "curves.npz", dates=panel.dates[first:], **curves)
    result = {
        "schema": "held-b-funded-comparison/1",
        "source_revision": source_revision,
        "source_sha256": provenance["source_sha256"],
        "adoption": False,
        "limitations": [
            "current-vintage reconstructed grades and universe",
            "reused historical and recent data",
            "legacy daily execution, not current intraday or broker fills",
            "conditional log means are plug-in forecast comparisons",
        ],
        "accounts": accounts,
        "paired_results": paired_results(accounts),
        "benchmarks": benchmark_rows,
        "artifacts": {
            name: file_hash(output / name)
            for name in ("inputs.json", "fit.json", "curves.npz")
        },
    }
    _write_json(output / "result.json", result)
    _write_json(
        output / "status.json",
        {
            "stage": "complete",
            "accounts": len(accounts),
            "result_sha256": file_hash(output / "result.json"),
            "source_revision": source_revision,
        },
    )
    return result
