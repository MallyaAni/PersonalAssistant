# Sell versus retain: held-B planning contract

The archived COHR sell intent says "graded B; the desk wants the money
elsewhere". Source confirms `_downgraded`, `_paper_inputs` and reset targets
exit held B/C by grade. Execution-price improvement does not decide whether
that sale is useful. VERIFIED: grade-driven sell boundary and actual rotation
recipient/funding logic. UNVERIFIED: a learned retention model, funded benefit
and production integration. Do not infer a universal sector or thesis rule
from one stock's later price rise.

Implement a separate pure held-B planning mechanism while the new execution
model fits. A caller must supply causal current grades, membership, marks,
held shares, NAV, actual capped rotation recipient weights and stock-specific
10-session SPY-relative log-return forecasts. Those forecasts are not yet
trained by this change. No fabricated predictions or reuse of incompatible
holding-return labels. Future training must use prior-only daily features,
open[t+1] to open[t+11], monthly matured/purged outcomes and fixed source hashes;
register its concrete training/evaluation source before any economic run.

Compare plug-in projected terminal wealth from continuing to hold against
selling and purchasing the declared destination basket after actual per-side
fees. This exponentiates conditional log-return forecasts; it is not a claim
that exp(E[logreturn]) equals E[wealth]. Total funded account gain must ultimately
judge it. Cash destinations require a separately supplied SPY log forecast to
restore absolute units; no silent zero market forecast. A fully invested
replacement basket cancels the common SPY factor. Keep all recipient weights
and missing forecasts: never drop unknown names and renormalize the survivors.
No confidence/profit-distance cutoff, outcome tuning or post-result window
choice. Zero relative projected advantage uses the incumbent exit.

Retain ONLY an existing eligible B holding with positive projected advantage.
Never add shares to a retained B. C, unavailable grades/forecasts/eligibility,
explicit thesis exits and event exits preserve the incumbent sale. Buy-blocked
names cannot receive new capital; that does not itself mandate liquidating an
existing holding. Optional trim-to-existing-hard-cap behavior must be explicit.
Invalid arrays, recipient weights, fees, marks or inconsistent NAV refuse.

At resets reserve retained marked weight, then allocate only the residual to
the caller's unchanged A/A+ composition subject to its existing cap. Otherwise
the next20-session reset would silently undo retention. Helpers do not credit
sales, fund orders, invent settlement or write an account. The eventual carried
execution comparison must preserve cash and deferred purchases, both daily
rotations and resets, company/event exits and every missed intent. Existing
fixed20-session timing curves are NOT matched controls for a changed daily
selection policy. Daily next-open research can support early-close sessions;
intraday broker-clock parity needs separate actual evidence.

This change ships only the pure planner/tests, with no production import.
Acceptance: negative held forecasts can still beat worse alternatives; fee
direction; cash units; full missing-recipient rejection; no retained-B additions;
event/thesis override; hard-cap trim; reset reserve; invalid NAV/weights refused.
No automatic live promotion, orders, provider calls, GPU/model-service changes,
frozen-history writes or repeated old timing evaluation. Diagram impact NONE.
