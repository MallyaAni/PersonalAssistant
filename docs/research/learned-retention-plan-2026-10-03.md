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

## Next atomic deliverable: causal daily forecast head

Objective: supply genuinely learned forecasts to this planner instead of
invented values. VERIFIED: the pure planner's 53 native and 111 combined-image
acceptance checks. FAILED: timing-only improvements have not established a
recent replacement advantage. UNVERIFIED: held-B retention forecasts, funded
benefit, daily-rotation replay and live integration. This deliverable changes
only a pure training module and its tests; it does not claim adoption.

Freeze before real fitting: use exactly the existing first13 daily context
features, shifted to include completed decision-close t. No intraday features,
new range feature, new price provider or model selection. Scale daily opens
with the existing adjusted_open helper: panel daily OHLC already carries its
split basis; do not convert a raw intraday cube with a dividend-only factor.
The stock label is log(open[t+11]/open[t+1]) minus SPY over exactly those opens.
The separate SPY head predicts its absolute matching log return. Labels become
available at opening t+11 on the supplied complete exchange-session calendar.
Training endpoints must precede the month's first decision session strictly;
freeze endpoints before2026-08-17 for later fits, since that recent interval
has already been repeatedly inspected. Missing future labels never suppress
scoring eligibility. Historical membership and grades remain a current-vintage
reconstruction; no original publication-time claim is introduced.

One pooled stock HGB and one SPY HGB, using the existing registered config
(64iterations,15leaves,.05learning,minleaf200,no early stopping,seed0).
Use the last756 eligible calendar decision rows, require504 distinct mature
feature-valid dates separately for each head; unavailable heads preserve the
incumbent. Train only declared stock membership with known grade and finite
labels, excluding SPY/QQQ; score any eligible held-B or declared destination
with valid causal features. Do not condition training on future account
holdings or buy decisions. Squared-error log forecasts are plug-in comparison
inputs, not a probability, guaranteed gain or expected arithmetic wealth.

Acceptance before fitting: exact next-open/ten-session endpoint and SPY
subtraction; split-basis invariance; monthly purge and reused-holdout cutoff;
future-prefix invariance; no future-label dependence in score eligibility;
head-specific warmup; stock-only training membership; rejection of invalid
calendar/shape/grades/prices; real small-model fit and deterministic scoring.
Publish input and training-row hashes, fit-date/cutoff and unavailable reasons.
No performance study until a separately reviewed daily account-aware adapter
preserves resets, rotations, deferred funding and event exits. A missing
forecast must reproduce its matched incumbent exactly. Old reset-only curves
are not a control for this selection change and must not be recycled as one.

### Pre-outcome estimator compatibility correction

The first real run at a8bc36aa failed inside sklearn1.9 histogram binning on an
all-missing SPY-only grade field, before saved fitted heads or account outcomes.
An independent504-row, two-feature reproduction fails only with the all-NaN
column; a constant observed column fits. Omit only columns with no finite value
in that head's mature training rows. Store their original feature indices and
apply the identical fitted mask at scoring; future availability cannot change
the mask. Constant observed and partly missing columns remain unchanged. With
no observed training feature, the head is unavailable. Labels, model config,
fit windows and comparison arms stay fixed; no outcome-driven tuning occurred.
