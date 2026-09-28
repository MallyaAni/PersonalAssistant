"""Profit-taking and dip-buying rules on the `/4` book, priced under the live executor.

The operator's reading of the live policy (`policy_v4.allocator`: every A/A+
name at equal weight, capped at 20%, exits on a downgrade, and since
2026-09-27 idle cash redeployed mid-cycle) is that it is bad at taking
profits and at buying dips, and that a top-tier book should lead the market
rather than follow its own reset clock. This module prices that reading as
a fixed set of registered trials: rules that TRIM a held A/A+ name between
resets and let the executor's own redeploy put the proceeds back to work
in the other names, one rule that ADDS to a name on a dip, and two rules
that trim on the stage-2 CNN's 20-session drawdown forecast
(`docs/research/deep-stage2-plan-2026-09-27.md`: IC 0.12-0.15 on the
drawdown, but dropping the flagged names lost 2 bp a session - so here the
flagged name is halved, not dropped).

The control is the live executor as the account runs it tonight -
`market_pit_scorecard._live_options` plus `midcycle_redeploy=True`
("ew-redeploy"). Every variant is that control with one rule added through
two hooks of `simulate.run`: the allocator wrapper (the policy's targets
with the rule's state applied - a trimmed name at half its target, a
dip-added name at 1.5x, the others scaled pro rata) and `weight_filter`
with `midcycle_trims=True`, which sells a held name down to the rule's
weight between resets. The restore is the executor's: once a trimmed
name's state clears, its full target is back in the allocator, and the
redeploy (from cash) or the next reset buys it back. A dip-add is restored
at the next reset.

The rules, fixed before any run (`VARIANTS`):

* ``trim-runup-20``: a name whose held weight has drifted to 1.5x its
  target is trimmed back to target, mid-cycle, at the next fill.
* ``trim-rsi``: the 14-session RSI above 80 halves the name (target x 0.5)
  until the RSI is back under 60.
* ``trim-band``: a close more than one sigma above the upper 20-day
  Bollinger band (z above 3 in sigma units; the upper band is 2) halves the
  name until the close is back inside the band (z under 2).
* ``dip-add``: a held A/A+ name more than 8% under its 21-session EMA has
  its target raised to 1.5x (capped at the 20% hold limit), paid from cash
  beyond the buffer and pro-rata trims of the other held names; restored at
  the next reset and re-armed once the name is back within 8% of the EMA.
* ``trim-dd-forecast``: the names whose forecast 20-session drawdown is in
  the worst decile of the day's A/A+ book (by rank, at least one name) are
  halved until they leave it.
* ``trim-dd-forecast-stop``: the same, plus a full exit (to the next reset)
  when the close is 15% below the close on the trim date - a model-guided
  stop. Both need the forecast npz (`drawdown_forecast`); without it they
  are skipped and the payload says so.

Statistics are the other studies': twenty offsets, 10 and 25 bp, the
scorecard's windows, paired Newey-West t (lag 20) against the control at
the median offset, offsets above the control, the exposure reading from a
`midcycle_ew.Ledger`; and for the trims themselves: trims a year, the mean
trim size (share of equity sold), the share of trims the name kept rising
after (its close 20 sessions later above the trim close - "sold too
early"), the median 20-session return after a trim, and what the sold
slice would have earned over those sessions in bp of equity. The CAGR
attributable to the trims is the whole gap to the control, since nothing
else differs. `verdict` reads the choosing window (2016-2023) at 25 bp:
ADOPT (registered) at >= +1.0 pt with paired t >= 2.0, not worse on
2024-2026 and a median worst drawdown within 3 pt on both windows; else
RECORD, with the per-offset sign test read as CONSISTENT the way the
mid-cycle study reads it. Nothing here trades or changes the executor.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from backend.agents.trading.desk import point_in_time, policy_v4, simulate
from backend.cli import market_pit_scorecard as scorecard
from backend.cli.market_pit_scorecard import WINDOWS, Curve, _on, _since, window_stats
from backend.market import candidate_stats, technical
from backend.market.midcycle_ew import (
    DIAGNOSTICS,
    Ledger,
    diagnostics,
    idle_target_path,
)

STUDY = "profit_taking"
CONTROL = "ew-redeploy"
# The rules.
RUNUP = "runup"
RSI = "rsi"
BAND = "band"
DIP = "dip"
FORECAST = "forecast"
RULES = (RUNUP, RSI, BAND, DIP, FORECAST)
# Indicator windows.
RSI_WINDOW = 14
BAND_WINDOW = 20
EMA_SPAN = 21
# Sessions after a trim the "sold too early" reading looks over.
FORWARD_SESSIONS = 20
HAC_LAG = 20
VERDICT_COST_BPS = 25.0
CHOOSING = "2016-2023"
REPORTED = "2024-2026"
# The floors, fixed before the run: CAGR points over the control on the
# choosing window at 25 bp, the paired Newey-West t there, not worse than
# the control on the reported window by paired bp/d, a median worst
# drawdown within this many points of the control's on both windows.
ADOPT_POINTS = 1.0
ADOPT_T = 2.0
DRAWDOWN_POINTS = 3.0
ADOPT = "ADOPT (registered)"
RECORD = "RECORD"
SKIPPED = "SKIPPED"
# The sign-test reading (the mid-cycle study's): a RECORD above the control
# on at least this share of the offsets by at least this many points.
CONSISTENT_SHARE = 0.9
CONSISTENT_POINTS = 2.0
CONSISTENT = "CONSISTENT, floor not cleared by daily t"
# Trim kinds.
TRIM = "trim"
ADD = "add"
STOP = "stop"
RESTORE = "restore"
# Rule states per name.
TRIMMED = "trimmed"
ADDED = "added"
STOPPED = "stopped"


@dataclass(frozen=True)
class Variant:
    """One named rule: which indicator, its trigger and restore levels, its size."""

    name: str
    rule: str | None = None
    # A trimmed name's target as a share of the policy's (rsi, band, forecast).
    fraction: float = 0.5
    # The drift multiple that trims (runup) or the raise multiple (dip).
    ratio: float = 1.5
    on: float = math.nan
    off: float = math.nan
    # The forecast rules: the worst share of the day's book that is trimmed.
    quantile: float = 0.1
    # The forecast stop: a full exit past this realized loss from the trim close.
    stop: float | None = None
    model: bool = False
    note: str = ""


# Fixed before the run and named in the payload: the control, four
# price-based rules and two model-based ones. Seven trials.
VARIANTS: tuple[Variant, ...] = (
    Variant(
        CONTROL,
        note=(
            "control: the live executor with the redeploy of idle cash "
            "(_live_options + midcycle_redeploy), no trims"
        ),
    ),
    Variant(
        "trim-runup-20",
        RUNUP,
        ratio=1.5,
        note=(
            "a held name whose weight has drifted to 1.5x its target is trimmed "
            "back to target mid-cycle; the redeploy puts the proceeds to work"
        ),
    ),
    Variant(
        "trim-rsi",
        RSI,
        fraction=0.5,
        on=80.0,
        off=60.0,
        note=(
            "14-session RSI above 80 halves the name's target until the RSI is "
            "under 60; the redeploy or the reset restores it"
        ),
    ),
    Variant(
        "trim-band",
        BAND,
        fraction=0.5,
        on=3.0,
        off=2.0,
        note=(
            "a close more than one sigma above the upper 20-day Bollinger band "
            "(z > 3 in sigma units) halves the name's target until the close is "
            "back inside the band (z < 2)"
        ),
    ),
    Variant(
        "dip-add",
        DIP,
        ratio=1.5,
        on=-0.08,
        note=(
            "a held A/A+ name more than 8% under its 21-session EMA has its "
            "target raised to 1.5x (capped at the 20% hold limit), paid from cash "
            "and pro-rata trims of the others; restored at the next reset"
        ),
    ),
    Variant(
        "trim-dd-forecast",
        FORECAST,
        fraction=0.5,
        quantile=0.1,
        model=True,
        note=(
            "the names whose CNN 20-session drawdown forecast is in the worst "
            "decile of the day's A/A+ book are halved until they leave it"
        ),
    ),
    Variant(
        "trim-dd-forecast-stop",
        FORECAST,
        fraction=0.5,
        quantile=0.1,
        stop=0.15,
        model=True,
        note=(
            "trim-dd-forecast plus a full exit to the next reset when the close "
            "is 15% below the close on the trim date"
        ),
    ),
)


# The variant by name, or KeyError.
def variant(name: str) -> Variant:
    """Return the registered variant called `name`."""
    for v in VARIANTS:
        if v.name == name:
            return v
    raise KeyError(name)


# The control's `simulate.run` options: the live policy exactly as the
# scorecard prices the account, plus the redeploy of idle cash the executor
# runs since 2026-09-27.
def control_options(panel) -> dict[str, Any]:
    """Return the keyword options of the control run."""
    options = scorecard._live_options(panel)
    options["midcycle_redeploy"] = True
    options["redeploy_buffer"] = simulate.REDEPLOY_BUFFER
    return options


# An options dict as JSON-able text: the FOMC path and the hook are named.
def _describe(options: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in options.items():
        if k == "event_exposure" and v is not None:
            out[k] = "event_risk.live_path(panel)"
        elif k == "weight_filter":
            out[k] = "ProfitTaking.weight_filter"
        else:
            out[k] = v
    return out


# Wilder's RSI per column over `window` sessions: NaN until `window` changes
# exist, 100 when there were no losses, 0 when there were no gains. A
# session without a close is skipped (the averages carry over it) and reads
# NaN itself.
def rsi(close: np.ndarray, window: int = RSI_WINDOW) -> np.ndarray:
    """Return the (T, N) RSI of a close panel."""
    close = np.asarray(close, dtype=float)
    rows, n = close.shape
    out = np.full((rows, n), np.nan)
    if rows < 2:
        return out
    with np.errstate(invalid="ignore"):
        change = np.diff(close, axis=0)
    gain = np.where(np.isfinite(change), np.maximum(change, 0.0), np.nan)
    loss = np.where(np.isfinite(change), np.maximum(-change, 0.0), np.nan)
    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)
    count = np.zeros(n, dtype=int)
    for i in range(len(change)):
        known = np.isfinite(gain[i])
        count = np.where(known, count + 1, count)
        seeding = known & (count <= window)
        # The first `window` changes seed the averages as a plain mean.
        avg_gain = np.where(
            seeding,
            np.where(count == 1, gain[i], avg_gain + (gain[i] - avg_gain) / count),
            avg_gain,
        )
        avg_loss = np.where(
            seeding,
            np.where(count == 1, loss[i], avg_loss + (loss[i] - avg_loss) / count),
            avg_loss,
        )
        smoothing = known & (count > window)
        avg_gain = np.where(
            smoothing, (avg_gain * (window - 1) + gain[i]) / window, avg_gain
        )
        avg_loss = np.where(
            smoothing, (avg_loss * (window - 1) + loss[i]) / window, avg_loss
        )
        ready = known & (count >= window)
        with np.errstate(invalid="ignore", divide="ignore"):
            value = np.where(
                avg_loss > 0,
                100.0
                - 100.0 / (1.0 + avg_gain / np.where(avg_loss > 0, avg_loss, 1.0)),
                np.where(avg_gain > 0, 100.0, 50.0),
            )
        out[i + 1] = np.where(ready, value, np.nan)
    return out


# The close's distance from its 20-day mean in sigma units: the upper
# Bollinger band is +2, the lower -2 (the desk's `entry.bollinger_z` is this
# halved). NaN before the window is full or where the sigma is zero.
def band_sigma_z(close: np.ndarray, window: int = BAND_WINDOW) -> np.ndarray:
    """Return the (T, N) band position in standard deviations."""
    close = np.asarray(close, dtype=float)
    mean = technical.sma(close, window)
    std = np.full_like(close, np.nan)
    for t in range(window - 1, close.shape[0]):
        with np.errstate(all="ignore"):
            std[t] = np.nanstd(close[t - window + 1 : t + 1], axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (close - mean) / std
    return np.where(np.isfinite(z), z, np.nan)


# The close's gap to its 21-session EMA as a fraction: -0.08 is 8% under.
def ema_gap(close: np.ndarray, span: int = EMA_SPAN) -> np.ndarray:
    """Return the (T, N) close / EMA - 1."""
    close = np.asarray(close, dtype=float)
    average = technical.ema(close, span)
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = close / average - 1.0
    return np.where(np.isfinite(gap), gap, np.nan)


@dataclass
class Trim:
    """One rule action: what was sold or added, at what weight, and what came after."""

    ticker: str
    column: int
    kind: str
    index: int
    date: str
    price: float
    weight_before: float
    weight_after: float
    # The share of equity sold (positive) or, for an add, the raise (negative).
    size: float
    indicator: float
    # Filled after the run: the name's close FORWARD_SESSIONS later over the
    # action's close minus one, and whether the name rose (a trim sold too
    # early) or fell further (a dip that continued). None when the panel ends
    # before the window does.
    forward: float | None = None
    rose: bool | None = None

    # The record as a JSON-able dict.
    def as_dict(self) -> dict[str, Any]:
        """Return the fields as a plain dict."""
        return asdict(self)


class ProfitTaking:
    """One rule around the policy's allocator: state per name, the trims, the record.

    `allocator` wraps the policy for `simulate.run(allocator=...)` and
    `weight_filter` is the per-session hook; both share this object's
    state. The allocator is called first on a reset session (before the
    hook) and after the hook on a mid-cycle session (for the redeploy's
    targets), which is how a reset is recognised: a session the hook has
    not seen yet.
    """

    # Bind the policy's allocator, the variant and the restricted report;
    # compute the rule's indicator over the whole panel (each row reads
    # closes through its own session only). `forecast` is the (T, N)
    # aligned drawdown forecast for the model rules, NaN where absent.
    def __init__(self, base, variant_: Variant, restricted, forecast=None) -> None:
        if variant_.rule is not None and variant_.rule not in RULES:
            raise ValueError(f"unknown rule {variant_.rule!r}")
        panel = restricted.panel
        self.base = base
        self.variant = variant_
        self.report = restricted
        self.panel = panel
        self.closes = np.asarray(panel.adj_close, dtype=float)
        self.tickers = list(panel.tickers)
        self.stamps = [str(d) for d in panel.dates]
        rule = variant_.rule
        self.indicator: np.ndarray | None = None
        if rule == RSI:
            self.indicator = rsi(self.closes)
        elif rule == BAND:
            self.indicator = band_sigma_z(self.closes)
        elif rule == DIP:
            self.indicator = ema_gap(self.closes)
        elif rule == FORECAST:
            if forecast is None:
                raise ValueError(f"{variant_.name} needs the aligned drawdown forecast")
            forecast = np.asarray(forecast, dtype=float)
            if forecast.shape != self.closes.shape:
                raise ValueError("forecast must be aligned to the panel (T, N)")
            self.indicator = forecast
        self.state: dict[int, str] = {}
        self.trim_price: dict[int, float] = {}
        self.cooling: set[int] = set()
        self.seen: set[int] = set()
        self.resets: list[int] = []
        self.trims: list[Trim] = []

    # The policy's targets on `t` with the rule's state applied: a trimmed
    # name at `fraction` of its target, a stopped name at zero, an added
    # name at `ratio` x its target under the hold cap with the other held
    # names scaled down pro rata so the book's gross is unchanged.
    def _apply_state(self, target: np.ndarray) -> np.ndarray:
        out = np.array(target, dtype=float)
        adds: list[int] = []
        for column, kind in self.state.items():
            if kind == TRIMMED:
                out[column] = target[column] * self.variant.fraction
            elif kind == STOPPED:
                out[column] = 0.0
            elif kind == ADDED and target[column] > 0:
                adds.append(column)
        if adds:
            raise_total = 0.0
            wanted: dict[int, float] = {}
            for column in adds:
                want = min(target[column] * self.variant.ratio, policy_v4.HOLD_CAP)
                wanted[column] = want
                raise_total += max(0.0, want - out[column])
            others = np.ones(len(out), dtype=bool)
            others[adds] = False
            others &= out > 0
            pool = float(out[others].sum())
            if pool > 0 and raise_total > 0:
                out[others] *= max(0.0, 1.0 - min(raise_total, pool) / pool)
            for column, want in wanted.items():
                out[column] = want
        return out

    # The rebalance allocator (and the redeploy's row-t targets): the policy's
    # targets with the state applied. A session the hook has not seen is a
    # reset, where a dip-add and a stop are restored.
    def allocator(self, report, panel, config, t: int) -> np.ndarray:
        """Return the policy's targets on `t` with the rule's state applied."""
        target = np.asarray(self.base(report, panel, config, t), dtype=float)
        if int(t) not in self.seen:
            self.resets.append(int(t))
            for column in [c for c, k in self.state.items() if k in (ADDED, STOPPED)]:
                if self.state[column] == ADDED:
                    self.cooling.add(column)
                del self.state[column]
        return self._apply_state(target)

    # Record one action of the rule on `column` at session `t`.
    def _record(
        self, kind: str, column: int, t: int, before: float, after: float, value: float
    ) -> None:
        self.trims.append(
            Trim(
                ticker=self.tickers[column],
                column=int(column),
                kind=kind,
                index=int(t),
                date=self.stamps[int(t)],
                price=float(self.closes[t, column]),
                weight_before=float(before),
                weight_after=float(after),
                size=float(before - after),
                indicator=float(value),
            )
        )

    # The per-session hook for `simulate.run`: `weights` is the held book's
    # weight per name between resets and the allocator's (state-applied)
    # targets on a reset; `prices` that session's adjusted closes. Reads the
    # rule's indicator on `t`, moves the state, records the action, and
    # returns the target the book should hold: on a mid-cycle session the
    # held weights with the trims cut in (the raise of a dip-add is left to
    # the redeploy, which buys toward the allocator's targets), on a reset
    # the allocator's targets recomputed with the new state.
    def weight_filter(self, t: int, weights, prices) -> np.ndarray:  # noqa: C901 - one rule per branch
        """Return `weights` with the rule's trims applied for session `t`."""
        t = int(t)
        self.seen.add(t)
        held = np.array(weights, dtype=float)
        prices = np.asarray(prices, dtype=float)
        rule = self.variant.rule
        if rule is None:
            return held
        base = np.asarray(self.base(self.report, self.panel, None, t), dtype=float)
        is_reset = bool(self.resets) and self.resets[-1] == t
        # A name the policy no longer wants (downgraded, or out of the book)
        # loses its state: the rotation sells it and the reset decides anew.
        for column in [c for c in self.state if not base[c] > 0]:
            del self.state[column]
        self.cooling = {c for c in self.cooling if base[c] > 0}
        out = held.copy()
        graded = np.flatnonzero((base > 0) & np.isfinite(prices) & (prices > 0))
        if rule == RUNUP:
            if not is_reset:
                for column in graded:
                    column = int(column)
                    if held[column] >= self.variant.ratio * base[column] - 1e-12:
                        out[column] = base[column]
                        self._record(
                            TRIM,
                            column,
                            t,
                            held[column],
                            out[column],
                            held[column] / base[column],
                        )
            return out
        assert self.indicator is not None
        signal = self.indicator[t]
        if rule in (RSI, BAND):
            for column in graded:
                column = int(column)
                value = float(signal[column])
                if not np.isfinite(value):
                    continue
                if column not in self.state and value > self.variant.on:
                    self.state[column] = TRIMMED
                    cut = base[column] * self.variant.fraction
                    if held[column] > cut:
                        out[column] = cut
                        self._record(TRIM, column, t, held[column], cut, value)
                elif self.state.get(column) == TRIMMED and value < self.variant.off:
                    del self.state[column]
                    self._record(RESTORE, column, t, held[column], held[column], value)
        elif rule == DIP:
            for column in list(self.cooling):
                if not float(signal[column]) < self.variant.on:
                    self.cooling.discard(column)
            for column in graded:
                column = int(column)
                value = float(signal[column])
                if (
                    column in self.state
                    or column in self.cooling
                    or not np.isfinite(value)
                    or not value < self.variant.on
                    or not held[column] > 0
                ):
                    continue
                self.state[column] = ADDED
                raised = self._apply_state(base)
                want = float(raised[column])
                if want <= held[column]:
                    del self.state[column]
                    continue
                self._record(ADD, column, t, held[column], want, value)
                if not is_reset:
                    # Pay the raise from cash beyond the buffer first, then
                    # pro rata from the other held A/A+ names; the buy itself
                    # is the redeploy's, toward the raised allocator target.
                    spare = max(0.0, 1.0 - float(held.sum()) - simulate.REDEPLOY_BUFFER)
                    need = max(0.0, want - held[column] - spare)
                    others = np.zeros(len(held), dtype=bool)
                    others[graded] = True
                    others[column] = False
                    others &= held > 0
                    pool = float(held[others].sum())
                    if need > 0 and pool > 0:
                        out[others] = held[others] * (1.0 - min(need, pool) / pool)
        elif rule == FORECAST:
            # The worst `quantile` of the day's scored A/A+ names by forecast,
            # at least one name, ties broken by column order - a rank, not a
            # threshold, so a tie never trims the whole book.
            scored = graded[np.isfinite(signal[graded])]
            k = max(1, int(math.ceil(self.variant.quantile * len(scored))))
            order = scored[np.argsort(signal[scored], kind="stable")]
            worst = {int(c) for c in order[:k]}
            for column in scored:
                column = int(column)
                value = float(signal[column])
                kind = self.state.get(column)
                if kind is None and column in worst:
                    self.state[column] = TRIMMED
                    self.trim_price[column] = float(prices[column])
                    cut = base[column] * self.variant.fraction
                    if held[column] > cut:
                        out[column] = cut
                        self._record(TRIM, column, t, held[column], cut, value)
                elif kind == TRIMMED and column not in worst:
                    del self.state[column]
                    self.trim_price.pop(column, None)
                    self._record(RESTORE, column, t, held[column], held[column], value)
            if self.variant.stop is not None:
                for column in [c for c, k in self.state.items() if k == TRIMMED]:
                    reference = self.trim_price.get(column)
                    price = float(prices[column])
                    if (
                        reference is not None
                        and np.isfinite(price)
                        and price < reference * (1.0 - self.variant.stop)
                    ):
                        self.state[column] = STOPPED
                        self._record(
                            STOP, column, t, held[column], 0.0, price / reference - 1.0
                        )
                        out[column] = 0.0
        if is_reset:
            return self._apply_state(base)
        # A persistent state is enforced every mid-cycle session, not only at
        # the trigger: a sale the live fill held back on a green open is
        # retried the next session, and a halved name that runs on is kept
        # at its cut (the planner's trade floor leaves dust alone).
        for column, kind in self.state.items():
            if kind == TRIMMED:
                cut = base[column] * self.variant.fraction
                if out[column] > cut:
                    out[column] = cut
            elif kind == STOPPED:
                out[column] = 0.0
        return out

    # Fill every action's forward reading from the panel's closes.
    def resolve_forward(self, sessions: int = FORWARD_SESSIONS) -> None:
        """Mark each trim with the name's return over the next `sessions`."""
        rows = self.closes.shape[0]
        for trim in self.trims:
            later = trim.index + sessions
            if later >= rows:
                continue
            close = self.closes[later, trim.column]
            if not (np.isfinite(close) and trim.price > 0):
                continue
            trim.forward = float(close / trim.price - 1.0)
            trim.rose = bool(trim.forward > 0)


@dataclass
class Priced:
    """One variant from one offset at one cost: curve, diagnostics, the trims."""

    curve: Curve
    diagnostics: dict[str, dict[str, float]] = field(default_factory=dict)
    trims: list[Trim] = field(default_factory=list)
    resets: int = 0


# The rule for a variant around the policy's allocator on the restricted report.
def build(
    variant_: Variant, mask: np.ndarray, restricted, forecast=None
) -> ProfitTaking:
    """Return the ProfitTaking for `variant_` around `policy_v4.allocator(mask)`."""
    return ProfitTaking(policy_v4.allocator(mask), variant_, restricted, forecast)


# Price one variant from one offset at one cost: `simulate.run` on the
# restricted report under the control's options, with the rule's allocator
# and hook for a variant with a rule, and a fresh Ledger for the exposure
# reading. The control is `simulate.run` under the control's options with
# the policy's own allocator and no hook, element for element.
def price(
    restricted,
    mask: np.ndarray,
    variant_: Variant,
    since,
    cost_bps: float,
    forecast=None,
    idle=None,
) -> Priced:
    """Return the variant's Priced result from `since` at `cost_bps`."""
    panel = restricted.panel
    options = control_options(panel)
    ledger = Ledger()
    ledger.exposure = options.get("event_exposure")
    ledger.idle = idle_target_path(restricted, mask) if idle is None else idle
    rule = None
    if variant_.rule is None:
        allocator = policy_v4.allocator(mask)
    else:
        rule = build(variant_, mask, restricted, forecast)
        allocator = rule.allocator
        options["weight_filter"] = rule.weight_filter
        options["midcycle_trims"] = True
    result = simulate.run(
        restricted,
        since=since,
        cost_bps=cost_bps,
        allocator=allocator,
        journal=ledger,
        **options,
    )
    trims: list[Trim] = []
    resets = 0
    if rule is not None:
        rule.resolve_forward()
        trims = rule.trims
        resets = len(rule.resets)
    return Priced(
        Curve(variant_.name, result.dates, result.returns),
        {w: diagnostics(ledger, s, e) for w, (s, e) in WINDOWS.items()},
        trims,
        resets,
    )


# Median over finite entries, NaN when there are none.
def _nanmedian(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.nanmedian(x)) if np.isfinite(x).any() else math.nan


# Minimum over finite entries, NaN when there are none.
def _nanmin(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.nanmin(x)) if np.isfinite(x).any() else math.nan


# Maximum over finite entries, NaN when there are none.
def _nanmax(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.nanmax(x)) if np.isfinite(x).any() else math.nan


# Mean over finite entries, NaN when there are none.
def _nanmean(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.nanmean(x)) if np.isfinite(x).any() else math.nan


# The reference calendar of one offset: the control's sessions, else the
# first variant that ran.
def _calendar(offset: dict[str, Priced]) -> np.ndarray:
    if CONTROL in offset:
        return offset[CONTROL].curve.dates
    return next(iter(offset.values())).curve.dates


# The actions of one run whose session falls inside a window.
def _in_window(trims: list[Trim], dates: np.ndarray, keep: np.ndarray) -> list[Trim]:
    inside = {str(d) for d in np.asarray(dates)[keep]}
    return [tr for tr in trims if tr.date in inside]


# The trim statistics' names, in payload order.
TRIM_STATS: tuple[str, ...] = (
    "trims_per_year",
    "adds_per_year",
    "restores_per_year",
    "stops_per_year",
    "mean_trim_size",
    "mean_add_size",
    "too_early_rate",
    "dip_continued_rate",
    "median_forward_after_trim",
    "trim_forward_bp",
    "trims_total",
    "trims_resolved",
)


# The trim statistics of one variant over one window, pooled across the
# offsets' actions inside it: actions a year (median across offsets), the
# mean size of a trim and of an add, the share of trims the name rose after
# ("sold too early"), the share of adds the name fell further after, the
# median forward return after a trim, and the bp of equity the sold slice
# would have earned over the forward window (size x forward, mean per trim).
def trim_stats(
    runs: list[Priced], base_dates: list[np.ndarray], keep: list[np.ndarray]
) -> dict[str, float]:
    """Return the pooled trim statistics over the runs' actions in the window."""
    per_year: dict[str, list[float]] = {TRIM: [], ADD: [], RESTORE: [], STOP: []}
    trims: list[Trim] = []
    adds: list[Trim] = []
    for run, dates, inside in zip(runs, base_dates, keep, strict=True):
        actions = _in_window(run.trims, dates, inside)
        years = int(inside.sum()) / 252.0
        for kind in per_year:
            count = sum(1 for a in actions if a.kind == kind)
            per_year[kind].append(count / years if years > 0 else math.nan)
        trims.extend(a for a in actions if a.kind in (TRIM, STOP))
        adds.extend(a for a in actions if a.kind == ADD)
    resolved = [a for a in trims if a.rose is not None]
    adds_resolved = [a for a in adds if a.rose is not None]
    return {
        "trims_per_year": _nanmedian(
            np.array(per_year[TRIM]) + np.array(per_year[STOP])
        ),
        "adds_per_year": _nanmedian(per_year[ADD]),
        "restores_per_year": _nanmedian(per_year[RESTORE]),
        "stops_per_year": _nanmedian(per_year[STOP]),
        "mean_trim_size": _nanmean([a.size for a in trims]),
        "mean_add_size": _nanmean([-a.size for a in adds]),
        "too_early_rate": (
            sum(1 for a in resolved if a.rose) / len(resolved) if resolved else math.nan
        ),
        "dip_continued_rate": (
            sum(1 for a in adds_resolved if not a.rose) / len(adds_resolved)
            if adds_resolved
            else math.nan
        ),
        "median_forward_after_trim": _nanmedian([a.forward for a in resolved]),
        "trim_forward_bp": _nanmean([a.size * a.forward * 1e4 for a in resolved]),
        "trims_total": float(len(trims)),
        "trims_resolved": float(len(resolved)),
    }


# One row per (variant, window) at one cost: the scorecard's medians and
# worsts, offsets above the control, the medians of the ledger diagnostics
# and the pooled trim statistics.
def summarise(priced: list[dict[str, Priced]], cost_bps: float) -> list[dict[str, Any]]:
    """Return the per-window rows across the offsets at `cost_bps`."""
    rows: list[dict[str, Any]] = []
    names = [v.name for v in VARIANTS if all(v.name in offset for offset in priced)]
    for window, (start, end) in WINDOWS.items():
        stats: dict[str, list[dict[str, float]]] = {name: [] for name in names}
        bases = [_calendar(offset) for offset in priced]
        keeps = [point_in_time.window(base, start, end) for base in bases]
        for offset, base, keep in zip(priced, bases, keeps, strict=True):
            for name in names:
                stats[name].append(window_stats(_on(base, offset[name].curve)[keep]))
        control = np.array([s["cagr"] for s in stats.get(CONTROL, [])], dtype=float)
        for name in names:
            cagrs = np.array([s["cagr"] for s in stats[name]], dtype=float)
            above = int(np.nansum(cagrs > control)) if len(control) == len(cagrs) else 0
            row: dict[str, Any] = {
                "line": name,
                "cost_bps": cost_bps,
                "window": window,
                "offsets": len(priced),
                "median_cagr": _nanmedian(cagrs),
                "worst_cagr": _nanmin(cagrs),
                "best_cagr": _nanmax(cagrs),
                "median_drawdown": _nanmedian([s["drawdown"] for s in stats[name]]),
                "median_sharpe": _nanmedian([s["sharpe"] for s in stats[name]]),
                "offsets_above_control": above,
                "sessions": int(np.nanmedian([s["sessions"] for s in stats[name]])),
            }
            for key in DIAGNOSTICS:
                row[key] = _nanmedian(
                    [
                        offset[name].diagnostics.get(window, {}).get(key, math.nan)
                        for offset in priced
                    ]
                )
            row.update(trim_stats([offset[name] for offset in priced], bases, keeps))
            rows.append(row)
    return rows


# The paired daily difference of every variant against the control at the
# median offset, per window: mean bp a day, Newey-West t at lag 20 and the
# probabilistic Sharpe.
def paired(priced: list[dict[str, Priced]], cost_bps: float) -> list[dict[str, Any]]:
    """Return the paired rows against the control at the median offset."""
    out: list[dict[str, Any]] = []
    offset = priced[len(priced) // 2]
    if CONTROL not in offset:
        return out
    base = _calendar(offset)
    for window, (start, end) in WINDOWS.items():
        keep = point_in_time.window(base, start, end)
        b = _on(base, offset[CONTROL].curve)[keep]
        for v in VARIANTS:
            if v.name == CONTROL or v.name not in offset:
                continue
            diff = _on(base, offset[v.name].curve)[keep] - b
            diff = diff[np.isfinite(diff)]
            mom = candidate_stats.moments(diff) if len(diff) > 2 else None
            out.append(
                {
                    "cost_bps": cost_bps,
                    "window": window,
                    "line": v.name,
                    "against": CONTROL,
                    "sessions": int(len(diff)),
                    "mean_daily_bp": float(diff.mean() * 1e4)
                    if len(diff)
                    else math.nan,
                    "hac_t": candidate_stats.hac_t(diff, HAC_LAG)
                    if len(diff) > 2
                    else math.nan,
                    "psr": (
                        candidate_stats.probabilistic_sharpe(
                            mom.sharpe, mom.length, mom.skew, mom.kurtosis
                        )
                        if mom is not None
                        else math.nan
                    ),
                }
            )
    return out


# The variants a run prices and the reasons the others are skipped: the
# model-based rules need the aligned forecast.
def selected(forecast) -> tuple[tuple[Variant, ...], dict[str, str]]:
    """Return (variants to price, {skipped name: reason})."""
    skipped: dict[str, str] = {}
    chosen: list[Variant] = []
    for v in VARIANTS:
        if v.model and forecast is None:
            skipped[v.name] = (
                "no drawdown forecast file (--drawdown-forecasts): the model-based "
                "trims read the CNN's OOS drawdown20 forecast exported by "
                "market_deep_stage2 --export-forecasts"
            )
        else:
            chosen.append(v)
    return tuple(chosen), skipped


# Run every variant at every offset and cost and assemble the payload.
# `store` is accepted for the scorecard's call shape and is not read.
# `forecast` is the (T, N) aligned drawdown forecast, or None to skip the
# model rules. The actions kept in the payload are those of the median
# offset at the verdict cost, per variant.
def run_variants(
    report,
    restricted,
    mask: np.ndarray,
    store,
    offsets: int,
    costs: tuple[float, ...],
    forecast=None,
) -> dict[str, Any]:
    """Return the study payload for the policy on the restricted report."""
    panel = restricted.panel
    costs = tuple(float(c) for c in costs)
    verdict_cost = VERDICT_COST_BPS if VERDICT_COST_BPS in costs else max(costs)
    chosen, skipped = selected(forecast)
    idle = idle_target_path(restricted, mask)
    payload: dict[str, Any] = {
        "study": STUDY,
        "policy": policy_v4.POLICY_VERSION,
        "asof": str(panel.dates[-1]),
        "offsets": int(offsets),
        "costs_bps": list(costs),
        "windows": {
            k: [str(s) if s else None, str(e) if e else None]
            for k, (s, e) in WINDOWS.items()
        },
        "trials": len(VARIANTS),
        "control": CONTROL,
        "variants": [
            {
                "name": v.name,
                "rule": v.rule,
                "fraction": v.fraction if v.rule in (RSI, BAND, FORECAST) else None,
                "ratio": v.ratio if v.rule in (RUNUP, DIP) else None,
                "on": v.on if np.isfinite(v.on) else None,
                "off": v.off if np.isfinite(v.off) else None,
                "quantile": v.quantile if v.rule == FORECAST else None,
                "stop": v.stop,
                "model": v.model,
                "note": v.note,
            }
            for v in VARIANTS
        ],
        "options": _describe(control_options(panel)),
        "forward_sessions": FORWARD_SESSIONS,
        "hac_lag": HAC_LAG,
        "diagnostics": list(DIAGNOSTICS),
        "trim_stats": list(TRIM_STATS),
        "rows": [],
        "paired": [],
        "trims": {},
        "skipped": skipped,
        "forecast_coverage": (
            float(np.isfinite(forecast).mean()) if forecast is not None else None
        ),
        "note": (
            "Every variant is one registered trial, fixed in VARIANTS before the run: "
            "the live executor with the redeploy of idle cash (the control) plus one "
            "trim or dip rule through the allocator wrapper and the weight_filter "
            "hook with midcycle_trims. Lines priced on identical sessions from each "
            "of the first `offsets` sessions of the restricted report; medians and "
            "worsts across offsets; paired statistics at the median offset against "
            "the control; trim statistics pooled across offsets over the actions in "
            "the window; the forward reading is the name's close FORWARD_SESSIONS "
            "later over the action's close."
        ),
    }
    for cost in costs:
        priced: list[dict[str, Priced]] = []
        for k in range(int(offsets)):
            since = _since(panel, k)
            priced.append(
                {
                    v.name: price(restricted, mask, v, since, cost, forecast, idle)
                    for v in chosen
                }
            )
        payload["rows"].extend(summarise(priced, cost))
        payload["paired"].extend(paired(priced, cost))
        if cost == verdict_cost:
            median = priced[len(priced) // 2]
            payload["trims"] = {
                name: [tr.as_dict() for tr in run.trims] for name, run in median.items()
            }
            payload["resets"] = {name: run.resets for name, run in median.items()}
    payload["ran"] = [v.name for v in chosen]
    return payload


# The row for a line and window at a cost, or None.
def _row(payload: dict[str, Any], line: str, window: str, cost: float) -> dict | None:
    for r in payload["rows"]:
        if r["line"] == line and r["window"] == window and float(r["cost_bps"]) == cost:
            return r
    return None


# The paired entry for a line against the control in a window at a cost, or None.
def _pair(payload: dict[str, Any], line: str, window: str, cost: float) -> dict | None:
    for p in payload["paired"]:
        if (
            p["line"] == line
            and p["against"] == CONTROL
            and p["window"] == window
            and float(p["cost_bps"]) == cost
        ):
            return p
    return None


# A payload value that may be None (after json_ready) or NaN, as a float.
def _f(value) -> float:
    return math.nan if value is None else float(value)


# A signed number to `digits` decimals, "n/a" for NaN.
def _signed(x: float, digits: int = 2) -> str:
    return "n/a" if not np.isfinite(x) else f"{x:+.{digits}f}"


# A fraction as a percentage to one decimal, "n/a" for NaN.
def _pct(x: float) -> str:
    return "n/a" if not np.isfinite(x) else f"{x * 100:.1f}%"


# The verdict: every variant is read against the control at 25 bp - CAGR
# points on the choosing window (the CAGR attributable to the trims, since
# nothing else differs), the paired t there, the paired bp/d on the
# reported window, the drawdown gap on both windows. ADOPT (registered)
# when all four floors hold; else RECORD; a skipped variant is SKIPPED with
# its reason. Beside the decision, the exposure-adjusted reading (the
# control's CAGR scaled to the variant's invested share), the per-offset
# sign test (CONSISTENT as the mid-cycle study reads it) and the trim
# statistics the floors do not read.
def verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the verdict block for the payload."""
    costs = [float(c) for c in payload.get("costs_bps", [])]
    cost = (
        VERDICT_COST_BPS
        if VERDICT_COST_BPS in costs
        else (max(costs) if costs else math.nan)
    )
    control = _row(payload, CONTROL, CHOOSING, cost) or {}
    control_later = _row(payload, CONTROL, REPORTED, cost) or {}
    control_cagr = _f(control.get("median_cagr"))
    control_dd = {
        CHOOSING: _f(control.get("median_drawdown")),
        REPORTED: _f(control_later.get("median_drawdown")),
    }
    skipped = payload.get("skipped", {}) or {}
    variants: dict[str, dict[str, Any]] = {}
    adopt: list[str] = []
    record: list[str] = []
    for v in VARIANTS:
        if v.name == CONTROL:
            continue
        row = _row(payload, v.name, CHOOSING, cost) or {}
        later = _row(payload, v.name, REPORTED, cost) or {}
        pair = _pair(payload, v.name, CHOOSING, cost) or {}
        later_pair = _pair(payload, v.name, REPORTED, cost) or {}
        points = (_f(row.get("median_cagr")) - control_cagr) * 100.0
        later_points = (
            _f(later.get("median_cagr")) - _f(control_later.get("median_cagr"))
        ) * 100.0
        t = _f(pair.get("hac_t"))
        later_bp = _f(later_pair.get("mean_daily_bp"))
        dd_gap = {
            CHOOSING: (_f(row.get("median_drawdown")) - control_dd[CHOOSING]) * 100.0,
            REPORTED: (_f(later.get("median_drawdown")) - control_dd[REPORTED]) * 100.0,
        }
        measured = bool(np.isfinite(points))
        passes = bool(
            measured and points >= ADOPT_POINTS and np.isfinite(t) and t >= ADOPT_T
        )
        not_worse = bool(np.isfinite(later_bp) and later_bp >= 0.0)
        drawdown_ok = bool(
            all(np.isfinite(g) and g >= -DRAWDOWN_POINTS for g in dd_gap.values())
        )
        if v.name in skipped and not measured:
            decision = SKIPPED
        else:
            decision = ADOPT if passes and not_worse and drawdown_ok else RECORD
        control_invested = 1.0 - _f(control.get("cash_share"))
        invested = 1.0 - _f(row.get("cash_share"))
        adjusted_control = (
            control_cagr * invested / control_invested
            if np.isfinite(control_invested)
            and control_invested > 0
            and np.isfinite(invested)
            else math.nan
        )
        adjusted_points = (_f(row.get("median_cagr")) - adjusted_control) * 100.0
        offsets = int(row.get("offsets") or 0)
        above = int(row.get("offsets_above_control") or 0) if offsets else 0
        needed = int(math.ceil(CONSISTENT_SHARE * offsets)) if offsets else 0
        consistent = bool(
            decision == RECORD
            and measured
            and offsets > 0
            and above >= needed
            and points >= CONSISTENT_POINTS
        )
        variants[v.name] = {
            "rule": v.rule,
            "model": v.model,
            "measured": measured,
            "skipped": skipped.get(v.name),
            "choosing_points": points,
            "trims_cagr_points": points,
            "choosing_bp_vs_control": _f(pair.get("mean_daily_bp")),
            "choosing_t_vs_control": t,
            "reported_points": later_points,
            "reported_bp_vs_control": later_bp,
            "drawdown_gap_points": dd_gap,
            "passes_choosing": passes,
            "not_worse_reported": not_worse,
            "drawdown_within": drawdown_ok,
            "invested_share": invested,
            "control_invested_share": control_invested,
            "exposure_adjusted_control_cagr": adjusted_control,
            "exposure_adjusted_points": adjusted_points,
            "offsets_above_control": above,
            "offsets": offsets,
            "reported_offsets_above_control": int(
                later.get("offsets_above_control") or 0
            ),
            "trims_per_year": _f(row.get("trims_per_year")),
            "adds_per_year": _f(row.get("adds_per_year")),
            "mean_trim_size": _f(row.get("mean_trim_size")),
            "too_early_rate": _f(row.get("too_early_rate")),
            "trim_forward_bp": _f(row.get("trim_forward_bp")),
            "consistent": consistent,
            "reading": CONSISTENT if consistent else decision,
            "decision": decision,
        }
        if decision == ADOPT:
            adopt.append(v.name)
        elif decision == RECORD:
            record.append(v.name)
    if not np.isfinite(control_cagr):
        text = f"not measured: the control has no {CHOOSING} CAGR at {cost:g} bp"
    else:
        parts = []
        for name, info in variants.items():
            if info["decision"] == SKIPPED:
                parts.append(f"{name} {SKIPPED} (no forecast file)")
                continue
            parts.append(
                f"{name} {_signed(info['choosing_points'], 1)} pt "
                f"(t {_signed(info['choosing_t_vs_control'])}, "
                f"{REPORTED} {_signed(info['reported_bp_vs_control'], 1)} bp/d, "
                f"DD {_signed(info['drawdown_gap_points'][CHOOSING], 1)}/"
                f"{_signed(info['drawdown_gap_points'][REPORTED], 1)} pt; "
                f"{info['trims_per_year']:.1f} trims/yr, sold too early "
                f"{_pct(info['too_early_rate'])}; exposure-adjusted "
                f"{_signed(info['exposure_adjusted_points'], 1)} pt, "
                f"{info['offsets_above_control']}/{info['offsets']} offsets above the "
                f"control) {info['reading']}"
            )
        consistent_names = [n for n, i in variants.items() if i["consistent"]]
        text = (
            f"{CHOOSING} at {cost:g} bp: control {control_cagr * 100:.1f}% CAGR, "
            f"median max drawdown {control_dd[CHOOSING] * 100:.1f}%, invested "
            f"{_pct(1.0 - _f(control.get('cash_share')))}. Variants against the "
            "control (CAGR points, all attributable to the rule): "
            + "; ".join(parts)
            + ". "
            + (
                f"{ADOPT}: {', '.join(adopt)}."
                if adopt
                else (
                    f"No rule clears {ADOPT_POINTS:g} pt with t >= {ADOPT_T:g}, not "
                    f"worse on {REPORTED} and drawdown within {DRAWDOWN_POINTS:g} pt; "
                    f"every priced rule is RECORD."
                )
            )
            + (
                f" {CONSISTENT}: {', '.join(consistent_names)} (above the control on "
                f"at least {CONSISTENT_SHARE:.0%} of the offsets with "
                f">= {CONSISTENT_POINTS:g} pt; a reading, not an adoption)."
                if consistent_names
                else ""
            )
        )
    return {
        "cost_bps": cost,
        "choosing_window": CHOOSING,
        "reported_window": REPORTED,
        "floors": {
            "points": ADOPT_POINTS,
            "hac_t": ADOPT_T,
            "drawdown_points": DRAWDOWN_POINTS,
            "consistent_share": CONSISTENT_SHARE,
            "consistent_points": CONSISTENT_POINTS,
        },
        "control_cagr": control_cagr,
        "control_drawdown": control_dd[CHOOSING],
        "variants": variants,
        "adopt": adopt,
        "record": record,
        "skipped": [n for n, i in variants.items() if i["decision"] == SKIPPED],
        "consistent": [n for n, i in variants.items() if i["consistent"]],
        "text": text,
    }
