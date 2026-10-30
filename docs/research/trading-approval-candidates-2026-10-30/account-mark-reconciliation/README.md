# Candidate: reconcile broker mark rounding in the funded account guard (no rule change)

The ordinary nightly plan was refused on 2026-10-29 because broker equity
(85,661.85) sat $8.72 below cash (43,910.22) plus the quote marks of the held
positions (41,760.353), a 1.0 bp difference between two separately fetched
broker snapshots. `joint_funded_policy._account` refused any excess over
1e-10 of equity, so even a sub-cent rounding difference was enough to block
the installed `grade-led-leader-weight/1` plan and the board
(`joint-funded-unavailable`, `GRADE PARITY MISMATCH`).

The guard now reconciles quote marks to the equity the broker reports inside a
declared 10 bp tolerance (`MARK_RECONCILIATION_TOLERANCE = 1e-3`), scaling the
marked positions so funded weights still sum to one for the optimizer's own
`current.sum() + cash_weight <= 1 + 1e-10` check. A disagreement larger than
10 bp of equity still returns `inconsistent_account_equity`, and cash above
equity still refuses. No rule, sizing, timing, model, cost or execution
parameter changes; the account simulator is untouched.

Bound source changed (1): `backend/market/joint_funded_policy.py`.

Targeted tests: `backend/tests/test_joint_funded_policy.py` 36 passed,
including the 2026-10-29 numbers reconciled with weights summing to one and a
29 bp disagreement refused. Adjacent funded and grade-led suites pass apart
from pre-existing `fastapi` import failures in the research virtualenv.
