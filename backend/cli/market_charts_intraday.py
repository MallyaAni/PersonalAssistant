"""The chart network on fifteen-minute bars: does the intraday chart know the next hour?

    python -m backend.cli.market_charts_intraday
    python -m backend.cli.market_charts_intraday --slots 4 12 20 --horizon 4 --seeds 2

The question
------------
The daily chart model draws twenty sessions and asks about the next
twenty. A person watching the tape reads the same shapes on a faster
clock: the last twenty fifteen-minute bars, at mid-morning, midday and
mid-afternoon, and asks about the next hour. The method transfers
unchanged - the same image layout, the same network - so the question
can be answered the same way rather than argued.

The material
------------
The book's names on their fifteen-minute bars, every complete session
since 2020. At each `--slots` bar of each session, the image is the last
twenty bars ending there, crossing into the previous session when it
must, as a trader's intraday chart does. The label is whether the close
`--horizon` bars later is above the close now, within the same session.

The measurement
---------------
Walk-forward by year with early stopping on a held-out third, as for the
daily model. The probability is then scored cross-sectionally at each
(session, slot): its rank correlation with the next hour's return across
the names, averaged, with a t over sessions; the spread between the top
and bottom fifth of names in basis points; and the same for two rules
on the same cells, continuation (the last four bars' return) and its
reverse. A round trip inside the session costs at least six basis
points on these names, which is the bar any spread has to clear.

Results
-------
Recorded below once the run is read.
"""

import argparse
from pathlib import Path

import numpy as np
import torch
from torch import nn

from backend.market import charts, intraday
from backend.market.universe import book_sides, build_universe

DAYS = 20  # bars in the image; the twenty-day spec draws twenty of anything
BATCH = 128
LEARNING_RATE = 1e-5
PATIENCE = 2
VALIDATION = 0.3
COST_BPS = 6.0
RENDER_CHUNK = 8_192
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="The chart network on fifteen-minute bars."
    )
    parser.add_argument("--slots", type=int, nargs="+", default=[4, 12, 20])
    parser.add_argument("--horizon", type=int, default=4, help="bars ahead")
    parser.add_argument(
        "--years", type=int, nargs="+", default=[2022, 2023, 2024, 2025, 2026]
    )
    parser.add_argument("--seeds", type=int, default=2)
    parser.add_argument("--max-epochs", type=int, default=20)
    parser.add_argument("--data-dir", default="data/market")
    return parser


# One name's bars as continuous arrays in session order, with each bar's
# session index and slot, complete sessions only.
def _series(root, ticker):
    got = intraday.load(root, ticker)
    day, slot, fields, _ = got
    order = np.lexsort((slot, day))
    day, slot = day[order], slot[order]
    arrays = {k: v[order] for k, v in fields.items()}
    # Keep only sessions with every bar.
    keep = np.zeros(len(day), dtype=bool)
    for d in np.unique(day):
        m = day == d
        if m.sum() == intraday.BARS and np.all(
            np.sort(slot[m]) == np.arange(intraday.BARS)
        ):
            keep |= m
    return day[keep], slot[keep], {k: v[keep] for k, v in arrays.items()}


# Every (name, session, slot) sample: the image window ends at the slot's
# bar; the label is the return `horizon` bars later within the session.
def _samples(root, tickers, slots, horizon):
    rows = []  # (ticker index, bar index within the name's series)
    series = []
    for ticker in tickers:
        try:
            day, slot, arrays = _series(root, ticker)
        except FileNotFoundError:
            continue
        if not len(day):
            continue
        close = arrays["close"]
        label = np.full(len(close), np.nan)
        ahead = np.arange(len(close)) + horizon
        same = (ahead < len(close)) & (day[np.minimum(ahead, len(close) - 1)] == day)
        with np.errstate(all="ignore"):
            label[same] = np.log(
                close[np.minimum(ahead, len(close) - 1)][same] / close[same]
            )
        bars = np.flatnonzero(
            np.isin(slot, list(slots)) & (np.arange(len(close)) >= 2 * DAYS)
        )
        series.append((ticker, day, slot, arrays, label))
        rows.extend((len(series) - 1, b) for b in bars)
    return series, np.array(rows)


# Render all samples into a memory-mapped cache, one name at a time.
def _cache(root: Path, series, rows, stamp: str):
    spec = charts.SPEC[DAYS]
    shape = (len(rows), spec["height"], charts.PIXELS_PER_DAY * DAYS)
    path = root / "charts" / f"intraday-{stamp}-{len(rows)}.u8"
    if path.exists() and path.stat().st_size == int(np.prod(shape)):
        return np.memmap(path, dtype=np.uint8, mode="r", shape=shape)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = np.memmap(path, dtype=np.uint8, mode="w+", shape=shape)
    for name_index, (_ticker, _day, _slot, arrays, _label) in enumerate(series):
        mine = np.flatnonzero(rows[:, 0] == name_index)
        if not len(mine):
            continue
        panel_arrays = {
            k: arrays[k][:, None] for k in ("open", "high", "low", "close", "volume")
        }
        for start in range(0, len(mine), RENDER_CHUNK):
            chunk = mine[start : start + RENDER_CHUNK]
            sessions = rows[chunk, 1]
            window, _ = charts.windows(
                panel_arrays, np.zeros(len(chunk), dtype=int), sessions, DAYS
            )
            out[chunk] = charts.render(window, DAYS)
    out.flush()
    return np.memmap(path, dtype=np.uint8, mode="r", shape=shape)


def _images(cache, rows) -> torch.Tensor:
    block = np.asarray(cache[np.sort(rows)])
    return torch.tensor(block, dtype=torch.float32, device=DEVICE)[:, None]


def _train(cache, rows_all, label, seed, max_epochs):
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    idx = rows_all[np.isfinite(label)]
    rng.shuffle(idx)
    cut = int(len(idx) * (1 - VALIDATION))
    fit, val = idx[:cut], idx[cut:]
    net = charts.ChartNet(DAYS).to(DEVICE)
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
            loss = loss_fn(net(_images(cache, rows)), y[rows])
            opt.zero_grad()
            loss.backward()
            opt.step()
        net.eval()
        total, count = 0.0, 0
        with torch.no_grad():
            for i in range(0, len(val), BATCH * 4):
                rows = np.sort(val[i : i + BATCH * 4])
                total += float(loss_fn(net(_images(cache, rows)), y[rows])) * len(rows)
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


def _predict(nets, cache, rows_all) -> np.ndarray:
    out = np.zeros(len(rows_all))
    with torch.no_grad():
        for i in range(0, len(rows_all), BATCH * 4):
            rows = rows_all[i : i + BATCH * 4]
            probs = sum(
                torch.softmax(net(_images(cache, rows)), dim=1)[:, 1] for net in nets
            )
            out[i : i + BATCH * 4] = (probs / len(nets)).cpu().numpy()
    return out


# Cross-sectional scoring at each (session, slot): rank IC with a t over
# sessions, and the top-fifth-less-bottom-fifth spread in basis points.
def _score(name, signal, label, keys):
    from scipy.stats import spearmanr

    ics, spreads = [], []
    order = np.argsort(keys, kind="stable")
    sorted_keys = keys[order]
    starts = np.flatnonzero(np.r_[True, sorted_keys[1:] != sorted_keys[:-1]])
    stops = np.r_[starts[1:], len(order)]
    for a, b in zip(starts, stops, strict=True):
        rows = order[a:b]
        s, y = signal[rows], label[rows]
        ok = np.isfinite(s) & np.isfinite(y)
        if ok.sum() < 20:
            continue
        s, y = s[ok], y[ok]
        ics.append(spearmanr(s, y).statistic)
        lo, hi = np.quantile(s, 0.2), np.quantile(s, 0.8)
        spreads.append(y[s >= hi].mean() - y[s <= lo].mean())
    ics, spreads = np.array(ics), np.array(spreads)
    t = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)) + 1e-12)
    print(
        f"{name:28} {ics.mean():+8.4f} {t:+7.2f} {spreads.mean() * 1e4:+9.1f} bps "
        f"{'clears cost' if spreads.mean() * 1e4 > COST_BPS else 'inside cost':>12} "
        f"({len(ics):,} cells)"
    )


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    root = intraday.partition()
    tickers = sorted(book_sides(build_universe()))
    series, rows = _samples(root, tickers, sorted(set(args.slots)), args.horizon)
    label = np.array([series[i][4][b] for i, b in rows])
    days = np.array([series[i][1][b] for i, b in rows])
    slots = np.array([series[i][2][b] for i, b in rows])
    years = days.astype("datetime64[Y]").astype(int) + 1970
    print(
        f"{len(rows):,} images of {DAYS} fifteen-minute bars over {len(series)} names, "
        f"slots {sorted(set(args.slots))}, horizon {args.horizon} bars, device {DEVICE}"
    )
    cache = _cache(Path(args.data_dir), series, rows, f"{days.max()}-{args.horizon}")
    all_rows = np.arange(len(rows))
    prob = np.full(len(rows), np.nan)
    for year in args.years:
        train, test = years < year, years == year
        if train.sum() < 10_000 or test.sum() == 0:
            continue
        print(
            f"\n=== {year}: training on {int(train.sum()):,}, "
            f"scoring {int(test.sum()):,}",
            flush=True,
        )
        nets = [
            _train(cache, all_rows[train], label[train], s, args.max_epochs)
            for s in range(args.seeds)
        ]
        prob[test] = _predict(nets, cache, all_rows[test])
    # Continuation: the last four bars' return; reversal: its negative.
    recent = np.array(
        [
            np.log(series[i][3]["close"][b] / series[i][3]["close"][b - 4])
            for i, b in rows
        ]
    )
    scored = np.isfinite(prob)
    keys = np.array([f"{d}-{s}" for d, s in zip(days, slots, strict=True)])
    universe_move = np.zeros(len(rows))
    for k in np.unique(keys[scored]):
        m = scored & (keys == k)
        universe_move[m] = np.nanmean(label[m])
    excess = label - universe_move
    print(f"\n{'signal':28} {'rank IC':>8} {'t':>7} {'top-bottom':>13} {'':>12}")
    _score("chart network", prob[scored], excess[scored], keys[scored])
    _score("continuation, last hour", recent[scored], excess[scored], keys[scored])
    _score("reversal, last hour", -recent[scored], excess[scored], keys[scored])
    for slot in sorted(set(args.slots)):
        m = scored & (slots == slot)
        _score(f"chart network at slot {slot}", prob[m], excess[m], keys[m])


if __name__ == "__main__":
    main()
