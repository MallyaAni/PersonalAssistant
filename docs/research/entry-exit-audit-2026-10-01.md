# Recorded entry timing audit

Objective: isolate timing validity from stock selection. The current rule keeps
a witnessed 1% dip/pop trigger active after price recovery. That is intentional
policy behavior, not evidence that the current price is still a favorable entry.
No model, grade threshold, timing level, portfolio policy or live activation was
changed in this task.

## Correctness findings and correction

On main `d9c30a29`, the shared timing reader could authorize a market order from
a future, incomplete, wrong-session, off-grid or non-crossing latch. A completed
candle whose receipt was still in the future also counted. The latch writer
could persist a future snapshot's opening price and contaminate later decisions.
These were reproduced against actual `intraday_orders.decide` and the personal
board, not a substitute decision function. Ordinary provider regular-hours
filtering already protects some malformed cases; occurrence in actual submitted
orders has not been established.

The correction checks both completed regular-bar time and observation time,
including actual crossing prices. It records `open_seen_at`, opening-bar receipt,
`history_started_at` and first-trigger revisions. A late-arriving earlier candle
can no longer erase the trigger available in an earlier prefix. Existing valid
latched triggers still survive recovery; this is not a stealth policy change.
Legacy files are not rewritten or given invented receipt times. Revision history
starts when the new writer first observes the row, not at an inferred past date.

Original test fixtures needed valid receipt times and actual crossing prices.
All their assertions remain intact. No real orders or account writes were made.

## Frozen evidence and limits

The read-only export contains 172 original research decisions across eight
observed sessions, September 14–October 1, 2026, and four final daily latches.
It retains source hashes, original publication/bar/deadline timestamps, nightly
and intraday grades, prices, states and pauses. These are archived research
observations, not recordings of every personal account action. The cutoff is
October 1 at 23:59:59 UTC. Prices and session levels are raw, within-session
comparisons; no split/dividend conversion or later-price calibration is used.

Frozen input on Mac and Spark:
`/tmp/codex-entry-timing-audit-inputs-20261001.json`, SHA256
`731809a94a500eb6b36cf6b31395f6892136a57e0c3cb8b91299202ddeca2a3e`.
No provider requests, model calls or history rewrites were needed.

Source-bound result: `/tmp/codex-entry-timing-audit-results-checkpoint-20261001.json`,
SHA256 `18bce65d255d1d41f44cdc7e5f52cbaf6c09065ea9ee3437bf55fa1c255d3d8e`.
This artifact pins both replay modules by byte hash. A history-completeness
correction was checked against the first diagnostic; every frozen result stayed
identical. No economic evaluation, model sampling or old baseline was repeated.

The strict audit retains **16,224 stock observations, 95 stocks and 10 original
policy-hash groups**. Missingness is material: 12,994 observations have no latch,
2,930 have no recorded opening receipt, and 300 have indeterminate prefixes.
There are **zero fully verified timing prefixes** in this legacy export. A final
latch with a future first-trigger receipt cannot prove that no other crossing
was known earlier; unavailable prefixes stay explicit.

A separately declared conditional diagnostic assumes the archived session open
was known after its first completed opening bar. This is an assumption, not
proven receipt evidence. It retains 1,942 conditional observations; another 988
lack opening-bar evidence. The other missing/indeterminate counts stay unchanged.
Statistics stay within each original source-policy group, never pooled as one
strategy performance series.

| October 1 research policy hash suffix | Grade-eligible triggered observations | Recovered observations | Recovered stock/session pairs | Median recovery above buy level | Maximum recovery |
|---|---:|---:|---:|---:|---:|
| `017e7c5d` | 12 | 4 | 2 | 2.81% | 4.72% |
| `351bac75` | 126 | 94 | 7 | 2.41% | 9.43% |

The eligible-grade subset means original nightly A/A+ and no recorded event
pause. It does not mean a funded Buy: positions, cash, full account gates and
execution quotes are absent from this audit. Repeated observations are not
independent trades; the separate stock/session count exposes that repetition.
The later group's median trigger age among recovered observations is about
196 minutes. This supports investigating persistent permissions, not choosing a
new expiry threshold or claiming missed profits.

## Next economic test

### Fixed bar diagnostic, registered October 2 before outcomes

Test A2 and B2 from the existing scenario catalogue separately, never combine
or tune them. A2: after the first completed 1% dip bar, buy only after a later
bar closes above that dip bar's low. B2: after the first completed 1% pop bar,
sell after a later bar closes below the immediately preceding bar's low.
Each signal executes at the next bar open; absent confirmation, use the
official session close. A last-bar signal also uses the official close as an
explicit closing-execution assumption. Neither convention proves broker fills.

Use the already frozen `open-source-inputs-20261001/portfolio.npz` and its
provenance, through September 30, plus existing SIP cubes read without rebuilding.
No desk/model rerun or provider fetch. The cash accounts share current-vintage
grades, declared membership, `/5` targets at 20-session resets, daily removal
of downgraded/ineligible names, and close-sized orders. This fixed selection
diagnostic omits the live mid-cycle entry/redeploy, event-order lifecycle and
receipt latency; it is not an exact live-policy backtest. Start January 4, 2016;
report all 20 reset phases and costs 10/25 bp. Nightly cash alone funds that
session's buys; later sale proceeds cannot fund earlier or same-day entries.

Missing/incomplete/early-close cube sessions use the same explicit official-close
fallback in every timing arm and are counted separately. Require raw-to-adjusted
session scaling, immutable inputs, chronological fills, no shorting/borrowing,
future-prefix invariance and shared-ledger tests before reading real outcomes.
Primary metric: compounded funded net gain; report CAGR, drawdown, Sharpe,
exposure, realized turnover, fees and rolling wins against both SPY and QQQ.
Report 2016–20 and 2021–26 continuously, without resetting the accounts. Results
are reused-history diagnostics and cannot by themselves authorize adoption.

**Measured result:** both candidates fail this screen. The executable CLI ran
against 96 existing cubes and 2,700 return sessions, with all 20 reset phases
at both costs. At 25 bp, the median **paired** CAGR difference is −0.104
percentage points for dip confirmation and −0.020 points for the trailing exit.
They improve compounded net gain at only 7/20 and 8/20 phases respectively.
Do not compare unpaired medians to claim improvement: the identity of the
middle-performing phase differs across accounts.

| Cost | Candidate | Median paired CAGR change, all | Phases improving net gain | 2016–20 paired CAGR change / wins | 2021–26 paired CAGR change / wins |
|---|---|---:|---:|---:|---:|
| 10 bp | Dip confirmation | −0.103 pp | 7/20 | −0.072 pp / 9 | −0.018 pp / 10 |
| 10 bp | Trailing pop exit | −0.015 pp | 8/20 | +0.298 pp / 20 | −0.337 pp / 0 |
| 25 bp | Dip confirmation | −0.104 pp | 7/20 | −0.073 pp / 9 | −0.019 pp / 10 |
| 25 bp | Trailing pop exit | −0.020 pp | 8/20 | +0.298 pp / 20 | −0.323 pp / 0 |

The later-period reversal is not permission to retrospectively select regimes.
Median trailing-exit drawdown loss rises from the control's 36.95% to 37.38%
at 25 bp. At that cost the conditional control's median CAGR is 24.99%, against
SPY 15.05% and QQQ 20.29%; these are this simplified current-vintage diagnostic's
numbers, **not validated performance of the dashboard or an exact live account**.
The complete artifact includes per-phase compounded gains, CAGR, positive
drawdown losses, Sharpe, fees, realized turnover, exposure and rolling SPY/QQQ
wins. In the predeclared middle phase (10), control/entry/exit each retain twelve
missing-cube close fallbacks; cash-scaled/unfilled counts are 348/348/347.

Artifact on Mac/Spark: `/tmp/codex-entry-exit-study-reviewed-20261002.json`,
SHA256 `7882e9c41b7886408d3807aed152da099ae6bed4b662322f40cb89e7a2c50580`.
Frozen daily input SHA256
`8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58`.
It binds all cube bytes and four shared implementation dependencies. Root review
corrected an executed-fill counter that initially counted scheduled opportunities;
the exclusive second artifact preserves every economic result and source hash
from the original run. No threshold, selection rule or funding assumption was
changed after outcomes. Both original artifacts remain intact.

**VERIFIED:** 15 new tests, no skips, including actual CLI, immutable sources,
next-bar execution, future-prefix invariance, split-scale equivalence, downgrade
exits and actual funded wealth; Ruff passes. The related funding/policy subset
has 31 passes and one optional-data skip; that skipped path remains unverified.
**UNVERIFIED:** exact live parity, quote/latency/auction fills and future profit.
No live imports, policy activation, orders, data rewrites or dashboard changes.

The dependency boundary matters when deciding which earlier evidence needs
revalidation:

| Path | Relationship to this correction | Evidence status |
|---|---|---|
| Personal guidance and paper intraday submission | Both call the shared timing reader | Corrected causal cases pass; occurrence in historical submitted orders remains unknown |
| Optional native quote replay | Reuses the actual intraday decision and timing guard | 49 native/executor cases pass against main `c9f34e94`; this proves engineering behavior, not an economic edge |
| `fill_timing` convention studies | Separate bar-based pricing engine; does not call the shared reader | Results are convention simulations and cannot establish receipt-time or broker-fill fidelity |
| Daily forecast and allocation ledgers | Separate daily execution path | This defect does not by itself invalidate their numbers or certify their other assumptions |

No old result is upgraded to live execution proof by fixing the reader today.
In particular, tests with supplied valid receipt times cannot create missing
historical receipt evidence. Future observation capture and frozen input hashes
are necessary to check the affected path without inventing a past account.

Keep recorded stock selection and account funding fixed. Evaluate the existing
opt-in bounded-execution contract against the unchanged timing rule, retaining
unfilled opportunities, actual receipt times and causally spendable cash. Its
price budget and expiry must be fixed before outcomes; an urgent exit and a trim
must remain separate intents. No threshold search on these recovered examples.

The primary decision criterion remains funded cumulative net gain against the
unchanged incumbent, SPY and QQQ, with 10/25 bp costs, drawdown, turnover,
exposure and missed fills reported. This signal audit cannot produce those
portfolio metrics, a CAGR or proof of midpoint execution. New timestamped
recording closes a concrete prerequisite for that test; it does not establish
an entry/exit edge or justify adopting the candidate.

Diagram impact: NONE — existing latch metadata and shared timing validation
changed; no component, store, provider, ownership or deployment boundary changed.

VERIFIED: 296 targeted cases passed, none skipped, in the test image with the
actual branch source mounted. Both balancer tests run there; the narrow local
environment lacked `pydantic` and cannot verify those integrations by itself.
Ruff passes and all 33 registered diagrams plus the architecture page are
synchronized. FAILED on the original source: causal boundary reproductions above.
UNVERIFIED: an economic advantage, historical account reconstruction, real fill
improvements and actual submitted-order occurrence of the defensive boundary gaps.
