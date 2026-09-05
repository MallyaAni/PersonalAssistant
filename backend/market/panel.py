"""The aligned cross-section every model and baseline reads from.

A Panel is the store's histories aligned onto one shared session calendar:
one row per session, one column per ticker, NaN where a ticker did not
trade. Everything downstream — window tensors for a model, momentum and
relative-strength baselines, the walk-forward harness — reads the same
matrices, so a baseline and a model are compared on identical data with
identical alignment.

Rotation lives here as theme returns: the equal-weight daily return of each
theme's members, computed from the same matrix. A ticker's return relative
to its theme, and its theme's return relative to the market, are the two
series a cross-sectional model needs to separate "money is leaving AI
infrastructure" from "this name is lagging its peers".

No interpolation anywhere: a missing session stays NaN and whatever reads
the panel decides what a gap means.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from backend.market.store import MarketStore
from backend.market.yahoo import TickerHistory

_FIELDS = ("open", "high", "low", "close", "adjusted_close", "volume")


@dataclass(frozen=True, slots=True)
class Panel:
    """Aligned daily matrices (sessions x tickers) plus theme membership."""

    dates: np.ndarray  # (T,) datetime64[D]
    tickers: tuple[str, ...]
    open: np.ndarray  # (T, N) float64, NaN where missing
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    adj_close: np.ndarray
    volume: np.ndarray
    themes: Mapping[str, tuple[str, ...]]
    benchmark: str

    # The column index of a ticker.
    def index(self, ticker: str) -> int:
        """Return the column of `ticker`, raising KeyError if absent."""
        try:
            return self.tickers.index(ticker)
        except ValueError as exc:
            raise KeyError(ticker) from exc

    # Daily log returns from adjusted close, NaN on the first row and
    # wherever either session is missing.
    def log_returns(self) -> np.ndarray:
        """Return the (T, N) matrix of daily log returns from adjusted close."""
        return _log_ratio(self.adj_close[1:], self.adj_close[:-1], leading=1)

    # The benchmark's daily log return series.
    def benchmark_returns(self) -> np.ndarray:
        """Return the (T,) daily log returns of the benchmark column."""
        return self.log_returns()[:, self.index(self.benchmark)]

    # The first theme tag of a ticker, or None when it carries none.
    def primary_theme(self, ticker: str) -> str | None:
        """Return the ticker's first theme, or None."""
        tags = self.themes.get(ticker, ())
        return tags[0] if tags else None

    # Equal-weight daily log return of each theme's members present that
    # day. A theme with no member trading on a day is NaN there.
    def theme_returns(self) -> dict[str, np.ndarray]:
        """Return {theme: (T,) equal-weight member log returns}."""
        returns = self.log_returns()
        out: dict[str, np.ndarray] = {}
        members_by_theme: dict[str, list[int]] = {}
        for column, ticker in enumerate(self.tickers):
            for theme in self.themes.get(ticker, ()):
                members_by_theme.setdefault(theme, []).append(column)
        for theme, columns in members_by_theme.items():
            block = returns[:, columns]
            known = np.isfinite(block)
            counts = known.sum(axis=1)
            total = np.where(known, block, 0.0).sum(axis=1)
            out[theme] = np.where(counts > 0, total / np.maximum(counts, 1), np.nan)
        return out

    # The per-ticker theme return series: each column is its ticker's
    # primary theme's return, or the benchmark's return for an untagged name
    # (so "relative to theme" degrades to "relative to market", never to a
    # fabricated zero).
    def theme_return_matrix(self) -> np.ndarray:
        """Return (T, N) where column j is ticker j's primary-theme return."""
        by_theme = self.theme_returns()
        bench = self.benchmark_returns()
        out = np.empty_like(self.adj_close)
        for column, ticker in enumerate(self.tickers):
            theme = self.primary_theme(ticker)
            out[:, column] = by_theme.get(theme, bench)
        return out

    # The K-session forward log return from each session, NaN where the
    # future is not fully known or either end is missing.
    def forward_log_returns(self, horizon: int) -> np.ndarray:
        """Return (T, N) of log(adj[t+h] / adj[t]), NaN in the last h rows."""
        if horizon < 1:
            raise ValueError("horizon must be >= 1")
        forward = np.full_like(self.adj_close, np.nan)
        forward[:-horizon] = _log_ratio(
            self.adj_close[horizon:], self.adj_close[:-horizon]
        )
        return forward


# Elementwise log(numerator / denominator) with NaN for any non-finite
# result, optionally padded with `leading` NaN rows at the top.
def _log_ratio(
    numerator: np.ndarray, denominator: np.ndarray, leading: int = 0
) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.log(numerator / denominator)
    ratio = np.where(np.isfinite(ratio), ratio, np.nan)
    if leading:
        pad = np.full((leading,) + ratio.shape[1:], np.nan)
        ratio = np.concatenate([pad, ratio], axis=0)
    return ratio


# Align histories onto the union of their session dates.
#
# `themes` should carry only the names whose returns define a theme (focus
# and member names), not the ETF benchmarks, or a basket would include its
# own proxy.
def panel_from_histories(
    histories: Mapping[str, TickerHistory],
    benchmark: str,
    themes: Mapping[str, tuple[str, ...]],
    start: date | None = None,
) -> Panel:
    """Build a Panel from per-ticker histories on their shared calendar."""
    if benchmark not in histories:
        raise ValueError(f"benchmark {benchmark} is not among the histories")
    tickers = tuple(sorted(histories))
    sessions: set[date] = set()
    for history in histories.values():
        sessions.update(
            b.session_date
            for b in history.bars
            if start is None or b.session_date >= start
        )
    calendar = sorted(sessions)
    index_of = {session: i for i, session in enumerate(calendar)}
    shape = (len(calendar), len(tickers))
    matrices = {field: np.full(shape, np.nan) for field in _FIELDS}
    for column, ticker in enumerate(tickers):
        for bar in histories[ticker].bars:
            row = index_of.get(bar.session_date)
            if row is None:
                continue
            for field in _FIELDS:
                value = getattr(bar, field)
                if value is not None:
                    matrices[field][row, column] = float(value)
    return Panel(
        dates=np.asarray(calendar, dtype="datetime64[D]"),
        tickers=tickers,
        open=matrices["open"],
        high=matrices["high"],
        low=matrices["low"],
        close=matrices["close"],
        adj_close=matrices["adjusted_close"],
        volume=matrices["volume"],
        themes={t: tuple(themes.get(t, ())) for t in tickers},
        benchmark=benchmark,
    )


# Read the requested tickers from the store as of a date and align them.
# Tickers the store does not hold are left out and reported by the caller
# through `status`, not silently zero-filled here.
def build_panel(
    store: MarketStore,
    tickers: Sequence[str],
    benchmark: str,
    themes: Mapping[str, tuple[str, ...]],
    asof: date | None = None,
    start: date | None = None,
) -> Panel:
    """Load histories from the store and build the aligned Panel."""
    histories: dict[str, TickerHistory] = {}
    for ticker in dict.fromkeys(list(tickers) + [benchmark]):
        history = store.read(ticker, asof)
        if history is not None:
            histories[ticker] = history
    return panel_from_histories(histories, benchmark, themes, start=start)
