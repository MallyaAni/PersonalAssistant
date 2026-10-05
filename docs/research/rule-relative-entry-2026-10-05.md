# Rule-relative entry continuation

Objective: improve entries while preserving original stock selection, sizing,
sell timing and zero execution costs. Starting clean source c99cf59b on the
isolated timing branch. VERIFIED prior buy-only intervention loses 11.0333pp
median paired full gain; FAILED consistent improvement; new policy UNVERIFIED.

Hypothesis: the previous recursively learned linear continuation target is an
unreliable reference. Estimate immediate execution price minus the first future
1% rule crossing's execution price (or the common final deadline), divided by
the currently observed price and prior 20-session volatility. Training outcomes
may see the future; prediction inputs must contain only the completed prefix.
The forecast sign determines act versus wait, with no fitted price threshold.
This is one-step policy improvement against an incumbent continuation, not a
proof of optimal stopping or a globally optimal trading strategy.

Use one fixed HistGradientBoostingRegressor, existing 64-tree/15-leaf/0.05 rate/
200-min-leaf/seed0 settings, no early stopping or hyperparameter search. Keep
the original 21 causal features. Train at clocks0/3/9/19, predict all24 clocks.
Monthly fit uses at most756 prior sessions, minimum504, labels strictly before
fit date and the existing August17 research freeze. All target horizons end
within their own session; no ten-day labels are consumed. Exclude SPY/QQQ from
training. Missing forecasts wait; both arms retain the final deadline. The
current forecast does not inspect the future continuation's crossing or price.

Preserve original96-name snapshot/cubes/prepared bytes; save numeric tree
nodes, verify saved numeric predictions against the trained estimator, and
save each monthly forecast once. Keep zero-cost 20-phase carried accounts,
original rule comparisons and fixed full/2018–20/2021–26/reused-recent windows.
No refit from economic outcomes. No old account reruns. Report misses and
drawdowns; paired median gain/winning phases are primary. This remains reused
conditional history, not a fresh holdout or historical live reconstruction.

Acceptance: label indexing/sign, same-session maturity, no future feature use,
numeric model replay including missing features, exact input hashes and saved
independent account readback. A failed economic candidate is not promoted.
No production model server, broker, account or dashboard mutations.
Diagram impact NONE: isolated alternative within existing research evaluation.

## Completed result

VERIFIED source7e6acb07, image5c6c5605, producer33c71e68 exited0/OOMfalse.
All104 monthly numeric models and4,081,392 predictions reproduce exactly as
float32 saved forecasts. Independent original accounting verifies20 accounts,
17,445 intents, source/input hashes, causal attempts, funding, fills, cash,
shares and daily wealth. Four initial tests passed; later formatting changed
no settings or decision logic. Raw original source remains in the private root.

FAILED advantage: full paired median -16.3362pp,6/20 phases win; early+0.2787pp,
later-8.8531pp, reused-recent-1.1412pp. No model promoted. Full hashes/window
ranges: rule-relative-entry-2026-10-05.json. Original artifacts and receipt:
Spark /home/animallya96/scratch/rule-relative-entry-20261005.
