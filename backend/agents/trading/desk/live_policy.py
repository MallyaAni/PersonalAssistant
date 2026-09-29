"""Which allocation policy the paper account runs, and its targets for tonight.

The paper executor (`paper.plan`, driven by `market_daily._paper_trade`) is
policy-agnostic: it takes target weights and applies the account's
conventions - whole shares, band-gated entries, rotations out of downgraded
names, deferred buys, the redeploy of idle cash, the twenty-session
rebalance clock. Until 2026-09-27 the targets came from `report.book`, the
`/3` sizing (inverse volatility, a 0.30 volatility target, regime
multipliers, top-decile concentration). On the point-in-time book that
sizing earned 14.6% a year under the live conventions against 23.3% for
`graded-equal-weight/4` under the same conventions (docs/NEXT_SESSION.md,
2026-09-27 addendum), so the operator moved the account to `/4`: every A/A+
member at equal weight, capped at 20%, fully invested. On 2026-09-29 the
operator raised the hold cap to 25% (`graded-equal-weight/5`, `policy_v5`;
its docstring has the cap-sweep evidence): the same rule, and the same
book whenever five or more names qualify. The operator's instruction was
that the paper account executes exactly as a live one would.

This module is the one place that says which policy is active. `POLICY` is
the active policy's module and `ACTIVE` its version string. `targets`
returns tonight's weights from `POLICY.targets` on the report's last
session, exactly as the shadow ledger decides them (`shadow_ledger.decide`;
a test pins the two equal), so the account, the board's buy/sell sizes and
the shadow all ask for the same book and the shadow's receipts measure the
executor alone. `allocator(mask)` is the same policy as a `simulate.run`
allocator, which the record's published rules lines are priced with.
`record_targets` is what the nightly writes into the desk record so the
dashboard's decision rows size against the active policy rather than the
`/3` book, which stays on the record for reference.

`ACTIVE` is stamped on the paper state, and a state stamped with another
version rebalances into the new book on its next plan, once - except
between two graded equal-weight versions (`EQUAL_WEIGHT`: `/4` and `/5`),
which differ only in the hold cap. A cap change moves the targets, not the
book: between resets the redeploy leg fills each held name toward its new
target from the cash beyond the buffer (a higher cap only ever raises a
target, so nothing has to be sold), the next reset brings the whole book to
the new targets on the account's own clock, and the nightly re-stamps the
state with `ACTIVE` the first time it plans under it. A state with no stamp
(the `/3` era) or any other version still takes the one forced rebalance.
"""

from __future__ import annotations

import numpy as np

from backend.agents.trading.desk import policy_v4, policy_v5

# The policy the paper account runs, as the module that decides it.
# Changing it is a release, not a setting: the record, the dashboard's
# rules line, the shadow ledger and the paper state all carry it.
POLICY = policy_v5
ACTIVE = POLICY.POLICY_VERSION
# The graded equal-weight versions: every A/A+ name at equal weight under a
# hold cap, fully invested when the count allows, and nothing else. They
# differ only in the cap, so moving between them moves the targets and not
# the book (`needs_rebalance`), and the board and the charts read their
# records the same way. A named tuple, never a prefix: a version this code
# has not seen is not assumed to be one of them.
EQUAL_WEIGHT = (policy_v4.POLICY_VERSION, policy_v5.POLICY_VERSION)


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
    weights = POLICY.targets(
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


# The active policy as a `simulate.run(allocator=...)` callable on a
# membership mask: the allocator the published rules lines are priced with,
# so the curve on the record is the policy the account runs.
def allocator(mask: np.ndarray):
    """Return `POLICY.allocator(mask)`."""
    return POLICY.allocator(mask)


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


# Whether `version` is one of the graded equal-weight policies; with no
# argument, whether the active policy is. None means "the active policy"
# here, so a caller holding a stamp that may be missing (a record's
# `targets.policy`, a history file's `policy`) tests `in EQUAL_WEIGHT`
# instead, where a missing stamp is simply not one of them.
def is_equal_weight(version: str | None = None) -> bool:
    """Return True when `version` (default `ACTIVE`) is in `EQUAL_WEIGHT`."""
    return (ACTIVE if version is None else version) in EQUAL_WEIGHT


# Whether a book planned under `version` is still the active policy's book:
# the active version itself, or another graded equal-weight version while
# the active one is too (the cap differs, the book does not have to move).
# A missing stamp (the `/3` era) or any other version is not.
def same_book(version: str | None) -> bool:
    """Return True when a plan made under `version` needs no forced rebalance."""
    if version == ACTIVE:
        return True
    return version in EQUAL_WEIGHT and is_equal_weight()


# Whether a paper state planned under another policy (or under none, the
# `/3` era before the stamp existed) must rebalance into `ACTIVE` tonight.
# Not between two graded equal-weight versions: the redeploy and the next
# reset carry the book to the new targets, and the nightly re-stamps the
# state with `ACTIVE` because this says no rebalance is needed.
def needs_rebalance(state_policy: str | None) -> bool:
    """Return True when `state_policy` cannot continue as the active book."""
    return not same_book(state_policy)
