# Direction-isolated entry decisions

Before results: reuse the original frozen sequential model, not the best of the
later regressors. Its buy-only intervention changed both earlier and later
actions simultaneously and lost 11.0333 percentage points at the median phase.
Determine which direction accounts for that failure in two disjoint tests.

Advance: allow an earlier learned buy, but never delay an incumbent crossing.
Defer: retain the incumbent gate, but delay a crossing when the model forecasts
that waiting is better. An unavailable forecast uses the incumbent. Both arms
retain original sells, quantities, morning cash budget, same-session terminal
attempt, unsupported sessions and zero costs. No refit or threshold search.

All twenty phases, all/early/later/reused-recent windows and recorded ledger
audit are required. Report both arms. A favorable arm remains development
evidence and requires exact live-path validation before production adoption.
