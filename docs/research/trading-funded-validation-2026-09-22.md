# Funded allocation implementation and fixed evaluation — 2026-09-22

Status: experimental source, not adopted or deployed. No real orders, model-service
changes, training, paid data, frozen-history rewrites or dashboard changes.

## Implementation evidence

Paper and simulation share the allocation decision and cash-funded order planner.
Decisions use close-time information and fill at the following open. Purchases
cannot spend same-session sale proceeds. Fees, shares and cash reconcile against
actual fills; whole-share paper orders explicitly report unexecutable residuals.
Legacy callers keep their defaults; the funded paper path remains opt-in.

Review reproduced and corrected these boundaries:

- Pending orders could replace a deliberate empty selection; retry now preserves
  it. Empty selection remains cash even when research index eligibility is true.
- Risk cuts could round to zero or below the required reduction. Binding cuts and
  company-cap trims round up, bounded by whole shares actually held.
- Explicit company exits survived neither missing policy evidence nor a later
  selection refresh. Exclusions persist in saved paper state and across simulator
  refreshes; both exclude the departed holding before fallback risk limits.
- A stale external NAV could double an order while the displayed allocation used
  actual NAV. Paper now sizes and reports against the same marked holdings plus
  cash; invalid or empty account evidence blocks explicitly.
- Funded sells could still route to close or be canceled on a green opening.
  Next-open timing survives pending-state persistence and dispatch.
- Evaluation used same-close exposure controls, planned exposure, and incomplete
  trace checks. It now uses verified adjusted opens, observed exposure, chronological
  cash/share/fee checks and correctly aligned/censored exit diagnostics.

New lifecycle tests read saved state back, settle/retry orders and exercise the
local broker queue. HTTP tests exercise the real decision route with isolated
account fixtures. They do not prove deployment, actual broker execution, or model
behavior. No prompt or router changes are part of this work.

## Frozen evaluation

2016-01-04 through 2026-09-18: 2,693 NAV observations / 2,692 returns. NAV1,
next-open execution, 10bps per side, zero cash yield, explicit hypothetical SPY
eligibility. Both SPY and QQQ are dividend-inclusive funded benchmark accounts.
No fitted parameters, threshold search, window selection or baseline recomputation.

| Account | CAGR | Maximum drawdown | Rolling annual windows meeting both objectives |
| --- | ---: | ---: | ---: |
| SPY | 15.07% | 33.72% | — |
| QQQ | 20.07% | 35.12% | — |
| vol | 22.01% | 24.59% | 34.08% |
| vol_trend | 16.78% | 15.30% | 26.34% |

The objective is higher compounded return and no larger maximum drawdown than
each benchmark. `vol` meets it over the full period; `vol_trend` fails QQQ's
return. The 2,441 rolling windows overlap and are not independent trials.

Predeclared **25bps stress**, including the same cost convention for benchmarks:

| Account | CAGR | Maximum drawdown | Rolling annual windows meeting both objectives |
| --- | ---: | ---: | ---: |
| SPY | 15.06% | 33.72% | — |
| QQQ | 20.06% | 35.12% | — |
| vol | 20.13% | 25.72% | 25.44% |
| vol_trend | 14.82% | 15.77% | 22.53% |

Vol's full-window return margin over QQQ shrinks to approximately 0.08 percentage
points per year. This is a fragile result, not grounds for adoption.

At vol's 58.47% average observed equity exposure, the hindsight constant-exposure
SPY and QQQ controls have drawdowns of 21.20% and 21.61%. Vol earns more but also
draws down more than these controls. The difference includes stock selection and
timing; it is not isolated timing alpha or an executable hindsight strategy.

## Provenance and practical limits

Spark1 artifacts:

- `/tmp/codex-mac-evaluation-reviewed-20260922/`: fixed evaluation, complete
  traces, source/input hashes captured before execution, candidate NAV arrays.
- `/tmp/codex-mac-cost-stress-20260922/`: predeclared stress and script/source/input
  hashes; script `/tmp/codex-trading-cost-stress-20260922.py`.
- `/tmp/codex-mac-controls-20260922/`: adjusted opens, cached parquet/input hashes,
  independent benchmark reproduction to 1e-12 tolerance.
- `/tmp/codex-trading-evaluation-inputs-20260921/`: original read-only inputs.
  Report SHA256: `d6f8fe0cbf74e7318352b8e9c02910cae00164a2a4900be6a8e24a9960401c26`.

The reviewed 10bps candidate NAV/return/exposure arrays exactly match the
preliminary arrays already checked by the independent scorecard. Later paper and
whole-share-only corrections do not affect these fractional NAV1 simulations.
The artifacts identify the precise measured source; they are not silently
relabeled as a later revision.

All this history is reused and survivor-biased. It is not an untouched holdout,
point-in-time historical membership, a future drawdown guarantee, or proof of a
universally best implementation. Production adoption remains unverified.
See [the primary-paper review](trading-ml-path-2026-09-22.md) for a single
prospective research specification; it authorizes no training or live adoption.

Diagram impact: none; the existing trading boundaries and stores are retained.
