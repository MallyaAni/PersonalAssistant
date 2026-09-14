# Dated decisions and forward evidence

The user authorized all five enhancements, commits and deployment. Started clean
on main `3e0337d3`; origin/main was current. This adds a plan-action view and a
research evaluation path, without promoting an intraday execution strategy.

Each action binds to the desk session, record timestamp, account equity and
saved shares. Expired quotes or technical inputs remove eligibility on screen.
Quote checks refresh every 15 seconds while visible; technical observations
remain on the existing 15-minute collector. Grades combine existing analyst
evidence, not every quote tick. Position percentages use the quoted midpoint
when available, which is not an executable valuation. The action is for the
adopted scheduled plan, not a new buy-now signal.

Execution evidence requires an open broker clock, positive displayed sizes, a
non-crossed consolidated quote younger than 30 seconds and a spread no wider
than 25 basis points. These predeclared quality filters are not optimized return
signals or proof of sufficient depth. September 14 read-only probes returned
SIP HTTP 403 and IEX HTTP 200. IEX is identified and cannot establish buy
eligibility. SIP entitlement is retried after five minutes; no purchase occurs.

Candidate version 2 records all graded names' existing entry states, quotes and
a correlation-cap challenger: 60 return observations, at least 40 common finite
observations, connected correlations at least 0.8, and a 30% gross cluster cap.
Weights only shrink; released exposure stays cash. These explicit research
parameters have not earned adoption. Existing DeepSeek economic judgments remain
inputs; no new model prompt was introduced. Re-entry research remains the dated
comparison in `fomc-restoration-2026-09-14.md`, which did not justify promotion.

Archives freeze the first decision per version/session/bar; evaluation separates
exact policy hashes. Grade outcomes take the first daily signal and a later
observed entry close before expiry, then the first close at or after the matching
time five or twenty trading sessions later. Wait signals are included; missing
data stays missing. Grade outcomes subtract SPY total returns and an additive
10/25 bp per-side cost allowance. Portfolio trackers deduct costs from each
modeled trade, use later closes and cash-funded whole-share buys, and model
reductions. They are not the full scheduled strategy or actual executions.

Recorded splits adjust shares and dividends accrue on ex-dates. Same-date splits
precede dividends, interpreted per post-split share. Receivables count in value
but cannot fund buys because pay dates are unknown. Merger, spinoff, tax and
cash-in-lieu accounting is absent. Reports require action files and complete
daily coverage for every symbol; later observations await daily validation.
These are research results, not audited brokerage returns. Reports cache for up
to 60 seconds and withhold archives above 10,000 records.

Uncertainty uses non-overlapping date cohorts, not simultaneous stocks as
independent trials. Twenty cohorts are required for an approximate normal 95%
interval. Intervals are descriptive, not proof of independence or calibrated
probabilities. There is no automatic promotion path.

Acceptance requires quote and context gating, unchanged files after HTTP
preview, known later-price and corporate-action outcomes, browser expiry and
empty-data behavior, and authenticated public browser verification of the
deployed source before calling the changes live.
