"""Does aiming work on interests it has never been shown?

The three aiming tests in `test_prompt_behaviour.py` use "Horses" and "Run
Clubs". Those are the two worked examples written into the prompt itself, so
between them they measure whether the model can repeat an answer it was handed
in the same context window. A prompt that had learned nothing more general would
pass all three, and a rewrite would be graded on how closely it copied the
wording it replaced.

Every interest below appears nowhere in any prompt. They are chosen to be
awkward in different ways: a two-word activity, a compound noun, a hobby that is
also an object, one that is also a place, one that is a profession for some
people, and one that a search engine will happily read as something else.

The last group is the direct test of over-fitting. If the prompt has taught the
model a template rather than a task, an interest with nothing to do with horses
or running still comes back smelling of them.
"""

import pytest

from backend.agents.scout.aiming import MAX_SUBJECT_CHARS, AimPlanner
from backend.discovery.personal_context import PersonalContext

pytestmark = pytest.mark.asyncio

# None of these appear in the aiming prompt, and none share a root with the
# examples it teaches from. There are exactly MAX_AIMS of them: one more and the
# tail is never sent to the model at all, comes back as a bare label, and reads
# as the prompt failing to describe it — which cost an hour here before
# `test_the_tail_beyond_the_cap_is_not_the_prompts_fault` said so out loud.
INTERESTS = (
    "Board Games",
    "Salsa Dancing",
    "Birdwatching",
    "Woodworking",
    "Astronomy",
    "Chess",
    "Beekeeping",
    "Sea Swimming",
    "Stand-up Comedy",
    "Printmaking",
)

# Vocabulary belonging to the prompt's own worked examples. None of it has any
# business in the aim for an unrelated interest.
_EXAMPLE_VOCABULARY = (
    "horse",
    "equestrian",
    "stable",
    "run club",
    "group run",
    "casual weekend",
)

_PLACE = "Arlington, Virginia"


# One planning call covers every interest, exactly as a sweep does, so the
# result is memoised rather than re-requested per assertion. The call is greedy,
# which is what makes one answer safe to measure a dozen properties against.
_PLANNED: dict[tuple[str, ...], dict[str, object]] = {}


# Ask for every interest in one call and hand back the aims keyed by label so
# each case can be asserted on its own.
async def _aim_all(llm, context: PersonalContext | None = None):
    context = context or PersonalContext()
    key = context.statements
    if key not in _PLANNED:
        plan = await AimPlanner(llm).plan(INTERESTS, context, _PLACE)
        _PLANNED[key] = {item.label: item for item in plan.aims}
    return _PLANNED[key]


@pytest.mark.parametrize("label", INTERESTS)
async def test_every_interest_gets_a_profile_worth_embedding(llm, label):
    aims = await _aim_all(llm)

    profile = aims[label].profile
    # The whole point of the stage. A two-word label cannot be matched against
    # an event description, so a profile that is still the label — or missing —
    # leaves that interest scored exactly as it was before this module existed.
    assert profile.casefold() != label.casefold(), profile
    assert len(profile.split()) >= 4, profile


@pytest.mark.parametrize("label", INTERESTS)
async def test_the_profile_is_about_the_interest_it_was_given(llm, label):
    aims = await _aim_all(llm)

    profile = aims[label].profile.casefold()
    # A profile is embedded in place of the label, so one that has drifted to a
    # different subject silently re-points that interest at the wrong events.
    #
    # Matched on a stem, and against the profile with its spaces removed, because
    # a compound label is legitimately written out: "Birdwatching" came back as
    # "bird watching tours and nature reserves", which is the right answer and
    # contains no run of the label's own letters.
    flattened = profile.replace(" ", "").replace("-", "")
    stems = [word[:4] for word in label.casefold().split() if len(word) >= 4]
    assert not stems or any(stem in profile or stem in flattened for stem in stems), (
        profile
    )


@pytest.mark.parametrize("label", INTERESTS)
async def test_no_interest_comes_back_smelling_of_the_prompt_examples(llm, label):
    aims = await _aim_all(llm)

    written = f"{aims[label].subject} {aims[label].profile}".casefold()
    # The over-fitting detector. Nothing in this list has anything to do with
    # any interest above, so its appearance means the prompt taught the model
    # its examples rather than the task.
    for term in _EXAMPLE_VOCABULARY:
        assert term not in written, f"{term!r} leaked into {label}: {written}"


@pytest.mark.parametrize("label", INTERESTS)
async def test_the_subject_stays_a_searchable_kind_of_thing(llm, label):
    aims = await _aim_all(llm)

    subject = aims[label].subject
    assert 0 < len(subject) <= MAX_SUBJECT_CHARS, subject
    lowered = subject.casefold()
    # The skeleton supplies the place and the month; a subject naming either
    # produces a query that says it twice.
    assert "arlington" not in lowered, subject
    assert "virginia" not in lowered, subject
    assert not any(character.isdigit() for character in subject), subject


@pytest.mark.parametrize("label", INTERESTS)
async def test_an_interest_with_no_facts_keeps_its_own_words(llm, label):
    aims = await _aim_all(llm)

    # The prompt's stated contract for an empty context: infer nothing about a
    # person no fact describes. A subject that has been elaborated anyway is the
    # model inventing a preference, which is the one thing an unattended sweep
    # must not do.
    assert aims[label].subject.casefold() == label.casefold(), aims[label].subject


async def test_the_tail_beyond_the_cap_is_not_the_prompts_fault(llm):
    from backend.agents.scout.aiming import MAX_AIMS

    overflowing = INTERESTS + ("Sourdough", "Model Railways")

    plan = await AimPlanner(llm).plan(overflowing, PersonalContext(), _PLACE)

    aims = {item.label: item for item in plan.aims}
    # Only the first MAX_AIMS reach the model; the rest keep the bare label they
    # had before this module existed. Asserted rather than left to be
    # rediscovered, because a bare label in the tail is indistinguishable from
    # the prompt failing to describe it, and reads as the more interesting bug.
    assert len(INTERESTS) == MAX_AIMS
    for label in ("Sourdough", "Model Railways"):
        assert aims[label].profile == label, aims[label]


# A fact, and a word that could only have come from having read it.
FACT_SCENARIOS = (
    (
        "Board Games",
        "They play board games in a group every fortnight and prefer long games.",
        ("long", "group"),
    ),
    (
        "Astronomy",
        "They only observe from dark-sky sites well away from town and dislike crowds.",
        ("dark", "sky"),
    ),
    (
        "Woodworking",
        "They turn bowls on a lathe and are not interested in flat-pack joinery.",
        ("lathe", "turn", "bowl"),
    ),
    (
        "Sea Swimming",
        "They swim in the sea all year round without a wetsuit.",
        ("year", "cold", "winter", "wetsuit"),
    ),
    (
        "Printmaking",
        "They make linocuts and screen prints and want to learn etching.",
        ("lino", "screen", "etch"),
    ),
)


@pytest.mark.xfail(
    reason=(
        "Measured, not suspected. Across the five facts below the profile picks "
        "up the fact 2/5 and the subject 0/5; the previous prompt scored 1/5 and "
        "1/5, and its single subject win was 'Board Games' — the label most "
        "resembling its own worked example 'Run Clubs'. So personalisation from "
        "an approved fact is weak in both, and the test that used to pass was "
        "rewarding the model for recognising the example it had been shown "
        "rather than for reading the person. Recorded rather than loosened: the "
        "module's premise is that a sweep is aimed at someone, and at 2/5 it "
        "mostly is not."
    ),
    strict=False,
)
@pytest.mark.parametrize(
    ("label", "statement", "expected"),
    FACT_SCENARIOS,
    ids=[scenario[0] for scenario in FACT_SCENARIOS],
)
async def test_an_approved_fact_reaches_the_text_it_bears_on(
    llm, label, statement, expected
):
    aimed = await _aim_all(llm, PersonalContext((statement,)))

    written = f"{aimed[label].subject} {aimed[label].profile}".casefold()
    # Personalisation has to be visible in the text, or reading approved memory
    # is an expensive no-op. Asserted on the fact's own vocabulary rather than on
    # "it differs from the unpersonalised run", because a difference can be
    # rewording and only a borrowed word proves the fact was read.
    assert any(term in written for term in expected), written


async def test_one_fact_does_not_redecorate_every_other_interest(llm):
    known = PersonalContext(
        ("They play board games in a group every fortnight and prefer long games.",)
    )

    with_fact = await _aim_all(llm, known)
    without = await _aim_all(llm)

    # Whatever personalisation does reach the text has to stay where it belongs.
    # A model treating the fact block as a style to apply rather than evidence to
    # use rewrites every interest in the voice of one of them.
    unchanged = [
        label
        for label in INTERESTS
        if label != "Board Games"
        and with_fact[label].subject.casefold() == without[label].subject.casefold()
    ]
    assert len(unchanged) >= len(INTERESTS) - 3, [
        (label, with_fact[label].subject) for label in INTERESTS
    ]
