"""Train the learned ranker walk-forward and report it beside the baselines.

    python -m backend.cli.market_train
    python -m backend.cli.market_train --encoder gru --epochs 12 --device cuda
    python -m backend.cli.market_train --horizon 20 --train-size 500 --test-size 63

Prints the baseline rows and the model row from the same harness on the
same panel, then where the focus names rank today under the model. The
out-of-sample score matrix is saved beside the store so a run can be
inspected without retraining.
"""

import argparse
import math
from datetime import date
from pathlib import Path

import numpy as np

from backend.config.settings import settings
from backend.market import baselines
from backend.market.harness import evaluate_scores
from backend.market.model import (
    TrainConfig,
    load_extra_features,
    score_today,
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


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the training run."""
    parser = argparse.ArgumentParser(description="Train and measure the ranker.")
    parser.add_argument(
        "--encoder",
        choices=("mlp", "gru", "xsect", "master", "lgbm", "chart_cnn"),
        default="mlp",
    )
    parser.add_argument(
        "--features",
        choices=(
            "raw",
            "alpha",
            "alpha+edgar",
            "raw+edgar",
            "alpha+tone",
            "alpha+edgar+tone",
            "alpha+edgar+technical",
            "alpha+edgar+technical+tone",
            "alpha+edgar+technical+intraday",
        ),
        default="raw",
    )
    parser.add_argument("--label", choices=("residual", "rank"), default="residual")
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--window-size", type=int, default=20)
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--train-size", type=int, default=750)
    parser.add_argument("--test-size", type=int, default=125)
    parser.add_argument("--embargo", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(settings.MARKET_DATA_ROOT)
    )
    parser.add_argument("--no-today", action="store_true", help="Skip today's ranks.")
    return parser


# A number for a fixed-width table, or a dash when it is not defined.
def _fmt(value: float, width: int = 8, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-".rjust(width)
    return f"{value:{width}.{digits}f}"


# One report row.
def _row(name: str, report) -> str:
    return (
        f"{name:28} {report.count:7d} {_fmt(report.mean_ic)} "
        f"{_fmt(report.ic_tstat, digits=2)} {_fmt(report.ic_hit_rate)} "
        f"{_fmt(report.mean_net_return, digits=4)} {_fmt(report.net_sharpe, digits=2)} "
        f"{_fmt(report.total_cost, digits=4)}"
    )


# Run the training and print the comparison.
def main() -> None:
    """Entry point: walk-forward train, compare with baselines, rank the focus names."""
    args = build_parser().parse_args()
    config = TrainConfig(
        window_size=args.window_size,
        horizon=args.horizon,
        train_size=args.train_size,
        test_size=args.test_size,
        embargo=args.embargo,
        encoder=args.encoder,
        features=args.features,
        label=args.label,
        seeds=args.seeds,
        hidden=args.hidden,
        epochs=args.epochs,
        seed=args.seed,
        device=args.device,
    )
    universe = build_universe()
    learn = tickers_with_role(universe, FOCUS, MEMBER)
    themes = {t: tags for t, tags in theme_map(universe).items() if t in set(learn)}
    store = MarketStore(args.data_dir)
    panel = build_panel(
        store, learn, MARKET_BENCHMARK, themes, asof=args.asof, start=args.start
    )
    print(
        f"panel: {len(panel.dates)} sessions {panel.dates[0]}..{panel.dates[-1]}, "
        f"{len(panel.tickers)} tickers; encoder={config.encoder} "
        f"window={config.window_size} horizon={config.horizon} device={config.device}"
    )
    try:
        extra = load_extra_features(store, panel, config.features, args.asof)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    result = walk_forward(panel, config, log=print, extra=extra)

    # Baselines are measured only where the model was scored, so the rows
    # are comparable session for session.
    scored = np.isfinite(result.scores).any(axis=1)
    print(
        f"\n{'signal':28} {'periods':>7} {'IC':>8} {'t':>8} {'hit':>8} "
        f"{'net/prd':>8} {'sharpe':>8} {'cost':>8}"
    )
    for name, matrix in baselines.all_baselines(panel).items():
        masked = np.where(scored[:, None], matrix, np.nan)
        print(
            _row(
                name,
                evaluate_scores(masked, panel, config.horizon, cost_bps=args.cost_bps),
            )
        )
    model_report = evaluate_scores(
        result.scores, panel, config.horizon, cost_bps=args.cost_bps
    )
    print(_row(f"ranker_{config.encoder}", model_report))
    print(
        "folds: "
        + ", ".join(
            f"val IC {f.best_validation_ic:.3f} ({f.epochs_run} ep)"
            for f in result.folds
        )
    )

    out_dir = args.data_dir / "models"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = (
        out_dir / f"ranker_{config.encoder}_h{config.horizon}_{panel.dates[-1]}.npz"
    )
    np.savez_compressed(
        out_path,
        scores=result.scores,
        dates=panel.dates,
        tickers=np.asarray(panel.tickers, dtype=object),
    )
    print(f"out-of-sample scores saved to {out_path}")

    if not args.no_today:
        today = score_today(panel, config, extra=extra)
        ranks = baselines.percentile_rank(today[None, :])[0]
        focus = [t for t in tickers_with_role(universe, FOCUS) if t in panel.tickers]
        print(f"\nranker on {panel.dates[-1]} (percentile rank, 1 = strongest):")
        print(
            "  "
            + "  ".join(
                f"{t}={_fmt(ranks[panel.index(t)], width=5, digits=2)}" for t in focus
            )
        )
        finite = np.flatnonzero(np.isfinite(today))
        order = finite[np.argsort(-today[finite])]
        top = [panel.tickers[i] for i in order[:10]]
        bottom = [panel.tickers[i] for i in order[::-1][:10]]
        print(f"  top 10: {' '.join(top)}")
        print(f"  bottom 10: {' '.join(bottom)}")


if __name__ == "__main__":
    main()
