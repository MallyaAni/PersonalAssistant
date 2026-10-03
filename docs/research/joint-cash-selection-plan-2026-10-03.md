# Joint purchase and cash-exit selection: fixed component contract

Objective: measure whether the same causal stock-specific forecasts improve
new purchases/additions and discretionary exits of held A/A+ stocks. Buying and
profit-taking both need selection decisions; scheduling existing intents does
not supply them. Existing held-B retention improved matched full/recent gains
over the daily rule but has uncertainty intervals spanning zero. This new
contract is frozen before its implementation or account outcomes; the previous
study has already been read. No claim of an untouched model-selection process.

## Economic verdicts

Reuse the existing authenticated monthly forecast arrays from evaluated source
95ee87086ac336ea81e80f6b29a693a62d686602. No model refit, hyperparameter change,
additional feature or outcome-chosen regime switch. Absolute stock log-return
mean is its stock-minus-SPY mean plus the absolute SPY mean. The target stays
next-open[t+1] to open[t+11], with the existing maturity purge and August17 freeze.

At decision close t, for an ordinary eligible A/A+ stock with both forecasts:

- A new purchase/addition requires its absolute mean to exceed log(1+buy cost).
  Otherwise block purchases of that name. Do not force a sale merely because
  buying is blocked. Preserve any incumbent reduction or concentration trim.
- An existing A/A+ holding receives a covered full-exit proposal if its mean is
  below log(1−sell cost): the forecast prefers sale proceeds held as zero-yield
  cash to continued ownership. Positive entry-basis profit is not required;
  absent cost basis, label this a forecast cash exit, never an asserted profit.
- Equality does not justify creating a discretionary exit; a zero purchase
  edge does not justify adding. With zero modeled cost these are zero expected
  log-return comparisons, not universal price-move thresholds.

These are mean-log, stock-specific economic comparisons. They are not calibrated
probabilities, expected terminal wealth, optimal sizing or proven execution
profit. Fees are the existing 0/10/25bp stress grid per side, not a claim that
the broker charges commission. Keep existing sizing, eligible-grade rules,
quantity rounding, concentration limits and mandatory event/thesis/risk exits.

Missing either forecast preserves incumbent behavior for that stock. Unknown
eligibility/grade never creates a new learned exit. All ordinary held-B decisions
continue through the previously tested retention adapter, including its
destination/cash requirements and caps. No B purchases. Mandatory overrides
have priority and cannot be cancelled by a favorable forecast.

## Actual account integration

Use a distinct opt-in selection hook before reset and shared daily planning.
It supplies explicit purchase-block and cash-exit masks, not orders or funding.
Apply a purchase block to reset shortfalls, ordinary entries, redeployment and
deferred retries. Clamp any surviving buy leg defensively; never block a sale
because purchase permission is absent. Exit proposals must be covered by actual
holdings and preserve original mandatory reasons. Do not respend proposed sale
proceeds. FOMC lifecycle bypasses discretionary selection as before.

No model forecast, reason, holding, cash balance or pending order is silently
fabricated. All-unavailable forecasts must preserve complete incumbent and
held-B-overlay journals bit exactly. Future array values cannot affect earlier
selection. Mandatory/reset trims must survive ordinary minimum-trade floors.
Refuse combinations whose additional purchase paths are not explicitly tested.

## Fixed funded comparison and proof

Same original 96-source snapshot/vintage, evaluation2018-02-01..2026-09-30,
twenty reset offsets0..19, NAV1 carried accounts, zero cash yield and three
costs. Run only sixty new joint-selection accounts. Authenticate and reuse the
independently verified sixty rule, sixty learned-B and sixty simple-B accounts,
plus six ETF controls; no original fits, scoring or strategy replays repeated.

Main contrast is joint versus learned-B alone, isolating purchase/A-exit
selection. Also retain every matched contrast versus the daily rule and simple
B retention. Report net cumulative gain first, CAGR, drawdown loss, Sharpe,
gross traded notional/NAV/year, fees and SPY/QQQ excess/rolling win rates over
the same full,2018–20,2021–26 and reused-recent windows. Missing outcomes stay
explicit. No favorable phase/window/regime selection. Supplemental full-period
uncertainty uses the same fixed63-session,2000-replicate,seed0 common-clock
method for all three controls and costs; it cannot establish live reliability.

Require real simulator acceptance for cash funding, covered exits, blocked
adds without liquidation, deferred prevention/recovery, concentration cuts,
mandatory priority, unavailable fallback and prefix invariance. Pin exact source,
saved-model/forecast/control anchors, journals and original result bytes. Verify
saved artifacts independently without fitting or strategy resimulation.

This remains a reconstructed daily selection component. It does not remove the
deployed 1% intraday scheduler, supply valid partial-day inference, prove broker
fills or resolve the full user objective by itself. A complete replacement needs
a matched test combining selection with causal intraday timing and actual live
input/quantity semantics; do not infer combined performance from separate tests.
