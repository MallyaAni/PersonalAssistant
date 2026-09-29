"""Bounded daily-action experiment; offline research, never a live policy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.cli.market_profit_taking import default_desk
from backend.market import benchmarks, candidate_stats, membership
from backend.market.allocation_controls import adjusted_open
from backend.market.research_journal import ResearchJournal, _new_directory
from backend.market.research_journal_replay import verify_snapshot
from backend.market.session_anatomy import json_ready

OFFSETS = (0, 5, 10, 15)
COSTS = (10.0, 25.0)
ARMS = ("original_v4", "daily_v4", "momentum", "mean", "ridge", "tree")


# Retain each immutable benchmark history once for every account in this run.
class FrozenIndexes:
    # Read both controls before fitting so later store partitions cannot change them.
    def __init__(self, store):
        self.histories = {symbol: store.read(symbol) for symbol in ("SPY", "QQQ")}
        if any(value is None for value in self.histories.values()):
            raise ValueError("Both SPY and QQQ histories are required")

    # Serve only the already captured histories through the existing benchmark loader.
    def read(self, symbol, asof=None):
        return self.histories.get(symbol)


# Save strict, human-readable research JSON without replacing any existing file.
def save_json(path: Path, value) -> None:
    with path.open("x") as stream:
        json.dump(json_ready(value), stream, indent=2, allow_nan=False)
        stream.write("\n")


# Refuse missing sessions rather than silently substituting a flat index return.
def index_prices(store, symbol, dates):
    history = store.read(symbol)
    if history is None:
        raise ValueError(f"Missing daily history for {symbol}")
    prices = benchmarks._aligned_prices(history, dates)
    close = prices["adjusted_close"]
    opens = adjusted_open(prices["open"], prices["close"], close)
    if not (
        np.isfinite(close).all()
        and (close > 0).all()
        and np.isfinite(opens).all()
        and (opens > 0).all()
    ):
        raise ValueError(f"Incomplete daily {symbol} prices")
    return opens, close


# Record an all-cash notional index purchase and independently verify every mark.
def index_account(store, symbol, dates, cost, *, run_id="daily-actions/1"):
    reference = benchmarks.load_benchmark(store, symbol, dates, cost_bps=cost)
    if not reference.available:
        raise ValueError(reference.reason)
    opens, close = index_prices(store, symbol, dates)
    journal = ResearchJournal(
        dates,
        (symbol,),
        opens[:, None],
        close[:, None],
        run_id=run_id,
        account_id=symbol,
        policy_id="buy-and-hold",
        cost_bps=cost,
        provenance={"notional_opening_order": True},
    )
    journal.open_account(0, 1.0, [0.0])
    journal.mark(0, 1.0, [0.0], 1.0, 0.0)
    decision = journal.decision(0, [1.0 / close[0]], [1.0], "Invest initial cash")
    units = 1.0 / (opens[1] * (1.0 + cost / 1e4))
    journal.adjustment(decision, 1, "open", [units], "Fixed opening cash budget")
    journal.fill_batch(
        decision,
        1,
        "open",
        [units],
        [opens[1]],
        [0.0],
        1.0,
        [units],
        0.0,
        1.0,
        1.0,
        False,
    )
    traded = units * opens[1]
    for t in range(1, len(dates)):
        journal.mark(t, 0.0, [units], float(reference.equity[t]), traded)
    journal.finish(len(dates) - 1, 0.0, [units], traded, {})
    proof = verify_snapshot(journal.snapshot())
    if not proof["ok"]:
        raise ValueError(f"Index journal failed verification: {proof['errors']}")
    nav = np.array([m["nav"] for m in proof["marks"]])
    np.testing.assert_allclose(nav, reference.equity, rtol=1e-12, atol=1e-12)
    return reference, journal


# Calculate net account metrics without discarding an interior missing return.
def metrics(returns):
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 1 or not len(returns) or not np.isfinite(returns).all():
        raise ValueError("Metrics require a complete, finite return window")
    if (returns <= -1).any():
        raise ValueError("Account lost all capital or has invalid returns")
    nav = np.r_[1.0, np.cumprod(1.0 + returns)]
    return {
        "sessions": len(returns),
        "total_return": float(nav[-1] - 1),
        "cagr": float(nav[-1] ** (252 / len(returns)) - 1),
        "drawdown": float(np.min(nav / np.maximum.accumulate(nav) - 1)),
        "mean_daily_bp": float(returns.mean() * 1e4),
    }


# Attach regime labels from the decision close before each earned return.
def regime_labels(spy_close):
    close = np.asarray(spy_close, dtype=float)
    labels = np.full(len(close), "unavailable", dtype="U32")
    returns = np.r_[np.nan, np.log(close[1:] / close[:-1])]
    for t in range(200, len(close)):
        prior = t - 1
        mean = close[prior - 199 : prior + 1].mean()
        vol = returns[prior - 19 : prior + 1].std(ddof=0) * np.sqrt(252)
        labels[t] = ("above200" if close[prior] >= mean else "below200") + (
            "_highvol" if vol >= 0.25 else "_lowvol"
        )
    return labels


# Summarize continuous returns by year and causal regime without resetting capital.
def account_summary(dates, daily, regimes):
    if len(daily) != len(dates) or len(regimes) != len(dates):
        raise ValueError("Account arrays must align")
    if not np.isnan(daily[0]):
        raise ValueError("First account row must identify unfunded starting capital")
    out = {"all": metrics(daily[1:]), "years": {}, "regimes": {}}
    years = dates.astype("datetime64[Y]").astype(str)
    for year in np.unique(years[1:]):
        keep = (years == year) & (np.arange(len(dates)) > 0)
        out["years"][year] = metrics(daily[keep])
    for regime in np.unique(regimes[1:]):
        keep = (regimes == regime) & (np.arange(len(dates)) > 0)
        r = daily[keep]
        # Discontinuous regime slices are not standalone funded accounts/CAGRs.
        out["regimes"][str(regime)] = {
            "sessions": int(keep.sum()),
            "mean_daily_bp": float(r.mean() * 1e4),
            "log_growth_contribution": float(np.log1p(r).sum()),
        }
    return out


# Compare identical sessions, with uncertainty retaining serial dependence.
def paired(dates, candidate, control):
    excess = np.asarray(candidate)[1:] - np.asarray(control)[1:]
    if not np.isfinite(excess).all():
        raise ValueError("Paired comparison has an unavailable return")
    recent = np.asarray(dates)[1:] >= np.datetime64("2024-01-01")
    return {
        "mean_daily_bp": float(excess.mean() * 1e4),
        "hac_t": candidate_stats.hac_t(excess, lag=20),
        "recent_mean_daily_bp": float(excess[recent].mean() * 1e4)
        if recent.any()
        else None,
    }


# Apply registered screening floors, never turning a research pass into promotion.
def verdict(runs):
    result = {}
    for name in ("ridge", "tree"):
        checks = {}
        for control in ("original_v4", "daily_v4"):
            selected = [r for r in runs if r["cost_bps"] == 25]
            gains = [
                r["accounts"][name]["all"]["cagr"]
                - r["accounts"][control]["all"]["cagr"]
                for r in selected
            ]
            drawdown_gaps = [
                r["accounts"][name]["all"]["drawdown"]
                - r["accounts"][control]["all"]["drawdown"]
                for r in selected
            ]
            zero = next(r for r in selected if r["offset"] == 0)
            pair = zero["paired"][name][control]
            median_gain = float(
                np.median([r["accounts"][name]["all"]["cagr"] for r in selected])
                - np.median([r["accounts"][control]["all"]["cagr"] for r in selected])
            )
            checks[control] = {
                "median_cagr_gain": median_gain,
                "offsets_above": sum(g > 0 for g in gains),
                "worst_drawdown_gap": min(drawdown_gaps),
                **pair,
                "passes": bool(
                    len(selected) == 4
                    and median_gain >= 0.01
                    and pair["hac_t"] >= 2
                    and min(drawdown_gaps) >= -0.03
                    and pair["recent_mean_daily_bp"] is not None
                    and pair["recent_mean_daily_bp"] >= 0
                    and sum(g > 0 for g in gains) >= 3
                ),
            }
        result[name] = {
            "status": "ADVANCE_RESEARCH_ONLY"
            if all(c["passes"] for c in checks.values())
            else "DO_NOT_PROMOTE",
            "checks": checks,
        }
    return result


# Fit the frozen model budget and evaluate continuous funded accounts in fresh output.
def run(store, membership_path: Path, output: Path, *, source_revision: str):
    from backend.market import daily_action_execution as execution
    from backend.market import daily_action_model as model

    output = _new_directory(output)
    report = default_desk(store)
    restricted, mask = point_in_time.point_in_time(report, membership_path)
    panel = restricted.panel
    indexes = FrozenIndexes(store)
    qqq_open, qqq = index_prices(indexes, "QQQ", panel.dates)
    spy_open, spy = index_prices(indexes, "SPY", panel.dates)
    np.testing.assert_array_equal(spy, panel.adj_close[:, panel.index(panel.benchmark)])
    data = model.build_dataset(panel, mask, restricted.graded.grades, qqq)
    missing = sorted(
        {r.ticker for r in membership.load_history(membership_path)}
        - set(panel.tickers)
    )
    save_json(
        output / "inputs.json",
        {
            "source_revision": source_revision,
            "membership_sha256": hashlib.sha256(
                membership_path.read_bytes()
            ).hexdigest(),
            "start": str(panel.dates[0]),
            "end": str(panel.dates[-1]),
            "tickers": panel.tickers,
            "missing_historical_members": missing,
            "feature_names": data.feature_names,
            "eligible_rows": int(data.eligible.sum()),
            "historical_availability_verified": False,
            "test_status": "reused historical development data, not pristine test",
        },
    )
    np.savez_compressed(
        output / "inputs.npz",
        dates=panel.dates,
        tickers=panel.tickers,
        features=data.features,
        labels=data.labels,
        eligible=data.eligible,
        label_end=data.label_end,
        membership=mask,
        grades=restricted.graded.grades,
        open=panel.open,
        high=panel.high,
        low=panel.low,
        close=panel.close,
        adj_close=panel.adj_close,
        volume=panel.volume,
        qqq=qqq,
        spy=spy,
        qqq_open=qqq_open,
        spy_open=spy_open,
    )
    print(
        f"Daily data: {data.features.shape}, missing historical names: {missing}",
        flush=True,
    )
    trained = model.train(data, output / "training")
    predictions = dict(trained.predictions)
    # The registered momentum control uses the same forecast-to-weight mapping.
    momentum = np.full(panel.adj_close.shape, np.nan)
    with np.errstate(all="ignore"):
        momentum[20:] = np.log(panel.adj_close[20:] / panel.adj_close[:-20]) * 0.25
    predictions["momentum"] = momentum
    first = int(np.searchsorted(panel.dates, np.datetime64("2019-01-01")))
    if first + max(OFFSETS) >= len(panel.dates) - 1:
        raise ValueError("Insufficient outer-test history")
    regimes = regime_labels(spy)
    runs = []
    for cost in COSTS:
        for offset in OFFSETS:
            start = first + offset
            dates = panel.dates[start:]
            curves, accounts = {}, {}
            for name in ARMS:
                priced = execution.price(
                    restricted,
                    mask,
                    predictions.get(name),
                    panel.dates[start].astype(object),
                    cost,
                    daily=name != "original_v4",
                    name=name,
                )
                np.testing.assert_array_equal(priced.result.dates, dates)
                daily = np.asarray(priced.result.returns, dtype=float)
                accounts[name] = account_summary(dates, daily, regimes[start:])
                accounts[name]["execution"] = priced.diagnostics
                curves[name] = daily
                priced.journal.archive(output / f"journal-{cost:g}-{offset}-{name}")
                print(
                    f"Priced {cost:g}bp offset {offset} {name}: "
                    f"CAGR {accounts[name]['all']['cagr']:.3%}",
                    flush=True,
                )
            for symbol in ("SPY", "QQQ"):
                index, journal = index_account(indexes, symbol, dates, cost)
                curves[symbol] = index.daily
                accounts[symbol] = account_summary(dates, index.daily, regimes[start:])
                journal.archive(output / f"journal-{cost:g}-{offset}-{symbol}")
            comparisons = {
                name: {
                    control: paired(dates, curves[name], curves[control])
                    for control in ("original_v4", "daily_v4", "SPY", "QQQ")
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
    forecast_scores = {}
    mature = data.eligible & np.isfinite(data.labels)
    for name in ("mean", "ridge", "tree"):
        pred = predictions[name]
        keep = mature & np.isfinite(pred)
        baseline = predictions["mean"]
        mse = float(np.mean((pred[keep] - data.labels[keep]) ** 2))
        baseline_mse = float(np.mean((baseline[keep] - data.labels[keep]) ** 2))
        forecast_scores[name] = {
            "rows": int(keep.sum()),
            "mse": mse,
            "skill_vs_mean": 1 - mse / baseline_mse,
        }
    summary = {
        "source_revision": source_revision,
        "forecasts": forecast_scores,
        "runs": runs,
        "verdict": verdict(runs),
        "promoted": False,
        "deployed": False,
    }
    save_json(output / "summary.json", summary)
    return summary
