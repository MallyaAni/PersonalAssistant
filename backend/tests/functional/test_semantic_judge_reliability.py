"""The semantic judge itself does not drift.

`semantic.states` backs the `holds`/`does_not_hold` assertions of a dozen
functional modules and of every journey in the sweep. Every one of those
assertions assumes the judge reads meaning and not wording. That assumption is
checked everywhere except the one place it has to hold first: the judge. If the
routing model changes, the quantisation degrades, or the schema path breaks,
every caller silently re-flakes - or, worse, passes for the wrong reason.

So the judge is measured against a set of unambiguous verdicts, deliberately
chosen to be cases no fair reader could call both ways, including the two
shapes that have actually bitten this repository: a reworded truth (the reply
says the memory is "gone now", which is no less a claim to have forgotten) and
a near-miss falsehood (a forecast with no place is not a forecast "for
Arlington"). Seeds are `(answer, statement, expected)`. The floor sits one miss
below the measured value so an exact tie does not fail an honest run.
"""

from __future__ import annotations

from backend.tests.functional.semantic import states

# (answer, statement, expected). Unambiguous on purpose: this test exists to
# catch a drifting judge, and a seed a fair reader could call both ways would
# just import the flake it is meant to find.
_JUDGE_SEEDS: tuple[tuple[str, str, bool], ...] = (
    # --- clear true -------------------------------------------------------
    ("Done - I'll remind you at 9am tomorrow.", "The reply confirms a reminder for tomorrow at 9 am.", True),
    ("I have no record of you mentioning a dentist. What would you like me to remember?", "The reply says it has no record of the reader mentioning a dentist, or asks what they would like remembered.", True),
    ("Got it - I've set a one-time reminder for tonight at 9pm to grab ice cream.", "The reply says it set a reminder.", True),
    ("Your dentist is Dr Lee on Wilson Boulevard.", "The reply mentions Dr Lee or Wilson Boulevard.", True),
    ("Forecast for Arlington: 88 degrees, feeling like 96, with storms later today.", "The reply gives a forecast for Arlington, Virginia or the Washington area.", True),
    # A reworded truth: no keyword from the statement, same meaning. The
    # statement is the journey's own ("forgot, removed, or will no longer
    # remember") - the judge reads action wording but not state wording
    # ("no longer remembers"), measured 2026-09-01, so a seed must use the
    # action phrasing the production statements already carry.
    ("The memory of Dr Lee is gone now.", "The reply says it forgot, removed, or will no longer remember what it had saved.", True),
    # --- clear false ------------------------------------------------------
    ("Your dentist is Dr Lee on Wilson Boulevard.", "The reply says it has no record of the reader mentioning a dentist.", False),
    ("Done - I'll remind you tonight at 7 to pick up milk.", "The reply confirms a reminder for tomorrow at 9 am.", False),
    ("The forecast is hot and sticky, 88 degrees.", "The reply gives today's forecast for Arlington, Virginia or the Washington area.", False),
    # A near-miss falsehood: the keyword is there, the meaning is not.
    ("The Love Island winners split the $100,000 prize.", "The reply presents facts about a different show as the answer about Surviving Paradise.", False),
)

# Measured on 2026-09-01 against the deployed routing model: 10/10. Held one
# miss below so an honest run cannot fail on a tie. The one near-miss worth
# knowing about: a reworded truth read as action wording ("forgot, removed")
# but not as state wording ("no longer remembers") - the journey statements
# already carry the action words for exactly this reason.
_JUDGE_FLOOR = 9


def test_the_semantic_judge_agrees_with_known_verdicts() -> None:
    """Run the judge over unambiguous seeds and fail loudly if it drifts below floor."""
    verdicts = [(answer, statement, expected, states(answer, statement)) for answer, statement, expected in _JUDGE_SEEDS]
    misses = [v for v in verdicts if v[2] != v[3]]
    assert len(misses) <= len(_JUDGE_SEEDS) - _JUDGE_FLOOR, (
        f"the semantic judge drifted: {len(_JUDGE_SEEDS) - len(misses)}/{len(_JUDGE_SEEDS)} on "
        f"known verdicts. Wrong verdicts: "
        + "; ".join(
            f"expected {expected}, got {got} for statement {statement!r} on answer {answer!r}"
            for answer, statement, expected, got in misses
        )
    )
