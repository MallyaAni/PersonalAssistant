"""Learned combinations of the analysts against the rule: linear, pairs, a network.

    python -m backend.cli.market_interactions
    python -m backend.cli.market_interactions --no-gap

The claim
---------
The desk's grade is a fixed rule: votes, thresholds, a veto. A review
asked that combinations be tested before networks are ruled out: a
regularised model that learns a few interactions, then a small network
on the same inputs and the same test, and the veto itself as a
candidate rather than a law. Gu, Kelly and Xiu attribute the gains of
trees and networks to nonlinear interactions; this is the test on the
desk's own inputs.

The inputs, per session and name, all known at the close
---------------------------------------------------------
The five analysts' convictions (fundamental, technical, sentiment,
value, rotation; -1 to +1), the twenty-session residual momentum (the
tape improving), sessions since the last report, and the gap between
the learner's expected growth and the growth the price implies from
`market_expectations` (off with --no-gap).

The models, walk-forward by year
--------------------------------
  linear        ridge on the eight inputs
  interactions  ridge on the inputs and every pairwise product
  network       two hidden layers of sixteen, tanh, weight decay, early
                stopping on the last tenth of the training window
Each year's model is trained on sessions whose twenty-session label
ends before that year, so no label reaches into the test year, and
scored on the year it never saw. The label is the beta-adjusted
twenty-session residual.

The measurement
---------------
Rank IC by year against the desk's own score, then the book under its
own rules: the rule; the rule with each model's score as the tie-break
within the grades; each model alone selecting the book (A for its top
fifth, B for the next, no veto); and the rule with the veto off. All
on the scorecard, matched to the rule's volatility.

Results, 2026-09-08
-------------------
Rank IC by year, 2019 to 2026, twenty sessions, walk-forward:

| score            | mean  | years positive |
| the desk's score | +0.055 | 7 of 8        |
| linear           | +0.003 | 3 of 8        |
| interactions     | +0.040 | 7 of 8        |
| network          | +0.023 | 7 of 8        |

Nothing learned beats the rule's own score at ranking, and the
interactions model comes closest. In the book from 2021-06, costs
included, the rule earns +35.4% a year (Sharpe 1.85, worst -19.0%).
Every learned score does worse both ways: as the tie-break inside the
grades, +28.0% to +29.8% (at the rule's volatility +33.3% to +34.2%),
with turnover up a fifth because the scores reorder the book every
session; alone selecting the book, +10.0% to +13.4%, Sharpe 0.8 to
1.1. The rule's votes and thresholds are the selection; a learned
ranking on the same inputs is not a better one on ninety names, which
is the network's third loss here on three different inputs (charts,
intraday bars, the analysts).

The veto is the finding. With it off, the book earns +39.5% a year
(Sharpe 1.87, worst -20.8%, turnover 6.3x against 5.9x), +36.2% at the
rule's volatility, and beats the rule in five years of six. The veto
was added after one trade (IREN, January 2026) and measured to lift the
A grade's return per twenty sessions; inside the book it costs about a
point a year at matched risk. Not adopted here: one challenger at a
time keeps the forward record readable, and the expectations gap is
already running. The veto is the next challenger.
"""

import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import grading, scorecard, simulate
from backend.agents.trading.desk.grading import Graded
from backend.market.harness import evaluate_scores
from backend.market.store import MarketStore

ANALYSTS = ("fundamental", "technical", "sentiment", "value", "rotation")
HORIZON = 20
FIRST_TEST_YEAR = 2019
MIN_TRAIN_YEARS = 3


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument(
        "--no-gap", action="store_true", help="leave the expectations gap out"
    )
    parser.add_argument("--book-since", default="2021-06-01")
    parser.add_argument("--ridge", type=float, default=10.0)
    return parser


# The inputs, (T, N, K), and their names.
def inputs(report, store, dates, with_gap: bool) -> tuple[np.ndarray, list[str]]:
    """Return the input block and the names of its columns."""
    panel = report.panel
    cols = []
    names = []
    for analyst in ANALYSTS:
        opinion = report.opinions.get(analyst) or (
            report.regime.rotation if analyst == "rotation" else None
        )
        if opinion is None:
            continue
        cols.append(opinion.conviction())
        names.append(analyst)
    adj = panel.adj_close
    bench = adj[:, panel.index(panel.benchmark)]
    beta = panel.rolling_beta(120)
    mom = np.full(adj.shape, np.nan)
    with np.errstate(all="ignore"):
        mom[20:] = (
            np.log(adj[20:] / adj[:-20])
            - beta[20:] * np.log(bench[20:] / bench[:-20])[:, None]
        )
    cols.append(mom)
    names.append("momentum_20")
    fund = report.opinions["fundamental"].evidence
    since = np.asarray(
        fund.get("sessions_since_earnings", np.full(adj.shape, np.nan)), dtype=float
    )
    cols.append(np.clip(since, 0, 120) / 120.0)
    names.append("since_report")
    if with_gap:
        cols.append(_gap(store, panel, dates))
        names.append("expectations_gap")
    return np.stack(cols, axis=2), names


# The expectations gap from the study, on the book's panel.
def _gap(store, book, dates) -> np.ndarray:
    from backend.cli import market_expectations as mx

    panel, sector = mx._universe_panel(store, False)
    udates = [d.astype("datetime64[D]").astype(object) for d in panel.dates]
    records, quarters, reactions = mx._records(store, panel, udates)
    fund, fidx, tone, tidx, _beta, mom, ratios = mx._features(store, panel, records)
    feats, implied = mx._block(panel, sector, fund, fidx, tone, tidx, mom, ratios)
    x, y, meta = mx._dataset(panel, udates, quarters, reactions, feats)
    meta_year = np.array([m[2] for m in meta])
    years = sorted(set(meta_year))
    expected = mx._carried(udates, x, y, meta_year, years, feats, 3)
    with np.errstate(all="ignore"):
        gap = expected - implied
    return mx._onto_book(gap, panel, book, udates)


# Training rows for a test year: sessions whose label ends before it.
def training_mask(years: np.ndarray, year: int, horizon: int) -> np.ndarray:
    """Return (T,) True where a session's label is fully before `year`."""
    before = years < year
    out = before.copy()
    idx = np.flatnonzero(before)
    if len(idx):
        out[idx[-horizon:]] = False
    return out


def _standardise(x_train, x_test):
    mean = np.nanmean(x_train, axis=0)
    std = np.nanstd(x_train, axis=0)
    std = np.where(std > 0, std, 1.0)
    return (np.nan_to_num(x_train) - mean) / std, (np.nan_to_num(x_test) - mean) / std


def _pairs(x: np.ndarray) -> np.ndarray:
    k = x.shape[1]
    parts = [x]
    for i in range(k):
        for j in range(i + 1, k):
            parts.append((x[:, i] * x[:, j])[:, None])
    return np.concatenate(parts, axis=1)


def _ridge(x_train, y_train, x_test, lam: float) -> np.ndarray:
    a, b = _standardise(x_train, x_test)
    a1 = np.concatenate([a, np.ones((len(a), 1))], axis=1)
    b1 = np.concatenate([b, np.ones((len(b), 1))], axis=1)
    reg = lam * np.eye(a1.shape[1])
    reg[-1, -1] = 0.0
    w = np.linalg.solve(a1.T @ a1 + reg, a1.T @ y_train)
    return b1 @ w


def _holdout(x_train, y_train):
    """Return (train, validation) for a network's early stopping.

    The validation is the most recent tenth of the rows, with the horizon of
    sessions before it purged from training, so no training label reaches
    into the validation window.
    """
    cut = int(len(x_train) * 0.9)
    xa, ya = x_train[:cut], y_train[:cut]
    xv, yv = x_train[cut:], y_train[cut:]
    purge = min(HORIZON, len(xa))
    if purge:
        xa, ya = xa[:-purge], ya[:-purge]
    return xa, ya, xv, yv


def _network(x_train, y_train, x_test, seed: int = 0) -> np.ndarray:
    import torch

    torch.manual_seed(seed)
    # The hold-out is split before anything is normalised, the horizon of
    # sessions before it is purged from training (their twenty-session
    # labels reach into it), and the features are standardised with the
    # purged training set's statistics alone - so the validation sees
    # normalisation it had no hand in and labels no training row overlaps.
    xa, ya, xv, yv = _holdout(x_train, y_train)
    a, v = _standardise(xa, xv)
    _, b = _standardise(xa, x_test)
    xa, ya = torch.tensor(a, dtype=torch.float32), torch.tensor(
        ya, dtype=torch.float32
    )
    xv, yv = torch.tensor(v, dtype=torch.float32), torch.tensor(
        yv, dtype=torch.float32
    )
    net = torch.nn.Sequential(
        torch.nn.Linear(a.shape[1], 16),
        torch.nn.Tanh(),
        torch.nn.Linear(16, 16),
        torch.nn.Tanh(),
        torch.nn.Linear(16, 1),
    )
    opt = torch.optim.Adam(net.parameters(), lr=1e-3, weight_decay=1e-3)
    best, best_state, patience = float("inf"), None, 0
    for _epoch in range(300):
        perm = torch.randperm(len(xa))
        for i in range(0, len(xa), 1024):
            idx = perm[i : i + 1024]
            opt.zero_grad()
            loss = torch.nn.functional.mse_loss(net(xa[idx]).squeeze(1), ya[idx])
            loss.backward()
            opt.step()
        with torch.no_grad():
            val = float(torch.nn.functional.mse_loss(net(xv).squeeze(1), yv))
        if val < best - 1e-7:
            best, patience = val, 0
            best_state = {k: v.clone() for k, v in net.state_dict().items()}
        else:
            patience += 1
            if patience >= 20:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    with torch.no_grad():
        return net(torch.tensor(b, dtype=torch.float32)).squeeze(1).numpy()


# Walk-forward scores for one model, (T, N).
def walk_forward(x, label, years, in_book, fit) -> np.ndarray:
    """Return (T, N) out-of-sample scores from `fit(x_train, y_train, x_test)`."""
    rows, cols, _k = x.shape
    out = np.full((rows, cols), np.nan)
    for year in sorted(set(years)):
        if year < FIRST_TEST_YEAR:
            continue
        train_rows = training_mask(years, year, HORIZON)
        if len(set(years[train_rows])) < MIN_TRAIN_YEARS:
            continue
        test_rows = years == year
        tr = (
            train_rows[:, None]
            & in_book[None, :]
            & np.isfinite(label)
            & np.isfinite(x).all(axis=2)
        )
        te = test_rows[:, None] & in_book[None, :] & np.isfinite(x).all(axis=2)
        if tr.sum() < 500 or not te.any():
            continue
        pred = fit(x[tr], label[tr], x[te])
        out[te] = pred
    return out


def _ic_by_year(scores, panel, years) -> dict[int, float]:
    out = {}
    for year in sorted(set(years)):
        rows = years == year
        if rows.sum() < 60 or not np.isfinite(scores[rows]).any():
            continue
        sub = replace(
            panel,
            dates=panel.dates[rows],
            open=panel.open[rows],
            high=panel.high[rows],
            low=panel.low[rows],
            close=panel.close[rows],
            adj_close=panel.adj_close[rows],
            volume=panel.volume[rows],
        )
        ics = evaluate_scores(
            scores[rows], sub, HORIZON, exclude=(panel.benchmark,)
        ).defined_ics
        if len(ics):
            out[year] = float(ics.mean())
    return out


# A report whose selection comes from `scores` alone: A for the top fifth
# of the book each session, B for the next, C otherwise, no veto.
def selected_by(report, scores: np.ndarray, in_book: np.ndarray):
    rows, cols = scores.shape
    grades = np.zeros((rows, cols), dtype=int)
    for t in range(rows):
        row = np.where(in_book & np.isfinite(scores[t]), scores[t], np.nan)
        known = np.isfinite(row)
        if known.sum() < 10:
            continue
        top = np.nanquantile(row, 0.8)
        mid = np.nanquantile(row, 0.6)
        grades[t] = np.where(
            known & (row >= top),
            grading.ORDINAL[grading.A],
            np.where(known & (row >= mid), grading.ORDINAL[grading.B], 0),
        )
    graded = Graded(grades, grades.astype(float), report.graded.stances, None)
    return replace(
        report, graded=graded, scores=np.where(np.isfinite(scores), scores, -np.inf)
    )


def main() -> None:
    """Run the study."""
    args = build_parser().parse_args()
    store = MarketStore(Path(args.root))
    report = trading_desk.run(store)
    panel = report.panel
    dates = panel.dates
    years = np.array([int(str(d)[:4]) for d in dates])
    in_book = np.array([t in report.sides for t in panel.tickers])
    x, names = inputs(report, store, dates, not args.no_gap)
    label = panel.forward_residual(HORIZON)
    print(f"book of {int(in_book.sum())} names, inputs: {', '.join(names)}")
    models = {
        "linear": lambda a, b, c: _ridge(a, b, c, args.ridge),
        "interactions": lambda a, b, c: _ridge(_pairs(a), b, _pairs(c), args.ridge),
        "network": _network,
    }
    scores = {
        name: walk_forward(x, label, years, in_book, fit)
        for name, fit in models.items()
    }
    print(
        f"\n{'rank IC by year, twenty sessions':20} "
        + " ".join(f"{y:>7}" for y in range(FIRST_TEST_YEAR, years.max() + 1))
    )
    table = {"the desk's score": _ic_by_year(report.scores, panel, years)}
    table.update({name: _ic_by_year(s, panel, years) for name, s in scores.items()})
    for name, values in table.items():
        cells = " ".join(
            f"{values[y]:+7.3f}" if y in values else f"{'':>7}"
            for y in range(FIRST_TEST_YEAR, years.max() + 1)
        )
        mean = (
            np.mean([v for y, v in values.items() if y >= FIRST_TEST_YEAR])
            if values
            else float("nan")
        )
        print(f"{name:20} {cells}   mean {mean:+.3f}")
    start = date.fromisoformat(args.book_since)
    results = {"the rule": simulate.run(report, since=start, use_exits=False)}
    no_veto = trading_desk.blended(report.opinions)
    graded = grading.grade(
        report.opinions["fundamental"],
        report.opinions["technical"],
        report.opinions["sentiment"],
        report.regime.rotation,
        report.opinions["value"],
        grading.ANALYST_WEIGHTS,
        veto=False,
    )
    results["the rule, veto off"] = simulate.run(
        replace(report, graded=graded, scores=graded.as_scores(no_veto)),
        since=start,
        use_exits=False,
    )
    for name, s in scores.items():
        filled = np.where(np.isfinite(s), s, report.scores)
        results[f"rule, {name} as tie-break"] = simulate.run(
            replace(report, scores=filled), since=start, use_exits=False
        )
        results[f"{name} alone selects"] = simulate.run(
            selected_by(report, s, in_book), since=start, use_exits=False
        )
    print(f"\nthe book from {args.book_since}:")
    print(scorecard.render(results, store))


if __name__ == "__main__":
    main()
