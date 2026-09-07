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
from backend.agents.trading.desk import risk
from backend.market import sizing
from backend.market.panel import Panel
from backend.market.sizing import apply_name_cap

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

    # The usual four numbers, from the daily series.
    def stats(self) -> dict[str, float]:
        """Return annual return, volatility, Sharpe and worst drawdown."""
        daily = self.returns[np.isfinite(self.returns)]
        if len(daily) < 2:
            nan = float("nan")
            return {
                "annual": nan,
                "volatility": nan,
                "sharpe": nan,
                "drawdown": nan,
                "total": nan,
            }
        curve = np.cumprod(1.0 + daily)
        annual = float(daily.mean() * 252)
        volatility = float(daily.std() * np.sqrt(252))
        drawdown = float((curve / np.maximum.accumulate(curve) - 1.0).min())
        return {
            "annual": annual,
            "volatility": volatility,
            "sharpe": annual / volatility if volatility > 0 else float("nan"),
            "drawdown": drawdown,
            "total": float(curve[-1] - 1.0),
        }


# The opening price on the same basis as the adjusted close, so a return
# from one to the other does not straddle a split or a dividend.
def adjusted_open(panel: Panel) -> np.ndarray:
    """Return (T, N) opening prices adjusted the way the close is."""
    with np.errstate(all="ignore"):
        factor = np.where(panel.close > 0, panel.adj_close / panel.close, np.nan)
    return panel.open * factor


# Engine weights at session t: the graded names, inverse volatility, caps.
def _engine_weights(report, t: int, config) -> np.ndarray:
    from dataclasses import replace

    panel = report.panel
    scores = np.where(report.graded.grades[t] > 0, report.scores[t], np.nan)
    total = max(int(np.isfinite(report.scores[t]).sum()) - 1, 1)
    graded = max(int(np.isfinite(scores).sum()), 1)
    scaled = replace(
        config, top_fraction=min(1.0, config.top_fraction * total / graded)
    )
    simple = np.expm1(panel.log_returns())
    simple = np.where(np.isfinite(simple), simple, 0.0)
    window = simple[max(0, t - config.volatility_lookback + 1) : t + 1]
    volatility = sizing.realised_volatility(panel, config.volatility_lookback)[t]
    weights = sizing.target_weights(
        scores, volatility, panel.themes, panel.tickers, scaled, history=window
    )
    weights[panel.index(panel.benchmark)] = 0.0
    return weights


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


# Walk the desk's own rules from `since` to the end of the panel.
def run(
    report,
    since: date | None = None,
    config=None,
    rebalance: int = REBALANCE,
    cost_bps: float = COST_BPS,
    use_exits: bool = True,
    redeploy: bool = REDEPLOY,
) -> SimResult:
    """Return the SimResult of the desk's rules over the panel."""
    panel: Panel = report.panel
    config = config or risk.BOOK_CONFIG
    rows, names = panel.adj_close.shape
    start = int(np.searchsorted(panel.dates, np.datetime64(since))) if since else 0
    evidence = exit_analyst.evidence(panel) if use_exits else None
    stamps = [str(d) for d in panel.dates]
    opens = adjusted_open(panel)
    closes = panel.adj_close

    book = _Book(names, START_EQUITY, cost_bps, panel, report, stamps)
    returns = np.full(rows, np.nan)
    invested = np.zeros(rows)
    equity = np.full(rows, np.nan)
    rebalances = 0

    equity[start] = book.equity(closes[start])
    for t in range(start, rows - 1):
        # Decided on t's close, filled at t+1's open.
        if (t - start) % rebalance == 0:
            target = _targets(report, panel, config, t)
            reason = "rebalanced out"
            rebalances += 1
        else:
            target, reason = book.between(evidence, closes[t], t, redeploy)
        # The quantity is decided from what the decision could see - t's
        # close - and only then filled at t + 1's open.
        order = book.plan(target, closes[t])
        book.settle(order, opens[t + 1], t + 1, reason)
        equity[t + 1] = book.equity(closes[t + 1])
        returns[t + 1] = (
            equity[t + 1] / equity[t] - 1.0 if equity[t] > 0 else float("nan")
        )
        invested[t + 1] = book.invested(closes[t + 1])
    book.finish(rows - 1)
    return SimResult(
        panel.dates[start:],
        returns[start:],
        invested[start:],
        book.trades,
        rebalances,
        equity[start:],
    )


# The account: shares per name, cash, and the trades that moved between
# them. It owns the trade log too, because when a position opened and what
# it was filled at are the same facts a trade is written from.
class _Book:
    """Shares and cash, and a readable record of what changed them."""

    def __init__(self, names, equity, cost_bps, panel, report, stamps) -> None:
        self.shares = np.zeros(names)
        self.cash = float(equity)
        self.cost = cost_bps / 1e4
        self.panel = panel
        self.report = report
        self.stamps = stamps
        self.opened: dict[int, int] = {}
        self.paid: dict[int, float] = {}
        self.trades: list[SimTrade] = []

    # The account's value at a set of prices, ignoring unpriced holdings.
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
    def between(self, evidence, prices, t: int, redeploy: bool):
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
            if exit_analyst.should_exit(evidence, t, column, entry):
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
    # here and filling later is what the two paths have in common.
    def plan(self, target: np.ndarray, prices: np.ndarray) -> np.ndarray:
        """Return the share count wanted per name, decided at `prices`."""
        total = self.equity(prices)
        wanted = np.array(self.shares, dtype=float)
        if total <= 0:
            return wanted
        tradable = np.isfinite(prices) & (prices > 0)
        value_now = np.where(tradable, self.shares * np.nan_to_num(prices), 0.0)
        value_want = np.where(tradable, target * total, 0.0)
        # A move too small to be worth its cost is not ordered, the same
        # rule the paper book applies.
        move = np.where(
            np.abs(value_want - value_now) < MIN_TRADE * total,
            0.0,
            value_want - value_now,
        )
        with np.errstate(all="ignore"):
            shares = np.where(prices > 0, (value_now + move) / prices, self.shares)
        wanted = np.where(tradable, shares, self.shares)
        wanted = np.where(np.isfinite(wanted), wanted, 0.0)
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


# While money is tightening, the same names weighted so the steadier ones
# take more of the book, holding the gross unchanged. This mirrors what
# `risk.size` does live.
#
# It re-caps afterwards. The tilt renormalises to the same gross, which
# moves weight onto the calmest names, and a review found that could carry
# one past `name_cap` - 0.1626 against a 0.15 cap, at every concentration
# tried. A cap a later step can undo is not a cap.
def _steepen(target: np.ndarray, panel: Panel, config, t: int) -> np.ndarray:
    volatility = sizing.realised_volatility(panel, config.volatility_lookback)[t]
    gross = float(target.sum())
    if gross <= 0:
        return target
    vol = np.where(np.isfinite(volatility) & (volatility > 0.10), volatility, 0.10)
    adjusted = target * (0.10 / vol) ** (risk.TIGHTENING_POWER - 1.0)
    total = float(adjusted.sum())
    if total <= 0:
        return target
    return apply_name_cap(adjusted / total * gross, config.name_cap, gross)
