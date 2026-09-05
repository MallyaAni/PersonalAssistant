"""Market state beyond the equity panel: volatility, rates, the dollar, oil.

The literature's most robust finding about *when* factors work is that
they depend on the regime: momentum and low-risk after calm, quality after
stress. The panel's own channels see the market only through the
benchmark's returns. This module adds the regime series every desk
watches, from the same store the bars live in (fetched by
`market_snapshot --tickers "^VIX,^TNX,DX-Y.NYB,CL=F"`):

    vix_level            the VIX close, in log
    vix_change_20        log change of the VIX over 20 sessions
    vix_vs_realised      log(VIX / annualised 20-session realised vol of SPY)
    tnx_level            the 10-year yield, percent
    tnx_change_20        change in the yield over 20 sessions, percent
    dollar_change_20     log change of the dollar index over 20 sessions
    oil_change_20        log change of front-month crude over 20 sessions

Per session, aligned to the panel by date, carried forward across a
missing print. They enter the market-state vector the gates read and,
broadcast per name, the "macro" feature layer.
"""

from datetime import date

import numpy as np

from backend.market.panel import Panel
from backend.market.store import MarketStore

MACRO_NAMES: tuple[str, ...] = (
    "vix_level",
    "vix_change_20",
    "vix_vs_realised",
    "tnx_level",
    "tnx_change_20",
    "dollar_change_20",
    "oil_change_20",
)
MACRO_COUNT = len(MACRO_NAMES)
SERIES: dict[str, str] = {
    "vix": "^VIX",
    "tnx": "^TNX",
    "dollar": "DX-Y.NYB",
    "oil": "CL=F",
}


# One stored series aligned to the panel's sessions, carried forward.
def aligned_close(
    store: MarketStore, symbol: str, panel: Panel, asof: date | None = None
) -> np.ndarray:
    """Return the symbol's close per panel session, NaN before its first print."""
    history = store.read(symbol, asof)
    out = np.full(len(panel.dates), np.nan)
    if history is None:
        return out
    closes = {b.session_date: b.close for b in history.bars if b.close is not None}
    last = np.nan
    for i, session in enumerate(panel.dates.astype("datetime64[D]").astype(object)):
        if session in closes:
            last = float(closes[session])
        out[i] = last
    return out


# Log change over `lag` sessions.
def _log_change(series: np.ndarray, lag: int) -> np.ndarray:
    out = np.full_like(series, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[lag:] = np.log(series[lag:] / series[:-lag])
    return np.where(np.isfinite(out), out, np.nan)


# The (T, MACRO_COUNT) market-state series for a panel.
def macro_by_session(
    store: MarketStore, panel: Panel, asof: date | None = None
) -> np.ndarray:
    """Return per-session macro features aligned to the panel."""
    vix = aligned_close(store, SERIES["vix"], panel, asof)
    tnx = aligned_close(store, SERIES["tnx"], panel, asof)
    dollar = aligned_close(store, SERIES["dollar"], panel, asof)
    oil = aligned_close(store, SERIES["oil"], panel, asof)
    spy = panel.benchmark_returns()
    realised = np.full_like(spy, np.nan)
    for t in range(20, len(spy)):
        window = spy[t - 19 : t + 1]
        if np.isfinite(window).all():
            realised[t] = window.std(ddof=1) * np.sqrt(252) * 100.0
    with np.errstate(divide="ignore", invalid="ignore"):
        columns = [
            np.log(vix),
            _log_change(vix, 20),
            np.log(vix / realised),
            tnx,
            np.concatenate([np.full(20, np.nan), tnx[20:] - tnx[:-20]]),
            _log_change(dollar, 20),
            _log_change(oil, 20),
        ]
    stacked = np.stack(columns, axis=1).astype(np.float32)
    return np.where(np.isfinite(stacked), stacked, np.nan)


# The macro state broadcast per name: (T, N, MACRO_COUNT), NaN where the
# series are not yet available (the first month of the panel).
def macro_features(
    store: MarketStore, panel: Panel, asof: date | None = None
) -> np.ndarray:
    """Return the per-session macro state repeated for every name."""
    per_session = macro_by_session(store, panel, asof)
    return np.repeat(per_session[:, None, :], len(panel.tickers), axis=1)
