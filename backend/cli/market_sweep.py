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
from backend.market.model import TrainConfig, walk_forward
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
    table = args.data_dir / "models" / "sweep.tsv"
    table.parent.mkdir(parents=True, exist_ok=True)
    if not table.exists():
        table.write_text("\t".join(COLUMNS) + "\n", encoding="utf-8")
    print(
        f"panel: {len(panel.dates)} sessions, {len(panel.tickers)} tickers; "
        f"device={args.device}"
    )
    momentum_scores = baselines.momentum(panel)
    for name in names:
        config = replace(SWEEP[name], device=args.device)
        started = time.time()
        print(
            f"\n=== {name}: {config.encoder} features={config.features} "
            f"label={config.label} h={config.horizon} seeds={config.seeds}"
        )
        result = walk_forward(panel, config, log=print)
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
