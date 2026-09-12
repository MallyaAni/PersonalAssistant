"""The technical analyst's rating re-read at the live price.

The desk grades on the close. During the session the board shows the
live price against that close, and a person watching a name fall asks
what the technical analyst would make of it here. This answers that:
the book's panel with today's row set from the fifteen-minute quotes
(open, high, low so far, last), the technical analyst run on it, and
each name's rank across the book on the resulting score, beside its
rank at the last close from the same run so the two are comparable.

It is a reading, not a rule. The analyst's playbook is the one measured
on these names, and on it strength beats dips: a quality name falling
through its averages reads lower, not higher, and the measurement
behind that stands (`backend/cli/market_snapback.py`). What the live
read gives is the size of the change, so a fall that has moved a name
from the top of the book to its middle is visible as such by the
candle rather than after the close.

The run computes the day's regime view on the live panel so the
analyst's playbook is the one the desk used; `now` against `close` from
the same run is the comparison the page makes. One run per candle,
cached.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import numpy as np

from backend.agents.trading.desk import regime
from backend.agents.trading.desk import technical as technical_analyst
from backend.agents.trading.desk.desk import book_panel, tightening_for
from backend.market import baselines, options
from backend.market import technical as daily_technical
from backend.market.panel import Panel

# The session date is the New York calendar date, not the UTC one: an
# afternoon in UTC is already the next date in New York's calendar, so a
# UTC "today" can point the live bar at the wrong session.
NEW_YORK = ZoneInfo("America/New_York")

_cache: dict[str, object] = {"key": None, "value": {}}

# The technical analyst's features grouped by chart timeframe, the way a
# trader reads them: the daily chart is the short term (the next week or
# so), the weekly chart is the medium term (one to three weeks), and the
# monthly picture is the long term beyond that. The drill-down shows the
# three separately so a person sees both where price is right now and
# whether the longer timeframes still agree with it.
SHORT = (
    "ema21_distance",
    "ema21_slope",
    "ema50_distance",
    "ema50_slope",
    "spread_21_50",
    "spread_21_50_slope",
    "converging_21_50",
    "stack_order",
    "daily_trend",
    "range_position_60",
    "support_distance",
    "resistance_distance",
    "support_level",
    "support_kind",
    "resistance_level",
    "resistance_kind",
)
MEDIUM = (
    "weekly_trend",
    "weekly_stack",
)
LONG = (
    "ema200_distance",
    "sma200_distance",
    "high_52w_distance",
    "low_52w_distance",
    "residual_momentum_120",
)


# The panel with today's row set from the live quotes: appended when the
# store ends before today, overwritten when it already has today. Names
# without a quote carry their last close forward, so the cross-section
# the rank is taken over is complete.
def with_live_row(panel: Panel, quotes: dict, today: date) -> Panel:
    """Return a Panel whose last row is today's live bar."""
    last = panel.dates[-1].astype("datetime64[D]").astype(object)
    if last > today:
        return panel
    if last < today:
        dates = np.append(panel.dates, np.datetime64(today, "D"))
        carry = lambda a: np.vstack([a, a[-1:]])  # noqa: E731
        open_, high, low, close = (
            carry(panel.open),
            carry(panel.high),
            carry(panel.low),
            carry(panel.close),
        )
        adj_close = carry(panel.adj_close)
        volume = np.vstack([panel.volume, np.full((1, panel.volume.shape[1]), np.nan)])
        # A carried row is the last close on every field, not the last high.
        open_[-1] = high[-1] = low[-1] = close[-1] = panel.close[-1]
    else:
        dates = panel.dates
        open_, high, low, close = (
            panel.open.copy(),
            panel.high.copy(),
            panel.low.copy(),
            panel.close.copy(),
        )
        adj_close, volume = panel.adj_close.copy(), panel.volume
    prev_close = close[-2] if close.shape[0] > 1 else close[-1]
    prev_adj = adj_close[-2] if adj_close.shape[0] > 1 else adj_close[-1]
    for symbol, quote in quotes.items():
        if symbol not in panel.tickers:
            continue
        j = panel.index(symbol)
        last_price = float(getattr(quote, "last", 0.0) or 0.0)
        if last_price <= 0:
            continue
        open_[-1, j] = float(getattr(quote, "open", 0.0) or last_price)
        high[-1, j] = max(float(getattr(quote, "high", 0.0) or last_price), last_price)
        low[-1, j] = min(float(getattr(quote, "low", 0.0) or last_price), last_price)
        close[-1, j] = last_price
        # Adjusted close moves with the raw close: the ratio carries any
        # split or dividend adjustment already in the history.
        with np.errstate(all="ignore"):
            ratio = prev_adj[j] / prev_close[j] if prev_close[j] > 0 else 1.0
        adj_close[-1, j] = last_price * (ratio if np.isfinite(ratio) else 1.0)
    return replace(
        panel,
        dates=dates,
        open=open_,
        high=high,
        low=low,
        close=close,
        adj_close=adj_close,
        volume=volume,
    )


# The live panel and the technical analyst's read of it, one run per candle.
def _live_read(store, quotes: dict, today: date) -> dict:
    """Return {"panel": live, "opinion": opinion}, cached by the candle."""
    key = (
        today,
        tuple(sorted((s, str(getattr(q, "bar", ""))) for s, q in quotes.items())),
    )
    if _cache["key"] == key:
        return _cache["value"]  # type: ignore[return-value]
    panel, sides = book_panel(store)
    live = with_live_row(panel, quotes, today)
    # The day's regime picks the analyst's playbook, as it does in the
    # desk run, so the live rank and the record's rank read the same way.
    view = regime.opine(live, sides, tightening_for(store, live, None))
    opinion = technical_analyst.opine(live, view.ai_trend)
    _cache["key"], _cache["value"] = key, {"panel": live, "opinion": opinion}
    return _cache["value"]  # type: ignore[return-value]


# The technical analyst's rank per name at the live price and at the last
# close, one run per candle.
def technical_now(store, quotes: dict, today: date | None = None) -> dict:
    """Return {symbol: {"now": rank, "close": rank}} for the names quoted."""
    today = today or datetime.now(NEW_YORK).date()
    read = _live_read(store, quotes, today)
    panel = read["panel"]
    scores = read["opinion"].scores
    if scores.shape[0] < 2:
        return {}
    ranks = baselines.percentile_rank(scores[-2:])
    # The stance the evening rule would hold with the live bar as today's
    # session: bullish or bearish only once the rank has sat past the line
    # for the rule's run of sessions (opinions.PERSISTENCE), so a name on a
    # threshold does not change grade every candle. Thresholding the live
    # rank alone did exactly that: ETN, bullish at the close on a rank of
    # 60 held over from earlier sessions, read neutral at 54 an hour later
    # and the page showed C for a name the rule still graded B.
    stances = read["opinion"].stances()
    out = {}
    for symbol in quotes:
        if symbol not in panel.tickers:
            continue
        j = panel.index(symbol)
        now, close = float(ranks[-1, j]), float(ranks[-2, j])
        if np.isfinite(now) and np.isfinite(close):
            out[symbol] = {"now": now, "close": close, "stance": int(stances[-1, j])}
    return out


# The option walls read from the newest stored chain for `symbol`, at
# `price`, as distances from it. None when the store has no chain or the
# price is absent, so a missing options partition costs the read nothing.
def _walls_for(store, symbol: str, price: float | None, today: date) -> dict | None:
    """Return the option walls near `price`, or None when none are stored."""
    if store is None or not price or price <= 0:
        return None
    frame = store.read_frame(options.KIND, symbol, today)
    if frame is None:
        return None
    columns, _meta = frame
    rows = options.rows_from_frame(columns)
    if not rows:
        return None
    w = options.walls(rows, price, today)
    out: dict = {
        "expiry": w.expiry.isoformat() if w.expiry else None,
        "put_wall": w.put_wall,
        "call_wall": w.call_wall,
        "put_wall_oi": w.put_wall_oi,
        "call_wall_oi": w.call_wall_oi,
        "net_gamma": w.net_gamma,
    }
    if w.put_wall:
        out["put_wall_distance"] = w.put_wall / price - 1.0
    if w.call_wall:
        out["call_wall_distance"] = w.call_wall / price - 1.0
    return out


# The technical features the analyst would cite for each name, read on the
# live panel and split by horizon, one run per candle. The drill-down shows
# these so a person sees the short-term where-price-is-now read beside the
# longer timeframes instead of one number.
def technical_detail(store, quotes: dict, today: date | None = None) -> dict:
    """Return each quoted name's technical features, split by horizon."""
    today = today or datetime.now(NEW_YORK).date()
    read = _live_read(store, quotes, today)
    panel = read["panel"]
    opinion = read["opinion"]
    scores = opinion.scores
    candles = daily_technical._candles(panel)
    last = panel.adj_close.shape[0] - 1
    out: dict = {}
    for symbol in quotes:
        if symbol not in panel.tickers:
            continue
        j = panel.index(symbol)
        feature = {}
        for name in SHORT + MEDIUM + LONG:
            arr = opinion.evidence.get(name)
            if arr is None or arr.shape[0] < 1:
                continue
            value = float(arr[-1, j])
            if np.isfinite(value):
                feature[name] = round(value, 4)
        now = None
        if scores.shape[0] >= 1 and np.isfinite(scores[-1, j]):
            now = float(baselines.percentile_rank(scores[-1:])[-1, j])
            now = round(now, 4)
        entry = {
            "now": now,
            "short": {k: feature[k] for k in SHORT if k in feature},
            "medium": {k: feature[k] for k in MEDIUM if k in feature},
            "long": {k: feature[k] for k in LONG if k in feature},
        }
        candle = _today_candle(candles, panel, last, j)
        if candle is not None:
            entry["candle"] = candle
        price = (
            float(panel.adj_close[-1, j])
            if np.isfinite(panel.adj_close[-1, j])
            else None
        )
        walls = _walls_for(store, symbol, price, today)
        if walls is not None:
            entry["walls"] = walls
        out[symbol] = entry
    return out


# The line a percentage distance reads as, e.g. "12.6% above".
def _pct_word(v) -> str | None:
    """Return a distance's line, or None without a finite figure."""
    if v is None or not np.isfinite(v):
        return None
    direction = "above" if v > 0 else "below" if v < 0 else "at"
    return f"{abs(v * 100):.1f}% {direction}"


# What a level kind reads as, so a line can name the level rather than
# only say how far away price sits.
def _level_word(kind, side: str) -> str | None:
    """Return the plain name of a level kind, or None."""
    if kind is None or not np.isfinite(kind):
        return None
    if int(kind) == 1:
        return "a swing low" if side == "support" else "a swing high"
    if int(kind) == 2:
        return "the 50-day average"
    if int(kind) == 3:
        return "the 200-day average"
    if int(kind) == 4:
        return "the weekly 21-day average"
    return None


# The line for the 21/50 EMA convergence.
def _convergence_line(conv) -> str:
    """Return the line for a converging_21_50 reading."""
    if conv > 0:
        return "the 21/50 EMAs are squeezing upward (a bullish cross is forming)"
    if conv < 0:
        return "the 21/50 EMAs are rolling over (a bearish cross is forming)"
    return "the 21/50 EMAs are not converging"


# The support and resistance lines, each naming what the level is.
def _level_lines(s: dict) -> list[str]:
    """Return the support and resistance lines for a detail's short dict."""
    lines_out: list[str] = []
    for side in ("support", "resistance"):
        dist = s.get(f"{side}_distance")
        if dist is None or not np.isfinite(dist):
            continue
        base = f"{_pct_word(dist)} nearest {side}"
        what = _level_word(s.get(f"{side}_kind"), side)
        lines_out.append(f"{base} — {what}" if what else base)
    return lines_out


# The short horizon's lines: where price sits against the averages, the
# daily trend, and the support and resistance that frame it.
def _short_lines(s: dict) -> list[str]:
    """Return the short-term readable lines for a detail's short dict."""
    short: list[str] = []
    conv = s.get("converging_21_50")
    if conv is not None and np.isfinite(conv):
        short.append(_convergence_line(conv))
    short.extend(_level_lines(s))
    e21 = _pct_word(s.get("ema21_distance"))
    if e21:
        short.append(f"{e21} the 21-day EMA")
    dt = s.get("daily_trend")
    if dt is not None and np.isfinite(dt):
        short.append(
            "daily trend up"
            if dt > 0
            else "daily trend down" if dt < 0 else "daily trend flat"
        )
    stack = s.get("stack_order")
    if stack is not None and np.isfinite(stack):
        if stack >= 3:
            short.append("full bullish EMA stack (9 > 21 > 50 > 200)")
        elif stack > 0:
            short.append(f"{stack:.0f} of the three EMA pairs stacked up")
        elif stack == 0:
            short.append("EMA stack mixed")
        else:
            short.append(f"{-stack:.0f} of the three EMA pairs stacked down")
    e50 = _pct_word(s.get("ema50_distance"))
    if e50:
        short.append(f"{e50} the 50-day EMA")
    rp = s.get("range_position_60")
    if rp is not None and np.isfinite(rp):
        short.append(f"sitting {rp * 100:.0f}% up in its 60-day range")
    return short


# The medium horizon's lines: the weekly trend and the weekly stack.
def _medium_lines(m: dict) -> list[str]:
    """Return the medium-term readable lines for a detail's medium dict."""
    medium: list[str] = []
    wt = m.get("weekly_trend")
    if wt is not None and np.isfinite(wt):
        medium.append(
            "weekly trend up"
            if wt > 0
            else "weekly trend down" if wt < 0 else "weekly trend flat"
        )
    ws = m.get("weekly_stack")
    if ws is not None and np.isfinite(ws):
        medium.append(
            "the weekly 9 EMA is above the 21"
            if ws > 0
            else "the weekly 9 EMA is below the 21"
        )
    return medium


# The long horizon's lines: the yearly range, the 200-day averages and the
# slow momentum. Both the EMA and the simple average are cited: a person
# watches the 200 SMA as the standing trend line, and a read that names
# only the EMA leaves that number out.
def _long_lines(features: dict) -> list[str]:
    """Return the long-term readable lines for a detail's long dict."""
    long: list[str] = []
    h52 = _pct_word(features.get("high_52w_distance"))
    lo52 = _pct_word(features.get("low_52w_distance"))
    if h52 and lo52:
        long.append(f"{h52} its 52-week high · {lo52} its 52-week low")
    e200 = _pct_word(features.get("ema200_distance"))
    if e200:
        long.append(f"{e200} the 200-day EMA")
    s200 = _pct_word(features.get("sma200_distance"))
    if s200:
        long.append(f"{s200} the 200-day simple average")
    mom = features.get("residual_momentum_120")
    if mom is not None and np.isfinite(mom):
        long.append("slow momentum positive" if mom >= 0 else "slow momentum negative")
    return long


# The detail for one name rendered as readable lines, grouped by horizon.
# These are the fallback when no model is available, and the text a model
# is given to rewrite in its own words, so the same numbers are never
# rendered two ways.
def lines(detail: dict) -> dict[str, list[str]]:
    """Return the readable lines for a technical detail, by horizon."""
    short = _short_lines(detail.get("short") or {})
    candle = detail.get("candle")
    if candle:
        short.append(_candle_line(candle))
    return {
        "short": short,
        "medium": _medium_lines(detail.get("medium") or {}),
        "long": _long_lines(detail.get("long") or {}),
    }


# The named reversal candle on today's daily bar, read off the daily OHLC
# the way the analyst reads it: an engulfing (with how much of the prior
# body it takes), a shooting star or a hammer (with how long the wick is
# against the body). The read surfaces the candle because a person
# watching the daily chart sees it first, and a bearish engulfing at
# today's close is the daily evidence for a weekly turn the medium
# horizon already points at.
def _today_candle(candles: dict, panel: Panel, t: int, j: int) -> dict | None:
    """Return {name, detail} for the candle on session t, or None."""
    o, h, low, c = panel.open, panel.high, panel.low, panel.close
    body = abs(c[t, j] - o[t, j])
    if not np.isfinite(body) or body <= 0:
        return None

    def fires(name: str) -> bool:
        arr = candles.get(name)
        return arr is not None and np.isfinite(arr[t, j]) and arr[t, j] > 0

    if fires("bearish_engulfing") or fires("bullish_engulfing"):
        name = (
            "bearish engulfing"
            if fires("bearish_engulfing")
            else "bullish engulfing"
        )
        prev_body = abs(c[t - 1, j] - o[t - 1, j]) if t >= 1 else np.nan
        detail = (
            f"{body / prev_body:.1f}x the prior session's body"
            if np.isfinite(prev_body) and prev_body > 0
            else ""
        )
        return {"name": name, "detail": detail}
    if fires("shooting_star"):
        upper = h[t, j] - max(o[t, j], c[t, j])
        detail = (
            f"upper wick {upper / body:.1f}x the body"
            if np.isfinite(upper) and upper > 0
            else ""
        )
        return {"name": "shooting star", "detail": detail}
    if fires("hammer"):
        lower = min(o[t, j], c[t, j]) - low[t, j]
        detail = (
            f"lower wick {lower / body:.1f}x the body"
            if np.isfinite(lower) and lower > 0
            else ""
        )
        return {"name": "hammer", "detail": detail}
    return None


# The candle as one readable line for the short horizon.
def _candle_line(candle: dict) -> str:
    """Return the line for a candle read on today's daily bar."""
    if candle.get("detail"):
        return f"today's daily candle is a {candle['name']}, {candle['detail']}"
    return f"today's daily candle is a {candle['name']}"
