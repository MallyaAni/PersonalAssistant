# Fifteen-minute entry comparison — frozen specification, 2026-09-22

Status: preparation only. No candidate historical outcomes have been scored.
Implementation base: aa73e5d (entry engine at1a2c2c1, personal boundary at95ee6fa).
VERIFIED: causal entry engine and personal/paper separation have focused tests.
FAILED: final worker boundary defects were reproduced and corrected by root.
UNVERIFIED: historical eligibility, comparison outcomes, live deployment and fills.

## Objective and acceptance

Compare the fixed reclaim candidate with the incumbent price-entry component on
identical causal observations and eligibility. Preserve unchanged production
momentum and separate paper accounts. No fitting, coefficient search, repeated
baseline runs, paid data or UI changes. A superior result is not assumed.

Before historical scoring, root must approve input provenance and the evaluation
implementation against synthetic acceptance cases. Report insufficient coverage
as insufficient evidence; do not manufacture eligibility from today's universe.

## One fixed daily-level mapping

The engine previously accepted supplied levels without fixing their origin. This
specification closes that gap before observing outcomes. Use the most recent20
completed daily adjusted closes strictly before the evaluated session. Require
finite positive prices, ordered unique dates, a finite positive prior-session
adjusted/raw close ratio and nonzero population standard deviation. Future daily
observations are removed before value validation. Insufficient history is unavailable.

With mean m, population standard deviation s, conversion factor r equal to the
latest prior adjusted close divided by raw close, supply raw-price levels:

- reference retest level: (m + 2*s) / r;
- entry level: (m + 2*s*paper.ENTRY_BAND_Z) / r;
- invalidation level: m / r.

The20-observation two-sigma band and incumbent ENTRY_BAND_Z=1.10 are existing
source conventions. The mapping is one new, unproven hysteresis hypothesis,
fixed for the entire session. No alternate widths or invalidations will be tried
on the same outcomes. It does not establish an optimal pullback depth.
Sessions with unhandled corporate-action scale changes must not be scored until
the daily/raw intraday adjustment provenance resolves them.

**Units clarification after input audit, before outcomes (2026-09-22):** cached
Alpaca history was fetched with adjustment=all and matches adjusted daily prices
in reviewed examples. The raw-input formulas above must not be applied directly
to those bars. A caller must declare raw or adjusted price basis. In adjusted
mode the levels stay m+2*s, m+2*s*ENTRY_BAND_Z and m; the incumbent appends the
adjusted intraday close without multiplying by r. In raw mode the original
conversion remains. Unknown/mixed basis blocks scoring. Require explicit output
basis and scale-equivalence tests; no silent relabelling or cache rewrites.
This corrects units without changing the band rule or choosing parameters from
outcomes. Cross-provider adjustment compatibility is still an evidence gate.

## Incumbent comparator and common eligibility

Reproduce the current price-entry component by calling the existing bollinger_z
on the last19 prior adjusted daily closes followed by the current completed
intraday close times r. Do not substitute a frozen prior-day band for the
incumbent's recomputed band. Use the existing entry_action gate and its current
threshold, grade requirement and rejecting-band flag, with the same supplied
holdings/name cap if a portfolio is evaluated.

The reclaim candidate must pass those same common eligibility gates, including
available timing/grade evidence. Eligibility or gate inputs must carry when they
became available. Unknown eligibility blocks a recommendation; an observation
whose eligibility was learned later cannot be retroactively enabled. Do not use
future full-session completeness or later bad prints to reject earlier prefixes.

Use the saved record's actual written time, not its session label: the09-14
record was written09-15 at10:18:21 New York and was unavailable at that morning's
open. Outcome horizons count trading sessions after the actual entry session;
an09-08 entry has a20-session exit on10-06, not a clock starting on09-04.

A historical run with only prior-night grades is a comparison under fixed
prior-night eligibility, not an exact reconstruction of live intraday reranking.
A price-only run must be labelled a component diagnostic, never a live strategy
backtest. Document which of these the available evidence supports before running.

## Events, execution and evaluation

Decision time is each completed15-minute bar end, regular full sessions only.
Exchange-calendar early closes must be excluded using a known schedule before
outcomes, not inferred from missing later bars. Partial, stale, missing, duplicate
or corrupt observed prefixes cannot recommend; unseen future corruption must not
alter an earlier result. Use the reviewed entry engine unchanged.

Record both raw readiness observations and first accepted entry event per
symbol/session for each method. Dedupe on method/symbol/session: repeated refreshes
and repeated ready bars are not additional trades. Retain signals that later
invalidate; never erase an earlier observation using its later outcome. This
event diagnostic is not a portfolio churn estimate; multi-session holdings and
cash require a separate common ledger before any portfolio-performance claim.

Primary execution proxy: next consecutive regular-session bar open after the
signal confirms. This assumes zero processing latency at that boundary and is
not a verified executable fill. Missing next-bar observations stay missing and
are counted, not silently removed. Zero added costs is the user's research
scenario. Historical bars cannot prove midpoint fills or limit-order acceptance.

Primary holding horizon for the portfolio-entry diagnostic:20 trading sessions,
matching the incumbent breakout horizon. Secondary precision diagnostic:5
sessions. Report both exactly as declared, with no horizon selection afterward.
Report event frequency, repeated readiness, missing execution/outcome coverage,
paired opportunity coverage, entry-price differences where both act, forward
return, adverse/favorable excursion and opportunities missed by waiting. Missing
or immature labels do not delete decision records. Use common opportunity
denominators; a rule that enters less often cannot win just by dropping difficult
observations. Correlated events must not be described as independent evidence.

The record archive may not support mature20-session outcomes. If so, report that
limitation; do not shorten the primary horizon to obtain a flattering result.
Retrospective results on previously inspected data are research diagnostics.
New forward evidence is required before adoption or a claim of superiority.

## Current implementation boundary

The first comparison worker implements only a pure causal adapter and synthetic
tests. No historical scoring, order placement, production wiring, persistent
personal acceptance state or portfolio simulator is part of that worker's scope.
Root owns this specification; changes require an explicit documented rationale
before outcomes. Separate evidence audit owns only its report.
