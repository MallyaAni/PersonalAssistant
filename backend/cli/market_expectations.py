"""An earnings-expectations model, and what the gap between it and the price pays.

    python -m backend.cli.market_expectations
    python -m backend.cli.market_expectations --overlay
    python -m backend.cli.market_expectations --leg --book-since 2018-06-01

Availability boundary
---------------------
The helpers accept an optional extraction-partition cutoff, propagated by the
desk through prices, records, tone and valuation. None retains latest-data
behavior. Training now retains the first filed label and bounds each annual
fit by its publication date, with the minimum sample count applied per fit.
The feature row now precedes both associated SEC acceptance and the start of
the target's date-only first filing. Date-only fundamentals and tone become
usable only on a later session. Reviewed exchange closes bound timestamps;
unknown calendar years or missing required sessions do not form training rows.
This changes training eligibility, not just metadata. It does not establish
historical membership, the first public press-release time, correct quarter-to-
release association, or all remaining within-vintage source assumptions. The older
study description/results below are historical development evidence, not
qualified performance or proof that those unresolved boundaries are correct.
The old naive comparator also used log growth against simple-growth targets.
Its accuracy and surprise diagnostics do not establish superiority over a
correctly scaled last-growth baseline. The reporting baseline now inverts log
growth and applies the target's clipping; no historical results were recomputed.
Upstream zero-filled missing growth still lacks a validity mask, so this
numerical correction does not qualify baseline observation coverage.
The gap was subsequently promoted on 2026-09-10; that operational decision is
not validation of the historical claims. This cutoff fix does not rerun or
repair the saved study.

The claim
---------
The sentiment analyst reads the release after it lands. A review named
the missing piece: what was expected, what changed, and how much the
price already reflects. There is no free history of analyst consensus,
so this builds the expectation the way van Binsbergen, Han and
Lopez-Lira do: a learner on what was known before the report, trained
only on quarters reported before the year it is scored on.

The dataset
-----------
One row per filed revenue quarter on the universe (some five hundred
names since 2016) whose results release (an 8-K with item 2.02) can be
placed: the reaction session `r`. The target is the quarter's revenue
growth over the same quarter a year earlier, clipped to [-0.9, 5]. The
features use a separate conservative pre-publication index, not `r - 1`, and are
what the desk already knows there: the point-in-time fundamental block
(last growth, sequential growth, acceleration, margins, the last
reaction, sessions since the last report), the release tone of the last
report where scored, price momentum over 20, 60 and 120 sessions with
   the market's part removed, log market value, and the growth the
   price implies (a valuation proxy: the sector-relative price/sales
   multiple transformed onto a growth-like scale, so the gap between
   the learner's expectation and the price is on the table).

The measurement
---------------
Three questions, each against the naive expectation (last quarter's
growth again) so the learner has to beat the obvious.

  accuracy   out-of-sample: mean absolute error and the correlation of
             the expected with the actual, by year
  after      the surprise, actual less expected, in fifths; the
             beta-adjusted residual over the twenty sessions from the
             close after the report (what a person could trade). The
             post-earnings drift, if the expectation is the right one.
  before     the gap, expected growth less the growth the price
             implies, read ten sessions before the report; the residual
             into the close before the print and through it. This is
             the ORCL question: cheap for what is expected.

Then the book. `--overlay` adds 3% ten sessions before a report on a
book name in the cheapest fifth for what is expected. `--leg` carries
the expectation every session (the year's learner asked on every
session's features), takes the gap to the growth the price implies as a
valuation leg, and runs the book with the valuation analyst blended
with it and replaced by it, by year. Newey-West t on per-session means,
as in the other studies.

Results, 2026-09-08
-------------------
13,515 report rows on 515 names, 2015 to 2026, scored out of sample
from 2018. The uncorrected study reported learner correlation with
the actual +0.628 against +0.531 for the mixed-scale naive comparator,
better in eight years of nine; this is not a valid baseline comparison.
It leaned almost entirely on last growth (66% of the gain), then
acceleration, margin and the price-implied growth.

After the report there is no drift on this universe: the top fifth of
the learner's surprise earns +0.02% over the twenty sessions from the
close after against the bottom fifth (t 0.1); the naive surprise
+0.35% (t 0.9). The reaction session takes it all.

Before the report the gap pays. The cheapest fifth for what is
expected, read ten sessions before, earned +0.38% into the close before
the print (t 1.5) and +1.23% through it (t 2.6, 1,939 events) against
the rest, positive in eight years of nine (2022 +4.8%, t 6.1; 2025
-1.4%). An improving tape does not help it: the half whose twenty-
session residual was falling earned more (+1.45%, t 2.9) than the half
that was rising (+1.06%, t 1.9), so "cheap, improving, favourable
expectations" is not the shape; cheap and not yet moved is.

In the book. The pre-report add (247 fires, 160 adds from 2021-06):
+34.1% a year at 19.1% volatility against the rule's +31.8% at 17.2%,
which is +35.3% at the same volatility: exposure, not skill, as every
overlay has been. The carried expectation as a valuation leg has a
lower IC than the current analyst (+0.029 against +0.038 at twenty
sessions) and a different book: from 2021-06 the analyst replaced by
the gap earns +35.6%, Sharpe 1.89, against +31.8%, 1.85 (the rule at
matched volatility +34.8%); from 2018-06 the analyst blended with the
gap earns +28.1%, Sharpe 1.56, against +23.9%, 1.46 (matched, +26.4%),
while the gap alone is a wash there. By year from 2018, the blend
earns more than the rule in seven years of nine (2019 +31.7% against
+22.9%, 2021 +28.2% against +20.1%, 2023 +59.6% against +37.2%, 2024,
2025, 2026 ahead as well) and less in the two flat or falling ones
(2018 +0.4% against +4.0%, 2022 -16.5% against -14.8%): it earns by
holding more of what it likes, and pays for it when the market falls.
The gap alone is ahead in four years and behind in five.

Verdict: the blend is the first input change since the desk was frozen
that beats the rule on compounded return in most years with a higher
Sharpe over the full window, and it is still development evidence: the
learner is walk-forward but the choice between blend and replacement
was made after seeing both. It is not adopted into the live desk. It is
the challenger: the next step is to compute it nightly beside the rule
and let the forward record decide, which the review asked for.
"""

import argparse
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from pathlib import Path

import numpy as np

from backend.cli.market_earnings import reaction_sessions
from backend.cli.market_snapback import _spread
from backend.market import calendar, edgar, language, valuation
from backend.market.levels_pit import point_in_time_levels
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.universe import (
    FOCUS,
    MARKET_BENCHMARK,
    MEMBER,
    book_sides,
    build_universe,
    theme_map,
    tickers_with_role,
)

FUND = (
    "revenue_yoy",
    "revenue_qoq",
    "revenue_acceleration",
    "eps_change_yoy",
    "net_margin",
    "gross_margin",
    "earnings_reaction",
    "sessions_since_earnings",
)
TONE = ("tone_guidance", "tone_demand", "tone_guidance_change", "tone_pricing")
PRICE = ("mom_20", "mom_60", "mom_120", "log_cap", "ps_implied_growth")
NAMES = FUND + TONE + PRICE
BEFORE = 10
# A small gradient-boosted regressor, fit and asked once per fold.
PARAMS = {
    "objective": "regression",
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_data_in_leaf": 40,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "feature_fraction": 0.8,
    "lambda_l2": 5.0,
    "verbosity": -1,
}


@dataclass(frozen=True)
class ReleaseWindow:
    """Keep the return index separate from a timestamp-bounded feature index."""

    reaction: int
    feature: int
    accepted: datetime
    accession: str


# Preserve each associated release's timing; never infer it from a return index.
def _release_windows(dates, record):
    windows = {}
    for event in record.events:
        before = calendar.publication_session(event.accepted, before=True)
        if before is None:
            continue
        feature = int(np.searchsorted(dates, before))
        if feature >= len(dates) or dates[feature] != before:
            continue
        reactions = reaction_sessions(
            dates,
            {
                "accepted": [event.accepted.isoformat()],
                "filed": [event.filed],
                "items": [event.items],
            },
        )
        if not reactions or feature >= reactions[0]:
            continue
        reaction = reactions[0]
        candidate = ReleaseWindow(reaction, feature, event.accepted, event.accession)
        previous = windows.get(reaction)
        if previous is None or candidate.accepted < previous.accepted:
            windows[reaction] = candidate
    return [windows[index] for index in sorted(windows)]


# Read available SEC timing even when absent financial facts prevented a full record.
def _tone_event_times(store, ticker, record, asof):
    if record is not None:
        rows = [(event.accession, event.accepted) for event in record.events]
    else:
        frame = store.read_frame("edgar_events", ticker, asof)
        columns = frame[0] if frame is not None else {}
        rows = [
            (accession, datetime.fromisoformat(str(accepted)))
            for accession, accepted in zip(
                columns.get("accession", []), columns.get("accepted", []), strict=True
            )
        ]
    times = {}
    for accession, accepted in rows:
        times.setdefault(accession, []).append(accepted)
    return times


# Load date-only tone conservatively, never ahead of a matching SEC acceptance.
def _tone_before_session(store, panel, records, asof):
    by_ticker = {}
    for ticker in panel.tickers:
        frame = store.read_frame(language.TONE_KIND, ticker, asof)
        if frame is None:
            continue
        times = _tone_event_times(store, ticker, records.get(ticker), asof)
        bounded = []
        for tone in language.records_from_frame(frame[0]):
            matched = times.get(tone.accession, ())
            if any(
                accepted.tzinfo is None or accepted.utcoffset() is None
                for accepted in matched
            ):
                continue
            not_before = max(
                [tone.reaction_date]
                + [
                    accepted.astimezone(calendar.NEW_YORK).date()
                    for accepted in matched
                ]
            )
            bounded.append(replace(tone, reaction_date=not_before))
        by_ticker[ticker] = bounded
    return (
        language.tone_features(panel, by_ticker, strict_before_session=True)
        if by_ticker
        else None
    )


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument(
        "--book", action="store_true", help="the desk's book names only"
    )
    parser.add_argument("--min-train-years", type=int, default=3)
    parser.add_argument(
        "--overlay", action="store_true", help="the book with a pre-report add"
    )
    parser.add_argument(
        "--leg",
        action="store_true",
        help="the expectation carried every session as a valuation leg, and the book",
    )
    parser.add_argument("--book-since", default="2021-06-01")
    return parser


# Read universe prices at the requested extraction cutoff, keeping current membership.
def _universe_panel(store, book_only: bool, asof: date | None = None):
    universe = build_universe()
    members = tickers_with_role(universe, MEMBER, FOCUS)
    if book_only:
        members = [t for t in members if t in book_sides(universe)]
    themes = {t: g for t, g in theme_map(universe).items() if t in members}
    sector = {m.ticker: (m.sector or "other") for m in universe if m.ticker in members}
    return (
        build_panel(store, tuple(sorted(members)), MARKET_BENCHMARK, themes, asof=asof),
        sector,
    )


# Load original labels and timestamp-bounded release windows at the partition cutoff.
def _records(store, panel, dates, asof: date | None = None):
    records, quarters, reactions = {}, {}, {}
    for ticker in panel.tickers:
        if ticker == panel.benchmark:
            continue
        events = store.read_frame("edgar_events", ticker, asof)
        facts = store.read_frame("edgar_facts", ticker, asof)
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
        records[ticker] = record
        quarters[ticker] = sorted(
            ((f.end, f.value, f.filed) for f in record.facts if f.name == "revenue"),
            key=lambda x: x[0],
        )
        reactions[ticker] = _release_windows(dates, record)
    return records, quarters, reactions


# Residual momentum over `k` sessions: the name's log return less beta
# times the market's, both over the same window.
def _momentum(panel, beta, k: int) -> np.ndarray:
    adj = panel.adj_close
    bench = adj[:, panel.index(panel.benchmark)]
    out = np.full(adj.shape, np.nan)
    with np.errstate(all="ignore"):
        own = np.log(adj[k:] / adj[:-k])
        mkt = np.log(bench[k:] / bench[:-k])[:, None]
        out[k:] = own - beta[k:] * mkt
    return out


def _fit_predict(x_train, y_train, x_test, names):
    """Fit the regressor on the training rows and return (predictions, booster)."""
    import lightgbm as lgb

    booster = lgb.train(
        PARAMS,
        lgb.Dataset(np.nan_to_num(x_train, nan=0.0), y_train, feature_name=list(names)),
        num_boost_round=300,
    )
    return booster.predict(np.nan_to_num(x_test, nan=0.0)), booster


# Bound every date-only filing/tone input while retaining the actual price session.
def _features(store, panel, records, asof: date | None = None):
    fund = edgar.edgar_features(panel, records, strict_publication=True)
    fidx = {n: i for i, n in enumerate(edgar.FEATURE_NAMES)}
    tone = _tone_before_session(store, panel, records, asof)
    tidx = {n: i for i, n in enumerate(language.FEATURE_NAMES)}
    beta = panel.rolling_beta(120)
    mom = {k: _momentum(panel, beta, k) for k in (20, 60, 120)}
    levels = point_in_time_levels(store, panel, asof, strict_publication=True)
    ratios = valuation.multiples(
        panel,
        levels["revenue"],
        levels["earnings"],
        levels["equity"],
        levels["shares"],
        levels["revenue_growth"],
    )
    return fund, fidx, tone, tidx, beta, mom, ratios


# Every session's feature vector, (T, N, F) in NAMES order, and the
# growth the price implies.
def _block(panel, sector, fund, fidx, tone, tidx, mom, ratios):
    rows_n, cols = panel.adj_close.shape
    groups = valuation.groups_from(panel, sector)
    with np.errstate(all="ignore"):
        # The growth the price implies is a valuation proxy, not a measured
        # expectation: a monotone transform of the name's price/sales
        # multiple against its group onto a growth-like scale (P/S of 5x a
        # group average of 3x maps to about 12% here). Calling it a growth
        # rate rather than a P/S reading would overstate what the market is
        # known to be pricing.
        implied = (
            np.exp(valuation.relative_to_group(ratios.get("price_sales"), groups) / 5.0)
            - 1.0
        )
        log_cap = np.log(ratios.market_cap)
    feats = np.full((rows_n, cols, len(NAMES)), np.nan)
    for k, n in enumerate(FUND):
        feats[:, :, k] = fund[:, :, fidx[n]]
    for k, n in enumerate(TONE):
        feats[:, :, len(FUND) + k] = tone[:, :, tidx[n]] if tone is not None else 0.0
    base = len(FUND) + len(TONE)
    feats[:, :, base + 0] = mom[20]
    feats[:, :, base + 1] = mom[60]
    feats[:, :, base + 2] = mom[120]
    feats[:, :, base + 3] = log_cap
    feats[:, :, base + 4] = implied
    return feats, implied


# Retain one first-report value per quarter; conflicting same-day values are unknown.
def _first_reports(quarters):
    first = {}
    ambiguous = set()
    dated = [q for q in quarters if type(q[0]) is date and type(q[2]) is date]
    for end, value, filed in sorted(dated, key=lambda q: (q[0], q[2])):
        if not np.isfinite(value) or filed < end:
            continue
        if end not in first:
            first[end] = (value, filed)
        elif first[end][1] == filed and first[end][0] != value:
            ambiguous.add(end)
    return {end: value for end, value in first.items() if end not in ambiguous}


# Select an observed, warmed-up close before both independently recorded source bounds.
def _pre_report_index(dates, window, filed):
    release_before = calendar.publication_session(window.accepted, before=True)
    filed_before = calendar.publication_session(
        datetime.combine(filed, time.min, calendar.NEW_YORK), before=True
    )
    if release_before is None or filed_before is None:
        return None
    if not 0 <= window.feature < len(dates) or dates[window.feature] != release_before:
        return None
    feature_day = min(release_before, filed_before)
    feature = int(np.searchsorted(dates, feature_day))
    if feature < 130 or feature >= len(dates) or dates[feature] != feature_day:
        return None
    return feature


# Keep features before both the associated SEC timestamp and date-only target filing.
def _dataset(panel, dates, quarters, reactions, feats):
    rows_n = panel.adj_close.shape[0]
    date_arr = np.array(dates)
    x, y, meta = [], [], []
    for j, ticker in enumerate(panel.tickers):
        if ticker not in quarters:
            continue
        by_end = _first_reports(quarters[ticker])
        ends = sorted(by_end)
        windows = reactions.get(ticker, [])
        if any(not isinstance(window, ReleaseWindow) for window in windows):
            raise ValueError("expectations require timestamp-bounded release windows")
        for e in ends:
            v, filed = by_end[e]
            prior = [
                p for p in ends if 350 <= (e - p).days <= 380 and by_end[p][1] <= filed
            ]
            if not prior or by_end[prior[-1]][0] <= 0:
                continue
            g = float(np.clip(v / by_end[prior[-1]][0] - 1.0, -0.9, 5.0))
            lo = np.searchsorted(date_arr, e)
            cand = sorted(
                (w for w in windows if lo < w.reaction <= min(rows_n - 1, lo + 70)),
                key=lambda w: w.reaction,
            )
            if len(cand) == 0:
                continue
            window = cand[0]
            r = window.reaction
            days = (dates[r] - e).days
            if days < 10 or days > 100 or r < 131:
                continue
            feature = _pre_report_index(dates, window, filed)
            if feature is None:
                continue
            row = feats[feature, j]
            if not np.isfinite(row[0]):
                continue
            x.append(row)
            y.append(g)
            # Facts retain a filing day, not an acceptance timestamp. Annual
            # cutoffs exclude the fit day itself; no earlier intraday claim is made.
            meta.append(
                (
                    j,
                    r,
                    dates[r].year,
                    max(filed, dates[r]),
                    feature,
                    window.accepted,
                    window.accession,
                )
            )
    return (
        np.asarray(x, dtype=float).reshape(-1, feats.shape[-1]),
        np.asarray(y, dtype=float),
        meta,
    )


# Select only published labels and apply coverage requirements at this fit date.
def _training_mask(y, available_dates, year, min_train_years, min_train_rows=500):
    if available_dates is None or len(available_dates) != len(y):
        raise ValueError("training requires one publication date per label")
    if any(type(d) is not date for d in available_dates):
        raise ValueError("publication dates must be explicit calendar dates")
    available = np.asarray(available_dates, dtype="datetime64[D]")
    train = (available < np.datetime64(date(int(year), 1, 1))) & np.isfinite(y)
    years = {available_dates[i].year for i in np.flatnonzero(train)}
    if train.sum() < min_train_rows or len(years) < min_train_years:
        train[:] = False
    return train


# Fit before each scoring year using only labels already published at its start.
def _expected(
    x,
    y,
    meta_year,
    years,
    min_train_years,
    x_score=None,
    ok=None,
    *,
    available_dates=None,
    score_dates=None,
):
    x_score = x if x_score is None else x_score
    ok = np.ones(len(y), dtype=bool) if ok is None else ok
    expected = np.full(len(y), np.nan)
    model = None
    if score_dates is None or len(score_dates) != len(y):
        raise ValueError("expectations require one actual scoring date per row")
    score_year = np.array([d.year for d in score_dates])
    for yr in sorted(set(score_year)):
        train = _training_mask(y, available_dates, yr, min_train_years)
        if not train.any():
            continue
        test = (score_year == yr) & ok
        if not test.any():
            continue
        expected[test], model = _fit_predict(x[train], y[train], x_score[test], NAMES)
    return expected, model


def _accuracy(expected, naive, y, meta_year, years, model):
    scored = np.isfinite(expected)
    print(f"\naccuracy out of sample on {int(scored.sum())} rows:")
    for name, pred in (("naive (last growth)", naive), ("learner", expected)):
        ok = scored & np.isfinite(pred)
        err = np.abs(pred[ok] - y[ok]).mean()
        corr = np.corrcoef(pred[ok], y[ok])[0, 1]
        print(f"  {name:22} MAE {err:.3f}  corr {corr:+.3f}")
    print("  by year (corr, learner | naive):")
    for yr in years:
        ok = scored & (meta_year == yr) & np.isfinite(naive)
        if ok.sum() < 30:
            continue
        c1 = np.corrcoef(expected[ok], y[ok])[0, 1]
        c2 = np.corrcoef(naive[ok], y[ok])[0, 1]
        print(f"    {yr}: {c1:+.3f} | {c2:+.3f}  n {int(ok.sum())}")
    if model is not None:
        gains = model.feature_importance(importance_type="gain")
        total = float(sum(gains)) or 1.0
        imp = sorted(zip(NAMES, gains, strict=True), key=lambda x: -x[1])[:8]
        print(
            "  what the last model leaned on: "
            + ", ".join(f"{n} {v / total:.0%}" for n, v in imp)
        )


# Fifths of `values` within each year, stamped on the session `offset`
# from each row's reaction session. The cutoffs are trailing: a row's fifth
# is set by the reports up to its own session, never by reports later in the
# year, or the buckets would know the future. A row is not bucketed until
# its own history has enough reports to place it. Explicit feature-session
# positions keep pre-report reads separate from reaction-relative return windows.
def _fifths(values, mask, meta, meta_year, years, shape, offset, *, positions=None):
    out = np.zeros((*shape, 5), dtype=bool)
    positions = [m[1] + offset for m in meta] if positions is None else positions
    for yr in years:
        sel = mask & (meta_year == yr) & np.isfinite(values)
        if sel.sum() < 25:
            continue
        indices = sorted(np.flatnonzero(sel), key=lambda i: positions[i])
        pool: list[float] = []
        for i in indices:
            pool.append(float(values[i]))
            if len(pool) < 25:
                continue
            cuts = np.quantile(pool, [0.2, 0.4, 0.6, 0.8])
            j = meta[i][0]
            position = positions[i]
            if not 0 <= position < shape[0]:
                continue
            out[position, j, int(np.searchsorted(cuts, values[i], side="right"))] = True
    return out


# Measure surprise returns only when the filed result was already available.
def _after(panel, expected, naive, y, meta, meta_year, years):
    label20 = panel.forward_residual(20)
    # A filing-day-only label cannot support a surprise trade before the next day.
    available = np.array(
        [
            r + 1 < len(panel.dates)
            and np.datetime64(published) < panel.dates[r + 1].astype("datetime64[D]")
            for _j, r, _year, published, *_timing in meta
        ],
        dtype=bool,
    )
    scored = np.isfinite(expected) & available
    shape = panel.adj_close.shape
    fm = _fifths(y - expected, scored, meta, meta_year, years, shape, 1)
    fn = _fifths(
        y - naive, scored & np.isfinite(naive), meta, meta_year, years, shape, 1
    )
    anyf, anyn = fm.any(axis=2), fn.any(axis=2)
    print("\nafter the report: residual over twenty sessions from the close after it")
    print(f"{'fifth of the surprise':40} {'learner':>22} {'naive':>22}")
    for q, label in enumerate(("most negative", "2nd", "3rd", "4th", "most positive")):
        m1, t1, n1 = _spread(label20, fm[:, :, q], anyf & ~fm[:, :, q], 20)
        m2, t2, n2 = _spread(label20, fn[:, :, q], anyn & ~fn[:, :, q], 20)
        print(
            f"{label:40} {m1:+8.2%} (t {t1:5.1f}) {n1:5d}  "
            f"{m2:+8.2%} (t {t2:5.1f}) {n2:5d}"
        )
    a = _spread(label20, fm[:, :, 4], fm[:, :, 0], 20)
    b = _spread(label20, fn[:, :, 4], fn[:, :, 0], 20)
    print(
        f"{'top fifth less bottom fifth':40} {a[0]:+8.2%} (t {a[1]:5.1f})"
        f"        {b[0]:+8.2%} (t {b[1]:5.1f})"
    )


# Read the gap BEFORE sessions ahead of the conservative feature cutoff,
# retaining separate associated reaction-return endpoints.
def _before(panel, dates, x, y, meta, meta_year, years, feats, beta, mom, args):
    rows_n, cols = panel.adj_close.shape
    # The feature bound may precede r - 1; retain the longest actual return window.
    through_horizon = max(
        (m[1] + 1 - (m[4] - BEFORE) for m in meta), default=BEFORE + 2
    )
    implied_col = NAMES.index("ps_implied_growth")
    x_before = x.copy()
    ok = np.zeros(len(y), dtype=bool)
    for i, (j, _r, _yy, _published, feature, *_source) in enumerate(meta):
        t = feature - BEFORE
        if t < 130:
            continue
        x_before[i] = feats[t, j]
        ok[i] = np.isfinite(feats[t, j, implied_col])
    expected, _m = _expected(
        x,
        y,
        meta_year,
        years,
        args.min_train_years,
        x_before,
        ok,
        available_dates=[m[3] for m in meta],
        score_dates=[dates[max(0, m[4] - BEFORE)] for m in meta],
    )
    gap = expected - x_before[:, implied_col]
    into = np.full((rows_n, cols), np.nan)
    through = np.full((rows_n, cols), np.nan)
    adj = panel.adj_close
    bench = adj[:, panel.index(panel.benchmark)]
    for i, (j, r, _yy, _published, feature, *_source) in enumerate(meta):
        t = feature - BEFORE
        if t < 130 or not np.isfinite(gap[i]):
            continue
        with np.errstate(all="ignore"):
            into[t, j] = np.log(adj[feature, j] / adj[t, j]) - beta[t, j] * np.log(
                bench[feature] / bench[t]
            )
            if r + 1 < rows_n:
                through[t, j] = np.log(adj[r + 1, j] / adj[t, j]) - beta[t, j] * np.log(
                    bench[r + 1] / bench[t]
                )
    fg = _fifths(
        gap,
        np.isfinite(gap),
        meta,
        meta_year,
        years,
        (rows_n, cols),
        0,
        positions=[m[4] - BEFORE for m in meta],
    )
    anyg = fg.any(axis=2)
    cheap = fg[:, :, 4]
    print(f"\ngap read {BEFORE} sessions before the conservative feature cutoff")
    print(
        f"{'fifth of the gap (expected - implied)':44} {'to feature cutoff':>24} "
        f"{'through reaction + 1':>22}"
    )
    labels = (
        "richest: price implies more than expected",
        "2nd",
        "3rd",
        "4th",
        "cheapest for what is expected",
    )
    for q, label in enumerate(labels):
        m1, t1, n1 = _spread(into, fg[:, :, q], anyg & ~fg[:, :, q], BEFORE)
        m2, t2, _n2 = _spread(
            through, fg[:, :, q], anyg & ~fg[:, :, q], through_horizon
        )
        print(f"{label:44} {m1:+8.2%} (t {t1:5.1f}) {n1:5d}  {m2:+8.2%} (t {t2:5.1f})")
    a = _spread(into, cheap, fg[:, :, 0], BEFORE)
    b = _spread(through, cheap, fg[:, :, 0], through_horizon)
    print(
        f"{'cheapest fifth less richest fifth':44} {a[0]:+8.2%} (t {a[1]:5.1f})"
        f"        {b[0]:+8.2%} (t {b[1]:5.1f})"
    )
    print("  cheapest fifth vs the rest, through the print, by year:")
    yrs = np.array([d.year for d in dates])
    for yr in years:
        rows = yrs == yr
        m, t, n = _spread(
            through[rows], cheap[rows], (anyg & ~cheap)[rows], through_horizon
        )
        if n:
            print(f"    {yr}: {m:+7.2%} (t {t:4.1f})  events {n}")
    _by_tape(meta, mom, cheap, anyg, into, through, (rows_n, cols), through_horizon)
    return cheap


# Split by tape at the same conservative feature-relative read used by the gap.
def _by_tape(meta, mom, cheap, anyg, into, through, shape, through_horizon) -> None:
    improving = np.zeros(shape, dtype=bool)
    for j, _r, _yy, _published, feature, *_source in meta:
        t = feature - BEFORE
        if t >= 130 and np.isfinite(mom[20][t, j]) and mom[20][t, j] > 0:
            improving[t, j] = True
    for name, mask in (
        ("cheapest fifth, tape improving", cheap & improving),
        ("cheapest fifth, tape not improving", cheap & ~improving),
    ):
        m1, t1, n1 = _spread(into, mask, anyg & ~cheap, BEFORE)
        m2, t2, _n2 = _spread(through, mask, anyg & ~cheap, through_horizon)
        print(f"{name:44} {m1:+8.2%} (t {t1:5.1f}) {n1:5d}  {m2:+8.2%} (t {t2:5.1f})")


# A (T, N) array on the universe's panel, onto the book's.
def _onto_book(values, panel, book, dates):
    book_dates = {
        d.astype("datetime64[D]").astype(object): i for i, d in enumerate(book.dates)
    }
    empty = False if values.dtype == bool else np.nan
    out = np.full(book.adj_close.shape, empty)
    for j, ticker in enumerate(panel.tickers):
        if ticker not in book.tickers:
            continue
        col = book.index(ticker)
        for t in range(values.shape[0]):
            tb = book_dates.get(dates[t])
            if tb is not None:
                out[tb, col] = values[t, j]
    return out


def _book_line(name, result) -> None:
    stats = result.stats()
    print(
        f"{name:40} {stats['annual']:+8.1%} {stats['volatility']:7.1%} "
        f"{stats['sharpe']:7.2f} {stats['drawdown']:8.1%} {stats['total']:+9.1%}"
    )


# The test that counts: the book under its own rules with a 3% add, ten
# sessions before a report, on a book name in the cheapest fifth for what
# is expected, against the rule.
def _overlay(store, panel, dates, cheap, since: str) -> None:
    from backend.agents.trading.desk import desk as trading_desk
    from backend.agents.trading.desk import simulate

    report = trading_desk.run(store)
    signal = _onto_book(cheap, panel, report.panel, dates) & (report.graded.grades >= 1)
    start = date.fromisoformat(since)
    print(
        f"\nthe book from {since}, a 3% add ten sessions before a report on a book "
        f"name in the cheapest fifth for what is expected, graded B or better "
        f"({int(signal.sum())} fires):"
    )
    print(f"{'':40} {'annual':>8} {'vol':>7} {'Sharpe':>7} {'maxDD':>8} {'total':>9}")
    for name, rule in (
        ("the rule", None),
        ("add from cash", simulate.DipRule(signal=signal, add=0.03, funded=False)),
        ("add, funded", simulate.DipRule(signal=signal, add=0.03, funded=True)),
    ):
        _book_line(name, simulate.run(report, since=start, use_exits=False, dip=rule))


# The report regraded with the valuation analyst's scores replaced.
def _with_value(report, scores):
    from backend.agents.trading.desk import desk as trading_desk
    from backend.agents.trading.desk import grading

    opinions = dict(report.opinions)
    opinions["value"] = replace(opinions["value"], scores=scores)
    graded = grading.grade(
        opinions["fundamental"],
        opinions["technical"],
        opinions["sentiment"],
        report.regime.rotation,
        opinions["value"],
        grading.ANALYST_WEIGHTS,
    )
    return replace(
        report,
        opinions=opinions,
        graded=graded,
        scores=graded.as_scores(trading_desk.blended(opinions)),
    )


# Carry annual fits forward only after each fit meets publication and sample gates.
def _carried(
    dates, x, y, meta_year, years, feats, min_train_years, *, available_dates=None
):
    rows_n, cols, width = feats.shape
    expected = np.full((rows_n, cols), np.nan)
    yrs = np.array([d.year for d in dates])
    for yr in years:
        train = _training_mask(y, available_dates, yr, min_train_years)
        if not train.any():
            continue
        rows = np.flatnonzero(yrs == yr)
        if not len(rows):
            continue
        block = feats[rows].reshape(-1, width)
        known = np.isfinite(block[:, 0])
        if not known.any():
            continue
        pred, _m = _fit_predict(x[train], y[train], block[known], NAMES)
        out = np.full(len(block), np.nan)
        out[known] = pred
        expected[rows] = out.reshape(len(rows), cols)
    return expected


# The expectation carried every session as a valuation leg, and the book
# with the valuation analyst blended with it and replaced by it, by year.
def _leg(
    store,
    panel,
    dates,
    x,
    y,
    meta_year,
    years,
    feats,
    implied,
    args,
    *,
    available_dates,
) -> None:
    from backend.agents.trading.desk import desk as trading_desk
    from backend.agents.trading.desk import simulate
    from backend.market import baselines
    from backend.market.harness import evaluate_scores

    expected = _carried(
        dates,
        x,
        y,
        meta_year,
        years,
        feats,
        args.min_train_years,
        available_dates=available_dates,
    )
    report = trading_desk.run(store)
    book = report.panel
    with np.errstate(all="ignore"):
        leg = _onto_book(expected - implied, panel, book, dates)
    v1 = report.opinions["value"].scores
    blend = baselines.rank_blend(v1, leg)

    def ic(scores, horizon):
        ics = evaluate_scores(
            scores, book, horizon, exclude=(book.benchmark,)
        ).defined_ics
        if len(ics) < 3:
            return float("nan"), float("nan")
        return float(ics.mean()), float(
            ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)))
        )

    print("\nthe expectation carried every session, as a valuation leg on the book:")
    print(f"{'rank IC':40} {'20 sessions':>18} {'60 sessions':>18}")
    for name, scores in (
        ("current valuation analyst", v1),
        ("expected growth less implied (gap)", leg),
        ("expected growth alone", _onto_book(expected, panel, book, dates)),
        ("current + gap, rank blend", blend),
    ):
        a, b = ic(scores, 20), ic(scores, 60)
        print(f"{name:40} {a[0]:+8.3f} (t {a[1]:4.1f}) {b[0]:+8.3f} (t {b[1]:4.1f})")
    start = date.fromisoformat(args.book_since)
    print(
        f"\nthe book from {args.book_since}: {'annual':>8} {'vol':>7} {'Sharpe':>7} "
        f"{'maxDD':>8} {'total':>9}"
    )
    results = {}
    for name, scores in (
        ("the rule", None),
        ("value = current + gap", blend),
        ("value = gap alone", leg),
    ):
        rep_ = report if scores is None else _with_value(report, scores)
        results[name] = simulate.run(rep_, since=start, use_exits=False)
        _book_line(name, results[name])
    print("  by year:")
    first = next(iter(results.values()))
    year_of = np.array([str(d)[:4] for d in first.dates])
    for yr in sorted(set(year_of)):
        cells = []
        for name, result in results.items():
            r = result.returns[(year_of == yr) & np.isfinite(result.returns)]
            cells.append(f"{name.split(' = ')[-1]:16} {np.prod(1 + r) - 1:+7.1%}")
        print(f"    {yr}: " + "   ".join(cells))


# Run the source-bounded study with separate feature and reaction-session clocks.
def main() -> None:
    """Run the study."""
    args = build_parser().parse_args()
    store = MarketStore(Path(args.root))
    panel, sector = _universe_panel(store, args.book)
    dates = [d.astype("datetime64[D]").astype(object) for d in panel.dates]
    records, quarters, reactions = _records(store, panel, dates)
    print(f"{len(records)} names with filings; building features")
    fund, fidx, tone, tidx, beta, mom, ratios = _features(store, panel, records)
    feats, implied = _block(panel, sector, fund, fidx, tone, tidx, mom, ratios)
    x, y, meta = _dataset(panel, dates, quarters, reactions, feats)
    meta_year = np.array([m[2] for m in meta])
    years = sorted(set(meta_year))
    if not len(y):
        print("no eligible published report labels")
        return
    print(
        f"{len(y)} report rows on {len({m[0] for m in meta})} names, "
        f"{meta_year.min()}-{meta_year.max()}"
    )
    if len(y) < 500:
        print("too few rows")
        return
    expected, model = _expected(
        x,
        y,
        meta_year,
        years,
        args.min_train_years,
        available_dates=[m[3] for m in meta],
        score_dates=[dates[m[4]] for m in meta],
    )
    # Compare like units without changing log-growth model inputs. This cannot
    # recover growth observations already zero-filled by the upstream producer.
    naive = np.clip(np.expm1(x[:, NAMES.index("revenue_yoy")]), -0.9, 5.0)
    _accuracy(expected, naive, y, meta_year, years, model)
    _after(panel, expected, naive, y, meta, meta_year, years)
    cheap = _before(panel, dates, x, y, meta, meta_year, years, feats, beta, mom, args)
    if args.overlay:
        _overlay(store, panel, dates, cheap, args.book_since)
    if args.leg:
        _leg(
            store,
            panel,
            dates,
            x,
            y,
            meta_year,
            sorted({d.year for d in dates}),
            feats,
            implied,
            args,
            available_dates=[m[3] for m in meta],
        )


if __name__ == "__main__":
    main()
