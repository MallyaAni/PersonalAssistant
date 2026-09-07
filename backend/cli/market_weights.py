"""Should the analysts be weighted equally? Measured, not assumed.

    python -m backend.cli.market_weights
    python -m backend.cli.market_weights --horizons 20 60 --shrink 0 1 10 100

The question
------------
The desk's score is the sum of its analysts' convictions at equal weight
(rotation at half). Nothing measured that. The analysts are not equally
good - valuation is the strongest at sixty sessions and tone at twenty,
and the technical analyst is weakest at both - so a fixed equal weight is
an assumption wearing a rule's clothes.

The suggestion was a network that learns the weights. The networks tried
here could not beat the rule, and the reason was sample size: about 65
independent periods against thousands of parameters. But five weights are
not thousands. A linear combiner over the five convictions, fit
walk-forward with the label horizon purged and shrunk toward the equal
weights it is replacing, is the smallest model that can answer the
question, and it is the one this runs.

The measurement
---------------
For every session, the five convictions (four analysts and rotation) and
the beta-adjusted forward residual. Walk-forward folds from the harness,
ridge with the penalty pulling the weights toward the equal-weight vector
rather than toward zero - so with infinite shrinkage it *is* the desk, and
with none it is unconstrained least squares. The fitted weights score the
test range; the out-of-sample scores are measured by `evaluate_scores`
against the desk's own equal-weight score on the same cells.

Also reported: the fitted weights per fold, so a weight that changes sign
across folds is seen for what it is - noise - rather than adopted.

Results
-------
Seventeen folds at twenty sessions, sixteen at sixty, 750 training
sessions each, a five-session embargo. `shrink` is in units of the data's
own scale; 100 is nearly the desk, 0 is least squares.

  horizon 20                  rank IC     t   net Sharpe
  equal weights (the desk)     0.0526  3.30   1.03
  fitted, shrink 100           0.0528  3.31   1.07
  fitted, shrink 10            0.0532  3.36   1.09
  fitted, shrink 1             0.0536  3.59   1.08
  fitted, shrink 0             0.0382  2.53   0.51

  horizon 60
  equal weights (the desk)     0.0526  1.81   0.65
  fitted, shrink 100           0.0531  1.83   0.67
  fitted, shrink 10            0.0544  1.90   0.67
  fitted, shrink 1             0.0631  2.25   0.78
  fitted, shrink 0             0.0402  1.39   0.54

The data wants unequal weights and wants them stably. At shrink 1 every
fold agrees on every sign and the spread across folds is a few hundredths:
value 0.60, fundamental 0.50, sentiment 0.42, technical 0.38, rotation
0.30 - the same ordering the analysts' individual measurements gave. At
the desk's own horizon the gain is inside the noise, 0.0526 to 0.0536. At
sixty sessions it is not: 0.0526 to 0.0631 and net Sharpe 0.65 to 0.78.

The row that matters is the last in each table. Least squares - five free
parameters, nothing more - loses to equal weights at both horizons, and
by a lot: 0.0382 against 0.0526 at twenty. Five parameters overfit this
sample. That is the sample-size argument made concrete, and it is the
reason no network over these same inputs has beaten the rule: what wins
is the rule plus a nudge the data can justify, not a fit.

The weights are not changed on this. Choosing the shrinkage by reading
these out-of-sample numbers is itself a fit, and the gain at the horizon
the book trades on is one thousandth of rank IC. The evidence for
reweighting toward value and away from the tape is real and is recorded;
the forward paper record is the place to see whether the longer horizon's
gain is worth acting on.
"""

import argparse

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk.grading import ROTATION_WEIGHT
from backend.market.harness import evaluate_scores, walk_forward_folds
from backend.market.store import MarketStore

ANALYSTS = ("fundamental", "technical", "sentiment", "value", "rotation")
COST_BPS = 10.0
MIN_NAMES = 15


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Weight the analysts by evidence.")
    parser.add_argument("--horizons", type=int, nargs="+", default=[20, 60])
    parser.add_argument(
        "--shrink", type=float, nargs="+", default=[0.0, 1.0, 10.0, 100.0]
    )
    parser.add_argument("--train", type=int, default=750)
    parser.add_argument("--test", type=int, default=126)
    parser.add_argument("--embargo", type=int, default=5)
    parser.add_argument("--data-dir", default="data/market")
    return parser


# The (T, N, 5) conviction block and the equal weights the desk uses.
def _convictions(report) -> tuple[np.ndarray, np.ndarray]:
    blocks = []
    for name in ANALYSTS:
        source = report.regime.rotation if name == "rotation" else report.opinions[name]
        blocks.append(np.nan_to_num(source.conviction()))
    prior = np.array([ROTATION_WEIGHT if n == "rotation" else 1.0 for n in ANALYSTS])
    return np.stack(blocks, axis=-1), prior


# Ridge toward a prior weight vector rather than toward zero: with penalty
# `shrink` the solution is the equal-weight desk plus whatever the data can
# justify moving it by.
def _fit(x, y, prior: np.ndarray, shrink: float) -> np.ndarray:
    gram = x.T @ x
    scale = np.trace(gram) / len(prior)  # so `shrink` is in units of the data
    penalty = shrink * scale * np.eye(len(prior))
    return np.linalg.solve(gram + penalty, x.T @ y + penalty @ prior)


# Out-of-sample scores from walk-forward fits, and the weights per fold.
def _fitted(conv, label, in_book, folds, prior, shrink):
    rows, names, _ = conv.shape
    scores = np.full((rows, names), np.nan)
    weights = []
    has = np.isfinite(label) & in_book[None, :]
    for train_range, test_range in folds:
        mask = np.zeros_like(has)
        mask[train_range.start : train_range.stop] = has[
            train_range.start : train_range.stop
        ]
        ft, fn = np.nonzero(mask)
        if len(ft) < 500:
            continue
        w = _fit(conv[ft, fn], label[ft, fn], prior, shrink)
        weights.append(w)
        block = slice(test_range.start, test_range.stop)
        scores[block] = conv[block] @ w
    return scores, np.array(weights)


# Rank IC and net Sharpe on given cells.
def _measure(scores, cells, panel, horizon):
    r = evaluate_scores(
        np.where(cells, scores, np.nan),
        panel,
        horizon,
        cost_bps=COST_BPS,
        min_names=MIN_NAMES,
    )
    return r.mean_ic, r.ic_tstat, r.net_sharpe


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    report = trading_desk.run(MarketStore(args.data_dir))
    panel = report.panel
    in_book = np.array([t in report.sides for t in panel.tickers])
    in_book[panel.index(panel.benchmark)] = False
    conv, prior = _convictions(report)
    equal = conv @ prior
    for horizon in args.horizons:
        label = panel.forward_residual(horizon)
        folds = list(
            walk_forward_folds(
                len(panel.dates), args.train, args.test, horizon, args.embargo
            )
        )
        print(f"\n=== horizon {horizon}, {len(folds)} folds ===")
        print(f"{'weights':44} {'rank IC':>9} {'t':>7} {'net Sharpe':>11}")
        cells = None
        for shrink in sorted(args.shrink, reverse=True):
            scores, weights = _fitted(conv, label, in_book, folds, prior, shrink)
            if cells is None:
                cells = np.isfinite(scores) & in_book[None, :]
                ic, t, sh = _measure(equal, cells, panel, horizon)
                print(
                    f"{'equal weights (the desk)':44} {ic:+9.4f} {t:+7.2f} {sh:+11.2f}"
                )
            ic, t, sh = _measure(scores, cells, panel, horizon)
            print(f"{f'fitted, shrink {shrink:g}':44} {ic:+9.4f} {t:+7.2f} {sh:+11.2f}")
            if len(weights):
                mean, sd = weights.mean(axis=0), weights.std(axis=0)
                signs = (np.sign(weights) == np.sign(mean)).mean(axis=0)
                print(
                    "    "
                    + "  ".join(
                        f"{n[:5]} {m:+.2f}±{s:.2f} ({int(round(g * 100))}% same sign)"
                        for n, m, s, g in zip(ANALYSTS, mean, sd, signs, strict=True)
                    )
                )


if __name__ == "__main__":
    main()
