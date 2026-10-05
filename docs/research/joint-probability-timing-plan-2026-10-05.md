# Funded allocation with probabilistic timing

Register `joint-stock-risk-funded/4-calibrated-probability-timing-research`
as a private integration of the unchanged v3 calibrated holding policy and
the existing `live-probability-timing/1-research` execution reader. This closes
a wiring gap, not an economic finding. V1–v3 orders use next-open execution;
passing an intraday model to those accounts previously had no effect.

The holding distribution determines funded whole-share quantities and exits;
the separate one-decision price-advantage distribution determines when an
ordinary allocation intent may submit. Their horizons are not interchangeable.
Do not resize an existing intent from the timing forecast or assume that a
timing probability is a calibrated confidence in the holding return.

Only ordinary allocation orders use probabilistic intraday timing. Structured
company exits retain next-open priority, and the existing event dispatcher
retains priority over ordinary learned planning. Preserve observed cash,
covered shares, grade permissions, missing holding risk, original identities,
costs and the common final-session submission deadline. The deadline is an
execution constraint, not a fixed price or profit target.

Persist the required timing policy on ordinary pending rows. Missing or invalid
timing evidence cannot revert to the 1% level before the deadline. Require
the original empirical-distribution loader and the real reader in historical
replays; reject an unused timing provider on next-open policies before writing
an account. Record the planned timing separately from actual submission/fills.
No production broker or selector is admitted by this change.

Acceptance: reproduce unused timing, then exercise the real nightly planner,
durable pending rows, observed private account, intraday sender, fill and
reconciliation. A buy can wait despite a 2% dip and execute later without a
1% dip; a discretionary sell uses the opposite price-advantage decision.
Missing forecasts wait, malformed contracts never downgrade, final deadlines
include early closes, and company/event priorities do not acquire timing delays.
Reject missing readers, substituted builders and misaligned saved inputs before
effects. Existing next-open and incumbent paths must remain unchanged.

This checkpoint adds no economic account grid. Complete and inspect the active
three-cost v3 screen first. Any combined economic run needs its own fixed source,
authenticated original boosting timing bank, identical costs/starts and saved
arithmetic verification; it must not rename or modify an active v3 account.
Reused development history is not prospective adoption evidence.
