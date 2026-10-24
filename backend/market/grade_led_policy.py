"""Grade direction with learned sizing, retaining every original research policy."""

import numpy as np

POLICY = "grade-led-learned-sizing/1"
LETTERS = {-1: None, 0: "C", 1: "B", 2: "A", 3: "A+"}
# The grade at which this policy admits a name; a policy that admits lower
# says so on its class and the signals are read against that boundary.
ENTRY_GRADE = 2
# How the boundary is named in a signal's reason: the admitted letters, and
# the letter a name has slipped below when it must be exited.
ENTRY_WORDS = {3: ("A+", "A+"), 2: ("A/A+", "A"), 1: ("B/A/A+", "B")}


# The letters a boundary admits, in the order the ladder names them.
def admitted_letters(entry_grade=ENTRY_GRADE):
    return tuple(
        letter
        for ordinal, letter in sorted(LETTERS.items())
        if letter and ordinal >= entry_grade
    )


# The letters the named policy admits a name at; a policy this module does not
# know keeps the A boundary the desk's readers always assumed.
def admitted_for(policy):
    from backend.market import learned_live_holding

    try:
        return admitted_letters(learned_live_holding.entry_grade(policy))
    except ValueError:
        return admitted_letters(ENTRY_GRADE)


# Describe grade permission independently of the optimizer and any resulting order.
# A policy may hold a name below the grade it admits at (`hold_grade`): a held
# name keeps its place while it is graded at least that, and is exited below it.
def signals(report, held, entry_grade=ENTRY_GRADE, hold_grade=None):
    if entry_grade not in ENTRY_WORDS:
        raise ValueError("Entry grade must be B, A or A+")
    hold_grade = entry_grade if hold_grade is None else hold_grade
    if hold_grade not in ENTRY_WORDS or hold_grade > entry_grade:
        raise ValueError("Hold grade must be B, A or A+ and no higher than the entry")
    admitted, boundary = ENTRY_WORDS[entry_grade]
    kept, floor = ENTRY_WORDS[hold_grade]
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
        owned = held.get(name, 0) > 0
        action = (
            "unavailable"
            if grade < 0
            else "hold"
            if grade >= hold_grade and owned
            else "buy"
            if grade >= entry_grade
            else "sell"
            if owned or prior >= entry_grade
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
                else f"{admitted} entry permission; learned sizing and funding apply"
                if grade >= entry_grade
                else f"Held while {kept}; no new purchase below {boundary}"
                if action == "hold"
                else (
                    f"Below {floor}; exit existing shares "
                    "and do not initiate a purchase"
                )
                if owned
                else (
                    f"Below {boundary}; exit existing shares "
                    "and do not initiate a purchase"
                )
            ),
        }
    return rows


# Keep eligible holdings when a zero model size would override the grade exit rule.
def preserve_grade_holdings(
    targets, receipt, grade_signals, prices, equity, *, basis=None
):
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
        target_basis=basis or "grade_constrained_learned_sizes",
        targets=result,
    )
    return result, receipt
