# Pre-registration: SUE coverage audit on the honest PIT universe

Written 2026-10-29 before any run of the audit. This is the C4 data audit from
`top-tier-algorithms-2026-10-28.md`: it measures whether the store's filing data can
support a post-earnings-surprise (SUE) signal on the honest point-in-time universe. It
is a coverage audit, not a performance test. No rank-IC, return or trading result is
read here, and no live rule changes.

## Question

For each year 2016-2023 (the choosing window) and 2016-2026 (reported), how many honest
PIT S&P 500 names have quarterly earnings filings with a filing date, a seasonal pair
(the current quarter against the same fiscal quarter one year earlier), and enough prior
seasonal changes to standardize the surprise? The denominator is every PIT member in the
year, including names with no usable filing.

## Data

- PIT cache: `~/dsv41/pit2/cache.npz`, the frozen S&P 500 point-in-time cache used by
  C1-C3 and the risk dial. `member` is the session-level membership matrix; 532 tickers,
  2,970 sessions 2015-01-02..2026-10-23; 343-502 members per year.
- Filings: the store's `edgar_facts_versions` frames
  (`~/deploy/anios/data/market/edgar_facts_versions`), read with
  `fundamentals_asof.versions_from_frame`. Primary earnings: `net_income`
  (`NetIncomeLoss` and its fallback tiers); secondary: `eps`
  (`EarningsPerShareDiluted`/`Basic`). Quarter spans only (`span_kind == "quarter"`,
  80-100 days). A version is usable when the value is finite, the period end is
  present, and the filing date is present; the decision date is `Version.available`
  (the first session the filing was public under the store's conservative rule).
- Deduplication: for each (ticker, period end, name), keep the earliest `available`
  version — the original filing, not a later amendment. A later amendment does not
  create a new observation.

## Definitions

- A quarterly series is the deduplicated `net_income` (or `eps`) quarters sorted by
  period end.
- A seasonal pair at quarter q is q and the quarter whose period end is 350-380 days
  earlier.
- A prior seasonal change is a seasonal change at an earlier quarter in the same
  series.
- Tier 0: at least two quarterly filings with usable earnings (the literal "two
  consecutive quarterly filings").
- Tier A: a seasonal pair exists.
- Tier B: a seasonal pair and at least 2 prior seasonal changes (a standard deviation
  is computable).
- Tier C: a seasonal pair and at least 4 prior seasonal changes (the usual 8-quarter
  SUE denominator).
- A name counts in a year if it is a PIT member on the first cache session at or after
  the current quarter's `available` date, and that session is in the year. The same
  name counts once per year even with several observations.

## Reported statistics

- Per year 2016-2023 and 2016-2026: PIT members (union in the year), names with any
  quarter, tier 0/A/B/C counts and shares; net-income-only and EPS-only counts; names
  with no quarterly filings.
- Per name: first and last usable quarter, number of quarters, number of seasonal
  pairs, tier. Names in the PIT universe with no frame, no quarter, or no seasonal
  pair are listed.
- Coverage by sector (the cache's sector column) for the tier C names, to show whether
  the gap is concentrated.
- The share of PIT members with tier C in each choosing-window year is the headline.

## Adequacy bar and stop conditions

- Adequate if, in every year 2016-2023, at least 150 PIT member names have tier C and
  at least 250 have tier A. The rank-IC study would then have a cross-section of at
  least 150 names per year.
- If a year is below 150 tier C but at least 200 tier B, the audit reports that a
  2-prior-seasonal-change denominator would cover it; that is a different SUE
  definition and needs its own pre-registration, not a silent substitution.
- If the audit is below the bar, record the gap and do not run the rank-IC study. Do
  not force the signal, do not use today's fundamentals for a historical decision, and
  do not fill missing quarters.
- If the store is missing frames for more than 10% of the PIT names that were members
  in 2016-2023, stop and report the data gap before the counts.

## What passing buys

Only a pre-registration for the rank-IC study at 20 and 60 sessions, by year, with a
placebo; no trading rule, no live use. The audit itself makes no performance claim.

## Look-ahead

The audit uses filing dates and period ends only; no price data. A name is counted only
if it is a PIT member on the decision date. The audit does not read any return.
