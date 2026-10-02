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
