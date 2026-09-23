# Fixed conditional entry diagnostic — first result

**Insufficient evidence to adopt the candidate.** This run has no paired entries,
only one candidate entry, and five incumbent entries. It measures a fixed price
component under assumed common eligibility, not the live portfolio strategy.

Source checkpoint `98bd6c10aae552b76cdd4ebaeed9a6787b2dd094` passed86 targeted
checks (including unchanged2 root acceptance cases and26 incumbent parity cases),
Ruff/format and scoped strict mypy. Test log:
`/tmp/codex-single-source-integrated-20260923.log` (16 known synthetic short-panel
NaN warnings). No source deployment occurred.

One real-data run at2026-09-23T02:57:39Z, following the frozen single-source
protocol. Artifact `/tmp/codex-single-source-diagnostic-20260923.json`; compact
log of the same name ending `.log`; driver
`/tmp/codex-run-single-source-diagnostic-20260923.py`. Do not rerun unchanged.
Snapshot SHA256 `ae25a49bb0a4b00ecc535bf9e46adedb59e4df3c51b53234799ad353fd083f9f`.
Artifact includes exact source revision, calendar hashes, provider fetch time,
per-source page hashes, all requested opportunities and reasoned missing inputs.

| Coverage / event | Count |
|---|---:|
| Requested symbol/session opportunities |204|
| Ready on common inputs |170|
| Unavailable (WRB missing prior-session coverage) |34|
| Both methods entered |0|
| Incumbent only |5|
| Candidate only |1|
| Neither |164|

Repeated readiness126 was deduplicated into six unique method/symbol/session
events. It does NOT mean126 actual trades prevented. Missing executions and
missing/immature labels among these six actual events are zero. Later sessions
without events have no-event labels, not invented outcomes.

| Method | Name / date | Observed NY time | Next-open proxy |20-session return |5-session return |
|---|---|---|---:|---:|---:|
| Incumbent |AVGO08-04|09:45|409.87|-9.9617%|+1.3151%|
| Incumbent |AVGO08-05|09:45|422.70|-13.2245%|-1.7956%|
| Incumbent |AVGO08-06|10:15|425.24|-16.1556%|-1.9377%|
| Incumbent |SPY08-04|10:15|762.96|-0.4220%|+0.7405%|
| Incumbent |SPY08-05|09:45|774.68|-1.4780%|-0.5228%|
| Candidate |SPY08-07|11:30|771.80|-0.4574%|+0.3343%|

WDC/APTV/QQQ supplied34 ready cases each but no entries; WRB remains in the
requested denominator. The incumbent's five conditional20-session returns average
-8.2484%; candidate's one is-0.4574%. These are DIFFERENT event sets, overlapping
horizons, unequal samples and selected names; their difference is not alpha,
a paired estimate, portfolio P&L or a win. All five incumbent-only outcomes were
negative at20sessions in this cohort; that does not establish a useful waiting
policy outside it. Relative paired entry-price improvement is unavailable.

Daily references and entries use the same fresh adjusted IEX15m snapshot; fixed
grade A/nonrejecting at each open is assumed for BOTH methods. Live grade refresh,
actual cash/holdings, within-account turnover and midpoint fills are not measured.
No thresholds, cohort or dates were changed after outcomes. Keep incumbent live;
the candidate remains experimental. Further adoption evidence must include actual
dated eligibility and enough independent opportunities, not repeated runs or
tuning this sparse diagnostic until it appears favorable.
