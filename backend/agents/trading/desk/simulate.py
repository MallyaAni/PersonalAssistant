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
from backend.agents.trading.desk import grading, planner, risk
from backend.market.panel import Panel

REBALANCE = 20
# Whether the cash an exit frees goes back to work in the names still held,
# or waits until the next rebalance.
REDEPLOY = True
COST_BPS = 10.0
MIN_TRADE = 0.005
START_EQUITY = 1.0


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
        drawdown = float((curve / np.maximum.accumulate(curve) - 1.0).min())
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
def _dip_add(target, fired, rule: DipRule, book, prices) -> tuple[np.ndarray, int]:
    out = target.copy()
    added = 0
    taken = 0.0
    for column in np.flatnonzero(fired):
        if not np.isfinite(prices[column]) or prices[column] <= 0:
            continue
        room = rule.name_cap - out[column]
        if room <= 1e-6:
            continue
        amount = min(rule.add, room)
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


# Walk the desk's own rules from `since` to the end of the panel.
def run(
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
) -> SimResult:
    """Return the SimResult of the desk's rules over the panel.

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
    """
    decide = allocator or _targets
    fired: np.ndarray | None = None
    blocked: np.ndarray | None = None
    if entry_gate:
        from backend.agents.trading.desk import entry
        from backend.market import levels

        fired = entry.entries(report.panel, levels.level_features(report.panel)).any()
    if block_overbought:
        blocked = exit_analyst.evidence(report.panel).signalled()
    dips = None
    if dip is not None:
        dips = (
            dip.signal
            if dip.signal is not None
            else _dip_signal(report, report.panel, dip)
        )
    panel: Panel = report.panel
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

    equity[start] = book.equity(closes[start])
    top = np.full(rows, np.nan)
    dip_adds = 0
    for t in range(start, rows - 1):
        # Decided on t's close, filled at t+1's open.
        if (t - start) % rebalance == 0:
            target = decide(report, panel, config, t)
            if fired is not None or blocked is not None:
                total = book.equity(closes[t])
                weights = (
                    (book.shares * closes[t]) / total
                    if total > 0
                    else np.zeros(names)
                )
                target = _gated_targets(target, fired, blocked, weights, t)
            reason = "rebalanced out"
            rebalances += 1
        else:
            target, reason = book.between(evidence, closes[t], t, redeploy, grace)
            if dips is not None and dips[t].any():
                target, added = _dip_add(target, dips[t], dip, book, closes[t])
                if added:
                    reason = "dip add"
                    dip_adds += added
        # The quantity is decided from what the decision could see - t's
        # close - and only then filled at t + 1's open.
        order = book.plan(target, closes[t])
        book.settle(order, opens[t + 1], t + 1, reason)
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
    # the exit analyst names.
    def between(
        self, evidence, prices, t: int, redeploy: bool, grace: int = exit_analyst.GRACE
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
            if exit_analyst.should_exit(evidence, t, column, entry, grace):
                leaving[column] = True
                reason = exit_analyst.reason(evidence, t, column)
        if not leaving.any():
            return weights, reason
        freed = float(weights[leaving].sum())
        weights = np.where(leaving, 0.0, weights)
        if redeploy:
            # The regime already decided how much of the book to carry, so
            # an exit changes which names hold it, not how much is held.
            remaining = float(weights.sum())
            if remaining > 0:
                weights = weights * (1.0 + freed / remaining)
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

    # Buy and sell the planned share difference at `prices`, charging for
    # what moves. A name with no price that session cannot be traded and
    # keeps the shares it has.
    def _fill(self, order: np.ndarray, prices: np.ndarray) -> None:
        tradable = np.isfinite(prices) & (prices > 0)
        wanted = np.where(tradable, order, self.shares)
        move = wanted - self.shares
        if not move.any():
            return
        notional = move * np.nan_to_num(prices)
        self.cash -= float(notional.sum()) + float(np.abs(notional).sum()) * self.cost
        self.traded += float(np.abs(notional).sum())
        self.shares = np.maximum(wanted, 0.0)

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
