"""Train the chart network and measure it where the desk is measured.

    python -m backend.cli.market_charts
    python -m backend.cli.market_charts --days 20 --years 2023 2024 2025 2026
    python -m backend.cli.market_charts --seeds 2 --max-epochs 10 --show IREN 2026-09-01

What it does
------------
Jiang, Kelly and Xiu's image model (`backend/market/charts.py`), trained
on every name in the universe with daily bars, walk-forward by year: the
network is fit on every session before the test year, thirty percent of
those held out at random for early stopping as in the paper, and it
scores every session of the test year it never saw. Its output is the
probability that the next `horizon` sessions' return is positive.

That probability is then measured exactly as the desk's analysts are:
as a cross-sectional score against the beta-adjusted forward residual,
with the harness's rank IC, t and net Sharpe, on the whole universe and
on the book; beside momentum and short-term reversal on the same cells,
which is the comparison the paper makes; and on the confirmed dips of
`market_dip`, which is the question that prompted all this - does a
model that reads the chart know which dips to buy?

`--show TICKER DATE` prints the model's probability for one name on one
session, from the fold that never saw that year.

The paper's numbers, for the record: on the US cross-section 2001-2019
the twenty-day image predicting the twenty-day return earned an
equal-weight long-short Sharpe of about 1.3 at a quarterly hold, more
at a weekly one, against roughly half that for momentum and reversal.
The cross-section here is five hundred large names over ten years, the
years the paper's advantage was already thinning, so the honest prior
is a smaller number.

Results
-------
Recorded below once the run is read.
"""

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import torch
from torch import nn

from backend.market import baselines, charts
from backend.market.harness import evaluate_scores
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.universe import (
    FOCUS,
    MARKET_BENCHMARK,
    MEMBER,
    book_sides,
    build_universe,
    theme_map,
    tickers_with_role,
)

BATCH = 128
RENDER_CHUNK = 8_192
LEARNING_RATE = 1e-5
PATIENCE = 2
VALIDATION = 0.3
COST_BPS = 10.0
MIN_NAMES = 15
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Train and measure the chart network.")
    parser.add_argument("--days", type=int, choices=(5, 20, 60), default=20)
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument(
        "--years", type=int, nargs="+", default=[2022, 2023, 2024, 2025, 2026]
    )
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--max-epochs", type=int, default=20)
    parser.add_argument(
        "--train-fraction",
        type=float,
        default=1.0,
        help="subsample the training images",
    )
    parser.add_argument("--show", nargs=2, metavar=("TICKER", "DATE"), default=None)
    parser.add_argument("--data-dir", default="data/market")
    return parser


# The universe on one panel and the arrays the images are drawn from.
def _panel(store):
    universe = build_universe()
    names = tickers_with_role(universe, MEMBER, FOCUS)
    themes = {t: g for t, g in theme_map(universe).items() if t in names}
    panel = build_panel(store, tuple(sorted(names)), MARKET_BENCHMARK, themes)
    # Adjusted OHLC: the image must not show a split as a crash.
    with np.errstate(all="ignore"):
        factor = np.where(panel.close > 0, panel.adj_close / panel.close, np.nan)
    arrays = {
        "open": panel.open * factor,
        "high": panel.high * factor,
        "low": panel.low * factor,
        "close": panel.adj_close,
        "volume": panel.volume,
    }
    return panel, arrays, book_sides(universe)


# Every (session, column) with a complete image and, where known, a label.
def _samples(panel, arrays, days: int, horizon: int):
    rows, names = panel.adj_close.shape
    close = panel.adj_close
    with np.errstate(all="ignore"):
        forward = np.log(np.roll(close, -horizon, axis=0) / close)
    forward[rows - horizon :] = np.nan
    bench = panel.index(panel.benchmark)
    sessions, columns = np.meshgrid(np.arange(rows), np.arange(names), indexing="ij")
    sessions, columns = sessions.ravel(), columns.ravel()
    keep = columns != bench
    sessions, columns = sessions[keep], columns[keep]
    _, complete = charts.windows(arrays, columns, sessions, days)
    sessions, columns = sessions[complete], columns[complete]
    label = forward[sessions, columns]
    return sessions, columns, label


# Every sample's image rendered once into a memory-mapped file under the
# store, keyed by the panel's last session, image length and sample
# count, so a rerun on the same data skips the rendering.
def _cached_images(root: Path, panel, arrays, sessions, columns, days: int):
    spec = charts.SPEC[days]
    shape = (len(sessions), spec["height"], charts.PIXELS_PER_DAY * days)
    stamp = f"{panel.dates[-1]}-{days}-{len(sessions)}"
    path = root / "charts" / f"images-{stamp}.u8"
    if path.exists() and path.stat().st_size == int(np.prod(shape)):
        return np.memmap(path, dtype=np.uint8, mode="r", shape=shape)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = np.memmap(path, dtype=np.uint8, mode="w+", shape=shape)
    for start in range(0, len(sessions), RENDER_CHUNK):
        rows = slice(start, start + RENDER_CHUNK)
        window, _ = charts.windows(arrays, columns[rows], sessions[rows], days)
        out[rows] = charts.render(window, days)
        if start % (RENDER_CHUNK * 20) == 0:
            print(f"    rendered {start:,} of {len(sessions):,}", flush=True)
    out.flush()
    return np.memmap(path, dtype=np.uint8, mode="r", shape=shape)


# A batch of images from the cache, as a float tensor on the device.
def _images(cache, rows) -> torch.Tensor:
    block = np.asarray(
        cache[np.sort(rows)] if isinstance(rows, np.ndarray) else cache[rows]
    )
    return torch.tensor(block, dtype=torch.float32, device=DEVICE)[:, None]


# Train one network with early stopping on the held-out third.
def _train(cache, rows_all, label, days, seed, max_epochs, fraction):
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    known = np.isfinite(label)
    idx = rows_all[known]
    if fraction < 1.0:
        idx = rng.choice(idx, size=int(len(idx) * fraction), replace=False)
    rng.shuffle(idx)
    cut = int(len(idx) * (1 - VALIDATION))
    fit, val = idx[:cut], idx[cut:]
    net = charts.ChartNet(days).to(DEVICE)
    opt = torch.optim.Adam(net.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.CrossEntropyLoss()
    positive = np.zeros(int(rows_all.max()) + 1, dtype=np.int64)
    positive[rows_all] = (np.nan_to_num(label) > 0).astype(np.int64)
    y = torch.tensor(positive, device=DEVICE)
    best, best_state, bad = float("inf"), None, 0
    for epoch in range(max_epochs):
        net.train()
        order = rng.permutation(fit)
        for i in range(0, len(order), BATCH):
            rows = np.sort(order[i : i + BATCH])
            x = _images(cache, rows)
            loss = loss_fn(net(x), y[rows])
            opt.zero_grad()
            loss.backward()
            opt.step()
        net.eval()
        total, count = 0.0, 0
        with torch.no_grad():
            for i in range(0, len(val), BATCH * 4):
                rows = np.sort(val[i : i + BATCH * 4])
                x = _images(cache, rows)
                total += float(loss_fn(net(x), y[rows])) * len(rows)
                count += len(rows)
        val_loss = total / max(count, 1)
        print(
            f"    seed {seed} epoch {epoch + 1}: validation loss {val_loss:.4f}",
            flush=True,
        )
        if val_loss < best - 1e-5:
            best, bad = val_loss, 0
            best_state = {k: v.clone() for k, v in net.state_dict().items()}
        else:
            bad += 1
            if bad >= PATIENCE:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    net.eval()
    return net


# The probability of an up move for a set of sample rows, seeds averaged.
def _predict(nets, cache, rows_all) -> np.ndarray:
    out = np.zeros(len(rows_all))
    with torch.no_grad():
        for i in range(0, len(rows_all), BATCH * 4):
            rows = rows_all[i : i + BATCH * 4]
            x = _images(cache, rows)
            probs = sum(torch.softmax(net(x), dim=1)[:, 1] for net in nets) / len(nets)
            out[i : i + BATCH * 4] = probs.cpu().numpy()
    return out


# Rank IC, t and net Sharpe of a (T, N) score on the given columns.
def _measure(scores, mask_cols, panel, horizon):
    masked = np.where(mask_cols[None, :], scores, np.nan)
    r = evaluate_scores(masked, panel, horizon, cost_bps=COST_BPS, min_names=MIN_NAMES)
    return r.mean_ic, r.ic_tstat, r.net_sharpe


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    store = MarketStore(args.data_dir)
    panel, arrays, sides = _panel(store)
    sessions, columns, label = _samples(panel, arrays, args.days, args.horizon)
    years = panel.dates[sessions].astype("datetime64[Y]").astype(int) + 1970
    print(
        f"{len(sessions):,} images of {args.days} days over "
        f"{len(panel.tickers) - 1} names, {panel.dates[sessions.min()]} to "
        f"{panel.dates[sessions.max()]}, device {DEVICE}"
    )
    cache = _cached_images(
        Path(args.data_dir), panel, arrays, sessions, columns, args.days
    )
    all_rows = np.arange(len(sessions))
    scores = np.full(panel.adj_close.shape, np.nan)
    nets_by_year = {}
    for year in args.years:
        train, test = years < year, years == year
        if train.sum() < 10_000 or test.sum() == 0:
            continue
        print(
            f"\n=== {year}: training on {int(train.sum()):,} images, "
            f"scoring {int(test.sum()):,}"
        )
        nets = [
            _train(
                cache,
                all_rows[train],
                label[train],
                args.days,
                s,
                args.max_epochs,
                args.train_fraction,
            )
            for s in range(args.seeds)
        ]
        nets_by_year[year] = nets
        prob = _predict(nets, cache, all_rows[test])
        scores[sessions[test], columns[test]] = prob
    saved = (
        Path(args.data_dir)
        / "charts"
        / f"scores-{panel.dates[-1]}-{args.days}-{args.horizon}.npz"
    )
    np.savez_compressed(
        saved,
        scores=scores.astype(np.float32),
        dates=panel.dates.astype("datetime64[D]"),
        tickers=np.array(panel.tickers),
    )
    print(f"\nout-of-sample probabilities saved to {saved}")
    in_universe = np.array([t != panel.benchmark for t in panel.tickers])
    in_book = np.array([t in sides for t in panel.tickers])
    momentum = baselines.momentum(panel, 252, 21)
    reversal = -baselines.momentum(panel, 5, 0)
    scored_rows = np.isfinite(scores).any(axis=1)
    print(f"\n{'signal':28} {'cells':>10} {'rank IC':>9} {'t':>7} {'net Sharpe':>11}")
    for name, s in (
        ("chart network", scores),
        ("momentum 252/21", momentum),
        ("reversal, 5 sessions", reversal),
    ):
        s = np.where(scored_rows[:, None], s, np.nan)
        for label_, cols in (("universe", in_universe), ("the book", in_book)):
            ic, t, sh = _measure(s, cols, panel, args.horizon)
            print(f"{name:28} {label_:>10} {ic:+9.4f} {t:+7.2f} {sh:+11.2f}")
    if args.show:
        ticker, when = args.show[0].upper(), date.fromisoformat(args.show[1])
        col = panel.index(ticker)
        t = int(np.searchsorted(panel.dates, np.datetime64(when)))
        year = int(str(panel.dates[t])[:4])
        if year not in nets_by_year:
            print(f"\nno fold scored {year}")
            return
        hit = np.flatnonzero((sessions == t) & (columns == col))
        if not len(hit):
            print(f"\nno complete image for {ticker} on {panel.dates[t]}")
            return
        p = _predict(nets_by_year[year], cache, hit)[0]
        day = scores[t][in_universe & np.isfinite(scores[t])]
        pct = np.mean(day <= p) if len(day) else float("nan")
        print(
            f"\n{ticker} on {panel.dates[t]}: P(up over {args.horizon}) = {p:.3f}, "
            f"percentile {pct:.0%} of the day's names"
        )


if __name__ == "__main__":
    main()
