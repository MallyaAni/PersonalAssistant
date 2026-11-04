# Candidate: report-bound leader live path (`grade-led-leader-weight/3`)

The installed `grade-led-leader-weight/3` release admits the leader rule through
the learned monthly generation: a holding model, an execution timing
publication and a residual month, all fitted on 2026-10-01. That generation
expired on 2026-11-01, and both the 2026-11-02 and 2026-11-03 nightlies refused
before any account effect with `Current causal timing publication required`.
There is no monthly producer and no original input snapshot on this host, so the
generation cannot be refitted locally. The `/3` forward record has zero
completed sessions.

This candidate changes the live input binding only. The approved `/3` contract
already says the leader rule does not read the learned scenario distribution or
the learned fifteen-minute timing; the monthly artifacts are a vestigial
requirement of the `/1` path the leader rule inherited. The leader live path
now binds the authenticated nightly report to the installed risk bank's
calendar prefix and symbol universe, keeps the installed timing configuration
hash and the funded policy's paper-broker guards, and never loads the monthly
holding model, execution publication or residual month.

## What changes

- `backend/market/report_holding.py` (new): a report-bound reader that exposes
  the report's dates and symbols, the same close-window clock guard as the
  learned close, and a byte-level report comparison. It refuses the learned
  distribution rather than fabricating one.
- `backend/market/learned_live_holding.py`: `prepare` routes only
  `leader.POLICY` through the report reader; `_timing_config` binds the
  installed timing configuration bytes without loading the monthly artifacts.
  `/1`, retained and timed policies keep the original `_timing`, `_model_report`
  and `ForwardVolatilityHoldingReader` path unchanged.
- `backend/market/joint_funded_policy.py`: accepts `ReportHoldingReader` on the
  funded path and skips the market-conditioning wrapper for it. The leader
  policy already overrides every risk read.
- `backend/market/strategy_publication.py`: publishes a report-based snapshot
  for the report reader. It records `report_context` (data as-of, daily
  publication, grade hash) and no fabricated features or model receipt.
- `backend/market/strategy_model_allocation.py`,
  `backend/market/live_model_decision.py`,
  `backend/market/strategy_entry_context.py`: the learned-close readers refuse
  a report-based record with a clear `ValueError`; their API callers already
  degrade to an unavailable view.
- `backend/cli/market_daily.py`: the close-window and broker guards accept the
  report reader.

## What does not change

The economic rule is byte-for-byte the `/3` rule: entry at A or better, held
while A, exit below A, 1% minimum trade, 63-session leader tilt 0.5, EWMA-20
volatility target 0.25 with exposure floor 0.5, 25% per-name cap, P/E tilt off,
valuation analyst at three votes, next-open execution. No new fit, no new
model publication, no parameter change. `grade-led-leader-weight/3` remains
the policy version.

## Bound sources changed

Eight entries in the 45-source identity change: the seven files above plus the
new `backend/market/report_holding.py`. The other 37 entries are unchanged.
`docs/research/grade-led-leader-weight-contract-2026-10-21.md` is unchanged:
the contract already describes the leader rule without the learned
distribution, and the live path now matches it.

## Known degradations

The learned intraday entry display (`strategy_entry_context` /
`strategy_entries`), the saved model-decision view (`live_model_decision`) and
the account-independent model allocation reader (`strategy_model_allocation`)
cannot authenticate a report-based record and report unavailable. The nightly
trading path is unaffected. `execution_reconciliation_audit` will not link a
report-based admission to a learned close.

## Known-stale caveat

The 17.1% A-cut cited when the leader rule was installed is stale
(2026-10-21 code) and remains retired. It is not cited by this candidate. The
current-code honest-universe readings are in
`docs/research/simplicity-ablation-results-2026-11-03.md`: 13.28% CAGR,
-34.39% median drawdown, -39.42% worst drawdown, 0.816 Sharpe, 8.44x turnover
at 25 bp.

## Acceptance

Targeted gate: `test_grade_led_leader_policy`, `test_learned_live_holding`,
`test_strategy_publication`, `test_grade_led_policy`,
`test_joint_funded_policy`, `test_learned_holding_transition`,
`test_market_release_admission`. Full unit gate on a fresh `anios_gate` must
pass before installation. The release ceremony installs under the paper lock,
records the actual `approved_at`, and admission must be ADMITTED. The first
ordinary nightly after deploy must complete with the report-bound reader, and
the `/3` forward record starts with that session.

Owner authorization: 2026-11-04, the incident note's option 1 — simplify the
live path to match the approved `/3` contract, keep the installed risk bank and
report validation, and install through a new release.
