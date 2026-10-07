# Buy versus exit attribution: fixed diagnostic contract

Freeze this contract after reading the joint result at evaluated sourcee8505b22,
before implementing these modes or running new account outcomes. Both buying
and profit-taking remain the goal. The joint overlay lowers drawdowns/recent
losses but raises churn and loses full-period paired net gain. Neither side's
contribution is identifiable from that aggregate. This is deliberate diagnostic
reuse of examined data, not an untouched validation or search for new thresholds.

## Three new arms, no new models

Reuse exact authenticated95ee8708 model forecasts, original96-source snapshot,
reconstructed grades/eligibility and source panel. Do not refit, download data,
alter features, targets, cost thresholds, windows, phases or regime rules.
All arms retain the same learned-B adapter and shared funding/event/sizing logic.

- `quantity_control`: retain finite forecast metadata and the known eligible
  A/A+ reset-quantity trim correction, but disable both discretionary purchase
  vetoes and A/A+ cash exits. This isolates the simulator correction that was
  introduced alongside joint selection from economic forecast decisions.
- `buy_only`: enable original purchase vetoes, never create a discretionary
  A/A+ cash exit. Incumbent/mandatory reductions remain possible; blocked buys
  never imply forced liquidation. The same quantity correction applies.
- `exit_only`: enable original covered A/A+ cash exits, leaving purchases alone
  except that a cash-exiting name must also deny additions/retries/destination
  funding. Without that restriction an exit can finance its own repurchase.
  The same quantity correction applies. Missing forecasts preserve incumbent.

`joint` remains the unchanged default with both decision sides. Make modes
explicit, validated and recorded in each receipt; never suppress exit purchase
denial or silently reinterpret an archived joint verdict. Forecasts/edge arrays
remain identical; only declared decision masks/reasons change. Missing all
forecasts preserves complete incumbent/held-B journals in every mode.
Future rows cannot affect earlier account decisions. Cash-exit proposals are
covered by actual holdings and do not guarantee fills or profitable realization.

## Fixed account and contrast grid

Run180new accounts: three modes×0/10/25bp×offsets0..19. Same carried NAV1,
2018-02-01..2026-09-30, zero cash yield, adjusted fractional units, daily legacy
execution, FOMC lifecycle, midcycle planning and four existing windows. Reuse
all60verified joint accounts plus the180verified prior stock/six ETF controls.
Do not replay those accounts or refit their models. No phase/window exclusion.

Main matched contrasts are buy_only−quantity_control and
exit_only−quantity_control. Also retain joint−quantity_control,
joint−buy_only, joint−exit_only and quantity_control−learned B. Pair same
cost/phase/window before summarizing. These comparisons separate masks and the
quantity correction; changed wealth/funding paths are part of the effect.
Interaction on each matched cumulative-gain cell is
joint−buy_only−exit_only+quantity_control. This arithmetic describes account
interaction; it does not attribute a unique market cause or independent effect.

Report cumulative net gain first, CAGR, positive drawdown loss, Sharpe, gross
traded notional/NAV/year, fees, both SPY/QQQ excess returns and overlapping252-day
win rates. Preserve all account scores and missing outcomes. Main full-period
uncertainty for the two main contrasts uses the existing fixed63-session,
2,000-replicate,seed0 common-clock circular bootstrap across all phases at all
three costs. Do not add window/regime/bootstrap searches or select the best mode
as validated live alpha on this reused evidence.

## Acceptance and limits

Real funded-simulator tests must demonstrate exit-only cannot rebuy or redirect
cash into its exit, buy-only blocks additions without liquidating held stock,
quantity-control retains the known tiny reset trim, mandatory FOMC priority,
finite/missing equality behavior, unavailable bit-exact fallback and future
prefix invariance. Existing joint/default acceptance assertions stay unchanged.
Pin source, registered contract, saved forecast/control/proof bytes and every
new ledger/verdict/NAV artifact. Independently verify saved evidence without
fitting, replaying strategies or rescoring original controls.

All new accounts stay research-only. No real orders, production data writes,
UI changes, deployment, model-service changes or GPU requirement. Current
selection is reconstructed and daily execution differs from the deployed
intraday scheduler. A useful attribution result supports a precise next model
or combined execution test; it cannot itself establish a reliable live replacement.
