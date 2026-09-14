"""Cash-bounded planning from the desk's existing target weights.

This is a sizing preview, not a new selection policy or an executable quote.
It never counts prospective sale proceeds or borrows from the paper account.
"""

from decimal import ROUND_FLOOR, Decimal


# Reject non-finite money before it reaches allocation arithmetic or JSON.
def amount(value: object, name: str, *, positive: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not parsed.is_finite() or parsed < 0 or (positive and parsed == 0):
        raise ValueError(
            f"{name} must be finite and {'positive' if positive else 'nonnegative'}"
        )
    return parsed


# Fund all eligible additions together, preserving relative requested dollars.
def preview(rows: list[dict], equity: float, cash: float) -> dict:
    equity_d = amount(equity, "Account equity", positive=True)
    cash_d = amount(cash, "Available cash")
    if cash_d > equity_d:
        raise ValueError(
            "Available cash cannot exceed account equity in this cash-only preview"
        )
    requests = []
    seen = set()
    for row in rows:
        ticker = row["ticker"]
        if ticker in seen:
            raise ValueError("Duplicate ticker in sizing inputs")
        seen.add(ticker)
        if row.get("action") not in ("buy", "add") or row.get("event_paused"):
            continue
        price = amount(row.get("last"), "Reference price", positive=True)
        held = amount(row.get("shares", 0), "Held shares")
        weight = amount(row.get("target_weight", 0), "Target weight")
        if weight > 1:
            raise ValueError("Target weight exceeds account equity")
        target = (equity_d * weight / price).to_integral_value(rounding=ROUND_FLOOR)
        wanted = max(Decimal(0), target - held).to_integral_value(rounding=ROUND_FLOOR)
        if wanted:
            requests.append((ticker, price, held, target, wanted))
    requested = sum((price * wanted for _, price, _, _, wanted in requests), Decimal(0))
    budget = min(cash_d, requested)
    result = []
    spent = Decimal(0)
    for ticker, price, held, target, wanted in requests:
        shares = (wanted * budget / requested).to_integral_value(rounding=ROUND_FLOOR)
        cost = shares * price
        spent += cost
        result.append(
            {
                "ticker": ticker,
                "reference_price": float(price),
                "held_shares": float(held),
                "target_total_shares": int(target),
                "additional_shares": int(shares),
                "estimated_cost": float(cost),
            }
        )
    return {
        "basis": "evening-targets-cash-preview-v1",
        "available_cash": float(cash_d),
        "estimated_cost": float(spent),
        "unallocated_cash": float(cash_d - spent),
        "cash_limited": requested > cash_d,
        "rows": result,
    }


# Show target reductions without counting them as spendable sale proceeds.
def reductions(rows: list[dict], equity: float) -> list[dict]:
    total = amount(equity, "Account equity", positive=True)
    result = []
    for row in rows:
        if row.get("action") not in ("trim", "sell") or row.get("event_paused"):
            continue
        price = amount(row.get("last"), "Reference price", positive=True)
        held = amount(row.get("shares"), "Held shares")
        weight = amount(row.get("target_weight"), "Target weight")
        target = (total * weight / price).to_integral_value(rounding=ROUND_FLOOR)
        result.append(
            {
                "ticker": row["ticker"],
                "held_shares": float(held),
                "target_total_shares": int(target),
                "reduction_shares": float(max(0, held - target)),
            }
        )
    return result
