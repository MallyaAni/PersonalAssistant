# Reporting-period eligibility for fundamental grades

## Connected policy and scope

`fundamentals-features/3` is an explicitly selected reporting-period safeguard,
not a replacement accounting definition or a qualified investment model.
`market_daily` opts into `desk.run(..., fundamentals="current")` for new records.
The generic `desk.run` and read-only `market_desk` defaults stay pinned to
`corrected` (`fundamentals-features/2`); the CLI exposes `--fundamentals current`.
Existing research callers, saved records and performance artifacts retain their
original identities. Execution policy `cash-bounded-breakout-rotation/3` is a
different version namespace and is unchanged.

The original feature calculation is preserved. An opt-in wrapper finds the
latest valid, decision-available reported revenue end across recognized revenue
tags. It admits quarter, YTD and annual spans without claiming a quarter can be
derived. Values must be finite, spans supported, and fiscal end no later than
filing date. Present acceptance times must be timezone-aware and cannot precede
the fiscal end on the New York calendar. The original availability rule applies;
impossible early acceptance is refused, not repaired by postponing it.

Every finite scored **and cited** feature must end at that reference period.
Older values become missing before cross-sectional ranking. No replacement
amount is borrowed from another concept; no gross profit, currency conversion,
quarter or absolute-age cutoff is invented. Original input ends and rejection
reasons are retained separately from the withheld output dates.

The new analyst checks named tensor alignment and period/status consistency
before assigning its source identity. Reordered but consistently named features
serialize correctly. Malformed dates, shapes, names or statuses are refused.

## Votes and records

The prior persistence rule could retain a bullish or bearish vote for two
sessions after its score became unavailable. The new policy resets both the
held vote and its confirmation count whenever:

- no score can be formed from eligible ranked inputs; or
- any previously accepted **scored** leg becomes rejected, even if other legs
  still provide a finite score.

With the default three-session rule, a reset starts confirmation from that
session's eligible raw stance. A recovered input cannot restore the old vote.
Losing a context-only metric does not reset a valid score. The generic reset
mechanism is optional; previous analyst behavior is unchanged when not selected.

New records retain `fundamental.dates` and an `eligibility` entry for every book
name, including unscored names, excluding the benchmark. Each entry records the
revenue reference end, score availability, reset status and per-feature original
end/reason. Source mismatches are refused. Tests save and read back actual files
and verify that an earlier `/2` record's bytes do not change.

The dashboard explains these checks in both evening-evidence views, with original
dates and plain exclusion reasons. Older and unknown sources are not upgraded;
missing or contradictory metadata cannot imply a pass, score or vote. Passing a
period check does not establish fair value, financial completeness, data
freshness or that the feature established a persisted vote. Funding assumptions
and fundamental-source warnings remain independent.

The simulation summary treats three identities independently: execution policy,
fundamental calculation and funding model. An older fundamental source cannot
hide a recorded cash-at-fill limit. Missing or unrecognized funding cannot be
described as either cash-capped or borrowing. Missing or unrecognized execution
policy cannot be called an earlier policy merely because it differs from the
current one. The expanded assumptions and summary use the same funding meaning.

## Retained SEC evidence

All 94 unchanged September 25 company-facts bodies were processed offline by the
real feature, analyst and record-block functions. The original `/2` scalars match
the earlier hash-bound diagnostic exactly. Every accepted `/3` scalar remains
identical; missing values never become finite. This is one current-source
session, not a historical policy run or a full combined-grade measurement.

| Result | Previous `/2` | Period-checked `/3` |
| --- | ---: | ---: |
| Finite feature cells | 602 | 424 |
| Names with a fundamental score | 89 | 64 |

178 older-period inputs are excluded across 33 companies. Of the 94 F score
outputs, 25 lose finite scores and 63 change through cross-sectional reranking;
one finite score remains identical. These changes are not evidence of better
returns or of a particular combined grade.

- AAPL: June 2018 inputs lose eligibility against June 27, 2026 revenue evidence.
- ORCL: May 2022 inputs and May 2018 gross margin lose eligibility against
  August 31, 2026 revenue evidence.
- AMZN: September 2009 gross margin, March 2017 capex and June 2018 remaining
  inputs lose eligibility against June 30, 2026 revenue evidence.
- AAOI: six June 2026 values remain identical; March 2026 capex is excluded.
  Its F score changes from 0.7207555482774217 to 0.7047258297258296 through
  reranking, not because capex is scored. This is not intrinsic fair value.

All 94 names survive the real record-block writer and strict JSON roundtrip.
The final root comparison, after contract validation was strengthened, is
`/private/tmp/anios-current-path-root.H5cS5W/final-current-94.json`, SHA256
`ac3f4d9e1f397653e32457ca3fd718c16c3defdf11af99f69b138e27473a880a`.
It binds all source and body hashes before/after the run. The original manifest
is `f0b5cc2e0540f35f10c7bf8ecbb6132f8c102af3432f84ef99e4851a0722021b`.

## Verification and limits

Root backend acceptance: 495 passed, one optional missing-Torch skip, four
retained strict known-defect xfails, 32 existing short-panel/numerical warnings.
Independent review: 258 passed, no failures/skips. The reset-only differential
matches the original function over 45,927 no-reset comparisons. Original feature
functions and previous analyst runtime ASTs are unchanged.

Fail-before evidence is retained: three feature-policy failures and nine
connected-path failures. The first connected fixture lacked a second ranked
company; it was corrected before implementation. Review found name/date/shape
contract gaps, now covered by 16 independent tests. Test-only missing themes and
temporary-directory setup errors were corrected without loosening assertions.
The first broad browser run found a real regression: an older-fundamental warning
hid the separate cash-capped funding explanation. That assertion was retained.
The strengthened matrix also exposed unsupported borrowing labels for absent
and unknown funding, and unsupported age claims for unknown execution policies;
the replacement wording is pinned across independent source combinations.
Final browser acceptance and publication are recorded in `NEXT_SESSION.md`.

This is a connected suppression safeguard, **not completion of the current
financial-input migration**. Unitless stored versions, legacy annual-partition
defects, definition comparability and true historical publication remain open.
The retained packet has no exact acceptance timestamps. Qualified newer revenue
definitions and same-interval, unit-preserving inputs must still be connected.
No new acquisition, fit, historical strategy rerun, orders or holdings changes
are part of this checkpoint. Neither `/3` superiority versus SPY/QQQ nor fresh
all-hours coverage is established. Deployment remains separately gated on Spark.

Diagram impact: NONE — internal calculation, optional vote resets and existing
record/UI fields; no new component, dependency, store or trust boundary.
