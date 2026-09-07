"""Did the desk beat the index every year? And its own names?

    python -m backend.cli.market_yearly
    python -m backend.cli.market_yearly --since 2021-06-01 --vol-target 0.50

The question
------------
An account's yardstick is an index it could have held instead: did the
book beat SPY and QQQ every year in total return? That is the standard
asked for, and it is answered here year by year. Beside it sits the
stricter yardstick that tests the desk's own work rather than the choice
of names: equal weight on all the book's names, which is what the
grading and sizing have to beat to have added anything. The book was
chosen in 2026 from names that had already won, so every row above the
indices is flattered by that choice, the equal-weight row most of all.

Results
-------
From 2021-06-01, the desk's weights, full rules:

  total return by year         2021*    2022    2023    2024    2025   2026*
  the desk, today's settings  +21.9%   -6.3%  +41.4%  +42.6%  +37.2%  +54.3%
  the desk, 50% vol target    +26.9%   -9.2%  +53.5%  +51.0%  +49.4%  +99.6%
  equal weight, all 93 names  +24.8%  -31.0%  +87.7%  +58.4%  +60.0%  +53.6%
  SPY                         +13.1%  -19.5%  +24.3%  +23.3%  +16.4%  +12.9%
  QQQ                         +19.1%  -33.1%  +53.8%  +24.8%  +20.2%  +17.0%
  (* partial years)

The desk beat SPY every year and QQQ in five of six; the exception is
2023, the recovery year. Against its own names it wins on risk and gives
up upside: half invested and risk-off while money tightens, it held 2022
to -6% where its names lost 31%, then trailed them in the three strong
years. Over the period, +388% against +529% for holding everything, with
a third of the drawdown. At the 50% volatility target the same rule
beats every row on total, +696%, with 2022 at -9%. The account's
standard is the yearly one; the rule's standard is the Sharpe, which is
what says the book can be run at more exposure at the same price.
"""

import argparse
from dataclasses import replace
from datetime import date

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import risk, simulate
from backend.market.store import MarketStore

INDICES = ("SPY", "QQQ")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="The book against the index, yearly.")
    parser.add_argument("--since", type=date.fromisoformat, default=date(2021, 6, 1))
    parser.add_argument("--vol-target", type=float, default=0.50)
    parser.add_argument("--data-dir", default="data/market")
    return parser


# Total return per calendar year from a daily series.
def yearly(dates: np.ndarray, daily: np.ndarray) -> dict[int, float]:
    """Return {year: total return} compounding the finite daily returns."""
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    out = {}
    for y in sorted(set(years.tolist())):
        m = (years == y) & np.isfinite(daily)
        out[y] = float(np.prod(1 + daily[m]) - 1)
    return out


# An index's daily returns from the store's bars, from `since`.
def _index(store, ticker: str, since: date):
    frame = store.read_frame("bars", ticker)
    if frame is None:
        return None
    cols = frame[0]
    key = next(
        k
        for k in cols
        if k not in ("open", "high", "low", "close", "volume", "adj_close")
    )
    dates = np.array([str(v)[:10] for v in cols[key]], dtype="datetime64[D]")
    close = np.array(
        cols["adj_close"] if "adj_close" in cols else cols["close"], dtype=float
    )
    daily = np.r_[np.nan, close[1:] / close[:-1] - 1]
    keep = dates >= np.datetime64(since)
    return dates[keep], daily[keep]


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    store = MarketStore(args.data_dir)
    report = trading_desk.run(store)
    panel = report.panel
    rows: dict[str, dict[int, float]] = {}
    base = simulate.run(report, since=args.since, use_exits=False)
    rows["the desk, today's settings"] = yearly(base.dates, base.returns)
    config = replace(
        risk.BOOK_CONFIG,
        target_volatility=args.vol_target,
        name_cap=0.25,
        theme_cap=0.80,
    )
    more = simulate.run(report, since=args.since, use_exits=False, config=config)
    rows[f"the desk, {args.vol_target:.0%} vol target"] = yearly(
        more.dates, more.returns
    )
    in_book = np.array([t in report.sides for t in panel.tickers])
    simple = np.expm1(panel.log_returns())
    with np.errstate(all="ignore"):
        equal = np.nanmean(np.where(in_book[None, :], simple, np.nan), axis=1)
    keep = panel.dates >= np.datetime64(args.since)
    rows[f"equal weight, all {int(in_book.sum())} names"] = yearly(
        panel.dates[keep], equal[keep]
    )
    for ticker in INDICES:
        got = _index(store, ticker, args.since)
        if got is not None:
            rows[ticker] = yearly(*got)
    years = sorted(set().union(*[set(v) for v in rows.values()]))
    print(f"{'total return by year':30}" + "".join(f"{y:>9}" for y in years))
    for name, by in rows.items():
        cells = "".join(f"{by[y]:+9.1%}" if y in by else f"{'-':>9}" for y in years)
        print(f"{name:30}{cells}")


if __name__ == "__main__":
    main()
