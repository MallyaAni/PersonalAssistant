"""Strict, independently loaded SPY/QQQ benchmark series for the comparison.

The comparison used to read the indexes out of the stock panel, which never
held QQQ on the current data, so QQQ silently disappeared; and
`strategy_bench.stats` then converted any missing return into zero, so a
benchmark gap read as flat cash. This is the one strict loader the comparison
uses: each benchmark (SPY and QQQ) is read from the MarketStore on its own,
must carry adjusted prices and complete coverage of the strategy's executable
calendar, and is priced exactly like the strategy it is judged against - the
same starting capital, the same executable sessions, a first fill at the first
next-open available to the strategy, the same configured one-way cost,
dividend-adjusted holding returns, and terminal holdings marked at the last
close with no extra hypothetical liquidation. Unavailable data is reported,
never invented.

A benchmark that cannot be loaded is reported as such with a reason; it is
never silently omitted from the comparison and never given fabricated returns.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.market.store import MarketStore

# The same starting capital and one-way cost the strategy's own simulation
# starts from, so a control and the strategy begin on identical terms.
DEFAULT_START_EQUITY = 1.0
DEFAULT_COST_BPS = 10.0


@dataclass(frozen=True)
class BenchmarkSeries:
    """One benchmark's aligned daily series, or why it is unavailable.

    `daily` and `equity` are aligned to the caller's session calendar: one
    value per session. `equity[0]` is the intentional starting capital (an
    initial NAV of 1, distinct from an unknown market return); `daily[0]` is
    NaN because no market return was earned before the first fill. Terminal
    holdings are marked at the last close, never hypothetically liquidated.
    """

    symbol: str
    available: bool
    daily: np.ndarray | None  # (T,) aligned daily returns, net of entry cost
    equity: np.ndarray | None  # (T,) NAV, first value the starting capital
    sessions: np.ndarray | None  # (T,) the aligned session dates
    reason: str = ""  # why unavailable, when not available


# Validate the loader's caller inputs before any pricing happens: a garbage
# calendar, equity or cost is a caller error, never a fake available series.
def _validate(
    sessions: np.ndarray, cost_bps: float, start_equity: float
) -> np.ndarray:
    """Return the validated, sorted, unique session calendar (raises on bad)."""
    if not np.isfinite(cost_bps) or cost_bps < 0:
        raise ValueError("cost_bps must be finite and nonnegative")
    if not np.isfinite(start_equity) or start_equity <= 0:
        raise ValueError("start_equity must be finite and positive")
    sessions = np.asarray(sessions, dtype="datetime64[D]")
    if sessions.ndim != 1:
        raise ValueError("the executable calendar must be one-dimensional")
    if len(sessions) < 2:
        raise ValueError(
            "the executable calendar must have at least two sessions, so a "
            "first next-open exists"
        )
    if np.isnat(sessions).any():
        raise ValueError("the executable calendar must not contain NaT dates")
    if len(np.unique(sessions)) != len(sessions):
        raise ValueError("the executable calendar must contain unique dates")
    if not np.all(sessions[1:] > sessions[:-1]):
        raise ValueError("the executable calendar must be sorted ascending")
    return sessions


# Build the aligned price maps a benchmark needs: adjusted close per session,
# and the raw open and close needed to put an opening price on the same
# adjusted basis as the close (so a fill never straddles a split or dividend).
def _aligned_prices(history, sessions: np.ndarray) -> dict[str, np.ndarray]:
    """Return {adjusted_close, open, close} aligned to `sessions`."""
    bars = {b.session_date: b for b in history.bars}
    out = {
        key: np.full(len(sessions), np.nan)
        for key in ("adjusted_close", "open", "close")
    }
    for i, session in enumerate(sessions):
        bar = bars.get(session.astype(object))
        if bar is None:
            continue
        value = float(bar.adjusted_close) if bar.adjusted_close is not None else np.nan
        out["adjusted_close"][i] = value
        value = float(bar.open) if bar.open is not None else np.nan
        out["open"][i] = value
        value = float(bar.close) if bar.close is not None else np.nan
        out["close"][i] = value
    return out


# The opening price on the same basis as the adjusted close, at one session.
def _adjusted_open(open_: float, close: float, adjusted_close: float) -> float:
    """Return the session's adjusted opening price, or NaN when unusable."""
    if not all(np.isfinite(x) and x > 0 for x in (open_, close, adjusted_close)):
        return float("nan")
    return open_ * (adjusted_close / close)


# Whether a benchmark covers the whole executable calendar with adjusted
# prices, and can be bought at the first next-open.
def _coverage_failure(
    prices: dict[str, np.ndarray], symbol: str, sessions: np.ndarray
) -> str | None:
    """Return the first coverage failure, or None when coverage is complete."""
    adj = prices["adjusted_close"]
    open_adj = _adjusted_open(
        float(prices["open"][1]), float(prices["close"][1]), float(adj[1])
    )
    if not np.isfinite(open_adj) or open_adj <= 0:
        return f"{symbol} cannot be bought at the first next-open {sessions[1]}"
    for i, session in enumerate(sessions):
        if not np.isfinite(adj[i]) or adj[i] <= 0:
            return (
                f"{symbol} has no adjusted price at {session}; adjusted prices "
                "required over the whole evaluation window"
            )
    return None


# One strict benchmark, priced on the strategy's own executable calendar.
def load_benchmark(
    store: MarketStore,
    symbol: str,
    sessions,
    cost_bps: float = DEFAULT_COST_BPS,
    start_equity: float = DEFAULT_START_EQUITY,
    asof=None,
) -> BenchmarkSeries:
    """Return the benchmark's aligned series, or an explicit unavailable result.

    `sessions` is the strategy's executable calendar (its panel dates), so
    the control is judged on the same sessions and the same starting NAV as
    the strategy. A benchmark with adjusted prices missing on any interior
    session fails coverage explicitly rather than being filled with zero
    returns; a benchmark the store does not hold at all is reported as
    unavailable rather than dropped from the comparison.

    Pricing mirrors `desk.simulate.run`: the account starts fully in cash at
    `start_equity`, buys the whole capital at the first next-open (session
    index 1) at the one-way cost charged the way the funded ledger charges it,
    holds the resulting shares, and marks the terminal holding at the last
    adjusted close without liquidating it. The first return is deliberately
    NaN - capital with no market exposure yet - not a manufactured zero or a
    manufactured market return.
    """
    sessions = _validate(sessions, cost_bps, start_equity)
    history = store.read(symbol, asof)
    if history is None:
        return BenchmarkSeries(
            symbol,
            False,
            None,
            None,
            sessions,
            reason=f"{symbol} has no bars in the store",
        )
    prices = _aligned_prices(history, sessions)
    failure = _coverage_failure(prices, symbol, sessions)
    if failure is not None:
        return BenchmarkSeries(symbol, False, None, None, sessions, reason=failure)

    adj = prices["adjusted_close"]
    equity = np.full(len(sessions), np.nan)
    daily = np.full(len(sessions), np.nan)
    equity[0] = float(start_equity)
    open_adj = _adjusted_open(
        float(prices["open"][1]), float(prices["close"][1]), float(adj[1])
    )
    # The funded ledger's cost convention: buying `notional` costs
    # notional * (1 + cost), so whole-capital investment buys
    # start_equity / (adjusted_open * (1 + cost)) shares. No terminal
    # liquidation fee is charged because the holding is never liquidated.
    cost = cost_bps / 1e4
    shares = float(start_equity) / (open_adj * (1.0 + cost))
    for t in range(1, len(sessions)):
        equity[t] = shares * float(adj[t])
    for t in range(1, len(sessions)):
        if np.isfinite(equity[t - 1]) and equity[t - 1] > 0:
            daily[t] = equity[t] / equity[t - 1] - 1.0
    return BenchmarkSeries(symbol, True, daily, equity, sessions)
