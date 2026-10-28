"""One realtime verdict per numerical entry row.

The entry engines already record a state, a timing reason and a model position.
This module only translates that evidence into the single vocabulary the
dashboard shows: buy, sell, or nothing, with one closed reason code. It does not
decide a trade, size a position, or replace any existing field.
"""

from backend.market.labels import (
    Action,
    TimingState,
    Verdict,
    VerdictReason,
    as_member,
)

VERDICTS = tuple(Verdict)
REASON_CODES = tuple(VerdictReason)
REASONS = {
    VerdictReason.EXECUTE_NOW: "Act now at the current price",
    VerdictReason.WAITING_BETTER_PRICE: "Wait one candle for a better price",
    VerdictReason.AT_TARGET: "The model position is already at target",
    VerdictReason.NO_ALLOCATION: "No model allocation for this name",
    VerdictReason.GRADE_BELOW_A: "The grade is below the entry grade",
    VerdictReason.AWAITING_CANDLE: "Awaiting a completed 15-minute candle",
    VerdictReason.PUBLICATION_EXPIRED: "The published assessment has expired",
    VerdictReason.QUOTE_STALE: "A fresh compatible quote is required",
    VerdictReason.PRICE_UNAVAILABLE: "No compatible execution price is available",
    VerdictReason.ENTRY_PENDING: "Entry price not yet confirmed this candle",
}
# The verdict a planned Buy or Sell reads as while its price is pending.
_DIRECTION = {Action.BUY: Verdict.BUY, Action.SELL: Verdict.SELL}


# Pick the reason a non-executing unavailable row cannot act.
def _unavailable_code(timing_reason, quote_available, distribution_available):
    lowered = timing_reason.lower()
    if not distribution_available or "distribution" in lowered or "candle" in lowered:
        return VerdictReason.AWAITING_CANDLE
    if not quote_available or "quote" in lowered:
        return VerdictReason.QUOTE_STALE
    if any(
        token in lowered
        for token in ("price", "moment", "funding", "wealth", "cost", "numeric")
    ):
        return VerdictReason.PRICE_UNAVAILABLE
    return VerdictReason.PUBLICATION_EXPIRED


# Pick the reason a no-trade row has nothing to do.
def _idle_code(action, timing_reason, target_weight, held_weight, resolved):
    lowered = timing_reason.lower()
    if resolved or "already resolved" in lowered:
        return VerdictReason.AT_TARGET
    if "no new model allocation" in lowered or "no original daily buy cash" in lowered:
        return VerdictReason.NO_ALLOCATION
    if target_weight is not None and target_weight == 0:
        return VerdictReason.NO_ALLOCATION
    if "no funded model reference change" in lowered:
        return VerdictReason.AT_TARGET
    if (
        target_weight is not None
        and held_weight is not None
        and abs(target_weight - held_weight) <= 1e-12
    ):
        return VerdictReason.AT_TARGET
    if timing_reason == "mandatory_grade_exit":
        return VerdictReason.GRADE_BELOW_A
    return VerdictReason.NO_ALLOCATION if action is None else VerdictReason.AT_TARGET


# The size of the trade the plan still calls for in the row's direction; None
# when the row does not say enough to know it (a sale needs the holding).
def _planned(action, target_weight, held_weight):
    if target_weight is None or (action == Action.SELL and held_weight is None):
        return None
    held = held_weight or 0.0
    return target_weight - held if action == Action.BUY else held - target_weight


# Map existing row evidence to one verdict and one closed reason code.
def classify(
    *,
    state,
    action=None,
    timing_reason="",
    target_weight=None,
    held_weight=None,
    quote_available=True,
    distribution_available=True,
    mandatory=False,
    resolved=False,
):
    reason = timing_reason or ""
    # A row's action is Buy, Sell or absent; its state is any timing state,
    # and a state outside that vocabulary is idle, as it always was.
    action = None if action is None else Action(action)
    state = as_member(TimingState, state)
    # A sale needs something held: a Sell row against a known empty reference
    # position is nothing to do, whatever the engine's state says.
    if action is Action.SELL and held_weight is not None and not held_weight > 0:
        return Verdict.NOTHING, VerdictReason.NO_ALLOCATION
    if state is TimingState.EXECUTE:
        if mandatory or reason == "mandatory_grade_exit":
            return Verdict.SELL, VerdictReason.GRADE_BELOW_A
        if action is Action.SELL:
            return Verdict.SELL, VerdictReason.EXECUTE_NOW
        if action is Action.BUY:
            return Verdict.BUY, VerdictReason.EXECUTE_NOW
        return Verdict.NOTHING, (
            VerdictReason.NO_ALLOCATION
            if target_weight == 0
            else VerdictReason.AT_TARGET
        )
    if state is TimingState.WAIT:
        return Verdict.NOTHING, VerdictReason.WAITING_BETTER_PRICE
    if state is TimingState.UNAVAILABLE:
        code = _unavailable_code(reason, quote_available, distribution_available)
        # A planned trade whose price the engine has not yet confirmed is still
        # the plan: the board says the direction and that the price is pending,
        # not "nothing", which read as "the model wants nothing here".
        if (
            code in (VerdictReason.QUOTE_STALE, VerdictReason.PRICE_UNAVAILABLE)
            and action in _DIRECTION
        ):
            planned = _planned(action, target_weight, held_weight)
            if planned is None or planned > 0:
                return _DIRECTION[action], VerdictReason.ENTRY_PENDING
        return Verdict.NOTHING, code
    return Verdict.NOTHING, _idle_code(
        action, reason, target_weight, held_weight, resolved
    )


# Add the verdict fields beside a row's existing timing reason without replacing it.
def annotate(
    row,
    *,
    reason_key="reason",
    target_weight=None,
    held_weight=None,
    quote_available=True,
    distribution_available=True,
    mandatory=False,
    resolved=False,
):
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    timing_reason = evidence.get("timing_reason", row.get("reason", ""))
    verdict, code = classify(
        state=row.get("state"),
        action=row.get("action"),
        timing_reason=timing_reason,
        target_weight=(
            target_weight
            if target_weight is not None
            else row.get("model_position_weight")
        ),
        held_weight=(
            held_weight
            if held_weight is not None
            else row.get("reference_position_weight")
        ),
        quote_available=quote_available,
        distribution_available=distribution_available,
        mandatory=mandatory,
        resolved=resolved,
    )
    served = {**row, "verdict": verdict, "reason_code": code, reason_key: REASONS[code]}
    if code is VerdictReason.ENTRY_PENDING:
        # The engine's own size is a placeholder until its objective resolves;
        # the plan's remaining trade is what the person can read now.
        target = row.get("model_position_weight")
        held = row.get("reference_position_weight")
        planned = _planned(
            row.get("action"),
            target_weight if target_weight is not None else target,
            held_weight if held_weight is not None else held,
        )
        if planned is not None:
            served["plan_weight"] = max(0.0, float(planned))
    return served
