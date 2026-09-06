"""Trade-by-trade backtest of the desk's rules on a few names.

One name at a time, on the daily clock, with the rules a desk would run:

* Enter when the grade is A or A+ and an entry trigger fires (a dip or a
  breakout), at the next session's open, sized by the grade and the
  regime's exposure.
* Hold while the grade stays at B or better. Exit at the next open when
  the grade has been C for `patience` consecutive sessions, or when the
  close breaks the support level recorded at entry by more than the stop
  buffer.
* Pay `cost_bps` on every entry and exit.

Variants switch each rule off so its contribution is visible: no entry
trigger (enter on the grade alone), no stop, no grade exit. The point is
not the equity curve of one name but whether each rule helped on every
name it touched; the per-trade table shows where it did not.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from backend.agents.trading.desk.entry import Entries
from backend.agents.trading.desk.grading import ORDINAL, SIZE_MULTIPLIER, A, B, C
from backend.market import levels

STOP_BUFFER = 0.03
PATIENCE = 3
SUPPORT = "support"
CHANDELIER = "chandelier"
ATR_SESSIONS = 20
ATR_MULTIPLE = 3.0


@dataclass(frozen=True)
class Rules:
    """Which rules a backtest run applies."""

    entry_trigger: bool = True
    stop: bool = True
    grade_exit: bool = True
    min_entry_grade: str = A
    hold_grade: str = B
    patience: int = PATIENCE
    stop_buffer: float = STOP_BUFFER
    # "support": a fixed stop under the support level at entry.
    # "chandelier": a trailing stop `atr_multiple` ATRs under the highest
    # close since entry, the classic trend-following exit.
    stop_kind: str = SUPPORT
    atr_multiple: float = ATR_MULTIPLE
    cost_bps: float = 10.0
    label: str = "desk rules"


@dataclass(frozen=True)
class Trade:
    """One round trip."""

    ticker: str
    entry_date: np.datetime64
    exit_date: np.datetime64 | None
    entry_kind: str
    entry_grade: str
    size: float
    sessions: int
    log_return: float  # of the name, entry open to exit open (or last close)
    contribution: float  # size-weighted, net of costs
    worst: float  # maximum adverse excursion from the entry
    exit_reason: str


@dataclass(frozen=True)
class Backtest:
    """The result for one name under one rule set."""

    ticker: str
    rules: Rules
    trades: list[Trade] = field(default_factory=list)
    equity: float = 0.0  # sum of contributions (log, sized)
    hold: float = 0.0  # buy-and-hold log return over the span
    benchmark: float = 0.0
    sessions: int = 0
    sessions_in: int = 0

    # Fraction of closed trades that made money.
    def hit_rate(self) -> float:
        """Return the share of trades with a positive contribution."""
        closed = [t for t in self.trades if t.exit_date is not None]
        if not closed:
            return float("nan")
        return float(np.mean([t.contribution > 0 for t in closed]))


# Adjusted opens: the open scaled the way the adjusted close is.
def _adjusted_open(panel) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return panel.open * (panel.adj_close / panel.close)


# The state of one name's position while the backtest walks the sessions.
@dataclass
class _Position:
    held: float = 0.0
    entry_t: int = -1
    entry_price: float = float("nan")
    kind: str = ""
    grade: str = ""
    stop_level: float = float("nan")
    worst: float = 0.0
    highest: float = float("nan")
    c_streak: int = 0
    pending: str | None = None  # "enter" or an exit reason, acted on next open


# Run one name through the rules from `since`.
def run_name(
    report,
    entries: Entries,
    ticker: str,
    rules: Rules,
    since: date | None = None,
    location: np.ndarray | None = None,
) -> Backtest:
    """Return the Backtest for `ticker`."""
    panel = report.panel
    column = panel.index(ticker)
    bench = panel.index(panel.benchmark)
    adj_open = _adjusted_open(panel)
    close = panel.adj_close
    loc = location if location is not None else levels.level_features(panel)
    support_distance = loc[:, :, levels.LEVEL_NAMES.index("support_distance")]
    start = int(np.searchsorted(panel.dates, np.datetime64(since))) if since else 0
    last = len(panel.dates) - 1
    trigger = entries.any()
    grades = report.graded.grades[:, column]
    atr = _atr(panel, ATR_SESSIONS)[:, column]
    trades: list[Trade] = []
    pos = _Position()
    equity = 0.0
    sessions = 0
    sessions_in = 0
    for t in range(start, last + 1):
        price_open = adj_open[t, column]
        price_close = close[t, column]
        if not np.isfinite(price_close):
            continue
        sessions += 1
        if np.isfinite(price_open):
            equity += _act_at_open(
                pos,
                t,
                price_open,
                ticker,
                panel,
                report,
                entries,
                column,
                close,
                support_distance,
                atr,
                rules,
                trades,
            )
        pos.pending = None
        if pos.held > 0:
            sessions_in += 1
            pos.worst = min(pos.worst, float(np.log(price_close / pos.entry_price)))
            pos.highest = float(np.fmax(pos.highest, price_close))
            if rules.stop_kind == CHANDELIER and np.isfinite(atr[t]):
                pos.stop_level = float(pos.highest - rules.atr_multiple * atr[t])
        _decide_at_close(
            pos, int(grades[t]), price_close, bool(trigger[t, column]), rules, t < last
        )
    if pos.held > 0:
        ret = float(np.log(close[last, column] / pos.entry_price))
        trades.append(
            Trade(
                ticker,
                panel.dates[pos.entry_t],
                None,
                pos.kind,
                pos.grade,
                pos.held,
                last - pos.entry_t,
                ret,
                pos.held * ret,
                pos.worst,
                "open",
            )
        )
        equity += pos.held * ret
    first_close = next(
        (
            close[t, column]
            for t in range(start, last + 1)
            if np.isfinite(close[t, column])
        ),
        float("nan"),
    )
    hold = float(np.log(close[last, column] / first_close))
    benchmark = float(np.log(close[last, bench] / close[start, bench]))
    return Backtest(
        ticker, rules, trades, equity, hold, benchmark, sessions, sessions_in
    )


# Carry out yesterday's decision at today's open; return the equity change.
def _act_at_open(
    pos,
    t,
    price_open,
    ticker,
    panel,
    report,
    entries,
    column,
    close,
    support_distance,
    atr,
    rules,
    trades,
) -> float:
    if pos.pending == "enter" and pos.held == 0.0:
        state = report.regime.states[t - 1]
        letter = _letter(int(report.graded.grades[t - 1, column]))
        pos.held = SIZE_MULTIPLIER[letter] * state.exposure
        pos.entry_t, pos.entry_price = t, float(price_open)
        pos.kind = entries.kind(t - 1, column) or "grade"
        pos.grade = letter
        sd = support_distance[t - 1, column]
        if np.isfinite(sd):
            pos.stop_level = float(
                close[t - 1, column] * (1 - sd) * (1 - rules.stop_buffer)
            )
        else:
            # No level below the price: the stop is a volatility distance.
            pos.stop_level = float(
                close[t - 1, column] - rules.atr_multiple * atr[t - 1]
            )
        pos.worst = 0.0
        pos.highest = float(price_open)
        pos.c_streak = 0
        if rules.stop_kind == CHANDELIER:
            pos.stop_level = float("nan")  # set from the first close
        return -pos.held * rules.cost_bps / 1e4
    if pos.pending not in (None, "enter") and pos.held > 0:
        ret = float(np.log(price_open / pos.entry_price))
        contribution = pos.held * ret - pos.held * rules.cost_bps / 1e4
        trades.append(
            Trade(
                ticker,
                panel.dates[pos.entry_t],
                panel.dates[t],
                pos.kind,
                pos.grade,
                pos.held,
                t - pos.entry_t,
                ret,
                contribution,
                pos.worst,
                pos.pending,
            )
        )
        pos.held = 0.0
        return contribution
    return 0.0


# Decide at the close what to do at the next open.
def _decide_at_close(pos, grade, price_close, triggered, rules, can_enter) -> None:
    if pos.held > 0:
        pos.c_streak = pos.c_streak + 1 if grade < ORDINAL[rules.hold_grade] else 0
        if rules.stop and np.isfinite(pos.stop_level) and price_close < pos.stop_level:
            pos.pending = "stop"
        elif rules.grade_exit and pos.c_streak >= rules.patience:
            pos.pending = "grade"
        return
    qualifies = grade >= ORDINAL[rules.min_entry_grade]
    if qualifies and ((not rules.entry_trigger) or triggered) and can_enter:
        pos.pending = "enter"


# Average true range over `n` sessions, in adjusted price units.
def _atr(panel, n: int) -> np.ndarray:
    """Return (T, N) ATR."""
    scale = panel.adj_close / panel.close
    high, low, close = panel.high * scale, panel.low * scale, panel.adj_close
    prev = np.vstack([np.full((1, close.shape[1]), np.nan), close[:-1]])
    with np.errstate(invalid="ignore"):
        tr = np.fmax(high - low, np.fmax(np.abs(high - prev), np.abs(low - prev)))
    out = np.full_like(close, np.nan)
    for t in range(n - 1, close.shape[0]):
        with np.errstate(all="ignore"):
            out[t] = np.nanmean(tr[t - n + 1 : t + 1], axis=0)
    return out


# Letter for an ordinal grade.
def _letter(ordinal: int) -> str:
    for letter, value in ORDINAL.items():
        if value == ordinal:
            return letter
    return C


# The standard set of rule variants, so each rule's contribution shows.
def variants() -> list[Rules]:
    """Return the rule sets a report compares."""
    return [
        Rules(label="support stop, 3-day grade exit"),
        Rules(stop_kind=CHANDELIER, label="chandelier 3 ATR, 3-day grade exit"),
        Rules(stop_kind=CHANDELIER, patience=10, label="chandelier 3 ATR, 10-day exit"),
        Rules(
            stop_kind=CHANDELIER,
            atr_multiple=5.0,
            patience=10,
            label="chandelier 5 ATR, 10-day exit",
        ),
        Rules(stop=False, patience=10, label="no stop, 10-day grade exit"),
        Rules(stop=False, grade_exit=False, label="hold to the end (no exits)"),
        Rules(
            stop_kind=CHANDELIER,
            patience=10,
            entry_trigger=False,
            label="chandelier 3 ATR, 10-day, no trigger",
        ),
    ]
