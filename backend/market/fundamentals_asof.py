"""Versioned filing inputs used by the current desk, learned inputs and shadow paths.

Stored Versions retain period starts/ends, filing dates, optional acceptance
times and accessions. The downstream selectors use only versions available by
each decision date, with the existing conservative daily availability rule and
table-order tag ties. This is not proof of original historical publication.

The parser still selects the largest unit group over the supplied snapshot and
drops its unit before storage. These legacy partitions cannot establish currency
compatibility; later source snapshots can change that initial unit selection.
The separate unit-source helper does not silently repair or replace this loader.

Quarter construction preserves the existing reported, YTD-difference and annual
remainder arithmetic. `_quarter_intervals` exposes its retained full spans for
the current margin adapter; `_quarters` keeps the original by-end projection and
priority for tag selection, growth and other consumers. Matching retained spans
does not validate the known gapped/overlapping annual-partition limitation.

Tag selection is per session, from the versions available then: the candidate
tag whose latest available period end is the most recent wins, then the one
with the most periods, then table order (`_ranked_tags`), the key the frozen
`edgar.parse_company_facts` already uses over its snapshot. Counting periods
alone kept a tag the filer had stopped using (ASC 606 moved most revenue to
RevenueFromContractWithCustomerExcludingAssessedTax in 2018) chosen for years,
behind the reported period. Every value still comes from the one chosen tag:
growth compares a quarter with the year-ago comparative filed under the same
tag, and stays missing, never borrowed from the old tag, where none was filed.

The level outputs retain the vocabulary consumed by `opportunity_learning.ratios`.
`levels_pit.point_in_time_levels` (the valuation analyst's levels) reads these
versions with the same per-session tag rank; `levels_pit.trailing_levels` and
the frozen `edgar` feature block remain on the stored facts frame.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from backend.market import edgar
from backend.market import growth_pilot as gp
from backend.market import opportunity_learning as ol
from backend.market.panel import Panel

KIND = "edgar_facts_versions"
VERSION = "fundamentals-asof/1"
NEW_YORK = ZoneInfo("America/New_York")
FLOW_NAMES = ("revenue", "net_income", "gross_profit", "operating_cash_flow", "capex")
INSTANT_NAMES = ("shares", "equity", "debt", "cash")
# The level names the ratio builder reads, in the frozen path's vocabulary.
LEVEL_NAMES = (
    "revenue",
    "earnings",
    "gross_profit",
    "operating_cash_flow",
    "capex",
    "shares",
    "equity",
    "debt",
    "cash",
    "revenue_growth",
)
_FLOW_TO_LEVEL = {"net_income": "earnings"}
# The frozen path derives quarters from six- and nine-month spans only for
# the cash-flow names, whose 10-Q spans run from the fiscal year's start.
# The as-of path does it for every flow name by default; the audit can
# restrict it to the frozen set to separate coverage from correction.
FROZEN_YTD_NAMES = frozenset({"capex", "operating_cash_flow"})
ALL_YTD_NAMES = frozenset(FLOW_NAMES)


@dataclass(frozen=True, slots=True)
class Version:
    """One filed value of one fundamental for one period, as filed."""

    name: str
    tag: str  # "taxonomy:Tag"
    start: date | None  # None for an instant
    end: date
    value: float
    filed: date
    accepted: datetime | None  # UTC when the source has it
    accession: str
    form: str

    # The first session date on which this version was public.
    @property
    def available(self) -> date:
        if self.accepted is not None:
            local = self.accepted.astimezone(NEW_YORK)
            return (
                local.date() + timedelta(days=1) if local.hour >= 16 else local.date()
            )
        return self.filed + timedelta(days=1)


# The span kinds the flow selector understands.
def span_kind(start: date | None, end: date) -> str | None:
    """Return "quarter", "year", "ytd" or None for a span."""
    if start is None:
        return None
    days = (end - start).days
    if 80 <= days <= 100:
        return "quarter"
    if 350 <= days <= 380:
        return "year"
    if 170 <= days <= 195 or 260 <= days <= 285:
        return "ytd"
    return None


# All rows of one tag in one taxonomy, from its largest unit.
def _rows(root: Mapping[str, Any], taxonomy: str, tag: str) -> list[dict]:
    units = ((root.get(taxonomy) or {}).get(tag) or {}).get("units") or {}
    return max(units.values(), key=len) if units else []


# One row as a Version, or None when it is not a fact this module keeps.
def _version(
    name: str, tag: str, row: Mapping[str, Any], instant: bool
) -> Version | None:
    try:
        start = None if instant else date.fromisoformat(row["start"])
        end = date.fromisoformat(row["end"])
        filed = date.fromisoformat(row["filed"])
        value = float(row["val"])
    except (KeyError, TypeError, ValueError):
        return None
    if not instant and span_kind(start, end) is None:
        return None
    accepted = row.get("accepted")
    when = (
        datetime.fromisoformat(str(accepted).replace("Z", "+00:00"))
        if accepted
        else None
    )
    return Version(
        name,
        tag,
        start,
        end,
        value,
        filed,
        when,
        str(row.get("accn") or ""),
        str(row.get("form") or ""),
    )


# Every candidate (name, taxonomy:tag, instant?) the tables name.
def _candidates() -> list[tuple[str, str, str, bool]]:
    out = []
    for name, tags in edgar.FACT_TAGS.items():
        for taxonomy in ("us-gaap", "ifrs-full"):
            out.extend((name, taxonomy, tag, False) for tag in tags)
    # The fallback tiers are us-gaap concepts; `ifrs-full:ProfitLoss` would be
    # profit including the noncontrolling interest under another name.
    for name, tiers in edgar.FALLBACK_FACT_TAGS.items():
        out.extend((name, "us-gaap", tag, False) for tier in tiers for tag in tier)
    for name, pairs in edgar.INSTANT_TAGS.items():
        out.extend((name, taxonomy, tag, True) for taxonomy, tag in pairs)
    return out


# Every filing of every candidate tag, nothing collapsed.
def parse_versions(payload: Mapping[str, Any]) -> list[Version]:
    """Return every Version in a company-facts payload."""
    root = payload.get("facts") or {}
    out: dict[tuple, Version] = {}
    for name, taxonomy, tag, instant in _candidates():
        for row in _rows(root, taxonomy, tag):
            if bool(row.get("start")) == instant:
                continue
            version = _version(name, f"{taxonomy}:{tag}", row, instant)
            if version is not None:
                key = (name, version.tag, version.start, version.end, version.filed)
                out[(*key, version.accession, version.value)] = version
    return sorted(
        out.values(), key=lambda v: (v.name, v.tag, v.end, v.filed, v.accession)
    )


# The candidate tags of a name in the table's order, which breaks ties: the
# `FACT_TAGS` (or `INSTANT_TAGS`) tags, then each fallback tier's.
def _tag_order(name: str) -> list[str]:
    return list(_tag_tiers(name))


# Every candidate tag of a name with its tier: 0 for the main table, 1, 2 ...
# for `edgar.FALLBACK_FACT_TAGS`, in table order.
def _tag_tiers(name: str) -> dict[str, int]:
    if name in edgar.FACT_TAGS:
        out = {
            f"{tx}:{tag}": 0
            for tx in ("us-gaap", "ifrs-full")
            for tag in edgar.FACT_TAGS[name]
        }
        for tier, tags in enumerate(edgar.FALLBACK_FACT_TAGS.get(name, ()), 1):
            out.update({f"us-gaap:{tag}": tier for tag in tags})
        return out
    return {f"{tx}:{tag}": 0 for tx, tag in edgar.INSTANT_TAGS.get(name, ())}


# Preserve quarterly spans and original YTD priority without changing arithmetic.
def _quarter_intervals(
    available: Mapping[tuple[date | None, date], Version], use_ytd: bool = True
) -> tuple[dict[tuple[date, date], float], set[tuple[date, date]]]:
    quarters: dict[tuple[date, date], float] = {}
    ytd: dict[tuple[date, date], float] = {}
    years: dict[tuple[date, date], float] = {}
    for (start, end), v in available.items():
        kind = span_kind(start, end)
        if kind == "quarter":
            quarters[(start, end)] = v.value
        elif kind == "ytd" and use_ytd:
            ytd[(start, end)] = v.value
        elif kind == "year":
            years[(start, end)] = v.value
    derived = _ytd_differences(quarters, ytd)
    quarters.update(derived)
    quarters.update(_fourth_quarters(quarters, years))
    return quarters, set(derived)


# Keep the original by-end values and reported-before-YTD ordering for consumers.
def _quarters(
    available: Mapping[tuple[date | None, date], Version], use_ytd: bool = True
) -> dict[date, float]:
    quarters, derived = _quarter_intervals(available, use_ytd)
    # By end; a reported quarter beats a derived one on the same end.
    by_end: dict[date, float] = {}
    for (_start, end), value in sorted(
        quarters.items(), key=lambda kv: (kv[0][1], kv[0] in derived)
    ):
        by_end.setdefault(end, value)
    return by_end


# Year-to-date differences: consecutive spans from the same start.
def _ytd_differences(
    quarters: Mapping[tuple[date, date], float], ytd: Mapping[tuple[date, date], float]
) -> dict[tuple[date, date], float]:
    by_start: dict[date, list[tuple[date, float]]] = {}
    for (start, end), value in list(quarters.items()) + list(ytd.items()):
        by_start.setdefault(start, []).append((end, value))
    derived: dict[tuple[date, date], float] = {}
    for spans in by_start.values():
        spans.sort()
        for (e1, v1), (e2, v2) in zip(spans, spans[1:], strict=False):
            key = (e1 + timedelta(days=1), e2)
            if span_kind(*key) == "quarter" and key not in quarters:
                derived[key] = v2 - v1
    return derived


# Fourth quarters from the year less the three quarters inside it.
def _fourth_quarters(
    quarters: Mapping[tuple[date, date], float],
    years: Mapping[tuple[date, date], float],
) -> dict[tuple[date, date], float]:
    ends = {end for _, end in quarters}
    out: dict[tuple[date, date], float] = {}
    for (ys, ye), yv in years.items():
        if ye in ends:
            continue
        inside = [(s, e, v) for (s, e), v in quarters.items() if s >= ys and e < ye]
        if len(inside) != 3:
            continue
        inside.sort(key=lambda q: q[1])
        out[(inside[-1][1] + timedelta(days=1), ye)] = yv - sum(v for _, _, v in inside)
    return out


# The trailing four consecutive quarters, as the frozen path defines them.
def _four_quarters(by_end: Mapping[date, float]) -> float:
    ends = sorted(by_end)
    if len(ends) < 4:
        return float("nan")
    last = ends[-4:]
    if any(not 75 <= (last[i + 1] - last[i]).days <= 105 for i in range(3)):
        return float("nan")
    return float(sum(by_end[e] for e in last))


# One name's levels at every session, from versions available by then.
def levels_for(
    versions: Iterable[Version],
    dates: np.ndarray,
    trace: dict | None = None,
    ytd_names: frozenset = ALL_YTD_NAMES,
) -> dict[str, np.ndarray]:
    """Return {level name: (T,)} for one company, as-of each session.

    `trace`, when given, receives {name: [chosen tag per session]} so an
    audit can tell a tag change from a value change. `ytd_names` are the
    flow names allowed to take quarters from year-to-date spans.
    """
    size = len(dates)
    calendar = dates.astype("datetime64[D]").astype(object)
    out = {name: np.full(size, np.nan) for name in LEVEL_NAMES}
    # Only the names the levels carry: EPS and assets are parsed and stored
    # for completeness but have no level here.
    wanted = set(FLOW_NAMES) | set(INSTANT_NAMES)
    ordered = sorted(
        (v for v in versions if v.name in wanted),
        key=lambda v: (v.available, v.filed, v.accession),
    )
    # state[name][tag][(start, end)] -> latest available version of that span
    state: dict[str, dict[str, dict[tuple[date | None, date], Version]]] = {}
    current: dict[str, float] = {}
    chosen: dict[str, str | None] = {}
    pointer = 0
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
        for name in dirty:
            current[name], chosen[name] = _select(name, state[name], name in ytd_names)
        if trace is not None:
            for name in FLOW_NAMES + INSTANT_NAMES:
                trace.setdefault(name, [None] * size)[t] = chosen.get(name)
        for name in FLOW_NAMES:
            out[_FLOW_TO_LEVEL.get(name, name)][t] = current.get(name, float("nan"))
        for name in INSTANT_NAMES:
            out[name][t] = current.get(name, float("nan"))
    rev = out["revenue"]
    growth = np.full(size, np.nan)
    with np.errstate(all="ignore"):
        growth[252:] = rev[252:] / rev[:-252] - 1.0
    out["revenue_growth"] = np.where(np.isfinite(growth), growth, np.nan)
    return out


# A version whose value is not finite, or whose period ends after its own
# filing or acceptance, cannot say which tag the filer reports under now.
def _dated_consistently(version: Version) -> bool:
    if not np.isfinite(version.value) or version.end > version.filed:
        return False
    accepted = version.accepted
    return accepted is None or accepted.astimezone(NEW_YORK).date() >= version.end


# The candidate tags holding data now, best first: the latest available period
# end (quarter end for a flow, instant date otherwise), then the better tier
# (a fallback tag wins only with a later period than every better-tier tag),
# then the number of periods, then table order. Only the versions passed in
# are read, so a tag the filer adopts later cannot change an earlier session;
# a tag with no consistently dated period still ranks, last, so a lone tag is
# still read.
def _ranked_tags(
    name: str,
    by_tag: Mapping[str, Mapping[tuple[date | None, date], Version]],
    use_ytd: bool = True,
) -> list[str]:
    ranked = []
    for order, (tag, tier) in enumerate(_tag_tiers(name).items()):
        spans = by_tag.get(tag)
        if not spans:
            continue
        dated = {k: v for k, v in spans.items() if _dated_consistently(v)}
        ends = (
            set(_quarters(dated, use_ytd))
            if name in FLOW_NAMES
            else {e for _, e in dated}
        )
        ranked.append(
            (max(ends) if ends else date.min, -tier, len(ends), -order, tag)
        )
    ranked.sort(reverse=True)
    return [tag for *_, tag in ranked]


# The value of one name now: the best ranked tag available now, then the
# trailing sum of its quarters or its latest instant.
def _select(
    name: str,
    by_tag: Mapping[str, Mapping[tuple[date | None, date], Version]],
    use_ytd: bool = True,
) -> tuple[float, str | None]:
    ranked = _ranked_tags(name, by_tag, use_ytd)
    if not ranked:
        return float("nan"), None
    best_tag = ranked[0]
    spans = by_tag[best_tag]
    if name in FLOW_NAMES:
        return _four_quarters(_quarters(spans, use_ytd)), best_tag
    latest_end = max(e for _, e in spans)
    return spans[(None, latest_end)].value, best_tag


# The tag chosen over the whole snapshot: the latest period end, then the
# most distinct quarter ends (or instant dates), over every version.
def snapshot_tag(name: str, versions: Iterable[Version]) -> str | None:
    """Return the whole-history tag choice for `name`."""
    by_tag: dict[str, dict[tuple[date | None, date], Version]] = {}
    for v in versions:
        if v.name == name:
            by_tag.setdefault(v.tag, {})[(v.start, v.end)] = v
    return _select(name, by_tag)[1]


# Levels for a panel: (T, N) per level name, from stored versions.
def levels(
    panel: Panel,
    versions_by_ticker: Mapping[str, Sequence[Version]],
    ytd_names: frozenset = ALL_YTD_NAMES,
) -> dict[str, np.ndarray]:
    """Return {level name: (T, N)} aligned to the panel."""
    shape = (len(panel.dates), len(panel.tickers))
    out = {name: np.full(shape, np.nan) for name in LEVEL_NAMES}
    for column, ticker in enumerate(panel.tickers):
        found = versions_by_ticker.get(ticker)
        if not found:
            continue
        for name, series in levels_for(found, panel.dates, None, ytd_names).items():
            out[name][:, column] = series
    return out


# The stored versions for a panel's names, as of a date.
def load_versions(
    store, panel: Panel, asof: date | None = None
) -> dict[str, list[Version]]:
    """Return {ticker: versions} for every name the store holds."""
    out = {}
    for ticker in panel.tickers:
        found = store.read_frame(KIND, ticker, asof)
        if found is not None:
            out[ticker] = versions_from_frame(found[0])
    return out


# The research feature block with as-of fundamentals, same columns as the
# frozen `opportunity_learning.features`, so the comparison is like for like.
def features(panel: Panel, versions_by_ticker: Mapping[str, Sequence[Version]]):
    """Return (dataset, values, names) with as-of fundamental ratios."""
    data = gp.dataset(panel)
    fundamentals = ol.ratios(panel.close, levels(panel, versions_by_ticker))
    values = np.concatenate((data.features, fundamentals), axis=-1)
    return data, values, (*gp.FEATURE_NAMES, *ol.FUNDAMENTAL_NAMES)


# ---- the store frame
def frame(versions: Sequence[Version]) -> dict[str, list]:
    """Return the columns of a versions frame."""
    return {
        "name": [v.name for v in versions],
        "tag": [v.tag for v in versions],
        "start": [v.start.isoformat() if v.start else "" for v in versions],
        "end": [v.end.isoformat() for v in versions],
        "value": [v.value for v in versions],
        "filed": [v.filed.isoformat() for v in versions],
        "accepted": [v.accepted.isoformat() if v.accepted else "" for v in versions],
        "accession": [v.accession for v in versions],
        "form": [v.form for v in versions],
    }


def versions_from_frame(columns: Mapping[str, list]) -> list[Version]:
    """Return the Versions of a stored frame."""
    out = []
    for i in range(len(columns.get("end", []))):
        accepted = str(columns["accepted"][i])
        out.append(
            Version(
                str(columns["name"][i]),
                str(columns["tag"][i]),
                (
                    date.fromisoformat(str(columns["start"][i]))
                    if str(columns["start"][i])
                    else None
                ),
                date.fromisoformat(str(columns["end"][i])),
                float(columns["value"][i]),
                date.fromisoformat(str(columns["filed"][i])),
                datetime.fromisoformat(accepted) if accepted else None,
                str(columns["accession"][i]),
                str(columns["form"][i]),
            )
        )
    return out


# Fetch one company's versions from the company-facts feed.
def fetch_versions(
    cik: int,
    transport: Callable[[str], tuple[int, bytes]] = edgar.sec_transport,
    pacer: edgar.Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Version]:
    """Return every Version for a CIK."""
    payload = edgar._get_json(
        edgar._FACTS_URL.format(cik=cik),
        transport,
        pacer or edgar.Pacer(sleep=sleep),
        sleep,
    )
    return parse_versions(payload)


# The frozen path's own choice for the whole snapshot, for the audit: which
# tag it would use and the values it would carry, so the two can be
# compared session by session.
def frozen_levels(
    store, panel: Panel, asof: date | None = None
) -> dict[str, np.ndarray]:
    """Return the frozen path's trailing levels on the same panel."""
    from backend.market.levels_pit import trailing_levels

    return trailing_levels(store, panel, asof)


def now_utc() -> datetime:
    """The current time, for callers that stamp frames."""
    return datetime.now(tz=UTC)
