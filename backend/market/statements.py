"""Standardised, anonymised statement blocks from the filed facts, point in time.

The A2 study (`docs/research/llm-statements-plan-2026-10-01.md`) hands a
model eight consecutive quarters of one company's filed facts and asks for
the direction of the next quarter's earnings. This module builds what the
model sees, and nothing else:

- **Point in time.** The stored filing versions (`fundamentals_asof`) are
  walked in order of availability (SEC acceptance time, with the tone and
  fundamental layers' rule: before the New York close, that day; after it
  or without a time, the next). After each availability date the quarterly
  series are rebuilt from the versions public by then, with the same tag
  choice and quarter arithmetic the fundamental analyst uses. Whenever the
  anchor line's latest quarter advances, one observation is made, dated
  by that availability date. A later filing can never change an earlier
  block.
- **Anonymised.** The block is a table of numbers: no company name, no
  ticker, no calendar date, no fiscal label, no currency name, no prose.
  Quarters are labelled Q1 (oldest) to Q8 (latest). Numbers are in
  millions with thousands separators and one decimal (EPS in units with
  two), so no run of four digits, and so no year, can appear in it.
- **Honest about what is filed.** Cost of revenue is revenue less gross
  profit and total liabilities is assets less equity, both derived; the
  store parses no tag for operating income, which reads "n/a" on every
  row rather than being manufactured from something else. EPS quarters
  are the reported quarter spans only: a difference of per-share figures
  is not a per-share figure.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from backend.market import fundamentals_asof as fa

KIND = "edgar_statements"
QUARTERS = 8
# The rows of the block, in statement order, with the key each is read
# from. "derived" lines are arithmetic on two filed lines; "absent" lines
# have no tag in the store and always read n/a.
LINES: tuple[tuple[str, str], ...] = (
    ("Revenue", "revenue"),
    ("Cost of revenue", "cost_of_revenue"),
    ("Gross profit", "gross_profit"),
    ("Operating income", "operating_income"),
    ("Net income", "net_income"),
    ("Diluted EPS", "eps"),
    ("Operating cash flow", "operating_cash_flow"),
    ("Capital expenditure", "capex"),
    ("Total assets", "assets"),
    ("Total liabilities", "liabilities"),
    ("Cash", "cash"),
    ("Debt", "debt"),
)
FLOW_LINES: tuple[str, ...] = (
    "revenue",
    "gross_profit",
    "net_income",
    "eps",
    "operating_cash_flow",
    "capex",
)
INSTANT_LINES: tuple[str, ...] = ("assets", "equity", "cash", "debt")
DERIVED: dict[str, tuple[str, str]] = {
    "cost_of_revenue": ("revenue", "gross_profit"),
    "liabilities": ("assets", "equity"),
}
ABSENT: tuple[str, ...] = ("operating_income",)
# The line whose quarters define an observation: net income, or revenue
# for a filer with no net income on file.
ANCHORS: tuple[str, ...] = ("net_income", "revenue")
# Per-share figures are not scaled to millions.
PER_SHARE: frozenset[str] = frozenset({"eps"})
MILLION = 1_000_000.0
# Consecutive quarter ends are this far apart (the fundamental path's rule).
MIN_GAP_DAYS = 75
MAX_GAP_DAYS = 105
# A balance-sheet instant within this many days of the quarter end is the
# quarter's.
INSTANT_TOLERANCE_DAYS = 7
NA = "n/a"
LABEL_WIDTH = 22
CELL_WIDTH = 12


@dataclass(frozen=True, slots=True)
class Observation:
    """One (name, quarter) the model is asked about, as it was knowable."""

    quarter_end: date
    available: date
    block: str
    # {line key: eight values, oldest first; None where not filed}
    values: Mapping[str, tuple[float | None, ...]]
    # The quarter ends behind the eight columns, oldest first.
    quarter_ends: tuple[date, ...]
    anchor: str

    # How many of the twelve lines carry at least one filed value.
    @property
    def lines_present(self) -> int:
        return sum(
            1 for _label, key in LINES if any(v is not None for v in self.values[key])
        )

    # The block's digest, stored with the score so a block can be audited.
    @property
    def sha256(self) -> str:
        return block_sha(self.block)


# The digest of a block's text.
def block_sha(block: str) -> str:
    """Return the SHA-256 hex digest of `block`."""
    return hashlib.sha256(block.encode("utf-8")).hexdigest()


# The candidate tags of a line, in the table's order (ties break by it).
def _tag_order(name: str) -> list[str]:
    return fa._tag_order(name)


# One flow line's quarterly series {end: value} from the spans of its best
# tag: the tag with the most quarters available now, ties by table order.
# EPS keeps reported quarter spans only.
def _flow_series(
    name: str, by_tag: Mapping[str, Mapping[tuple[date | None, date], fa.Version]]
) -> dict[date, float]:
    best: dict[date, float] = {}
    best_count = -1
    for tag in _tag_order(name):
        spans = by_tag.get(tag)
        if not spans:
            continue
        if name in PER_SHARE:
            series = {
                end: v.value
                for (start, end), v in spans.items()
                if fa.span_kind(start, end) == "quarter"
            }
        else:
            series = fa._quarters(spans, True)
        if len(series) > best_count:
            best, best_count = series, len(series)
    return best


# One instant line's series {end: value} from its best tag: the tag with
# the most distinct dates available now, ties by table order.
def _instant_series(
    name: str, by_tag: Mapping[str, Mapping[tuple[date | None, date], fa.Version]]
) -> dict[date, float]:
    best: dict[date, float] = {}
    best_count = -1
    for tag in _tag_order(name):
        spans = by_tag.get(tag)
        if not spans:
            continue
        series = {end: v.value for (_start, end), v in spans.items()}
        if len(series) > best_count:
            best, best_count = series, len(series)
    return best


# The value of an instant line at a quarter end: the exact date, else the
# nearest within the tolerance, else None.
def _instant_at(series: Mapping[date, float], end: date) -> float | None:
    if end in series:
        return series[end]
    nearest = None
    for when, value in series.items():
        gap = abs((when - end).days)
        if gap <= INSTANT_TOLERANCE_DAYS and (nearest is None or gap < nearest[0]):
            nearest = (gap, value)
    return None if nearest is None else nearest[1]


# The last `count` quarter ends of a series when they are consecutive, else
# None.
def _consecutive_ends(
    series: Mapping[date, float], count: int
) -> tuple[date, ...] | None:
    ends = sorted(series)
    if len(ends) < count:
        return None
    last = ends[-count:]
    for a, b in zip(last, last[1:], strict=False):
        if not MIN_GAP_DAYS <= (b - a).days <= MAX_GAP_DAYS:
            return None
    return tuple(last)


# A number for the block: millions with one decimal (per-share figures in
# units with two), thousands separated; None reads n/a.
def format_cell(value: float | None, per_share: bool = False) -> str:
    """Return the block's rendering of one value."""
    if value is None or not math.isfinite(value):
        return NA
    if per_share:
        return f"{value:,.2f}"
    return f"{value / MILLION:,.1f}"


# The block's text from the per-line values: a header row of Q1..Qn and one
# row per line, every cell right-aligned.
def render_block(
    values: Mapping[str, Sequence[float | None]], count: int = QUARTERS
) -> str:
    """Return the anonymised table for `values`."""
    header = "Line".ljust(LABEL_WIDTH) + "".join(
        f"Q{i + 1}".rjust(CELL_WIDTH) for i in range(count)
    )
    rows = [header]
    for label, key in LINES:
        cells = values.get(key, (None,) * count)
        rows.append(
            label.ljust(LABEL_WIDTH)
            + "".join(
                format_cell(cell, key in PER_SHARE).rjust(CELL_WIDTH) for cell in cells
            )
        )
    return "\n".join(rows)


# The per-line eight values at the given quarter ends from the current
# series, with the derived lines computed where both inputs are filed.
def _values_at(
    flows: Mapping[str, Mapping[date, float]],
    instants: Mapping[str, Mapping[date, float]],
    ends: Sequence[date],
) -> dict[str, tuple[float | None, ...]]:
    out: dict[str, tuple[float | None, ...]] = {}
    for name in FLOW_LINES:
        series = flows.get(name, {})
        out[name] = tuple(series.get(end) for end in ends)
    for name in INSTANT_LINES:
        series = instants.get(name, {})
        out[name] = tuple(_instant_at(series, end) for end in ends)
    for name, (left, right) in DERIVED.items():
        out[name] = tuple(
            (a - b) if a is not None and b is not None else None
            for a, b in zip(out[left], out[right], strict=True)
        )
    for name in ABSENT:
        out[name] = (None,) * len(ends)
    return out


# Every observation of one company from its stored versions, oldest first.
def observations(
    versions: Iterable[fa.Version], count: int = QUARTERS
) -> list[Observation]:
    """Return the point-in-time observations a company's versions allow.

    The versions are applied in availability order; after each date's
    batch the series are rebuilt, and an observation is made when the
    anchor line's latest quarter end is newer than the last observation's
    and the last `count` quarter ends are consecutive.
    """
    wanted = set(FLOW_LINES) | set(INSTANT_LINES)
    ordered = sorted(
        (v for v in versions if v.name in wanted),
        key=lambda v: (v.available, v.filed, v.accession),
    )
    state: dict[str, dict[str, dict[tuple[date | None, date], fa.Version]]] = {}
    out: list[Observation] = []
    last_quarter: date | None = None
    pointer = 0
    while pointer < len(ordered):
        available = ordered[pointer].available
        while pointer < len(ordered) and ordered[pointer].available == available:
            v = ordered[pointer]
            pointer += 1
            spans = state.setdefault(v.name, {}).setdefault(v.tag, {})
            held = spans.get((v.start, v.end))
            if held is None or (v.filed, v.accession) >= (held.filed, held.accession):
                spans[(v.start, v.end)] = v
        flows = {name: _flow_series(name, state.get(name, {})) for name in FLOW_LINES}
        instants = {
            name: _instant_series(name, state.get(name, {})) for name in INSTANT_LINES
        }
        anchor = next((a for a in ANCHORS if flows.get(a)), None)
        if anchor is None:
            continue
        latest = max(flows[anchor])
        if last_quarter is not None and latest <= last_quarter:
            continue
        ends = _consecutive_ends(flows[anchor], count)
        if ends is None or ends[-1] != latest:
            continue
        values = _values_at(flows, instants, ends)
        out.append(
            Observation(
                quarter_end=latest,
                available=available,
                block=render_block(values, count),
                values=values,
                quarter_ends=ends,
                anchor=anchor,
            )
        )
        last_quarter = latest
    return out


# The realised year-over-year and sequential directions of the anchor line
# one quarter after each observation, from the observation that follows it:
# +1 up, -1 down, 0 unchanged, None when the next quarter is not on file
# or is not the quarter immediately after.
def realised_directions(
    rows: Sequence[Observation],
) -> list[tuple[int | None, int | None]]:
    """Return [(yoy, sequential)] per observation, from the next one."""
    out: list[tuple[int | None, int | None]] = []
    for i, row in enumerate(rows):
        following = rows[i + 1] if i + 1 < len(rows) else None
        if (
            following is None
            or following.anchor != row.anchor
            or not MIN_GAP_DAYS
            <= (following.quarter_end - row.quarter_end).days
            <= MAX_GAP_DAYS
        ):
            out.append((None, None))
            continue
        nxt = following.values[following.anchor]
        yoy = _sign(nxt[-1], nxt[-5]) if len(nxt) >= 5 else None
        seq = _sign(nxt[-1], nxt[-2]) if len(nxt) >= 2 else None
        out.append((yoy, seq))
    return out


# The sign of a - b, None when either is unknown.
def _sign(a: float | None, b: float | None) -> int | None:
    if a is None or b is None:
        return None
    if a > b:
        return 1
    if a < b:
        return -1
    return 0


# The naive persistence call for an observation: the sign of its own latest
# year-over-year change (Q8 against Q4), the baseline the accuracy report
# sets beside the model's.
def persistence_direction(row: Observation) -> int | None:
    """Return the sign of the anchor's Q8 - Q4, or None."""
    values = row.values[row.anchor]
    if len(values) < 5:
        return None
    return _sign(values[-1], values[-5])


# Per-observation stances carried forward over a session calendar until
# the next observation of the same name, the alignment the tone layer
# uses: an observation is visible from the first session on or after its
# availability date. Rows are {ticker: [(available, stance), ...]}; NaN
# where a name has no observation yet.
def aligned_stances(
    dates: np.ndarray,
    tickers: Sequence[str],
    rows: Mapping[str, Sequence[tuple[date, float]]],
) -> np.ndarray:
    """Return (T, N) stances carried forward from each observation's session."""
    size = len(dates)
    out = np.full((size, len(tickers)), np.nan)
    calendar = np.asarray(dates).astype("datetime64[D]")
    for column, ticker in enumerate(tickers):
        items = sorted(rows.get(ticker, ()), key=lambda r: r[0])
        if not items:
            continue
        positions = np.searchsorted(
            calendar,
            np.asarray([d for d, _ in items], dtype="datetime64[D]"),
            side="left",
        )
        for index, (_when, stance) in enumerate(items):
            start = int(positions[index])
            if start >= size:
                break
            end = int(positions[index + 1]) if index + 1 < len(items) else size
            end = min(max(end, start), size)
            out[start:end, column] = stance
    return out


__all__ = [
    "ABSENT",
    "ANCHORS",
    "DERIVED",
    "FLOW_LINES",
    "INSTANT_LINES",
    "KIND",
    "LINES",
    "QUARTERS",
    "Observation",
    "aligned_stances",
    "block_sha",
    "format_cell",
    "observations",
    "persistence_direction",
    "realised_directions",
    "render_block",
]
