"""Is there information in an earnings release beyond the five fields the
reader already extracts?

    python -m backend.cli.market_release_eval
    python -m backend.cli.market_release_eval --horizons 20 60 --train 750

The question
------------
The desk's most valuable signal is a language model reading each release
into five categorical fields. A general text model turns the same release
into a 768-wide vector without being told what to look for. If a small
supervised model on that vector predicts the desk's own label better than
the five fields do - or adds to them - the release carries information the
reader is leaving on the table. If it does not, the reader has it.

The measurement
---------------
For every session and name, the vector of the newest release whose
reaction date is on or before the session (`release_text.active_index`),
against the beta-adjusted forward residual the whole desk is measured on,
at twenty and sixty sessions.

Fitted walk-forward with `harness.walk_forward_folds`: a ridge regression
and a gradient-boosted model are fit on the training range's cells, with
the label horizon purged before the test range and standardisation taken
from training cells only, and they score the test range. The out-of-sample
scores are assembled into one matrix and measured by `evaluate_scores`
exactly as every other signal here is. Every comparison is made on the
same cells, so coverage cannot flatter anyone.

  release vector -> ridge          the text alone, linearly
  release vector -> boosted trees  the text alone, nonlinearly
  the sentiment analyst            the five fields the reader extracts
  the desk's score                 everything the desk knows
  the desk + a vote for the text   the incremental test: does adding the
                                   vector's ranking to the desk's summed
                                   conviction raise its rank IC and its
                                   net Sharpe, at three weights

Two things this cannot claim, written before the result is known. The
embedding model was trained on public text that postdates many of these
releases; it cannot know prices, but it is not a point-in-time model, and
a vector could encode what was later said about a company. That caveat
applies equally to the reader. And the supervised layer sees about 5,500
releases across 93 names over six years - enough for a linear model on
768 inputs with ridge, marginal for trees, and the walk-forward will say
which.

Results
-------
3,401 releases over 88 names (five book names have none), nomic-embed
v1.5 at width 768 over the front of each release cut to the server's
2,048-token context - about a quarter of what the tone reader sees.
Seventeen folds at twenty sessions, 160,403 out-of-sample cells; "fresh"
is the 54,029 within twenty sessions of a release.

  horizon 20                        rank IC     t   net Sharpe   fresh IC
  ridge (lambda 100)                 0.0133  1.13       0.31      -0.0012
  boosted trees                      0.0309  1.79       0.37      -0.0164
  the sentiment analyst              0.0310  2.17       0.55       0.0024
  the desk's score                   0.0549  3.37       1.02      -0.0003

  the desk + text (trees) at 0.25    0.0573  3.46       0.95
  the desk + text (trees) at 0.50    0.0590  3.59       0.83
  the desk + text (trees) at 1.00    0.0578  3.46       0.70

  horizon 60
  ridge (lambda 100)                 0.0080  0.39      -0.36      -0.0375
  boosted trees                      0.0168  0.53      -0.04      -0.0285
  the sentiment analyst              0.0478  2.00       0.67       0.0212
  the desk's score                   0.0582  1.99       0.63       0.0795

  the desk + text (trees) at 0.25    0.0600  2.04       0.63
  the desk + text (trees) at 1.00    0.0625  2.08       0.80

Read plainly: the vector carries about as much cross-sectional
information at twenty sessions as the five fields do, and no more. Trees
reach the analyst's rank IC but not its t or its net Sharpe; ridge does
not get close; and on the cells nearest a release, where new information
would show, the text reads zero at both horizons while the desk reads
0.0795 at sixty. Adding a vote for the text to the desk raises rank IC by
a few thousandths and lowers net Sharpe at the horizon the book trades
on, 1.02 to 0.83 at half weight, because the vector's ranking churns. At
sixty sessions the vote helps Sharpe, 0.63 to 0.80, but the text alone is
not significant there, so that is one reading of a noisy sum.

The reader has it. Nothing is changed on this. The bounded caveat stands:
the embedder saw a quarter of each release, and a server context of
8,192 tokens (`VLLM_EMBEDDING_MAX_MODEL_LEN`) would let it read the whole
thing; that is one `embed` run and one more evaluation, not new code.
"""

import argparse

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk.grading import ROTATION_WEIGHT
from backend.market import release_text
from backend.market.harness import evaluate_scores, walk_forward_folds
from backend.market.store import MarketStore

COST_BPS = 10.0
MIN_NAMES = 15
RIDGE_LAMBDAS = (100.0, 1000.0)
TREE_ROUNDS = 300


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Measure the release vectors.")
    parser.add_argument("--horizons", type=int, nargs="+", default=[20, 60])
    parser.add_argument("--train", type=int, default=750)
    parser.add_argument("--test", type=int, default=126)
    parser.add_argument("--embargo", type=int, default=5)
    parser.add_argument("--fresh", type=int, default=20)
    parser.add_argument("--data-dir", default="data/market")
    return parser


# Every stored release vector for the book, with the ticker each belongs to.
def _vectors(store: MarketStore, tickers) -> tuple[list, dict[str, str], int]:
    records: list = []
    ticker_of: dict[str, str] = {}
    width = 0
    for ticker in tickers:
        frame = store.read_frame(release_text.RELEASE_VEC_KIND, ticker)
        if frame is None:
            continue
        for record in release_text.vectors_from_frame(frame[0]):
            records.append(record)
            ticker_of[record.accession] = ticker
            width = len(record.vector)
    return records, ticker_of, width


# Ridge regression in closed form on standardised inputs.
def _ridge(x_fit, y_fit, x_test, lam: float) -> np.ndarray:
    mean, std = x_fit.mean(axis=0), x_fit.std(axis=0) + 1e-8
    zf, zt = (x_fit - mean) / std, (x_test - mean) / std
    y_mean = y_fit.mean()
    gram = zf.T @ zf + lam * np.eye(zf.shape[1])
    beta = np.linalg.solve(gram, zf.T @ (y_fit - y_mean))
    return zt @ beta + y_mean


# Gradient-boosted trees on the raw inputs.
def _trees(x_fit, y_fit, x_test) -> np.ndarray:
    import lightgbm as lgb

    params = {
        "objective": "regression",
        "learning_rate": 0.03,
        "num_leaves": 15,
        "min_data_in_leaf": 100,
        "feature_fraction": 0.3,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "lambda_l2": 10.0,
        "verbosity": -1,
    }
    booster = lgb.train(
        params, lgb.Dataset(x_fit, label=y_fit), num_boost_round=TREE_ROUNDS
    )
    return booster.predict(x_test)


# Fit walk-forward and return out-of-sample (T, N) score matrices, one per
# model, NaN wherever a cell was never in a test range or had no release.
def _fitted(vectors, index, label, folds, models: dict) -> dict[str, np.ndarray]:
    rows, names = index.shape
    out = {name: np.full((rows, names), np.nan) for name in models}
    has = (index >= 0) & np.isfinite(label)
    for train_range, test_range in folds:
        fit_mask = np.zeros_like(has)
        fit_mask[train_range.start : train_range.stop] = has[
            train_range.start : train_range.stop
        ]
        test_mask = np.zeros_like(has)
        test_mask[test_range.start : test_range.stop] = (
            index[test_range.start : test_range.stop] >= 0
        )
        ft, fn = np.nonzero(fit_mask)
        tt, tn = np.nonzero(test_mask)
        if len(ft) < 500 or not len(tt):
            continue
        x_fit, y_fit = vectors[index[ft, fn]], label[ft, fn]
        x_test = vectors[index[tt, tn]]
        for name, fit in models.items():
            out[name][tt, tn] = fit(x_fit, y_fit, x_test)
    return out


# Rank IC and net Sharpe of a score matrix on the book, on given cells only.
def _measure(scores, cells, panel, horizon) -> tuple[float, float, float]:
    masked = np.where(cells, scores, np.nan)
    r = evaluate_scores(masked, panel, horizon, cost_bps=COST_BPS, min_names=MIN_NAMES)
    return r.mean_ic, r.ic_tstat, r.net_sharpe


# Cross-sectional rank in [0, 1] per session, NaN preserved.
def _ranks(scores: np.ndarray) -> np.ndarray:
    out = np.full(scores.shape, np.nan)
    for t in range(scores.shape[0]):
        known = np.isfinite(scores[t])
        if known.sum() >= 2:
            order = scores[t, known].argsort().argsort()
            out[t, known] = order / (known.sum() - 1)
    return out


# The desk's summed conviction, rebuilt so a vote can be added to it.
def _summed(report, extra: np.ndarray | None, weight: float) -> np.ndarray:
    total = np.zeros(report.scores.shape)
    for opinion in report.opinions.values():
        total = total + np.nan_to_num(opinion.conviction())
    total = total + ROTATION_WEIGHT * np.nan_to_num(report.regime.rotation.conviction())
    if extra is not None and weight:
        centred = np.clip((extra - 0.5) * 2.0, -1.0, 1.0)
        total = total + weight * np.nan_to_num(
            np.sign(centred) * np.abs(centred) ** 0.5
        )
    return total


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    store = MarketStore(args.data_dir)
    report = trading_desk.run(store)
    panel = report.panel
    tickers = tuple(t for t in panel.tickers if t in report.sides)
    records, ticker_of, width = _vectors(store, tickers)
    if not records:
        raise SystemExit("no release vectors stored; run market_release_text embed")
    vectors = np.array([r.vector for r in records], dtype=np.float32)
    index, since = release_text.active_index(
        panel.dates, panel.tickers, records, ticker_of
    )
    in_book = np.array([t in report.sides for t in panel.tickers])
    index = np.where(in_book[None, :], index, -1)
    covered = index >= 0
    print(
        f"{len(records):,} release vectors of width {width} over "
        f"{len(set(ticker_of.values()))} names; a vector on "
        f"{covered[-500:].mean():.0%} of book cells in the last 500 sessions"
    )

    models = {
        f"ridge (lambda {int(lam)})": (lambda a, b, c, lam=lam: _ridge(a, b, c, lam))
        for lam in RIDGE_LAMBDAS
    }
    models["boosted trees"] = _trees

    for horizon in args.horizons:
        label = panel.forward_residual(horizon)
        folds = walk_forward_folds(
            len(panel.dates), args.train, args.test, horizon, embargo=args.embargo
        )
        fitted = _fitted(vectors, index, label, list(folds), models)
        cells = np.isfinite(next(iter(fitted.values()))) & in_book[None, :]
        fresh = cells & (since >= 0) & (since <= args.fresh)
        print(
            f"\n=== horizon {horizon}: {int(cells.sum()):,} out-of-sample cells, "
            f"{int(fresh.sum()):,} within {args.fresh} sessions of a release ==="
        )
        print(
            f"{'score':40} {'rank IC':>9} {'t':>7} {'net Sharpe':>11}   "
            f"{'fresh IC':>9} {'t':>7}"
        )
        rows = list(fitted.items()) + [
            (
                "the sentiment analyst (five fields)",
                report.opinions["sentiment"].ranks(),
            ),
            ("the desk's score", report.scores),
        ]
        for name, scores in rows:
            ic, t, sh = _measure(scores, cells, panel, horizon)
            fic, ft, _ = _measure(scores, fresh, panel, horizon)
            print(
                f"{name:40} {ic:+9.4f} {t:+7.2f} {sh:+11.2f}   {fic:+9.4f} {ft:+7.2f}"
            )
        best_name = max(
            fitted, key=lambda k: _measure(fitted[k], cells, panel, horizon)[0]
        )
        text_rank = _ranks(fitted[best_name])
        print(f"\nthe desk with a vote for the text ({best_name}), same cells:")
        print(f"{'weight':40} {'rank IC':>9} {'t':>7} {'net Sharpe':>11}")
        for weight in (0.0, 0.25, 0.5, 1.0):
            ic, t, sh = _measure(
                _summed(report, text_rank, weight), cells, panel, horizon
            )
            label_ = (
                "the desk as it stands" if not weight else f"text weighted {weight:.2f}"
            )
            print(f"{label_:40} {ic:+9.4f} {t:+7.2f} {sh:+11.2f}")


if __name__ == "__main__":
    main()
