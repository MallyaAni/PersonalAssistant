"""Grade direction with learned sizing, retaining every original research policy."""

import numpy as np

POLICY = "grade-led-learned-sizing/1"
LETTERS = {-1: None, 0: "C", 1: "B", 2: "A", 3: "A+"}


# Describe grade permission independently of the optimizer and any resulting order.
def signals(report, held):
    rows = {}
    for column, name in enumerate(report.panel.tickers):
        if name in ("SPY", "QQQ"):
            continue
        grade = int(report.graded.grades[-1, column])
        prior = (
            int(report.graded.grades[-2, column]) if len(report.panel.dates) > 1 else -1
        )
        if grade not in LETTERS or prior not in LETTERS:
            raise ValueError("Observed ordinal grades required")
        action = (
            "unavailable"
            if grade < 0
            else "hold"
            if grade >= 2 and held.get(name, 0) > 0
            else "buy"
            if grade >= 2
            else "sell"
            if held.get(name, 0) > 0 or prior >= 2
            else "avoid"
        )
        rows[name] = {
            "action": action,
            "grade": LETTERS[grade],
            "previous_grade": LETTERS[prior],
            "changed": grade != prior,
            "session": str(report.panel.dates[-1]),
            "basis": "observed_close_grade",
            "reason": (
                "Grade unavailable; preserve existing shares"
                if grade < 0
                else "A/A+ entry permission; learned sizing and funding apply"
                if grade >= 2
                else "Below A; exit existing shares and do not initiate a purchase"
            ),
        }
    return rows


# Keep eligible holdings when a zero model size would override the grade exit rule.
def preserve_grade_holdings(targets, receipt, grade_signals, prices, equity):
    result = dict(targets)
    preserved = []
    for name, signal in grade_signals.items():
        current = receipt["current_weights"].get(name, 0.0)
        if signal["action"] == "hold" and current > 0 and result.get(name, 0.0) <= 0:
            result[name] = current
            preserved.append(name)
        elif signal["action"] == "hold" and current > 0:
            # Whole-share rounding must not turn a sizing trim into a grade exit.
            result[name] = max(
                result[name], min(current, float(prices[name]) / float(equity))
            )
    # Preserving a holding cannot fund the model's proposed purchases.
    current = receipt["current_weights"]
    increases = sum(
        max(0.0, value - current.get(name, 0.0)) for name, value in result.items()
    )
    room = max(
        0.0,
        1.0 - sum(min(value, current.get(name, 0.0)) for name, value in result.items()),
    )
    if increases > room and increases > 0:
        factor = room / increases
        result = {
            name: min(value, current.get(name, 0.0))
            + factor * max(0.0, value - current.get(name, 0.0))
            for name, value in result.items()
        }
    if not np.isfinite(list(result.values())).all() or sum(result.values()) > 1 + 1e-10:
        raise ValueError("Grade-led targets exceed observed capital")
    receipt.update(
        grade_signals=grade_signals,
        grade_preserved_holdings=preserved,
        target_basis="grade_constrained_learned_sizes",
        targets=result,
    )
    return result, receipt
