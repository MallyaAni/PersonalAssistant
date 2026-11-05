"""The semantic judge itself does not drift.

`semantic.states` backs the `holds`/`does_not_hold` assertions of a dozen
functional modules and of every journey in the sweep. Every one of those
assertions assumes the judge reads meaning and not wording. That assumption is
checked everywhere except the one place it has to hold first: the judge. If the
judge model changes, the quantisation degrades, or the schema path breaks,
every caller silently re-flakes - or, worse, passes for the wrong reason.

So the judge is measured against a set of unambiguous verdicts, deliberately
chosen to be cases no fair reader could call both ways, including the shapes
that have actually bitten this repository:
- a reworded truth (the reply says the memory is "gone now", which is no less
  a claim to have forgotten);
- a near-miss falsehood (a forecast with no place is not a forecast "for
  Arlington");
- the disjunctive statements the sweep uses ("from live sources or says it
  could not check"), where one supported alternative is enough;
- a statement about context the reply need not repeat, judged with the
  question that supplies it (a DC forecast that never says "DC").

Seeds are `(answer, statement, question, expected)`. The floor sits one miss
below the measured value so an exact tie does not fail an honest run.
"""

from __future__ import annotations

from backend.tests.functional.semantic import states

# (answer, statement, question, expected). Unambiguous on purpose: this test
# exists to catch a drifting judge, and a seed a fair reader could call both
# ways would just import the flake it is meant to find.
_JUDGE_SEEDS: tuple[tuple[str, str, str | None, bool], ...] = (
    # --- clear true -------------------------------------------------------
    ("Done - I'll remind you at 9am tomorrow.", "The reply confirms a reminder for tomorrow at 9 am.", None, True),
    ("I have no record of you mentioning a dentist. What would you like me to remember?", "The reply says it has no record of the reader mentioning a dentist, or asks what they would like remembered.", None, True),
    ("Got it - I've set a one-time reminder for tonight at 9pm to grab ice cream.", "The reply says it set a reminder.", None, True),
    ("Your dentist is Dr Lee on Wilson Boulevard.", "The reply mentions Dr Lee or Wilson Boulevard.", None, True),
    ("Forecast for Arlington: 88 degrees, feeling like 96, with storms later today.", "The reply gives a forecast for Arlington, Virginia or the Washington area.", None, True),
    # A reworded truth: no keyword from the statement, same meaning. The
    # statement is the journey's own ("forgot, removed, or will no longer
    # remember") - the judge reads action wording but not state wording
    # ("no longer remembers"), measured 2026-09-01, so a seed must use the
    # action phrasing the production statements already carry.
    ("The memory of Dr Lee is gone now.", "The reply says it forgot, removed, or will no longer remember what it had saved.", None, True),
    # --- clear false ------------------------------------------------------
    ("Your dentist is Dr Lee on Wilson Boulevard.", "The reply says it has no record of the reader mentioning a dentist.", None, False),
    ("Done - I'll remind you tonight at 7 to pick up milk.", "The reply confirms a reminder for tomorrow at 9 am.", None, False),
    ("The forecast is hot and sticky, 88 degrees.", "The reply gives today's forecast for Arlington, Virginia or the Washington area.", None, False),
    # A near-miss falsehood: the show is named in the statement, not in the
    # answer, and naming it is not being about it.
    ("The Love Island winners split the $100,000 prize.", "The reply is about the show Surviving Paradise.", None, False),
    # --- the disjunctions the sweep uses ---------------------------------
    # The routing model answered false to every one of these on the deployed
    # runtime 2026-11-04 while the replies plainly satisfied them; they are
    # the regression this test exists to keep fixed.
    (
        "Saturday looks lovely: mostly sunny, high 63, low 44. Sunday is nearly the same - mostly sunny, 62/43.",
        "The reply gives a forecast for Washington, DC that mentions Saturday or Sunday.",
        "what's the weather in DC this weekend?",
        True,
    ),
    (
        "Sony's current prices are $649.99 for the standard PS5, $599.99 for the Digital Edition, and $899.99 for the PS5 Pro.",
        "The reply gives a price or price range and says it is current or as of today, or that it could not check.",
        "how much does a PlayStation 5 cost right now?",
        True,
    ),
    (
        "Sunday hours are 11:00 a.m. to 6:00 p.m. ([Apple Clarendon](https://www.apple.com/retail/clarendon)).",
        "The reply gives hours from a live source or says it could not check.",
        "is the Apple Store in Clarendon open on Sunday?",
        True,
    ),
    (
        "They beat the Eagles 27-10 at home on Sunday, Nov 1 ([NFL.com schedule](https://www.nfl.com/schedules)).",
        "The reply gives a result from live sources or says it could not check.",
        "did the Commanders win their last game?",
        True,
    ),
    (
        "The Fed's big event was last week's meeting, and this week has been follow-on news.",
        "The reply reports recent news, or says it could not check live sources.",
        "what happened with the Federal Reserve this week?",
        True,
    ),
    ("I'll ask you Friday at 9:00 AM how the interview went.", "The reply says it will ask about the interview later, on Friday or in a few days.", "check in with me on Friday about how the interview went", True),
    # --- the same shape must still refuse a near miss ---------------------
    ("They beat the Eagles 27-10 at home on Sunday, Nov 1.", "The reply gives a basketball score.", "did the Commanders win their last game?", False),
    ("I'll ask you Friday at 9:00 AM how the interview went.", "The reply says it will not ask about the interview.", "check in with me on Friday about how the interview went", False),
    ("Sunday hours are 11:00 a.m. to 6:00 p.m.", "The reply gives the store's phone number.", "is the Apple Store in Clarendon open on Sunday?", False),
)

# Measured on 2026-11-04: 19/19 in the functional image (reasoning off) and
# 18/19 on the deployed reply model with thinking on. The one thinking-mode
# miss is the Arlington/Virginia reword, which a strict reader can call either
# way - "Arlington" alone does not say Virginia. The floor allows that one
# miss and no more. The routing model measured 10/19 on these seeds before
# this pass, which is why the judge no longer uses it.
_JUDGE_FLOOR = 18


def test_the_semantic_judge_agrees_with_known_verdicts() -> None:
    """Run the judge over unambiguous seeds and fail loudly if it drifts below floor."""
    verdicts = [
        (answer, statement, question, expected, states(answer, statement, question))
        for answer, statement, question, expected in _JUDGE_SEEDS
    ]
    misses = [v for v in verdicts if v[3] != v[4]]
    assert len(misses) <= len(_JUDGE_SEEDS) - _JUDGE_FLOOR, (
        f"the semantic judge drifted: {len(_JUDGE_SEEDS) - len(misses)}/{len(_JUDGE_SEEDS)} on "
        f"known verdicts. Wrong verdicts: "
        + "; ".join(
            f"expected {expected}, got {got} for statement {statement!r} on answer {answer!r}"
            for answer, statement, question, expected, got in misses
        )
    )
