"""Run a named set of ranker configurations and record each in one table.

    python -m backend.cli.market_sweep --device cuda
    python -m backend.cli.market_sweep --only lgbm_alpha_rank,master_alpha_rank
    python -m backend.cli.market_sweep --list

Every run goes through the same walk-forward and the same harness; one row
per run is appended to <data-dir>/models/sweep.tsv with the baseline's
row on the same sessions beside it, so the table answers one question:
which configuration beats momentum, by how much, net of cost.
"""

import argparse
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from backend.config.settings import settings
from backend.market import baselines
from backend.market.harness import HarnessReport, evaluate_scores
from backend.market.model import (
    TrainConfig,
    load_extra_features,
    load_market_extra,
    load_tape,
    walk_forward,
)
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.universe import (
    FOCUS,
    MARKET_BENCHMARK,
    MEMBER,
    build_universe,
    theme_map,
    tickers_with_role,
)

# The sweep, in the order it runs. Each is a delta from the defaults.
SWEEP: dict[str, TrainConfig] = {
    "mlp_alpha_rank": TrainConfig(features="alpha", label="rank", encoder="mlp"),
    "lgbm_alpha_rank": TrainConfig(features="alpha", label="rank", encoder="lgbm"),
    "xsect_alpha_rank": TrainConfig(features="alpha", label="rank", encoder="xsect"),
    "master_alpha_rank": TrainConfig(
        features="alpha", label="rank", encoder="master", epochs=10
    ),
    "master_alpha_rank_seeds3": TrainConfig(
        features="alpha", label="rank", encoder="master", epochs=10, seeds=3
    ),
    "lgbm_alpha_rank_h20": TrainConfig(
        features="alpha", label="rank", encoder="lgbm", horizon=20
    ),
    "master_alpha_rank_h20": TrainConfig(
        features="alpha", label="rank", encoder="master", epochs=10, horizon=20
    ),
    "master_alpha_rank_h5": TrainConfig(
        features="alpha", label="rank", encoder="master", epochs=10, horizon=5
    ),
    # The horizons where the positive control found structure: five sessions
    # (short-term reversal) and sixty (theme momentum persists).
    "lgbm_alpha_rank_h5": TrainConfig(
        features="alpha", label="rank", encoder="lgbm", horizon=5
    ),
    "mlp_alpha_rank_h5": TrainConfig(
        features="alpha", label="rank", encoder="mlp", horizon=5
    ),
    "xsect_alpha_rank_h5": TrainConfig(
        features="alpha", label="rank", encoder="xsect", horizon=5
    ),
    "lgbm_alpha_rank_h60": TrainConfig(
        features="alpha", label="rank", encoder="lgbm", horizon=60
    ),
    "mlp_alpha_rank_h60": TrainConfig(
        features="alpha", label="rank", encoder="mlp", horizon=60
    ),
    "master_alpha_rank_h60": TrainConfig(
        features="alpha", label="rank", encoder="master", epochs=10, horizon=60
    ),
    # Regularised ensembles at five sessions: the models could not keep the
    # reversal their inputs hold; smaller nets, longer windows, more seeds.
    "mlp_alpha_rank_h5_reg": TrainConfig(
        features="alpha",
        label="rank",
        encoder="mlp",
        horizon=5,
        hidden=32,
        dropout=0.3,
        weight_decay=1e-2,
        train_size=1250,
        validation_fraction=0.2,
        seeds=3,
    ),
    "xsect_alpha_rank_h5_reg": TrainConfig(
        features="alpha",
        label="rank",
        encoder="xsect",
        horizon=5,
        hidden=32,
        dropout=0.3,
        weight_decay=1e-2,
        train_size=1250,
        validation_fraction=0.2,
        seeds=3,
    ),
    # With the EDGAR layer: events, reaction, fundamentals, point in time.
    "lgbm_edgar_h20": TrainConfig(
        features="alpha+edgar", label="rank", encoder="lgbm", horizon=20
    ),
    "mlp_edgar_h20": TrainConfig(
        features="alpha+edgar", label="rank", encoder="mlp", horizon=20
    ),
    "xsect_edgar_h20": TrainConfig(
        features="alpha+edgar", label="rank", encoder="xsect", horizon=20
    ),
    "lgbm_edgar_h60": TrainConfig(
        features="alpha+edgar", label="rank", encoder="lgbm", horizon=60
    ),
    "mlp_edgar_h60": TrainConfig(
        features="alpha+edgar", label="rank", encoder="mlp", horizon=60
    ),
    "master_edgar_h60": TrainConfig(
        features="alpha+edgar", label="rank", encoder="master", epochs=10, horizon=60
    ),
    # With the trader's toolkit (EMAs, levels, candles, MACD family).
    "lgbm_technical_h20": TrainConfig(
        features="alpha+edgar+technical", label="rank", encoder="lgbm", horizon=20
    ),
    "mlp_technical_h20": TrainConfig(
        features="alpha+edgar+technical", label="rank", encoder="mlp", horizon=20
    ),
    "lgbm_technical_h60": TrainConfig(
        features="alpha+edgar+technical", label="rank", encoder="lgbm", horizon=60
    ),
    "mlp_technical_h60": TrainConfig(
        features="alpha+edgar+technical", label="rank", encoder="mlp", horizon=60
    ),
    # The chart-image CNN of Jiang, Kelly and Xiu (2023).
    "chart_cnn_h20": TrainConfig(
        features="raw", label="rank", encoder="chart_cnn", horizon=20, epochs=5
    ),
    "chart_cnn_h5": TrainConfig(
        features="raw", label="rank", encoder="chart_cnn", horizon=5, epochs=5
    ),
    # The tape: a sequence model over the last five sessions of 15-minute
    # bars with the daily window as context, mixed across names.
    "tape_h5": TrainConfig(
        features="alpha+technical", label="rank", encoder="tape", horizon=5
    ),
    "tape_h20": TrainConfig(
        features="alpha+technical", label="rank", encoder="tape", horizon=20
    ),
    # With the Fed calendar, which no earlier input carried.
    "lgbm_calendar_h5": TrainConfig(
        features="alpha+edgar+technical+calendar",
        label="rank",
        encoder="lgbm",
        horizon=5,
    ),
    "lgbm_calendar_h20": TrainConfig(
        features="alpha+edgar+technical+calendar",
        label="rank",
        encoder="lgbm",
        horizon=20,
    ),
    "master_calendar_h5": TrainConfig(
        features="alpha+technical+calendar",
        label="rank",
        encoder="master",
        horizon=5,
        epochs=10,
    ),
    # With the calendar and the macro state (VIX, rates, dollar, oil).
    "lgbm_macro_h20": TrainConfig(
        features="alpha+edgar+technical+calendar+macro",
        label="rank",
        encoder="lgbm",
        horizon=20,
    ),
    "master_macro_h20": TrainConfig(
        features="alpha+technical+calendar+macro",
        label="rank",
        encoder="master",
        horizon=20,
        epochs=10,
    ),
    "xsect_raw_rank": TrainConfig(features="raw", label="rank", encoder="xsect"),
    "mlp_raw_residual": TrainConfig(),
}

COLUMNS = (
    "name",
    "encoder",
    "features",
    "label",
    "horizon",
    "seeds",
    "periods",
    "names",
    "ic",
    "t",
    "hit",
    "net_per_period",
    "sharpe",
    "cost",
    "momentum_ic",
    "momentum_sharpe",
    "minutes",
    "finished",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the sweep."""
    parser = argparse.ArgumentParser(description="Run the ranker sweep.")
    parser.add_argument("--only", default="", help="Comma-separated run names.")
    parser.add_argument("--list", action="store_true", help="Print the run names.")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(settings.MARKET_DATA_ROOT)
    )
    return parser


# One TSV row for a run and its momentum reference.
def _row(
    name: str,
    config: TrainConfig,
    report: HarnessReport,
    momentum: HarnessReport,
    minutes: float,
) -> str:
    values = (
        name,
        config.encoder,
        config.features,
        config.label,
        config.horizon,
        config.seeds,
        report.count,
        int(np.mean([p.names for p in report.periods])) if report.periods else 0,
        f"{report.mean_ic:.4f}",
        f"{report.ic_tstat:.2f}",
        f"{report.ic_hit_rate:.3f}",
        f"{report.mean_net_return:.5f}",
        f"{report.net_sharpe:.2f}",
        f"{report.total_cost:.4f}",
        f"{momentum.mean_ic:.4f}",
        f"{momentum.net_sharpe:.2f}",
        f"{minutes:.1f}",
        time.strftime("%Y-%m-%d %H:%M"),
    )
    return "\t".join(str(v) for v in values)


# Run the sweep.
def main() -> None:
    """Entry point: run each configuration and append its row to the table."""
    args = build_parser().parse_args()
    if args.list:
        print("\n".join(SWEEP))
        return
    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(SWEEP)
    universe = build_universe()
    learn = tickers_with_role(universe, FOCUS, MEMBER)
    themes = {t: tags for t, tags in theme_map(universe).items() if t in set(learn)}
    store = MarketStore(args.data_dir)
    panel = build_panel(
        store, learn, MARKET_BENCHMARK, themes, asof=args.asof, start=args.start
    )
    # Rows here are measured against the beta-adjusted residual; the earlier
    # sweep.tsv (plain residual) and sweep_themed_only.tsv are kept as history.
    table = args.data_dir / "models" / "sweep_beta.tsv"
    table.parent.mkdir(parents=True, exist_ok=True)
    if not table.exists():
        table.write_text("\t".join(COLUMNS) + "\n", encoding="utf-8")
    print(
        f"panel: {len(panel.dates)} sessions, {len(panel.tickers)} tickers; "
        f"device={args.device}"
    )
    momentum_scores = baselines.momentum(panel)
    extras: dict[str, np.ndarray | None] = {}
    market_extra = load_market_extra(store, panel, args.asof)
    state = "macro on" if market_extra is not None else "no macro series stored"
    print(f"market state: {state}")
    tape = None
    if any(SWEEP[n].encoder == "tape" for n in names):
        tape = load_tape(store, panel, args.asof)
        if tape is None:
            raise SystemExit("no 15-minute bars in the store; run market_intraday")
        covered = np.isfinite(tape).all(axis=(2, 3))
        print(f"tape: {int(covered[-1].sum())} names with a full tape today")
    for name in names:
        config = replace(SWEEP[name], device=args.device)
        started = time.time()
        print(
            f"\n=== {name}: {config.encoder} features={config.features} "
            f"label={config.label} h={config.horizon} seeds={config.seeds}"
        )
        if config.features not in extras:
            try:
                extras[config.features] = load_extra_features(
                    store, panel, config.features, args.asof
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
        result = walk_forward(
            panel,
            config,
            log=print,
            extra=extras[config.features],
            tape=tape,
            market_extra=market_extra,
        )
        report = evaluate_scores(
            result.scores, panel, config.horizon, cost_bps=args.cost_bps
        )
        scored = np.isfinite(result.scores).any(axis=1)
        momentum = evaluate_scores(
            np.where(scored[:, None], momentum_scores, np.nan),
            panel,
            config.horizon,
            cost_bps=args.cost_bps,
        )
        minutes = (time.time() - started) / 60
        row = _row(name, config, report, momentum, minutes)
        with table.open("a", encoding="utf-8") as handle:
            handle.write(row + "\n")
        print(row)
        np.savez_compressed(
            args.data_dir / "models" / f"sweep_{name}.npz",
            scores=result.scores,
            dates=panel.dates,
            tickers=np.asarray(panel.tickers, dtype=object),
        )
    print(f"\ntable: {table}")
    print(table.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
