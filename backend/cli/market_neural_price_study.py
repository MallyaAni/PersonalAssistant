"""Run the predeclared price-only neural ranking study; never change live accounts."""

import argparse
import hashlib
import json
import pickle
import subprocess
from datetime import date
from pathlib import Path

import numpy as np
import torch

from backend.agents.trading.desk import event_risk, simulate
from backend.cli.market_growth_pilot import predict, return_network
from backend.market import growth_pilot as gp
from backend.market import neural_policy_comparison as comparison
from backend.market import neural_price_basis as basis
from backend.market import neural_study_metrics as metrics
from backend.market import opportunity_learning as ol
from backend.market.allocation_controls import constant_exposure
from backend.market.store import MarketStore

REPORT_SHA256 = "d6f8fe0cbf74e7318352b8e9c02910cae00164a2a4900be6a8e24a9960401c26"
ASOF = date(2026, 9, 18)
SINCE = date(2025, 1, 2)
POLICY = "neural-price-only-live-ranking/1"


# Hash the exact artifact before loading or describing it.
def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# Load only the exact previously produced trusted report named in the protocol.
def load_report(path):
    if digest(path) != REPORT_SHA256:
        raise ValueError("The report differs from the predeclared trusted artifact")
    with Path(path).open("rb") as stream:
        return pickle.load(stream)  # noqa: S301 - exact trusted artifact pinned above


# Verify the complete common date grid against the exchange, without trimming it.
def verify_calendar(dates):
    import exchange_calendars

    calendar = exchange_calendars.get_calendar(
        "XNYS", start=str(dates[0]), end=str(dates[-1])
    )
    expected = calendar.sessions.values.astype("datetime64[D]")
    if not np.array_equal(dates, expected):
        missing = np.setdiff1d(expected, dates)
        extra = np.setdiff1d(dates, expected)
        raise ValueError(f"Incomplete exchange grid: missing={missing}, extra={extra}")
    return exchange_calendars.__version__


# Tie every consumed price field to immutable source partitions and preserve hashes.
def prepare(report, store):
    panel = report.panel
    calendar_version = verify_calendar(panel.dates)
    histories, manifests, hashes = {}, {}, {}
    for column, symbol in enumerate(panel.tickers):
        history = store.read(symbol, ASOF)
        if history is None:
            raise ValueError(f"Missing source history: {symbol}")
        histories[symbol] = history
        manifests[symbol] = basis.PriceBasis(
            source=history.source,
            source_time=history.source_time,
            action_coverage_start=min(bar.session_date for bar in history.bars),
            action_coverage_end=history.source_time.astimezone(
                basis.fa.NEW_YORK
            ).date(),
            actions_complete=False,
            fundamental_units_verified=False,
        )
        source = {bar.session_date: bar for bar in history.bars}
        for field in ("open", "high", "low"):
            expected = np.asarray(
                [
                    getattr(source[day], field) if day in source else np.nan
                    for day in panel.dates.astype(object)
                ],
                dtype=float,
            )
            if not np.array_equal(
                expected, getattr(panel, field)[:, column], equal_nan=True
            ):
                raise ValueError(f"{symbol}: source {field} mismatch")
        vintage = store.latest_asof(symbol, ASOF)
        for kind in ("bars", "actions"):
            path = store.root / kind / f"asof={vintage}" / f"{symbol}.parquet"
            hashes[str(path)] = digest(path)
    audit = {}
    data, raw, names = basis.features(
        panel, {}, histories, basis_by_ticker=manifests, audit=audit
    )
    if np.isfinite(raw[:, :, 8:]).any():
        raise AssertionError("This declared variant must contain no financial values")
    return (
        data,
        raw,
        names,
        {
            "source_hashes": hashes,
            "input_audit": audit,
            "exchange_calendar_version": calendar_version,
        },
    )


# Purge complete twenty-session outcomes and fit normalization on training only.
def training_inputs(data, raw):
    labels = ol.labels(data.prices)
    rows = gp.split_rows(data, "2018-01-01", "2024-01-01", horizon=21)[::5]
    mask = np.zeros(data.eligible.shape, dtype=bool)
    mask[rows] = data.eligible[rows] & np.isfinite(labels[rows])
    if not mask.any():
        raise ValueError("No complete eligible training labels")
    used = np.flatnonzero(mask.any(axis=1))
    if np.any(data.dates[used + 21] >= np.datetime64("2024-01-01")):
        raise AssertionError("A training label crossed the fixed cutoff")
    values, normalization = ol.normalize(raw, raw[mask])
    return values, labels, mask, normalization, str(data.dates[used[-1] + 21])


# Fit the fixed CPU architecture once, without selecting on evaluation outcomes.
def fit(values, labels, mask):
    torch.set_num_threads(2)
    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True)
    model = return_network(values.shape[-1])
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.001)
    x = torch.as_tensor(values[mask], dtype=torch.float32)
    y = torch.as_tensor(labels[mask], dtype=torch.float32)
    losses = []
    for _ in range(10):
        for batch in torch.randperm(len(x)).split(2048):
            loss = torch.nn.functional.mse_loss(model(x[batch]).squeeze(-1), y[batch])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        losses.append(float(loss.detach()))
    return model, losses


# Keep equal-weight eligibility causal and omit all grade/entry/event overlays.
def equal_allocator(data):
    # The current completed observation determines the equal-weight basket.
    def allocate(report, panel, config, t):
        eligible = data.eligible[t]
        return eligible.astype(float) / max(int(eligible.sum()), 1)

    return allocate


# Create a benchmark account from the same dates and explicit next-open prices.
def benchmark(store, dates, symbol, cost, hashes):
    history = store.read(symbol, ASOF)
    if history is None:
        raise ValueError(f"Missing benchmark source: {symbol}")
    declared = basis.PriceBasis(
        source=history.source,
        source_time=history.source_time,
        action_coverage_start=min(bar.session_date for bar in history.bars),
        action_coverage_end=history.source_time.astimezone(basis.fa.NEW_YORK).date(),
        actions_complete=False,
    )
    basis._validate_identity(symbol, history, declared)
    if declared.action_coverage_end > ASOF:
        raise ValueError("Benchmark source is newer than the declared snapshot")
    bars = {bar.session_date: bar for bar in history.bars}
    ordered = [bars[day] for day in dates.astype(object)]
    closes = np.asarray([bar.adjusted_close for bar in ordered], dtype=float)
    opens = np.asarray(
        [bar.open * bar.adjusted_close / bar.close for bar in ordered], dtype=float
    )
    path = (
        store.root
        / "bars"
        / f"asof={store.latest_asof(symbol, ASOF)}"
        / f"{symbol}.parquet"
    )
    hashes[str(path)] = digest(path)
    return metrics.Curve(dates, constant_exposure(closes, opens, 1.0, cost), cost)


# Evaluate the frozen predictions at both declared costs and retain all curves.
def evaluate(report, data, forecasts, model_hash, input_hash, label_end, store, output):
    rows = len(data.dates)
    evidence = comparison.ForecastEvidence(
        dates=data.dates,
        tickers=data.tickers,
        values=forecasts,
        fit_on=np.full(rows, np.datetime64("2025-01-01")),
        training_label_end=np.full(rows, np.datetime64(label_end)),
        selection_label_end=np.full(rows, np.datetime64("2024-12-31")),
        feature_available_on=np.broadcast_to(data.dates[:, None], forecasts.shape),
        model_sha256=model_hash,
        input_sha256=input_hash,
    )
    events = event_risk.live_path(report.panel)
    tables, benchmark_hashes = {}, {}
    for cost in (10, 25):
        pair = comparison.compare(
            report, evidence, since=SINCE, event_exposure=events, cost_bps=cost
        )
        curves = {
            name: metrics.from_simulation(pair[name], cost)
            for name in ("incumbent", "candidate")
        }
        equal = simulate.run(
            report,
            since=SINCE,
            cost_bps=cost,
            rebalance=21,
            use_exits=False,
            allocator=equal_allocator(data),
        )
        curves["equal_weight"] = metrics.from_simulation(equal, cost)
        dates = curves["incumbent"].dates
        for symbol in ("SPY", "QQQ"):
            curves[symbol] = benchmark(store, dates, symbol, cost, benchmark_hashes)
        tables[str(cost)] = metrics.scorecard(curves, cost_bps=cost)
        tables[str(cost)]["calendar_years"] = {}
        for year in (2025, 2026):
            first = max(
                0, int(np.searchsorted(dates, np.datetime64(f"{year}-01-01"))) - 1
            )
            last = int(np.searchsorted(dates, np.datetime64(f"{year + 1}-01-01")))
            annual = {
                name: metrics.Curve(
                    curve.dates[first:last], curve.equity[first:last], cost
                )
                for name, curve in curves.items()
            }
            tables[str(cost)]["calendar_years"][str(year)] = metrics.scorecard(
                annual, cost_bps=cost
            )
        np.savez_compressed(
            output / f"curves-{cost}bps.npz",
            dates=dates,
            **{name: curve.equity for name, curve in curves.items()},
        )
    return tables, benchmark_hashes


# Preserve a complete new research artifact without overwriting any previous run.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    report = load_report(args.report)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    store = MarketStore(args.data_dir)
    data, raw, names, provenance = prepare(report, store)
    values, labels, mask, normalization, label_end = training_inputs(data, raw)
    manifest = {
        "policy": POLICY,
        "adoption_eligible": False,
        "report_sha256": REPORT_SHA256,
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "tickers": data.tickers,
        "features": names,
        "training_examples": int(mask.sum()),
        "last_training_label": label_end,
        "test_start": str(SINCE),
        "test_end": str(ASOF),
        "financial_values_present": False,
        "torch": torch.__version__,
        **provenance,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    np.savez_compressed(
        output / "inputs.npz",
        dates=data.dates,
        raw=raw,
        values=values,
        labels=labels,
        train_mask=mask,
        median=normalization[0],
        scale=normalization[1],
    )
    if args.prepare_only:
        print(
            json.dumps({"prepared": str(output), "training_examples": int(mask.sum())})
        )
        return
    model, losses = fit(values, labels, mask)
    torch.save(model.state_dict(), output / "model.pt")
    forecasts = predict(model, values)
    restored = return_network(values.shape[-1])
    restored.load_state_dict(torch.load(output / "model.pt", weights_only=True))
    np.testing.assert_array_equal(forecasts, predict(restored, values))
    np.save(output / "forecasts.npy", forecasts)
    tables, benchmark_hashes = evaluate(
        report,
        data,
        forecasts,
        digest(output / "model.pt"),
        digest(output / "inputs.npz"),
        label_end,
        store,
        output,
    )
    result = {
        "policy": POLICY,
        "adoption_eligible": False,
        "tables": tables,
        "last_batch_training_losses": losses,
        "benchmark_hashes": benchmark_hashes,
        "limitations": [
            "Price-only retrain, not frozen nightly neural",
            "Examined 2025+ period",
            "Current survivor cohort and reconstructed grades",
            "No actual midpoint fills",
        ],
    }
    (output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps({"artifact": str(output), "tables": tables}, indent=2))


if __name__ == "__main__":
    main()
