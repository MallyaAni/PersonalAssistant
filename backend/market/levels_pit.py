"""Point-in-time levels from the filings: revenue, earnings, equity, shares.

`edgar.edgar_features` turns the filings into ratios and growth rates. The
valuation analyst needs the levels themselves, dated the same way: the
value that had been filed and was public at each session, never a later
restatement. `point_in_time_levels` reads the stored filing versions and
chooses each fundamental's tag per session from what had been filed by
then (the stored facts frame only for a name with no versions on file);
`trailing_levels` still reads the stored facts frame. Nothing else has to
know how the filing store is shaped.
"""

from datetime import date, datetime

import numpy as np

from backend.market import edgar
from backend.market.panel import Panel
from backend.market.store import MarketStore

EVENTS = "edgar_events"
FACTS = "edgar_facts"
# A quarter annualised. Four trailing quarters would be better, but the
# stored fact series keeps lags 0, 1, 4 and 5, which is what the growth
# features need; the latest quarter times four is the level those lags
# support and it is consistent across every name.
QUARTERS = 4.0


# The trailing four quarters of one fundamental as known at each session:
# the sum of the four most recent distinct quarter-ends that had been
# filed by that session, provided they are consecutive quarters (each
# gap 75 to 105 days) so a missing quarter never leaves a three-quarter
# sum dressed as a year. Derived fourth quarters count like any other.
# NaN until four consecutive quarters are known.
def ttm_series(facts, name: str, dates: np.ndarray) -> np.ndarray:
    """Return (T,) trailing-four-quarter sums of `name`, point in time."""
    rows = sorted((f for f in facts if f.name == name), key=lambda f: (f.filed, f.end))
    size = len(dates)
    out = np.full(size, np.nan)
    if not rows:
        return out
    calendar = dates.astype("datetime64[D]")
    by_end: dict = {}
    pointer = 0
    current = np.nan
    for t in range(size):
        session = calendar[t].astype("datetime64[D]").astype(object)
        changed = False
        while pointer < len(rows) and rows[pointer].filed <= session:
            fact = rows[pointer]
            if fact.end not in by_end:
                by_end[fact.end] = fact.value
                changed = True
            pointer += 1
        if changed:
            current = _four_quarters(by_end)
        out[t] = current
    return out


# The sum of the last four consecutive quarter-ends in `by_end`, or NaN.
def _four_quarters(by_end: dict) -> float:
    ends = sorted(by_end)
    if len(ends) < 4:
        return np.nan
    last = ends[-4:]
    gaps = [(last[i + 1] - last[i]).days for i in range(3)]
    if any(g < 75 or g > 105 for g in gaps):
        return np.nan
    return float(sum(by_end[e] for e in last))


# The trailing-four-quarter levels the second valuation analyst needs:
# revenue, earnings and gross profit over the last four filed quarters,
# and the share count and equity as last reported, all known at each
# session. Revenue growth is the year-over-year growth of the trailing
# sum, so a single quarter cannot swing the growth adjustment.
def trailing_levels(
    store: MarketStore, panel: Panel, asof=None
) -> dict[str, np.ndarray]:
    """Return the trailing levels per name, known at each session."""
    shape = (len(panel.dates), len(panel.tickers))
    names = (
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
    out = {name: np.full(shape, np.nan) for name in names}
    for column, ticker in enumerate(panel.tickers):
        events = store.read_frame(EVENTS, ticker, asof)
        facts = store.read_frame(FACTS, ticker, asof)
        if events is None or facts is None:
            continue
        meta = facts[1]
        stamp = meta.get("source_time")
        record = edgar.record_from_frames(
            ticker,
            int(meta.get("cik", "0")),
            events[0],
            facts[0],
            datetime.fromisoformat(stamp) if stamp else datetime.now(),
        )
        out["revenue"][:, column] = ttm_series(record.facts, "revenue", panel.dates)
        out["earnings"][:, column] = ttm_series(record.facts, "net_income", panel.dates)
        out["gross_profit"][:, column] = ttm_series(
            record.facts, "gross_profit", panel.dates
        )
        for name in ("operating_cash_flow", "capex"):
            out[name][:, column] = ttm_series(record.facts, name, panel.dates)
        for name in ("shares", "equity", "debt", "cash"):
            out[name][:, column] = edgar._known_series(record.facts, name, panel.dates)[
                0
            ][0]
        # Growth of the trailing sum against the trailing sum a year earlier,
        # taken from the same point-in-time series 252 sessions back.
        rev = out["revenue"][:, column]
        growth = np.full(len(rev), np.nan)
        with np.errstate(all="ignore"):
            growth[252:] = rev[252:] / rev[:-252] - 1.0
        out["revenue_growth"][:, column] = np.where(np.isfinite(growth), growth, np.nan)
    return out


# Every level the valuation analyst needs, as (T, N) arrays aligned to the
# panel and known at each session.
# The splits on file for a name: (date, ratio) pairs from the store's
# corporate-action history, empty when there is none.
def _splits(store: MarketStore, ticker: str, asof=None) -> list[tuple[date, float]]:
    try:
        history = store.read(ticker, asof)
    except Exception:  # noqa: BLE001 - no history is no splits
        return []
    if history is None:
        return []
    return [
        (a.action_date, float(a.value))
        for a in getattr(history, "actions", []) or []
        if a.kind == "split" and float(a.value) > 0
    ]


# A filed share count is on the basis of its filing; the close it is
# multiplied by is on today's split basis. Every split between the session
# a count first appeared (its filing) and the session it is used on
# multiplies it, so NVDA's 10:1 in 2024 does not read as a tenfold
# re-rating until the next 10-Q and a tenfold cheapness before it. When supplied,
# source basis dates take precedence over inferred first-visible rows.
def split_adjusted_shares(
    shares: np.ndarray,
    dates: np.ndarray,
    splits: list[tuple[date, float]],
    *,
    basis_dates: np.ndarray | None = None,
) -> np.ndarray:
    """Return the share series with later splits applied to earlier filings."""
    out = np.asarray(shares, dtype=float).copy()
    if not splits or len(out) == 0:
        return out
    days = np.asarray(dates).astype("datetime64[D]")
    basis = (
        None if basis_dates is None else np.asarray(basis_dates, dtype="datetime64[D]")
    )
    if basis is not None and basis.shape != days.shape:
        raise ValueError(
            "one source filing basis date is required per share observation"
        )
    first_seen = np.zeros(len(out), dtype=int)
    for t in range(1, len(out)):
        same = np.isfinite(out[t]) and np.isfinite(out[t - 1]) and out[t] == out[t - 1]
        first_seen[t] = first_seen[t - 1] if same else t
    split_days = [(np.datetime64(d), r) for d, r in splits]
    last = days[-1]
    for t in range(len(out)):
        if not np.isfinite(out[t]):
            continue
        seen = days[first_seen[t]] if basis is None else basis[t]
        if np.isnat(seen):
            out[t] = np.nan
            continue
        factor = 1.0
        for day, ratio in split_days:
            # Every split after the count was filed, through the price series'
            # own vintage (its last session): the stored closes are back-adjusted
            # for every split up to then, including splits after t, so a count
            # filed before a later split must carry it on every earlier session
            # too. Applying it only from the split day put market caps (and P/S,
            # P/E, the expectations gap) a split factor too low before each
            # later split: NVDA read 40x too cheap before July 2021.
            if seen < day <= last:
                factor *= ratio
        out[t] = out[t] * factor
    return out


# The valuation levels, point in time, from the stored filing versions.
#
# The stored facts frame (`edgar.parse_company_facts`) keeps ONE tag per
# fundamental, chosen over the whole history by its latest period end:
# hindsight. A filer that moved to the ASC 606 revenue tag in 2018 had its
# revenue chosen from that tag, which holds nothing before about 2017, so
# the valuation analyst saw no revenue (no P/S) for most of the market
# before then. The versions frame (`fundamentals_asof.KIND`) keeps every
# filing of every candidate tag, so the choice can be made at each session
# from what had been filed by then: the tag with the latest period end on
# file, then the most periods, then table order (`fundamentals_asof`'s
# `_ranked_tags` key). Every value still comes from one tag at a time, so
# growth compares a quarter with the year-ago quarter filed under the same
# tag. Values keep the frames path's semantics: each period's first-filed
# value, a fourth quarter derived from the year once its parts were all
# filed, and a value never rewritten once a session has seen it.
_PIT_NAMES = ("revenue", "net_income", "equity", "shares")
_PIT_FLOWS = frozenset({"revenue", "net_income"})


class _TagSeries:
    """One candidate tag of one fundamental, from the versions filed so far."""

    __slots__ = ("spans", "by_end", "filed_by_end", "key")

    def __init__(self) -> None:
        self.spans: dict = {}  # (start, end) -> first-filed Version
        self.by_end: dict[date, float] = {}  # first value known per period end
        self.filed_by_end: dict[date, date] = {}
        self.key: tuple = (date.min, 0)  # (latest end, count) for the ranking

    # Keep the version if it is the first filed for its period.
    def add(self, version) -> bool:
        span = (version.start, version.end)
        held = self.spans.get(span)
        if held is not None and held.filed <= version.filed:
            return False
        self.spans[span] = version
        return True

    # Extend the period values (never rewriting one already known) and the
    # rank key, after new versions were added.
    def refresh(self, flow: bool) -> None:
        from backend.market import fundamentals_asof as fa

        if flow:
            facts = _flow_facts(self.spans)
        else:
            facts = [(e, v.value, v.filed) for (_s, e), v in self.spans.items()]
        for end, value, filed in sorted(facts, key=lambda f: (f[2], f[0])):
            if end not in self.by_end:
                self.by_end[end] = value
                self.filed_by_end[end] = filed
        dated = {k: v for k, v in self.spans.items() if fa._dated_consistently(v)}
        ends = set(fa._quarters(dated, False)) if flow else {e for _, e in dated}
        self.key = (max(ends) if ends else date.min, len(ends))


# One tag's quarters as the frozen parser builds them: each reported quarter,
# plus a fourth quarter from a year whose first three quarters are on file,
# stamped with the latest filing of its parts.
def _flow_facts(spans: dict) -> list[tuple[date, float, date]]:
    from backend.market import fundamentals_asof as fa

    quarters = {k: v for k, v in spans.items() if fa.span_kind(*k) == "quarter"}
    years = {k: v for k, v in spans.items() if fa.span_kind(*k) == "year"}
    out = [(e, v.value, v.filed) for (_s, e), v in quarters.items()]
    ends = {e for _s, e in quarters}
    for (start, end), year in years.items():
        if end in ends:
            continue
        inside = [v for (s, e), v in quarters.items() if s >= start and e < end]
        if len(inside) != 3:
            continue
        filed = max([year.filed] + [v.filed for v in inside])
        out.append((end, year.value - sum(v.value for v in inside), filed))
    return out


# The best ranked tag holding any filing: the latest end, then the better tier
# (`fundamentals_asof._tag_tiers`: a fallback tag only with a later quarter
# than every better-tier tag), then the count, then table order.
def _best_tag(by_tag: dict, order: list[str], tiers: dict | None = None) -> str | None:
    best = None
    for rank, tag in enumerate(order):
        series = by_tag[tag]
        if not series.spans:
            continue
        latest, count = series.key
        key = (latest, -(tiers or {}).get(tag, 0), count, -rank)
        if best is None or key > best[0]:
            best = (key, tag)
    return None if best is None else best[1]


# One company's levels at each session from its filing versions. Returns
# {name: (latest, four quarters back, source filing date)} of (T,) arrays
# for revenue, net_income, equity and shares; NaN / NaT where unknown. A
# version counts from its filing date (strictly after it when
# `strict_publication`), the clock the frames path uses. Like the frames
# path, a level is carried however old its period is; `max_flow_age_days`
# (off by default) instead leaves revenue and earnings unknown once their
# latest quarter ended longer ago than that: a tag the filer stopped using
# (JNJ's lone `Revenues` quarters of 2014, read as 2016 revenue) or a metric
# it now reports under a tag the table does not list.
def versions_levels(
    versions,
    dates: np.ndarray,
    *,
    strict_publication: bool = False,
    max_flow_age_days: int | None = None,
) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Return the per-session levels of one company, tag chosen per session."""
    from backend.market import fundamentals_asof as fa

    size = len(dates)
    calendar = np.asarray(dates).astype("datetime64[D]").astype(object)
    rows = sorted(
        (v for v in versions if v.name in _PIT_NAMES),
        key=lambda v: (v.filed, v.accession, v.tag, v.end),
    )
    order = {name: fa._tag_order(name) for name in _PIT_NAMES}
    tiers = {name: fa._tag_tiers(name) for name in _PIT_NAMES}
    state = {name: {tag: _TagSeries() for tag in order[name]} for name in _PIT_NAMES}
    out = {
        name: (
            np.full(size, np.nan),
            np.full(size, np.nan),
            np.full(size, np.datetime64("NaT", "D")),
        )
        for name in _PIT_NAMES
    }
    chosen: dict[str, str | None] = {}
    pointer = 0
    for t in range(size):
        session = calendar[t]
        dirty: dict[str, set[str]] = {}
        while pointer < len(rows) and (
            rows[pointer].filed < session
            or (not strict_publication and rows[pointer].filed == session)
        ):
            version = rows[pointer]
            pointer += 1
            series = state[version.name].get(version.tag)
            if series is not None and series.add(version):
                dirty.setdefault(version.name, set()).add(version.tag)
        for name, tags in dirty.items():
            for tag in tags:
                state[name][tag].refresh(name in _PIT_FLOWS)
            chosen[name] = _best_tag(state[name], order[name], tiers[name])
        for name in _PIT_NAMES:
            tag = chosen.get(name)
            if tag is None or not state[name][tag].by_end:
                continue
            series = state[name][tag]
            ends = sorted(series.by_end)
            last = ends[-1]
            if (
                max_flow_age_days is not None
                and name in _PIT_FLOWS
                and (session - last).days > max_flow_age_days
            ):
                continue
            out[name][0][t] = series.by_end[last]
            out[name][1][t] = edgar._quarters_back(series.by_end, ends, last, 4)
            out[name][2][t] = np.datetime64(series.filed_by_end[last], "D")
    return out


# Read valuation inputs with optional strict publication and source share-basis bounds.
# Each name is read from its stored filing versions, the tag chosen per
# session; a name with no versions frame on file falls back to the stored
# facts frame (`_frames_levels`), so a store without versions behaves as before.
def point_in_time_levels(
    store: MarketStore, panel: Panel, asof=None, *, strict_publication: bool = False
) -> dict[str, np.ndarray]:
    """Return {"revenue", "earnings", "equity", "shares", "revenue_growth"}."""
    from backend.market import fundamentals_asof as fa

    shape = (len(panel.dates), len(panel.tickers))
    out = {
        name: np.full(shape, np.nan)
        for name in ("revenue", "earnings", "equity", "shares", "revenue_growth")
    }
    for column, ticker in enumerate(panel.tickers):
        found = store.read_frame(fa.KIND, ticker, asof)
        versions = fa.versions_from_frame(found[0]) if found is not None else []
        if versions:
            known = versions_levels(
                versions, panel.dates, strict_publication=strict_publication
            )
        else:
            known = _frames_known(store, ticker, panel.dates, asof, strict_publication)
            if known is None:
                continue
        with np.errstate(all="ignore"):
            out["revenue"][:, column] = known["revenue"][0] * QUARTERS
            out["earnings"][:, column] = known["net_income"][0] * QUARTERS
            out["equity"][:, column] = known["equity"][0]
            out["shares"][:, column] = split_adjusted_shares(
                known["shares"][0],
                panel.dates,
                _splits(store, ticker, asof),
                basis_dates=known["shares"][2] if strict_publication else None,
            )
            out["revenue_growth"][:, column] = (
                known["revenue"][0] / known["revenue"][1] - 1.0
            )
    return out


# The same per-session levels from the stored facts frame (one tag per
# fundamental, chosen over the snapshot), for a name with no versions frame.
def _frames_known(
    store: MarketStore, ticker: str, dates: np.ndarray, asof, strict_publication: bool
) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] | None:
    events = store.read_frame(EVENTS, ticker, asof)
    facts = store.read_frame(FACTS, ticker, asof)
    if events is None or facts is None:
        return None
    meta = facts[1]
    stamp = meta.get("source_time")
    record = edgar.record_from_frames(
        ticker,
        int(meta.get("cik", "0")),
        events[0],
        facts[0],
        datetime.fromisoformat(stamp) if stamp else datetime.now(),
    )
    out = {}
    for name in _PIT_NAMES:
        series, _filed_at, source = edgar._known_quarters(
            record.facts, name, dates, strict_before_session=strict_publication
        )
        out[name] = (series[0], series[4], source)
    return out
