"""One realtime verdict per numerical entry row.

The entry engines already record a state, a timing reason and a model position.
This module only translates that evidence into the single vocabulary the
dashboard shows: buy, sell, or nothing, with one closed reason code. It does not
decide a trade, size a position, or replace any existing field.
"""

VERDICTS = ("buy", "sell", "nothing")
REASON_CODES = (
    "execute_now",
    "waiting_better_price",
    "at_target",
    "no_allocation",
    "grade_below_a",
    "awaiting_candle",
    "publication_expired",
    "quote_stale",
    "price_unavailable",
)
REASONS = {
    "execute_now": "Act now at the current price",
    "waiting_better_price": "Wait one candle for a better price",
    "at_target": "The model position is already at target",
    "no_allocation": "No model allocation for this name",
    "grade_below_a": "The grade is below A",
    "awaiting_candle": "Awaiting a completed 15-minute candle",
    "publication_expired": "The published assessment has expired",
    "quote_stale": "A fresh compatible quote is required",
    "price_unavailable": "No compatible execution price is available",
}


# Pick the reason a non-executing unavailable row cannot act.
def _unavailable_code(timing_reason, quote_available, distribution_available):
    lowered = timing_reason.lower()
    if not distribution_available or "distribution" in lowered or "candle" in lowered:
        return "awaiting_candle"
    if not quote_available or "quote" in lowered:
        return "quote_stale"
    if any(
        token in lowered
        for token in ("price", "moment", "funding", "wealth", "cost", "numeric")
    ):
        return "price_unavailable"
    return "publication_expired"


# Pick the reason a no-trade row has nothing to do.
def _idle_code(action, timing_reason, target_weight, held_weight, resolved):
    lowered = timing_reason.lower()
    if resolved or "already resolved" in lowered:
        return "at_target"
    if "no new model allocation" in lowered or "no original daily buy cash" in lowered:
        return "no_allocation"
    if target_weight is not None and target_weight == 0:
        return "no_allocation"
    if "no funded model reference change" in lowered:
        return "at_target"
    if (
        target_weight is not None
        and held_weight is not None
        and abs(target_weight - held_weight) <= 1e-12
    ):
        return "at_target"
    if timing_reason == "mandatory_grade_exit":
        return "grade_below_a"
    return "no_allocation" if action is None else "at_target"


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
    if state == "execute":
        if mandatory or reason == "mandatory_grade_exit":
            return "sell", "grade_below_a"
        if action == "Sell":
            return "sell", "execute_now"
        if action == "Buy":
            return "buy", "execute_now"
        return "nothing", "no_allocation" if target_weight == 0 else "at_target"
    if state == "wait":
        return "nothing", "waiting_better_price"
    if state == "unavailable":
        return "nothing", _unavailable_code(
            reason, quote_available, distribution_available
        )
    return "nothing", _idle_code(action, reason, target_weight, held_weight, resolved)


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
    return {**row, "verdict": verdict, "reason_code": code, reason_key: REASONS[code]}
