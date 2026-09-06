"""The whole desk walked through history, not just its scores.

`sizing.simulate` runs a score matrix through the sizing engine and answers
a narrow question: is this ranking worth anything. The desk is more than a
ranking. It grades, it multiplies each position by that grade, it cuts
exposure when the regime says so, it leans on steadier names while money is
tightening, and it now leaves a position when the exit analyst says the move
is finished. None of that reached the book's own backtest, so every risk
rule added here has been measured in a scratch script and never in the
thing that reports the book's numbers.

This walks the rules themselves, one session at a time:

  every `rebalance` sessions   the graded names are sized by the engine,
                               each multiplied by its grade and by the
                               regime's exposure for that session
  in between                   nothing trades except an exit the exit
                               analyst names, and the weight that frees is
                               either held as cash or spread over the names
                               still held, depending on `redeploy`
  always                       the decision on a session uses only what was
                               known then, and is filled at the next open

It returns the daily series so the same statistics as everywhere else can
be taken from it, and the trades so a run can be read rather than trusted.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from backend.agents.trading.desk import exit as exit_analyst
from backend.agents.trading.desk import risk
from backend.market import sizing
from backend.market.panel import Panel

REBALANCE = 20
# Whether the weight an exit frees goes back to work in the names still
# held, or sits as cash until the next rebalance. See the note in `run`.
REDEPLOY = True
COST_BPS = 10.0
MIN_TRADE = 0.005


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
    invested: np.ndarray  # (T,) gross weight held
    trades: list[SimTrade] = field(default_factory=list)
    rebalances: int = 0

    # The usual four numbers, from the daily series.
    def stats(self) -> dict[str, float]:
        """Return annual return, volatility, Sharpe and worst drawdown."""
        daily = self.returns[np.isfinite(self.returns)]
        if len(daily) < 2:
            return {
                "annual": float("nan"),
                "volatility": float("nan"),
                "sharpe": float("nan"),
                "drawdown": float("nan"),
                "total": float("nan"),
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
    simple = np.expm1(panel.log_returns())
    simple = np.where(np.isfinite(simple), simple, 0.0)
    start = int(np.searchsorted(panel.dates, np.datetime64(since))) if since else 0
    evidence = exit_analyst.evidence(panel) if use_exits else None
    stamps = [str(d) for d in panel.dates]

    held = np.zeros(names)
    opened: dict[int, int] = {}
    entry_weight: dict[int, float] = {}
    returns = np.full(rows, np.nan)
    invested = np.zeros(rows)
    trades: list[SimTrade] = []
    rebalances = 0
    for t in range(start, rows - 1):
        if (t - start) % rebalance == 0:
            held, cost = _rebalance(
                report,
                panel,
                config,
                t,
                held,
                opened,
                entry_weight,
                stamps,
                trades,
                cost_bps,
            )
            rebalances += 1
        else:
            held, cost = _take_exits(
                report,
                panel,
                evidence,
                t,
                held,
                opened,
                entry_weight,
                stamps,
                trades,
                cost_bps,
                redeploy,
            )
        invested[t] = float(held.sum())
        returns[t + 1] = float((held * simple[t + 1]).sum()) - cost
    for column in np.flatnonzero(held > 0):
        trades.append(
            _close(
                panel,
                trades,
                column,
                opened,
                entry_weight,
                rows - 1,
                stamps,
                report,
                "still held",
            )
        )
    return SimResult(
        panel.dates[start:], returns[start:], invested[start:], trades, rebalances
    )


# Bring the book to the desk's targets for session `t`, recording what left.
def _rebalance(
    report, panel, config, t, held, opened, entry_weight, stamps, trades, cost_bps
):
    weights = _engine_weights(report, t, config)
    state = report.regime.states[t]
    target = np.zeros(len(held))
    for column in np.flatnonzero(weights > 0):
        letter = report.graded.letter(t, column)
        target[column] = weights[column] * risk.SIZE_MULTIPLIER[letter] * state.exposure
    if state.tightening:
        target = _steepen(target, panel, config, t)
    # A move too small to be worth its cost is not made.
    target = np.where(np.abs(target - held) < MIN_TRADE, held, target)
    for column in np.flatnonzero((held > 0) & (target <= 0)):
        trades.append(
            _close(
                panel,
                trades,
                column,
                opened,
                entry_weight,
                t,
                stamps,
                report,
                "rebalanced out",
            )
        )
    for column in np.flatnonzero((held <= 0) & (target > 0)):
        opened[column] = t
        entry_weight[column] = float(target[column])
    cost = float(np.abs(target - held).sum()) * cost_bps / 1e4
    return target, cost


# Between rebalances the only trade is an exit the exit analyst names.
def _take_exits(
    report,
    panel,
    evidence,
    t,
    held,
    opened,
    entry_weight,
    stamps,
    trades,
    cost_bps,
    redeploy=REDEPLOY,
):
    if evidence is None:
        return held, 0.0
    cost = 0.0
    held = held.copy()
    before = float(held.sum())
    left = False
    for column in np.flatnonzero(held > 0):
        entry = opened.get(column, t)
        if exit_analyst.should_exit(evidence, t, column, entry):
            trades.append(
                _close(
                    panel,
                    trades,
                    column,
                    opened,
                    entry_weight,
                    t,
                    stamps,
                    report,
                    exit_analyst.reason(evidence, t, column),
                )
            )
            cost += float(held[column]) * cost_bps / 1e4
            held[column] = 0.0
            left = True
    if left and redeploy:
        # The book's gross is a risk decision the regime already made, so
        # an exit changes which names hold it, not how much is held. The
        # weight goes to the names still in the book, in their own
        # proportions, and is charged for at the same rate.
        remaining = float(held.sum())
        if remaining > 0:
            held = held * (before / remaining)
            cost += (before - remaining) * cost_bps / 1e4
    return held, cost


# Record one position leaving, with what it did while it was held.
def _close(panel, trades, column, opened, entry_weight, t, stamps, report, reason):
    entry = opened.pop(column, t)
    weight = entry_weight.pop(column, 0.0)
    a, b = panel.adj_close[entry, column], panel.adj_close[t, column]
    ret = (
        float(b / a - 1.0)
        if np.isfinite(a) and np.isfinite(b) and a > 0
        else float("nan")
    )
    return SimTrade(
        ticker=panel.tickers[column],
        opened=stamps[entry],
        closed=stamps[t] if t < len(stamps) - 1 else None,
        weight=weight,
        grade=report.graded.letter(entry, column),
        reason=reason,
        ret=ret,
    )


# While money is tightening, the same names weighted so the steadier ones
# take more of the book, holding the gross unchanged. This mirrors what
# `risk.size` does live.
def _steepen(target: np.ndarray, panel: Panel, config, t: int) -> np.ndarray:
    volatility = sizing.realised_volatility(panel, config.volatility_lookback)[t]
    gross = float(target.sum())
    if gross <= 0:
        return target
    vol = np.where(np.isfinite(volatility) & (volatility > 0.10), volatility, 0.10)
    adjusted = target * (0.10 / vol) ** (risk.TIGHTENING_POWER - 1.0)
    total = float(adjusted.sum())
    return adjusted / total * gross if total > 0 else target
