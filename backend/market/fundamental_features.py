"""Quarterly fundamental features, point-in-time, from stored versions.

The frozen feature path (`edgar.edgar_features`) chooses one tag per name
over the whole snapshot, keeps the earliest-filed value of each period, and
turns any missing ratio into a zero: `np.where(np.isfinite(series), series,
0.0)`. The fundamental analyst (`agents/trading/desk/fundamental.py`) then
reads a row whose `has_fundamentals` flag is set — set from revenue being
known — and ranks those fabricated zeros as valid inputs.

This module is the research-only correction, built on the as-of versions in
`fundamentals_asof` and otherwise standalone:

- Every feature is computed from the versions available at each session,
  never from a later filing or a future period; a restatement changes a
  feature only from its availability on, and a later filing cannot change
  any earlier feature, including the tag-selection decision.
- Each name's quarterly values come from the tag the as-of selector would
  choose with the periods available then (deterministic table-order ties),
  with quarters derived from six/nine-month spans and from the year exactly
  as `fundamentals_asof._quarters` derives them.
- Missing values stay NaN. No zero is fabricated: a genuinely zero growth
  or margin is a real zero, while a missing lagged quarter or a zero
  denominator is NaN.
- Ratios divide values of the same fiscal period: numerator and denominator
  are taken from the latest quarter end where both are known, so an old
  numerator is never divided by a newer quarter of revenue.
- Every economic feature's reference period end is exposed as a separate
  datetime64[D] tensor (`period_ends`), NaT where the feature is unknown, so
  a consumer can see that a margin still sits on an older quarter while
  revenue growth has moved on. Filing staleness is a separate, filing
  activity counter, not a freshness flag for each feature.

Nothing here is read by the nightly desk or the frozen shadow ledger. This
is a research input only and does not by itself establish a profitable
strategy or promote any model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from backend.market import fundamentals_asof as fa
from backend.market.panel import Panel

# The economic feature columns, in a fixed order. The incumbent EDGAR path
# names them the same, so a corrected-versus-frozen comparison is like for
# like, but here a missing value stays NaN instead of reading as zero.
FEATURE_NAMES = (
    "revenue_yoy",
    "revenue_qoq",
    "revenue_acceleration",
    "gross_margin",
    "net_margin",
    "ocf_to_revenue",
    "capex_to_revenue",
)

# The as-of flow names the features read, in `fundamentals_asof`'s own
# vocabulary, so `_select` and `_quarters` apply unchanged.
FLOW_NAMES = fa.FLOW_NAMES

# margin feature -> (numerator level, denominator level), all revenue ratios.
_MARGINS = (
    ("gross_margin", "gross_profit", "revenue"),
    ("net_margin", "net_income", "revenue"),
    ("ocf_to_revenue", "operating_cash_flow", "revenue"),
    ("capex_to_revenue", "capex", "revenue"),
)

# The incumbent calls the period about `quarters` before another the one
# whose end falls within this many days of 91*quarters back; a lagged
# quarter outside the window is treated as missing, never filled from
# a neighbouring period.
_LAG_WINDOW_DAYS = 20
_QUARTER_DAYS = 91


@dataclass(frozen=True, slots=True)
class FundamentalFeatures:
    """The (T, N, K) feature tensor plus its non-economic companions.

    `values` carries the `FEATURE_NAMES` columns with NaN wherever a feature
    is not computable. `period_ends` is a parallel datetime64[D] tensor: the
    fiscal period end each economic feature references, NaT wherever the
    feature is NaN, so a consumer can detect an individual ratio that still
    sits on an older quarter while revenue has moved on. `available` is a
    mask: has this name published any fundamental by this session. `staleness`
    is the number of sessions since the name's latest newly available filing
    — a filing activity counter, not a freshness flag for every feature,
    which is what `period_ends` is for. The mask and the staleness are
    deliberately separate from the economic columns, so a caller can tell
    "no data on file" from "data but this feature missing".
    """

    values: np.ndarray
    names: tuple[str, ...]
    available: np.ndarray
    staleness: np.ndarray
    period_ends: np.ndarray

    # One named feature's column.
    def feature(self, name: str) -> np.ndarray:
        """Return the (T, N) values of one named feature."""
        return self.values[..., self.names.index(name)]

    # One named feature's reference period ends.
    def feature_period(self, name: str) -> np.ndarray:
        """Return the (T, N) datetime64[D] period ends of one named feature."""
        return self.period_ends[..., self.names.index(name)]


@dataclass(frozen=True, slots=True)
class _TickerSeries:
    """One ticker's (T, K) features, period ends, and (T,) companions."""

    values: np.ndarray
    period_ends: np.ndarray
    available: np.ndarray
    staleness: np.ndarray


# Build one ticker's features across the sessions, updating only the names a
# newly available filing touches and carrying everything else forward, so
# the quarterly derivation is not recomputed from scratch on every session.
def _ticker_features(
    versions: Sequence[fa.Version],
    dates: np.ndarray,
    ytd_names: frozenset,
) -> _TickerSeries:
    size = len(dates)
    values = np.full((size, len(FEATURE_NAMES)), np.nan)
    period_ends = np.full((size, len(FEATURE_NAMES)), np.datetime64("NaT", "D"))
    available = np.zeros(size, dtype=bool)
    staleness = np.full(size, np.nan)
    wanted = set(FLOW_NAMES)
    ordered = sorted(
        (v for v in versions if v.name in wanted),
        key=lambda v: (v.available, v.filed, v.accession),
    )
    # state[name][tag][(start, end)] -> latest available version of the span.
    state: dict[str, dict[str, dict[tuple[date | None, date], fa.Version]]] = {}
    # quarters_by_name[name] -> the chosen tag's per-end quarterly values.
    quarters_by_name: dict[str, dict[date, float]] = {}
    pointer = 0
    last_update = -1
    calendar = dates.astype("datetime64[D]").astype(object)
    for t in range(size):
        session = calendar[t]
        dirty: set[str] = set()
        while pointer < len(ordered) and ordered[pointer].available <= session:
            v = ordered[pointer]
            pointer += 1
            spans = state.setdefault(v.name, {}).setdefault(v.tag, {})
            held = spans.get((v.start, v.end))
            if held is None or (v.filed, v.accession) >= (held.filed, held.accession):
                spans[(v.start, v.end)] = v
            dirty.add(v.name)
        if dirty:
            last_update = t
            for name in dirty:
                quarters_by_name[name] = _chosen_quarters(
                    state[name], name, name in ytd_names
                )
        if pointer == 0:
            continue
        available[t] = True
        if last_update >= 0:
            staleness[t] = float(t - last_update)
        row, ends = _feature_row(quarters_by_name)
        values[t, :] = row
        for k, end in enumerate(ends):
            if end is not None:
                period_ends[t, k] = np.datetime64(end, "D")
    return _TickerSeries(values, period_ends, available, staleness)


# The chosen tag's per-end quarterly values, or {} when no tag qualifies.
# Reuses the as-of selector so the tie-break order and the
# most-periods-available rule are the documented ones.
def _chosen_quarters(
    by_tag: Mapping[str, Mapping[tuple[date | None, date], fa.Version]],
    name: str,
    use_ytd: bool,
) -> dict[date, float]:
    chosen = fa._select(name, by_tag, use_ytd)[1]
    if chosen is None:
        return {}
    return fa._quarters(by_tag[chosen], use_ytd)


# One session's feature row and each feature's reference period end, from the
# per-name quarterly values available by then; every piece that is not known
# stays NaN (and its period end NaT), never a fabricated zero.
def _feature_row(
    quarters_by_name: Mapping[str, Mapping[date, float]],
) -> tuple[np.ndarray, list[date | None]]:
    out = np.full(len(FEATURE_NAMES), np.nan)
    ends: list[date | None] = [None] * len(FEATURE_NAMES)
    rev = quarters_by_name.get("revenue")
    if not rev:
        return out, ends
    latest = max(rev)
    q0 = rev[latest]
    q1 = _quarter_back(rev, latest, 1)
    q4 = _quarter_back(rev, latest, 4)
    q5 = _quarter_back(rev, latest, 5)
    yoy = _log_ratio(q0, q4)
    qoq = _log_ratio(q0, q1)
    # Acceleration: this quarter's year-over-year growth less the previous
    # quarter's, both on the same fiscal calendar as the incumbent.
    accel = yoy - _log_ratio(q1, q5)
    out[FEATURE_NAMES.index("revenue_yoy")] = yoy
    out[FEATURE_NAMES.index("revenue_qoq")] = qoq
    out[FEATURE_NAMES.index("revenue_acceleration")] = accel
    for feature in ("revenue_yoy", "revenue_qoq", "revenue_acceleration"):
        if np.isfinite(out[FEATURE_NAMES.index(feature)]):
            ends[FEATURE_NAMES.index(feature)] = latest
    for feature, numerator, denominator in _MARGINS:
        index = FEATURE_NAMES.index(feature)
        out[index], ends[index] = _aligned_ratio(
            quarters_by_name, numerator, denominator
        )
    return out, ends


# The value of the fiscal period ending about `quarters` periods before
# `end`, NaN when no stored end is within the incumbent's lag window. Among
# eligible ends the nearest one wins, ties broken by the earlier date, so
# the choice never depends on dict insertion order.
def _quarter_back(by_end: Mapping[date, float], end: date, quarters: int) -> float:
    target = end - timedelta(days=_QUARTER_DAYS * quarters)
    best = None
    best_key = None
    for candidate in by_end:
        distance = abs((candidate - target).days)
        if distance > _LAG_WINDOW_DAYS:
            continue
        key = (distance, candidate)
        if best_key is None or key < best_key:
            best_key = key
            best = candidate
    return by_end[best] if best is not None else float("nan")


# log(a / b) as log(a) - log(b), NaN when either operand is unknown or b is
# not positive. The difference form keeps huge finite operands finite where
# a/b would overflow to inf, so a genuinely zero growth (a == b > 0) is a
# valid 0 and a zero or negative denominator is not.
def _log_ratio(a: float, b: float) -> float:
    if not (np.isfinite(a) and np.isfinite(b)) or b <= 0 or a <= 0:
        return float("nan")
    return float(np.log(a) - np.log(b))


# a / b, NaN when either operand is unknown, b is zero, or the quotient is
# not finite, so a genuine zero margin (a == 0, b > 0) stays a valid 0, a
# zero denominator is NaN, and an overflowing quotient never reads as inf.
def _ratio(a: float, b: float) -> float:
    if not (np.isfinite(a) and np.isfinite(b)) or b == 0:
        return float("nan")
    value = a / b
    return float(value) if np.isfinite(value) else float("nan")


# numerator / denominator on the latest quarter end where both are known, so
# the ratio always compares one fiscal period and never an old numerator
# against a newer quarter of revenue; returns (value, that end) with the end
# None when there is no common end or the ratio is not finite.
def _aligned_ratio(
    quarters_by_name: Mapping[str, Mapping[date, float]],
    numerator: str,
    denominator: str,
) -> tuple[float, date | None]:
    num = quarters_by_name.get(numerator)
    den = quarters_by_name.get(denominator)
    if not num or not den:
        return float("nan"), None
    end = None
    for candidate in num:
        if candidate in den and (end is None or candidate > end):
            end = candidate
    if end is None:
        return float("nan"), None
    value = _ratio(num[end], den[end])
    if not np.isfinite(value):
        return float("nan"), None
    return value, end


# Point-in-time quarterly fundamental features for a whole panel.
def features(
    panel: Panel,
    versions_by_ticker: Mapping[str, Sequence[fa.Version]],
    ytd_names: frozenset = fa.ALL_YTD_NAMES,
) -> FundamentalFeatures:
    """Return a `FundamentalFeatures` aligned to the panel, NaN where unknown.

    One column per panel ticker, one value per session, NaN wherever the
    feature is not computable from the versions public by that session, with
    each feature's reference period end in `period_ends` (NaT where the
    feature is NaN). A ticker with no versions on file stays entirely
    missing rather than vanishing or reading as a fabricated zero.
    """
    shape = (len(panel.dates), len(panel.tickers))
    values = np.full(shape + (len(FEATURE_NAMES),), np.nan)
    period_ends = np.full(shape + (len(FEATURE_NAMES),), np.datetime64("NaT", "D"))
    available = np.zeros(shape, dtype=bool)
    staleness = np.full(shape, np.nan)
    for column, ticker in enumerate(panel.tickers):
        found = versions_by_ticker.get(ticker)
        if not found:
            continue
        per = _ticker_features(found, panel.dates, ytd_names)
        values[:, column, :] = per.values
        period_ends[:, column, :] = per.period_ends
        available[:, column] = per.available
        staleness[:, column] = per.staleness
    return FundamentalFeatures(values, FEATURE_NAMES, available, staleness, period_ends)
