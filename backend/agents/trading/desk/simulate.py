"""The whole desk walked through history as an account, not as a weight vector.

`sizing.simulate` runs a score matrix through the sizing engine and answers
a narrow question: is this ranking worth anything. The desk is more than a
ranking. It grades, it multiplies each position by that grade, it cuts
exposure when the regime says so, and it leans on steadier names while
money is tightening. None of that reached the book's own backtest, so
every risk rule was measured in a scratch script and never in the thing
that reports the book's numbers.

This walks the rules themselves, one session at a time:

  every `rebalance` sessions   the graded names are sized by the engine,
                               each multiplied by its grade and by the
                               regime's exposure for that session
  in between                   nothing trades except an exit the exit
                               analyst names
  always                       a decision on session t uses only what was
                               known at t's close and is filled at t+1's
                               open, at a cost

What it holds is shares and cash
--------------------------------
The first version of this file held a weight vector and applied
close-to-close returns to it. Both were wrong, and a review caught them:

* It never read an opening price. A decision made at Friday's close was
  paid Monday's whole move including the overnight gap - the part a fill
  at Monday's open cannot capture, and exactly the part that moves on
  news the decision was made before.

* Holding weights constant between rebalances is not holding anything. A
  position that doubles has its weight sold back to target the next
  session, so the book quietly rebalanced daily while claiming to
  rebalance every twenty sessions. Turnover was understated and a
  winner never compounded: a tenth of the book quadrupling should take
  equity from 1.00 to 1.30, and it produced 1.21.

So the ledger is shares and cash now. Prices are adjusted throughout - the
opening price is scaled by the same factor that turns the close into the
adjusted close, because mixing a raw open with an adjusted close puts a
split in the middle of a return.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from backend.agents.trading.desk import exit as exit_analyst
from backend.agents.trading.desk import funded_execution, grading, planner, risk
from backend.agents.trading.desk import trend_brake as trend_brake_rule
from backend.market.panel import Panel

REBALANCE = 20
# Whether the cash an exit frees goes back to work in the names still held,
# or waits until the next rebalance.
REDEPLOY = True
COST_BPS = 10.0
MIN_TRADE = 0.005
START_EQUITY = 1.0
FUNDING_MODEL = "cash-at-fill-v1"

# The one versioned execution policy the live paper account runs, used
# wherever a backtest is published so the measured curve and the live book
# decide the same way. Each flag is a `simulate.run` argument; the paper
# account applies them at the rebalance (the band blocker on buys) and at
# the fill (sells at the close, holds a sell on a name up at the open).
# Any change to how the live book executes edits this dict and nothing
# else, so a backtest cannot drift from the account it is measured against.
LIVE_POLICY: dict[str, bool] = {
    "block_overbought": True,
    "exit_at_close": True,
    "green_day_skip": True,
    "live_midcycle": True,
    "deferred_buys": True,
}


# The session's inputs to the shared paper planner, read from the book and
# the report the way `market_daily` reads them from the account and the desk.
def _paper_inputs(book, report, t, blocked):
    """Return (prices, held, grades, finished, excluded) for session `t`."""
    from backend.agents.trading.desk import paper

    panel = report.panel
    prices = {
        s: float(panel.adj_close[t, j])
        for j, s in enumerate(panel.tickers)
        if np.isfinite(panel.adj_close[t, j]) and panel.adj_close[t, j] > 0
    }
    held = {
        s: float(book.shares[j])
        for j, s in enumerate(panel.tickers)
        if book.shares[j] > 0
    }
    letters = {0: "C", 1: "B", 2: "A", 3: "A+"}
    grades = {
        s: (g if isinstance(g, str) else letters.get(int(g), "C"))
        for s, g in zip(panel.tickers, report.graded.grades[t], strict=True)
    }
    finished = {
        s: "grade rotation" for s in held if grades[s] not in paper.ENTRY_MIN_GRADE
    }
    excluded = {
        s for j, s in enumerate(panel.tickers) if blocked is not None and blocked[t, j]
    }
    return prices, held, grades, finished, excluded


# Replay the paper planner's joint rotation and entry orders without share rounding.
# `deferred`, when given, is the previous session's unpaid buy shares per
# symbol, retried first from the cash on hand exactly as `paper.plan` does;
# `unfunded`, when a dict is given, receives tonight's unpaid buy shares.
def _live_midcycle(book, report, t, bands, blocked, deferred=None, unfunded=None):
    from backend.agents.trading.desk import paper

    panel = report.panel
    prices, held, grades, finished, excluded = _paper_inputs(book, report, t, blocked)
    entries = {
        s: float(bands[t, j])
        for j, s in enumerate(panel.tickers)
        if s != panel.benchmark and np.isfinite(bands[t, j])
    }
    equity = book.equity(panel.adj_close[t])
    session = str(panel.dates[t])
    retry, _unpaid = paper._fund_buys(
        paper._deferred_orders(
            deferred or {},
            held,
            prices,
            equity,
            grades,
            finished,
            excluded,
            session,
            paper.PaperState(),
            whole_shares=False,
        ),
        book.cash,
        prices,
        whole_shares=False,
    )
    spent = sum(o.qty * prices[o.symbol] for o in retry)
    reserved = dict(held)
    for order in retry:
        reserved[order.symbol] = reserved.get(order.symbol, 0.0) + order.qty
    orders = retry + paper.midcycle_orders(
        session,
        paper.PaperState(),
        equity,
        reserved,
        prices,
        grades,
        finished,
        entries,
        excluded,
        book.cash - spent,
        whole_shares=False,
        unfunded=unfunded,
    )
    wanted = book.shares.copy()
    for order in orders:
        wanted[panel.index(order.symbol)] += order.qty * (
            1 if order.side == "buy" else -1
        )
    return wanted


# The buy shares a basket asks for beyond the cash on hand, per symbol, the
# way `paper.bound_orders` scales a rebalance's buys to the cash: sells fill
# on the following close and pay for nothing tonight.
def _unpaid_buys(book, order, prices) -> dict[str, float]:
    """Return {symbol: buy shares the cash on hand cannot pay for}."""
    priced = np.isfinite(prices) & (prices > 0)
    buys = np.where(priced, np.maximum(order - book.shares, 0.0), 0.0)
    requested = float((buys * np.where(priced, prices, 0.0)).sum())
    if requested <= 0:
        return {}
    scale = min(1.0, max(0.0, book.cash) / requested)
    return {
        book.tickers[j]: float(buys[j] * (1.0 - scale))
        for j in np.flatnonzero(buys > 0)
        if buys[j] * (1.0 - scale) > 1e-12
    }


# The previous session's unpaid remainder, retried on a plain hold session
# (no `live_midcycle`): the same gates and cap as the paper book, bounded
# by the cash on hand, added to the shares the book already means to hold.
def _deferred_leg(book, report, t, blocked, deferred, order) -> np.ndarray:
    """Return `order` with the retried remainder's shares added."""
    from backend.agents.trading.desk import paper

    panel = report.panel
    prices, held, grades, finished, excluded = _paper_inputs(book, report, t, blocked)
    retry, _unpaid = paper._fund_buys(
        paper._deferred_orders(
            deferred,
            held,
            prices,
            book.equity(panel.adj_close[t]),
            grades,
            finished,
            excluded,
            str(panel.dates[t]),
            paper.PaperState(),
            whole_shares=False,
        ),
        book.cash,
        prices,
        whole_shares=False,
    )
    wanted = np.array(order, dtype=float)
    for o in retry:
        wanted[panel.index(o.symbol)] += o.qty
    return wanted


@dataclass(frozen=True)
class SimTrade:
    """One position, from the session it was opened to the session it left."""

    ticker: str
    opened: str
    closed: str | None
    weight: float
    grade: str
    reason: str
    ret: float


@dataclass(frozen=True)
class SimResult:
    """What the desk's rules did, session by session."""

    dates: np.ndarray
    returns: np.ndarray  # (T,) daily, net of cost
    invested: np.ndarray  # (T,) the fraction of equity held in positions
    trades: list[SimTrade] = field(default_factory=list)
    rebalances: int = 0
    equity: np.ndarray | None = None  # (T,) the account's value
    dip_adds: int = 0  # mid-cycle adds the dip rule made
    traded: float = 0.0  # notional bought and sold over the run
    top_weight: np.ndarray | None = None  # (T,) the largest position's share of equity
    # The optional funded-allocation trace: one entry per decision day, from
    # the real ledger, absent on the incumbent path.
    trace: list[dict] | None = None
    # The trend brake's state per session, True while it held the book at
    # `brake_scale`; all False when the brake was off, so a scorecard can
    # read the shadow back without knowing whether it ran.
    risk_off: np.ndarray | None = None

    # The usual four numbers, from the daily series.
    def stats(self) -> dict[str, float]:
        """Return annual return, volatility, Sharpe and worst drawdown."""
        daily = self.returns[np.isfinite(self.returns)]
        if len(daily) < 2:
            # Too short to measure, but still the full shape, so a caller
            # that reads every key (the scorecard's table) never sees a
            # missing one.
            return {
                "annual": float("nan"),
                "cagr": float("nan"),
                "volatility": float("nan"),
                "sharpe": float("nan"),
                "drawdown": float("nan"),
                "total": float("nan"),
                "turnover": float("nan"),
                "max_weight": float("nan"),
                "years": 0.0,
            }
        curve = np.cumprod(1.0 + daily)
        annual = float(daily.mean() * 252)
        volatility = float(daily.std() * np.sqrt(252))
        drawdown = float(
            (curve / np.maximum.accumulate(np.r_[1.0, curve])[1:] - 1.0).min()
        )
        years = len(daily) / 252.0
        # The objective's numbers: compounded money, what it cost to
        # trade, and how concentrated the book got. `cagr` is the
        # compounded rate, not the arithmetic mean `annual`; turnover is
        # notional traded per year over the average account; max_weight
        # the largest single position the run ever held.
        cagr = float(curve[-1] ** (1.0 / years) - 1.0) if years > 0 else float("nan")
        mean_equity = (
            float(np.nanmean(self.equity)) if self.equity is not None else float("nan")
        )
        turnover = (
            self.traded / mean_equity / years
            if years > 0 and np.isfinite(mean_equity) and mean_equity > 0
            else float("nan")
        )
        top = (
            self.top_weight[np.isfinite(self.top_weight)]
            if self.top_weight is not None
            else np.array([])
        )
        return {
            "annual": annual,
            "cagr": cagr,
            "volatility": volatility,
            "sharpe": annual / volatility if volatility > 0 else float("nan"),
            "drawdown": drawdown,
            "total": float(curve[-1] - 1.0),
            "turnover": turnover,
            "max_weight": float(top.max()) if len(top) else float("nan"),
            "years": years,
        }


# The opening price on the same basis as the adjusted close, so a return
# from one to the other does not straddle a split or a dividend.
def adjusted_open(panel: Panel) -> np.ndarray:
    """Return (T, N) opening prices adjusted the way the close is."""
    with np.errstate(all="ignore"):
        factor = np.where(panel.close > 0, panel.adj_close / panel.close, np.nan)
    return panel.open * factor


@dataclass(frozen=True)
class DipRule:
    """Buy a graded name's own sharp fall between rebalances.

    Measured on the book: a fall of 8% or more within three sessions, at
    least five points worse than the book's own move, in a name graded A
    or A+ that day, bought at that close, earned +1.23% beta-adjusted over
    the next ten sessions against +0.64% for an A name on an ordinary day;
    waiting two sessions for the low to hold gave all of it back. So the
    rule acts the day the fall completes and fills at the next open.
    """

    fall: float = 0.08  # the name's own fall over up to three sessions
    vs_book: float = 0.05  # how much worse than the book's move
    add: float = 0.03  # weight of equity added, from cash
    min_grade: str = grading.A
    name_cap: float = 0.15
    # Funded: the add is taken pro rata from the other held names, so the
    # gross the regime chose is unchanged and only the selection moves.
    # Unfunded, it comes from cash and raises the gross.
    funded: bool = False
    # A precomputed (T, N) signal in place of the fall rule, so any
    # mid-cycle add (a breakout, a structure state) is measured inside
    # the book's own rules the same way. The signal is responsible for
    # its own grade condition.
    signal: np.ndarray | None = None
    # A (T, N) per-name entry size in weight, used in place of `add` when
    # given. The flat `add` sizes every entry the same; this lets the size
    # follow the score that ranked the name in the first place.
    size: np.ndarray | None = None


# Which (session, name) pairs the dip rule fires on: the name's fall over
# one to three sessions, against the book's own move over the same
# sessions, in a name graded at least `min_grade` that day.
def _dip_signal(report, panel: Panel, rule: DipRule) -> np.ndarray:
    logr = panel.log_returns()
    rows = logr.shape[0]
    in_book = np.array([t in report.sides for t in panel.tickers])
    in_book[panel.index(panel.benchmark)] = False
    with np.errstate(all="ignore"):
        book = np.nanmean(np.where(in_book[None, :], logr, np.nan), axis=1)
    book = np.where(np.isfinite(book), book, 0.0)
    clean = np.where(np.isfinite(logr), logr, 0.0)
    own = np.full(logr.shape, np.inf)
    against = np.full(logr.shape, np.inf)
    for k in (1, 2, 3):
        own_k = np.zeros_like(clean)
        book_k = np.zeros(rows)
        own_k[k - 1 :] = (
            np.cumsum(clean, axis=0)[k - 1 :]
            - np.r_[np.zeros((1, clean.shape[1])), np.cumsum(clean, axis=0)][
                : rows - k + 1
            ]
        )
        book_k[k - 1 :] = (
            np.cumsum(book)[k - 1 :] - np.r_[0.0, np.cumsum(book)][: rows - k + 1]
        )
        own = np.minimum(own, own_k)
        against = np.minimum(against, own_k - book_k[:, None])
    graded = report.graded.grades >= grading.ORDINAL[rule.min_grade]
    fell = (own <= np.log(1.0 - rule.fall)) & (against <= np.log(1.0 - rule.vs_book))
    return fell & graded & in_book[None, :]


# Add the rule's weight to every firing name, from cash, inside the name
# cap; returns the new target and how many names were added to.
def _dip_add(
    target, fired, rule: DipRule, book, prices, sizes=None
) -> tuple[np.ndarray, int]:
    out = target.copy()
    added = 0
    taken = 0.0
    for column in np.flatnonzero(fired):
        if not np.isfinite(prices[column]) or prices[column] <= 0:
            continue
        room = rule.name_cap - out[column]
        if room <= 1e-6:
            continue
        # A per-name size when the caller supplies one, so an entry can be
        # sized on how good the opportunity is rather than taking the same
        # slice of the account whatever the name.
        want = rule.add if sizes is None else float(sizes[column])
        if not np.isfinite(want) or want <= 0:
            continue
        amount = min(want, room)
        out[column] += amount
        taken += amount
        added += 1
    if rule.funded and added and taken > 0:
        others = np.ones(len(out), dtype=bool)
        others[np.flatnonzero(fired)] = False
        pool = float(out[others].sum())
        if pool > 0:
            out[others] *= max(0.0, 1.0 - taken / pool)
    return out, added


# The target weight of every name on a rebalance session.
#
# This is `risk.desk_targets` and nothing else. The two used to be separate
# calculations in a different order - the paper path tilted and capped
# before the grade and exposure multipliers, this one after - and capping
# and scaling do not commute, so in a tightening regime they disagreed on
# every name. A backtest that sizes differently from the book it describes
# is not evidence about that book.
#
# The panel is sliced to `t` so the engine's volatility and the tilt read
# the session being decided rather than the end of history.
def _targets(report, panel: Panel, config, t: int) -> np.ndarray:
    from dataclasses import replace as _replace

    window = _replace(
        panel,
        dates=panel.dates[: t + 1],
        open=panel.open[: t + 1],
        high=panel.high[: t + 1],
        low=panel.low[: t + 1],
        close=panel.close[: t + 1],
        adj_close=panel.adj_close[: t + 1],
        volume=panel.volume[: t + 1],
    )
    _positions, targets = risk.desk_targets(
        report.scores[t],
        report.graded.grades[t],
        window,
        report.regime.states[t],
        config,
    )
    targets[window.index(window.benchmark)] = 0.0
    return targets


# Apply the buy gate to a rebalance's targets: cap any increase for names
# the gate denies, so trims and sells pass but the book cannot grow a
# position the gate refused.
def _gated_targets(target, fired, blocked, weights, t) -> np.ndarray:
    """Return `target` with denied increases capped at `weights`."""
    gate = np.zeros(weights.shape, dtype=bool)
    if fired is not None:
        gate |= ~fired[t]
    if blocked is not None:
        gate |= blocked[t]
    blocked_inc = gate & (target > weights)
    return np.where(blocked_inc, weights, target)


# Whether each name closes above its 200-day average, the standing
# per-name trend read. A close at the bands means different things in an
# uptrend and a downtrend, and both candidate rules below are gated on it.
def _trend_up(panel: Panel) -> np.ndarray:
    """Return (T, N) True where a name closes above its 200-day average."""
    from backend.market import technical

    features = technical.technical_features(panel)
    index = {n: i for i, n in enumerate(technical.TECHNICAL_NAMES)}
    return features[:, :, index["ema200_distance"]] > 0


# Which (session, name) pairs a lower-band dip fires on: price in the
# bottom of its 20-day band while the name is still in its long uptrend.
# This is the mirror of the exit analyst's upper-band read, and the dip is
# only a dip in a trend - a lower band with no trend is a falling knife.
def _band_dip_signal(report, panel: Panel, band_up: np.ndarray) -> np.ndarray:
    """Return (T, N) True where a name is oversold at the lower band in an uptrend."""
    from backend.agents.trading.desk import exit as exit_analyst

    ev = exit_analyst.evidence(panel)
    in_book = np.array([t in report.sides for t in panel.tickers])
    in_book[panel.index(panel.benchmark)] = False
    graded = report.graded.grades >= grading.ORDINAL[grading.A]
    with np.errstate(invalid="ignore"):
        # Band position runs 0 at the lower band to 1 at the upper (bands.py),
        # so the lower fifth is <= 0.20, the mirror of the exit analyst's
        # upper fifth (>= 0.80). A threshold below the band's own span would
        # be a close that never happens and a buy option that can never fire.
        at_lower = (ev.band_position <= 0.20) & np.isfinite(ev.band_position)
    return at_lower & band_up & graded & in_book[None, :]


# The mid-cycle add signal the run will use, whichever way it is made: a
# caller's own precomputed signal, the fall rule, or the band-dip read.
def _dip_signal_for(
    report, panel: Panel, dip, band_dip_buy: bool, trend_up
) -> np.ndarray:
    """Return the (T, N) dip signal the run should act on, or None."""
    if band_dip_buy:
        return _band_dip_signal(report, panel, trend_up)
    if dip is not None:
        if dip.signal is not None:
            return dip.signal
        return _dip_signal(report, panel, dip)
    return None


# The buy gates and the dip signal the run is asked to apply, all read in
# one place so the session loop only decides what to trade.
def _signals_for(
    report, entry_gate, block_overbought, band_dip_buy, trend_gated_exit, dip
):
    """Return (fired, blocked, trend_up, dips) the run's options require."""
    fired = blocked = None
    if entry_gate:
        from backend.agents.trading.desk import entry
        from backend.market import levels

        fired = entry.entries(report.panel, levels.level_features(report.panel)).any()
    if block_overbought:
        blocked = exit_analyst.evidence(report.panel).signalled()
    trend_up = None
    if band_dip_buy or trend_gated_exit:
        trend_up = _trend_up(report.panel)
    dips = _dip_signal_for(report, report.panel, dip, band_dip_buy, trend_up)
    return fired, blocked, trend_up, dips


# Validate a research exposure path before any simulated orders are planned.
def _event_path(path: np.ndarray | None, rows: int) -> np.ndarray | None:
    if path is None:
        return None
    path = np.asarray(path, dtype=float)
    if path.shape != (rows,) or not np.all(
        np.isfinite(path) & (path > 0) & (path <= 1)
    ):
        raise ValueError("Event exposure must be one finite (0, 1] value per session")
    return path


# Scale fresh targets absolutely and held targets relatively, avoiding repeated cuts.
# `label` names the overlay that moved the ceiling in the trade's reason.
def _event_target(target, path, t, rebalanced, previous, reason, label="FOMC"):
    if path is None:
        return target, previous, reason, False
    scale = float(path[t])
    target = target * (scale if rebalanced else scale / previous)
    changed = scale != previous
    if changed:
        reason = (
            f"{label} risk reduction"
            if scale < previous
            else f"{label} risk restoration"
        )
    return target, scale, reason, changed


# The one exposure ceiling the incumbent loop applies: the FOMC path and the
# trend brake's path composed as a per-session minimum, so whichever overlay
# asks for less exposure on a session is the one that binds. Either alone
# is passed through unchanged, so a run with one overlay is byte-identical
# to what it was before the other existed.
def _ceiling_path(event_exposure, brake_path):
    """Return the per-session ceiling, or None when neither overlay is on."""
    if brake_path is None:
        return event_exposure
    if event_exposure is None:
        return brake_path
    return np.minimum(event_exposure, brake_path)


# Fill one event transition and retain only the shares that actually changed hands.
def _settle_event(book, baseline, sold, scale, prices, t):
    if baseline is None:
        baseline = book.shares.copy()
        sold = np.zeros_like(baseline)
    before = book.shares.copy()
    if scale < 1:
        cut = np.maximum(0, baseline * (1 - scale) - sold)
        order = np.maximum(0, before - cut)
        reason = "FOMC risk reduction"
    else:
        restore = np.minimum(sold, np.maximum(0, baseline - before))
        order = before + restore
        reason = "FOMC risk restoration"
    book.settle(order, prices, t, reason)
    sold += before - book.shares
    remaining = np.minimum(sold, np.maximum(0, baseline - book.shares))
    priced = np.isfinite(prices) & (prices > 0)
    if scale == 1:
        complete = np.all(remaining < 1e-8)
        cash_limited = book.cash <= 1e-12 and np.all(priced | (remaining < 1e-8))
        if complete or cash_limited:
            baseline = None
    return baseline, sold


# Whether a value parses as a plain ISO YYYY-MM-DD date.
def _is_iso_date(value: str) -> bool:
    """Return True when `value` parses as a plain ISO YYYY-MM-DD date."""
    try:
        parsed = np.datetime64(value, "D")
    except (TypeError, ValueError):
        return False
    return not np.isnat(parsed) and len(value) == 10


# Normalize the optional explicit company-removal map into {ISO date: set}.
def _excluded_by_session(raw) -> dict[str, frozenset[str]]:
    """Return `raw` as {ISO date: frozenset of symbols}, validated.

    A key that is not an ISO date is a caller error, because a silently
    ignored date would leave a company exit unapplied. Values may be any
    iterable of symbols; each is normalized to its string form so the map
    matches `str(panel.dates[t])` however the caller wrote the key.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("excluded_symbols_by_session must be a mapping")
    out: dict[str, frozenset[str]] = {}
    for key, symbols in raw.items():
        date_key = str(key)
        if not _is_iso_date(date_key):
            raise ValueError(
                f"excluded_symbols_by_session keys must be ISO dates, got {date_key!r}"
            )
        out[date_key] = frozenset(str(symbol) for symbol in symbols)
    return out


# Walk the desk's rules, optionally applying the selected event execution lifecycle.
def run(  # noqa: C901 - explicit chronological order and event/fill boundaries
    report,
    since: date | None = None,
    config=None,
    rebalance: int = REBALANCE,
    cost_bps: float = COST_BPS,
    use_exits: bool = True,
    redeploy: bool = REDEPLOY,
    allocator=None,
    dip: "DipRule | None" = None,
    exits=None,
    grace: int = exit_analyst.GRACE,
    entry_gate: bool = False,
    block_overbought: bool = False,
    band_dip_buy: bool = False,
    trend_gated_exit: bool = False,
    trim: float = 1.0,
    exit_at_close: bool = False,
    green_day_skip: bool = False,
    event_exposure: np.ndarray | None = None,
    event_lifecycle: bool = False,
    live_midcycle: bool = False,
    deferred_buys: bool = False,
    funded_allocation: bool = False,
    allocation_policy: str = "vol_trend",
    index_eligible: bool = False,
    benchmark_prices: dict | None = None,
    excluded_symbols_by_session: dict | None = None,
    trend_brake: bool = False,
    brake_scale: float = 0.5,
    brake_path_override: np.ndarray | None = None,
) -> SimResult:
    """Return the SimResult of the desk's rules over the panel.

    The defaults here are NOT the live configuration. Bare, this runs the
    exit analyst's between-rebalance exits (`use_exits=True`) and none of
    the account's execution rules; the live paper book runs no exit overlay
    and every flag in `LIVE_POLICY`. The published curve is the one
    `market_daily.curve_block` draws - `use_exits=False`, the live reset
    cadence, the FOMC lifecycle and `**LIVE_POLICY` - and a measurement
    meant to describe the account has to be made the same way.

    `allocator(report, panel, config, t)` replaces the rule's targets on
    rebalance sessions when given; everything else - fills, costs, the
    holding between rebalances - stays the desk's, so a learned
    allocation is measured by the book it makes and nothing else.
    `exits` is an ExitEvidence (anything with `signalled()`) in place of
    the exit analyst's own reading, so a candidate exit rule is measured
    inside the same book; `grace` is how many sessions a position is left
    alone after it opens before any exit may fire.

    `entry_gate` mirrors the live paper planner's rule: on a rebalance, no
    name may be bought or added to unless its entry trigger (a dip or a
    breakout) fired that session. Sells and trims still happen; a name
    already held keeps its weight but cannot grow without a trigger. This
    is how the measured book and the paper account decide the same orders.
    `block_overbought` is the narrow alternative: only a name whose daily
    is rejecting its upper Bollinger band (the exit analyst's own signal)
    is held back, so a book is not starved of every un-triggered buy.
    `band_dip_buy` adds the symmetric lower edge mid-cycle: a name at the
    bottom of its 20-day band (position <= 0.20, the mirror of the exit
    analyst's upper fifth) while still above its 200-day average is a dip
    in an uptrend and earns a small add. Measured on 2015-2026 it never
    fires - these ninety-four names hug the top of their own band
    (median band position +0.59), so a close in the bottom fifth does
    not occur; the fall-based dip rule is the dip that exists here.
    `trend_gated_exit` is the symmetric upper edge, and it encodes the rule
    that a band read only fires as an exit in a downtrend: the exit
    analyst's signal sells a name only when it closes below its 200-day
    average, and never in an uptrend, where an extension has measured as a
    pause, not a turn. Measured the same way it still loses a little
    (Sharpe 1.43 against 1.44 ungated; total +1242% against +1259%), the
    same reason as the retired overlay: these names resume after the
    pause. Both options stay for the measurement, not for trading.
    `trim` is how much of a signalled position an exit sells, from a
    third (1/3) through half (1/2) to the full exit (1.0). The retired
    overlay was a full exit; a partial trim keeps some of a name that may
    resume, which is the "take profit, keep the runner" version measured
    here to see whether partial beats doing nothing where the full exit
    lost. `exit_at_close` fills sells at the execution session's close instead
    of its open, so an exit captures the day's move rather than an opening
    print it has not seen. `green_day_skip` holds a sell back when the
    name opens up for the day - the desk never exits into a name's own
    rally. Both are the paper account's live behavior since 2026-09-11 and
    are measured here so the change from the old all-at-the-open fills is
    visible.

    `deferred_buys` is the paper book's deferred buy leg, and it needs
    `exit_at_close`: with buys paid from the cash on hand at the open and
    sells filled on the following close, a rebalance or rotation whose buys
    outran the cash left the proceeds idle until the next entry or reset.
    The unpaid remainder is retried once on the next session, under the
    mid-cycle entry's own gates (graded A or better, not blocked, inside
    the name cap, bounded by cash) and then dropped, exactly as
    `paper.plan` does it. Off, the run is identical to what it was, so the
    two can be compared.

    `funded_allocation` is the optional shared allocation path. When enabled,
    every session is a daily decision, but the stable unscaled stock
    composition is refreshed only on the scheduled rebalance clock (respecting
    `rebalance` and the initial `since` start) and supplied to each day's
    decision unchanged between those sessions, so a daily risk cut or a missing
    score on an ordinary day can neither lose the names to re-enter nor
    resurrect one that left. `allocation.decide` applies the current absolute
    regime and event ceilings against the dated SPY/QQQ context passed in
    `benchmark_prices`, and the shared `funded_execution.plan_funded` sizes the
    orders from the cash actually on hand - never from the proceeds of the same
    day's sells. Risk reductions fill at the next open even on a green open;
    there is no grace period and no closing-auction deferral, and the FOMC
    lifecycle is not applied a second time (`event_exposure[t]` is used as the
    absolute event ceiling instead). The options that would conflict -
    `event_lifecycle`, `green_day_skip`, `exit_at_close`, `live_midcycle`, the
    buy gates, `dip`, `exits` and a caller `allocator` - are refused rather
    than silently ignored; `use_exits` is not consulted because the daily
    decision replaces the exit analyst's between-rebalance exits. The result
    carries a per-session `trace` derived from the real ledger - composition,
    actual fills and fees, deltas over the union of holdings, plan blocked
    reasons, and an explicit `unavailable` marker when a held valuation is
    missing - so turnover, false exits, re-entry delay and actual exposure are
    measurable. `excluded_symbols_by_session`, a map of ISO decision dates to
    symbol sets, is the explicit company-removal input: the shared
    `funded_execution.exclude_names` removes each named company from the stable
    composition before that day's decision, the removal persists through every
    later session and the next scheduled refresh (so a fresh selection cannot
    resurrect it), and a missing grade, a risk cut or text is never an exit.
    With `funded_allocation` False the incumbent path is unchanged.

    `trend_brake` is the opt-in shadow overlay on the incumbent path: the
    predeclared state machine in `trend_brake.risk_off_path` reads the QQQ
    history in `benchmark_prices` (required, aligned to the panel's dates)
    and, while it is risk_off, holds the book at `brake_scale` of what the
    rules would otherwise hold, the rest in cash. The scale is an absolute
    ceiling applied where the FOMC path already caps the target, and the
    two compose as a per-session minimum. It trades only when the state
    changes - a cut on entering risk_off, a restoration from cash on leaving
    it, both next-open orders the way an FOMC change is - and at the normal
    rebalances; between those the held weights already carry the scale, so
    nothing is nudged daily. While risk_off, mid-cycle entries and deferred
    buy retries are paused (rotation sells still go through), because the
    cash the brake released is not a buy budget - the live FOMC cycle pauses
    entries the same way. `funded_allocation` has its own trend ceiling
    and refuses it. Off, the run is byte-identical to what it was, and the
    result's `risk_off` is all False.

    `brake_path_override` is an experimental, externally fitted exposure
    ceiling on the same calendar. It is mutually exclusive with the fixed
    trend brake and uses the identical fill, cash and FOMC composition path.
    Supplying None leaves the incumbent behavior unchanged.
    """
    decide = allocator or _targets
    fired, blocked, trend_up, dips = _signals_for(
        report, entry_gate, block_overbought, band_dip_buy, trend_gated_exit, dip
    )
    panel: Panel = report.panel
    from backend.agents.trading.desk import entry

    if funded_allocation:
        # Refuse options the shared allocation path would have to ignore,
        # rather than silently running a different book than was asked for.
        incompatible: list[str] = []
        if allocator is not None:
            incompatible.append("allocator")
        if event_lifecycle:
            incompatible.append("event_lifecycle")
        if green_day_skip:
            incompatible.append("green_day_skip")
        if exit_at_close:
            incompatible.append("exit_at_close")
        if live_midcycle:
            incompatible.append("live_midcycle")
        if deferred_buys:
            incompatible.append("deferred_buys")
        if dip is not None:
            incompatible.append("dip")
        if exits is not None:
            incompatible.append("exits")
        if entry_gate or block_overbought or band_dip_buy or trend_gated_exit:
            incompatible.append(
                "entry_gate/block_overbought/band_dip_buy/trend_gated_exit"
            )
        if trend_brake or brake_path_override is not None:
            # The shared allocation path carries its own trend ceiling; a
            # second one on top would measure neither.
            incompatible.append("trend_brake")
        if incompatible:
            raise ValueError(
                "funded_allocation cannot be combined with: " + ", ".join(incompatible)
            )
        funded_execution.validate_benchmarks(panel, benchmark_prices)
        excluded_map = _excluded_by_session(excluded_symbols_by_session)
    # The trend brake's per-session ceiling, decided at each close from the
    # QQQ history up to that close; None when the brake is off so the
    # incumbent loop sees exactly the FOMC path it always saw.
    brake_path = None
    risk_off = np.zeros(len(panel.dates), dtype=bool)
    if trend_brake and brake_path_override is not None:
        raise ValueError("choose the fixed trend brake or an explicit learned path")
    if brake_path_override is not None:
        brake_path = np.asarray(brake_path_override, dtype=float)
        if (
            brake_path.shape != (len(panel.dates),)
            or not np.isfinite(brake_path).all()
            or np.any((brake_path <= 0) | (brake_path > 1))
        ):
            raise ValueError("brake path must align with sessions and be in (0, 1]")
        risk_off = brake_path < 1.0
    if trend_brake:
        if not (np.isfinite(brake_scale) and 0 < brake_scale <= 1):
            raise ValueError("brake_scale must be a finite value in (0, 1]")
        qqq = trend_brake_rule.aligned_qqq(panel.dates, benchmark_prices)
        risk_off = trend_brake_rule.risk_off_path(qqq)
        brake_path = np.where(risk_off, float(brake_scale), 1.0)
    if deferred_buys and not exit_at_close:
        # With sells filled at the open their proceeds already pay for the
        # same session's buys, so there is no idle cash to defer and the
        # remainder this would record would be one the fill never left.
        raise ValueError("deferred_buys requires exit_at_close")

    live_bands = entry.bollinger_z(panel.adj_close) if live_midcycle else None
    # The previous session's unpaid buy shares per symbol, when the deferred
    # leg is on: written on a rebalance or a live mid-cycle plan, consumed by
    # the very next plan (retried, or superseded by a rebalance), never kept.
    pending_deferred: dict[str, float] = {}
    # A research overlay changes exposure only when its close-time scale changes.
    # Between rebalances the held weights already contain yesterday's scale;
    # applying the absolute scale again would halve the account every day.
    event_exposure = _event_path(event_exposure, len(panel.dates))
    # The FOMC path and the brake's path as one minimum; the lifecycle
    # below still reads the FOMC path alone, so the brake never defers a
    # rebalance the way an event window does.
    ceiling = _ceiling_path(event_exposure, brake_path)
    previous_scale = 1.0
    previous_brake = 1.0
    event_baseline = None
    event_sold = None
    config = config or risk.BOOK_CONFIG
    rows, names = panel.adj_close.shape
    start = int(np.searchsorted(panel.dates, np.datetime64(since))) if since else 0
    evidence = exits
    if evidence is None and use_exits:
        evidence = exit_analyst.evidence(panel)
    stamps = [str(d) for d in panel.dates]
    opens = adjusted_open(panel)
    closes = panel.adj_close

    book = _Book(names, START_EQUITY, cost_bps, panel, report, stamps)
    returns = np.full(rows, np.nan)
    invested = np.zeros(rows)
    equity = np.full(rows, np.nan)
    rebalances = 0
    stable_desired: dict[str, float] = {}

    equity[start] = book.equity(closes[start])
    top = np.full(rows, np.nan)
    dip_adds = 0
    next_rebalance = start
    funded_trace: list[dict] = []
    excluded: set[str] = set()
    for t in range(start, rows - 1):
        if funded_allocation:
            # An explicit company exit, named for this decision date, removes
            # the name from the stable composition for this session and every
            # later one - including the next scheduled refresh, so a fresh
            # selection cannot resurrect it. Only the caller's explicit map
            # removes a name; a missing grade or a risk cut never does.
            if excluded_map:
                removed = excluded_map.get(str(panel.dates[t]))
                if removed:
                    excluded.update(removed)
            # The stable unscaled stock composition refreshes only on the
            # scheduled rebalance clock, never between dates, so a daily risk
            # cut or a missing score on an ordinary day can neither lose the
            # names to re-enter nor resurrect one that left.
            rebalanced = t >= next_rebalance
            if rebalanced:
                next_rebalance = t + rebalance
                stable_desired = funded_execution.stable_composition(
                    report, panel, config, t
                )
                rebalances += 1
            if excluded:
                stable_desired = funded_execution.exclude_names(
                    stable_desired, excluded
                )
            # One daily shared decision: the supplied composition, the pure
            # allocation under the current absolute regime and event ceilings,
            # and the shared cash-bounded order plan, filled at the next open
            # whatever the open looks like.
            equity_t = book.equity(closes[t])
            price_map = {
                s: float(closes[t, j])
                for j, s in enumerate(panel.tickers)
                if np.isfinite(closes[t, j]) and closes[t, j] > 0
            }
            held_map = {
                s: float(book.shares[j])
                for j, s in enumerate(panel.tickers)
                if book.shares[j] > 0
            }
            regime_cap = float(report.regime.states[t].exposure)
            event_cap = float(event_exposure[t]) if event_exposure is not None else 1.0
            daily = funded_execution.daily_decision(
                report,
                panel,
                config,
                t,
                policy=allocation_policy,
                index_eligible=index_eligible,
                benchmark_prices=benchmark_prices,
                desired=stable_desired,
                held=held_map,
                prices=price_map,
                equity=equity_t,
                regime_cap=regime_cap,
                event_cap=event_cap,
                excluded_symbols=excluded,
            )
            before = book.shares.copy()
            cash_before = float(book.cash)
            traded_before = float(book.traded)
            entry = {
                "decision_date": str(panel.dates[t]),
                "fill_date": str(panel.dates[t + 1]),
                "equity_date": str(panel.dates[t + 1]),
                "excluded": sorted(excluded),
                "policy": daily.policy,
                "as_of": daily.as_of,
                "reason": daily.reason,
                "blocked": list(daily.blocked),
                "composition": dict(stable_desired),
                "desired": {},
                "executable": {},
                "cash_projected": None,
                "cash_before": cash_before,
                "cash_after": float(book.cash),
                "notional_traded": 0.0,
                "fees": 0.0,
                "shares_before": {
                    s: float(before[j])
                    for j, s in enumerate(panel.tickers)
                    if before[j] > 0
                },
                "shares_after": {},
                "deltas": {},
                "fills": {},
                "missing": [],
                "plan_blocked": [],
                "binding": "",
                "unavailable": [],
            }
            if daily.decision is not None:
                plan = funded_execution.plan_funded(
                    daily.decision,
                    held_map,
                    price_map,
                    equity_t,
                    book.cash,
                    cost_bps=cost_bps,
                    whole_shares=False,
                    index_eligible=index_eligible,
                )
                order = book.funded_order(plan)
                book.settle_split(
                    order,
                    opens[t + 1],
                    opens[t + 1],
                    t + 1,
                    plan.reason,
                    sell_at_close=False,
                    recycle_sells=False,
                )
                entry["desired"] = dict(plan.desired)
                entry["executable"] = dict(plan.executable)
                entry["cash_projected"] = float(plan.cash)
                entry["missing"] = list(plan.missing)
                entry["plan_blocked"] = list(plan.blocked)
                entry["binding"] = plan.binding
                entry["reason"] = plan.reason
                entry["notional_traded"] = float(book.traded - traded_before)
                entry["fees"] = (book.traded - traded_before) * book.cost
            entry["cash_after"] = float(book.cash)
            entry["shares_after"] = {
                s: float(book.shares[j])
                for j, s in enumerate(panel.tickers)
                if book.shares[j] > 0
            }
            # Deltas over the union of before and after holdings, so a full
            # exit - held yesterday, gone today - is present in the trace and
            # never silently zeroed.
            entry["deltas"] = {
                s: float(book.shares[panel.index(s)] - before[panel.index(s)])
                for s in sorted(set(panel.tickers))
                if abs(book.shares[panel.index(s)] - before[panel.index(s)]) > 1e-12
            }
            # Actual fills from the ledger's share changes at the opening
            # price the book actually filled at - never from the proposed
            # orders, which could have been scaled or skipped.
            fill_price = opens[t + 1]
            for symbol, delta in entry["deltas"].items():
                column = panel.index(symbol)
                price = float(fill_price[column])
                if not np.isfinite(price) or price <= 0:
                    continue
                entry["fills"][symbol] = {
                    "side": "buy" if delta > 0 else "sell",
                    "qty": abs(delta),
                    "fill_price": price,
                    "notional": abs(delta) * price,
                }
            # A held position whose closing valuation is missing makes this
            # session's NAV and return unavailable: shares and cash are
            # retained, and the scorecard rejects the return rather than
            # showing a fake loss or recovery from a dropped value.
            unpriced = [
                symbol
                for j, symbol in enumerate(panel.tickers)
                if book.shares[j] > 0
                and not (np.isfinite(closes[t + 1, j]) and closes[t + 1, j] > 0)
            ]
            if unpriced:
                entry["unavailable"] = unpriced
                equity[t + 1] = float("nan")
                returns[t + 1] = float("nan")
                invested[t + 1] = float("nan")
                top[t + 1] = float("nan")
            else:
                equity[t + 1] = book.equity(closes[t + 1])
                returns[t + 1] = (
                    equity[t + 1] / equity[t] - 1.0 if equity[t] > 0 else float("nan")
                )
                invested[t + 1] = book.invested(closes[t + 1])
                top[t + 1] = book.top_weight(closes[t + 1])
            funded_trace.append(entry)
            continue
        scale = float(event_exposure[t]) if event_exposure is not None else 1.0
        # The promoted lifecycle defers a rebalance and restores only executed cuts.
        if event_lifecycle and (scale < 1 or event_baseline is not None):
            event_baseline, event_sold = _settle_event(
                book, event_baseline, event_sold, scale, opens[t + 1], t + 1
            )
            equity[t + 1] = book.equity(closes[t + 1])
            returns[t + 1] = equity[t + 1] / equity[t] - 1 if equity[t] > 0 else np.nan
            invested[t + 1] = book.invested(closes[t + 1])
            top[t + 1] = book.top_weight(closes[t + 1])
            continue
        # Decided on t's close, filled at t+1's open.
        rebalanced = t >= next_rebalance
        if rebalanced:
            next_rebalance = t + rebalance
            target = decide(report, panel, config, t)
            if fired is not None or blocked is not None:
                total = book.equity(closes[t])
                weights = (
                    (book.shares * closes[t]) / total if total > 0 else np.zeros(names)
                )
                target = _gated_targets(target, fired, blocked, weights, t)
            reason = "rebalanced out"
            rebalances += 1
        else:
            target, reason = book.between(
                evidence, closes[t], t, redeploy, grace, trend_up, trim
            )
            if dips is not None and dips[t].any():
                target, added = _dip_add(
                    target,
                    dips[t],
                    dip,
                    book,
                    closes[t],
                    None if dip.size is None else dip.size[t],
                )
                if added:
                    reason = "dip add"
                    dip_adds += added
        # The quantity is decided from what the decision could see - t's
        # close - and only then filled at t + 1's open. Buys and sells can
        # fill at different prices (the paper account sells on the close
        # and never into a green open since 2026-09-11), so the fill is
        # split by side.
        # The brake owns the reason when its own scale is what moved since
        # the last session that reached this point; otherwise the FOMC path
        # is the overlay that changed the ceiling.
        label = "FOMC"
        if brake_path is not None:
            if float(brake_path[t]) != previous_brake:
                label = "trend brake"
            previous_brake = float(brake_path[t])
        target, previous_scale, reason, event_changed = _event_target(
            target,
            ceiling,
            t,
            rebalanced,
            previous_scale,
            reason,
            label,
        )
        order = book.plan(target, closes[t])
        # The deferred leg: last session's unpaid remainder is retried on a
        # plain session and superseded by a rebalance; an event session
        # leaves it waiting, as the live book does while the event cycle
        # owns the plan.
        carried: dict[str, float] = {}
        # While the brake holds the book down, the cash it released is not
        # a buy budget: a breakout entry or a deferred retry would put it
        # straight back to work and undo the cut the brake just made. The
        # live FOMC cycle pauses entries the same way (`event_execution.plan`
        # owns the plan for the whole cycle). Sells still go through.
        braked = brake_path is not None and float(brake_path[t]) < 1.0
        event_paused = event_exposure is not None and float(event_exposure[t]) < 1.0
        reduced = braked or event_paused
        if deferred_buys and not event_changed and not reduced:
            carried, pending_deferred = ({} if rebalanced else pending_deferred), {}
        if live_midcycle and not rebalanced and not event_changed:
            unfunded: dict[str, float] = {}
            order = _live_midcycle(
                book,
                report,
                t,
                live_bands,
                blocked,
                deferred=carried or None,
                unfunded=unfunded if deferred_buys and not reduced else None,
            )
            if reduced:
                order = np.minimum(order, book.shares)
            else:
                pending_deferred = unfunded
            reason = "shared paper rotation and entry policy"
        elif carried:
            order = _deferred_leg(book, report, t, blocked, carried, order)
        if event_paused:
            # Live FOMC execution owns the cycle and cannot add positions.
            order = np.minimum(order, book.shares)
        if deferred_buys and rebalanced and not event_changed and not reduced:
            pending_deferred = _unpaid_buys(book, order, closes[t])
        buy_prices = opens[t + 1]
        sell_prices = opens[t + 1]
        if exit_at_close and not event_changed:
            sell_prices = closes[t + 1]
        # Event-risk changes are explicitly next-open orders, including a green open.
        # Restoring a deferred cut's theoretical size would add unintended risk.
        if green_day_skip and not event_changed:
            # Hold a sell back when the name opens up for the day: the
            # desk does not exit into a name's own rally.
            up_at_open = (
                (opens[t + 1] > closes[t])
                & np.isfinite(opens[t + 1])
                & np.isfinite(closes[t])
            )
            skip = (order < book.shares) & up_at_open
            order = np.where(skip, book.shares, order)
        book.settle_split(
            order,
            buy_prices,
            sell_prices,
            t + 1,
            reason,
            sell_at_close=exit_at_close and not event_changed,
        )
        equity[t + 1] = book.equity(closes[t + 1])
        returns[t + 1] = (
            equity[t + 1] / equity[t] - 1.0 if equity[t] > 0 else float("nan")
        )
        invested[t + 1] = book.invested(closes[t + 1])
        top[t + 1] = book.top_weight(closes[t + 1])
    book.finish(rows - 1)
    return SimResult(
        panel.dates[start:],
        returns[start:],
        invested[start:],
        book.trades,
        rebalances,
        equity[start:],
        dip_adds,
        book.traded,
        top[start:],
        funded_trace if funded_allocation else None,
        risk_off[start:],
    )


# The account: shares per name, cash, and the trades that moved between
# them. It owns the trade log too, because when a position opened and what
# it was filled at are the same facts a trade is written from.
class _Book:
    """Shares and cash, and a readable record of what changed them."""

    def __init__(self, names, equity, cost_bps, panel, report, stamps) -> None:
        self.shares = np.zeros(names)
        self.cash = float(equity)
        self.traded = 0.0
        self.cost = cost_bps / 1e4
        self.panel = panel
        self.report = report
        self.stamps = stamps
        # The names the shared planner keys its orders by; a bare book built
        # for an isolated plan/settle test has synthetic names rather than a
        # panel's.
        self.tickers = (
            list(panel.tickers)
            if panel is not None
            else [f"T{i}" for i in range(names)]
        )
        self.opened: dict[int, int] = {}
        self.paid: dict[int, float] = {}
        self.trades: list[SimTrade] = []

    # The account's value at a set of prices, ignoring unpriced holdings.
    # The largest position's share of the account at `prices`.
    def top_weight(self, prices: np.ndarray) -> float:
        """Return the biggest single weight, 0 when nothing is held."""
        total = self.equity(prices)
        priced = (self.shares > 0) & np.isfinite(prices)
        if total <= 0 or not priced.any():
            return 0.0
        return float((self.shares[priced] * prices[priced]).max() / total)

    def equity(self, prices: np.ndarray) -> float:
        """Return cash plus the value of every priced holding."""
        priced = (self.shares > 0) & np.isfinite(prices)
        return float(self.cash + (self.shares[priced] * prices[priced]).sum())

    # The fraction of the account in positions rather than cash.
    def invested(self, prices: np.ndarray) -> float:
        """Return the gross weight held."""
        total = self.equity(prices)
        if total <= 0:
            return 0.0
        priced = (self.shares > 0) & np.isfinite(prices)
        return float((self.shares[priced] * prices[priced]).sum() / total)

    # What to hold between rebalances: what is already held, less anything
    # the exit analyst names. `trend_up` gates an exit to a downtrend: a
    # name above its 200-day average is left alone even when a band signal
    # fires, because an extension in an uptrend has measured as a pause.
    def between(
        self,
        evidence,
        prices,
        t: int,
        redeploy: bool,
        grace: int = exit_analyst.GRACE,
        trend_up: np.ndarray | None = None,
        trim: float = 1.0,
    ):
        """Return (target weights, the reason anything leaves)."""
        total = self.equity(prices)
        priced = np.isfinite(prices) & (prices > 0)
        value = np.where(priced, self.shares * np.nan_to_num(prices), 0.0)
        weights = value / total if total > 0 else np.zeros_like(value)
        if evidence is None:
            return weights, "held"
        leaving = np.zeros(len(weights), dtype=bool)
        reason = "held"
        for column in np.flatnonzero(self.shares > 0):
            entry = self.opened.get(column, t)
            in_downtrend = trend_up is None or not bool(trend_up[t, column])
            if in_downtrend and exit_analyst.should_exit(
                evidence, t, column, entry, grace
            ):
                leaving[column] = True
                reason = exit_analyst.reason(evidence, t, column)
        if not leaving.any():
            return weights, reason
        # A trim sells the fraction `trim` of a signalled position and keeps
        # the rest - the "take some profit off the table" version of the
        # exit - while `trim == 1` is the full exit the analyst retired.
        cut = np.where(leaving, weights * (1.0 - trim), weights)
        freed = float((weights - cut).sum())
        weights = cut
        if redeploy:
            # The regime already decided how much of the book to carry, so
            # an exit changes which names hold it, not how much is held.
            # The freed weight goes to the names still held in full; a
            # trimmed name is deliberately being reduced, so it must not
            # receive back a share of the very weight it just shed.
            staying = ~leaving
            remaining = float(weights[staying].sum())
            if remaining > 0:
                weights = np.where(
                    staying,
                    weights * (1.0 + freed / remaining),
                    weights,
                )
        return weights, reason

    # How many shares of each name to end up holding, decided at `prices`.
    #
    # This is the order, and it is fixed before the fill. The simulator
    # used to size at the opening price it was about to fill at, which is
    # information the decision did not have: with a 10% target, a $100
    # close and a $120 open, it bought 83.33 shares where the paper
    # planner - working from the same close - had submitted 100. Sizing
    # here and filling later is what the two paths have in common, and the
    # sizing itself is the shared planner's, so the paper account and the
    # record tracker decide the same orders from the same close.
    def plan(self, target: np.ndarray, prices: np.ndarray) -> np.ndarray:
        """Return the share count wanted per name, decided at `prices`."""
        total = self.equity(prices)
        if total <= 0:
            return np.array(self.shares, dtype=float)
        tickers = self.tickers
        targets = {
            t: float(w)
            for t, w in zip(tickers, target, strict=False)
            if w > 0 and np.isfinite(w)
        }
        held = {
            t: float(s) for t, s in zip(tickers, self.shares, strict=False) if s > 0
        }
        by_price = {
            t: float(p)
            for t, p in zip(tickers, prices, strict=False)
            if np.isfinite(p) and p > 0
        }
        orders = planner.plan(targets, held, total, by_price)
        wanted = np.array(self.shares, dtype=float)
        for o in orders:
            index = tickers.index(o.symbol)
            current = held.get(o.symbol, 0.0)
            wanted[index] = current + (o.qty if o.side == "buy" else -o.qty)
        return np.maximum(wanted, 0.0)

    # The share target of one shared funded plan: current shares moved by the
    # plan's own continuous orders, for the same `_Book` to fill.
    def funded_order(self, plan) -> np.ndarray:
        """Return the share target the shared funded plan wants held."""
        wanted = np.array(self.shares, dtype=float)
        for o in plan.orders:
            if o.symbol not in self.tickers:
                continue
            index = self.tickers.index(o.symbol)
            wanted[index] = self.shares[index] + (o.qty if o.side == "buy" else -o.qty)
        return np.maximum(wanted, 0.0)

    # Fill the planned order at `prices`, then write down what changed.
    def settle(self, order, prices, session: int, reason: str) -> None:
        """Fill `order` at `prices` and record the positions that changed."""
        before = self.shares > 0
        self._fill(order, prices)
        for column in np.flatnonzero((self.shares > 0) & ~before):
            self.opened[column] = session
            self.paid[column] = float(prices[column])
        for column in np.flatnonzero(before & (self.shares <= 0)):
            self._log(column, session, prices, reason)

    # Fill same-time sells first, then scale competing buys to cash after costs.
    # Missing prices preserve holdings; only executed quantities enter the ledger.
    # `recycle_sells` lets the same day's sale proceeds fund buys; the funded
    # allocation path leaves it off so a buy is never paid for with money a
    # sell has not delivered yet. The sale proceeds are still credited to the
    # closing cash either way - only their use as a buy budget is conditional.
    def _fill(
        self, order: np.ndarray, prices: np.ndarray, recycle_sells: bool = True
    ) -> None:
        tradable = (
            np.isfinite(prices) & (prices > 0) & np.isfinite(order) & (order >= 0)
        )
        wanted = np.where(tradable, order, self.shares)
        move = wanted - self.shares
        if not move.any():
            return
        priced = np.where(tradable, prices, 0.0)
        sells = np.minimum(move, 0.0)
        buys = np.maximum(move, 0.0)
        gross_proceeds = -float((sells * priced).sum())
        net_proceeds = gross_proceeds * (1.0 - self.cost)
        old_cash = float(self.cash)
        # The cash this basket's buys may spend: the same session's sale
        # proceeds only fund buys when recycling is on, and are earmarked
        # rather than spendable otherwise.
        buy_budget = old_cash + (net_proceeds if recycle_sells else 0.0)
        requested = float((buys * priced).sum())
        spend = requested * (1.0 + self.cost)
        scale = min(1.0, max(0.0, buy_budget) / spend) if spend > 0 else 0.0
        # Closing cash always receives the net sale proceeds; only the actual
        # buy spend leaves it, so a no-recycle basket still credits the sale.
        self.cash = max(0.0, old_cash + net_proceeds - spend * scale)
        self.traded += gross_proceeds + requested * scale
        self.shares += sells + buys * scale

    # Fill the plan with buys paid at `buy_prices` and sells paid at
    # `sell_prices` - the paper account buys at the open and sells on the
    # close since 2026-09-11, so a buy and a sell on the same session
    # trade at different prices and the ledger must not pretend otherwise.
    def settle_split(
        self,
        order: np.ndarray,
        buy_prices: np.ndarray,
        sell_prices: np.ndarray,
        session: int,
        reason: str,
        sell_at_close: bool = True,
        recycle_sells: bool = True,
    ) -> None:
        """Fill the plan, buys at `buy_prices` and sells at `sell_prices`."""
        before = self.shares > 0
        if sell_at_close:
            self._fill_split(order, buy_prices, sell_prices, recycle_sells)
        else:
            self._fill(order, buy_prices, recycle_sells)
        for column in np.flatnonzero((self.shares > 0) & ~before):
            self.opened[column] = session
            self.paid[column] = float(buy_prices[column])
        for column in np.flatnonzero(before & (self.shares <= 0)):
            self._log(column, session, sell_prices, reason)

    # Pay opening buys from existing cash before crediting any closing sale.
    def _fill_split(
        self,
        order: np.ndarray,
        buy_prices: np.ndarray,
        sell_prices: np.ndarray,
        recycle_sells: bool = True,
    ) -> None:
        self._fill(np.maximum(order, self.shares), buy_prices, recycle_sells)
        self._fill(np.minimum(order, self.shares), sell_prices, recycle_sells)

    # One position leaving, with what it made between its two fills.
    def _log(self, column: int, session: int, prices, reason: str) -> None:
        entry = self.opened.pop(column, session)
        paid = self.paid.pop(column, float("nan"))
        got = float(prices[column])
        ret = got / paid - 1.0 if np.isfinite(paid) and paid > 0 else float("nan")
        self.trades.append(
            SimTrade(
                ticker=self.panel.tickers[column],
                opened=self.stamps[min(entry, len(self.stamps) - 1)],
                closed=self.stamps[min(session, len(self.stamps) - 1)],
                weight=float("nan"),
                grade=self.report.graded.letter(
                    min(entry, len(self.stamps) - 1), column
                ),
                reason=reason,
                ret=ret,
            )
        )

    # Everything still open when the walk ends.
    def finish(self, last: int) -> None:
        """Write a trade for each position the run ends holding."""
        for column in np.flatnonzero(self.shares > 0):
            entry = self.opened.get(column, last)
            paid = self.paid.get(column, float("nan"))
            price = float(self.panel.adj_close[last, column])
            ret = (
                price / paid - 1.0
                if np.isfinite(paid) and paid > 0 and np.isfinite(price)
                else float("nan")
            )
            self.trades.append(
                SimTrade(
                    ticker=self.panel.tickers[column],
                    opened=self.stamps[min(entry, len(self.stamps) - 1)],
                    closed=None,
                    weight=float("nan"),
                    grade=self.report.graded.letter(
                        min(entry, len(self.stamps) - 1), column
                    ),
                    reason="still held",
                    ret=ret,
                )
            )
