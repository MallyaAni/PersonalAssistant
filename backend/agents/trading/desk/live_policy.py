"""Which allocation policy the paper account runs, and its targets for tonight.

The paper executor (`paper.plan`, driven by `market_daily._paper_trade`) is
policy-agnostic: it takes target weights and applies the account's
conventions - whole shares, band-gated entries, rotations out of downgraded
names, deferred buys, the twenty-session rebalance clock. Until 2026-09-27
the targets came from `report.book`, the `/3` sizing (inverse volatility,
a 0.30 volatility target, regime multipliers, top-decile concentration).
On the point-in-time book that sizing earned 14.6% a year under the live
conventions against 23.3% for `graded-equal-weight/4` under the same
conventions (docs/NEXT_SESSION.md, 2026-09-27 addendum), so the operator
moved the account to `/4`: every A/A+ member at equal weight, capped at
`policy_v4.HOLD_CAP`, fully invested. The operator's instruction was that
the paper account executes exactly as a live one would.

This module is the one place that says which policy is active. `targets`
returns tonight's weights from `policy_v4.targets` on the report's last
session, exactly as the shadow ledger decides them (`shadow_ledger.decide`;
a test pins the two equal), so the account, the board's buy/sell sizes and
the shadow all ask for the same book and the shadow's receipts measure the
executor alone. `ACTIVE` is stamped on the paper state; a state stamped
with another version (or none, the `/3` era) rebalances into the new book
on its next plan, once. `record_targets` is what the nightly writes into
the desk record so the dashboard's decision rows size against the active
policy rather than the `/3` book, which stays on the record for reference.
"""

from __future__ import annotations

import numpy as np

from backend.agents.trading.desk import policy_v4

# The policy the paper account runs. Changing it is a release, not a
# setting: the record, the dashboard's rules line and the paper state all
# carry it, and the change forces one rebalance into the new targets.
ACTIVE = policy_v4.POLICY_VERSION


# Tonight's target weights for the active policy, keyed by ticker, holding
# only the names it wants. Every name in the panel is eligible today (the
# panel is the current book; the dated membership matters for history, not
# for what can be bought tonight), the benchmark never is, and a name with
# no close tonight cannot be sized.
def targets(report) -> dict[str, float]:
    """Return {ticker: weight} for the report's last session under `ACTIVE`."""
    panel = report.panel
    last = len(panel.dates) - 1
    eligible = np.ones(len(panel.tickers), dtype=bool)
    weights = policy_v4.targets(
        report.graded.grades[last],
        panel.close[last],
        eligible,
        panel.index(panel.benchmark),
    )
    return {
        ticker: float(w)
        for ticker, w in zip(panel.tickers, weights, strict=True)
        if w > 0
    }


# The block the desk record carries for the dashboard: the active policy
# and a weight for every graded name (zero where the policy holds none),
# which is the shape `decision_view.build(targets=...)` validates - the same
# names as the record's grades, each in [0, 1], summing to at most one.
def record_targets(report) -> dict:
    """Return {"policy", "weights"} for the record, every graded name present."""
    panel = report.panel
    wanted = targets(report)
    weights = {
        ticker: wanted.get(ticker, 0.0)
        for ticker in panel.tickers
        if ticker != panel.benchmark
    }
    return {"policy": ACTIVE, "weights": weights}


# Whether a paper state planned under another policy (or under none, the
# `/3` era before the stamp existed) must rebalance into `ACTIVE` tonight.
def needs_rebalance(state_policy: str | None) -> bool:
    """Return True when `state_policy` is not the active policy."""
    return state_policy != ACTIVE
