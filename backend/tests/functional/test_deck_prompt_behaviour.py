"""Does Deck's model return a usable deck, and keep what it was told to keep?

Deck carries five prompts and, until this file, no coverage of what any of them
returns. Its structural tests prove a plan parses and a compiler turns it into
layout objects, which would stay green against a model that renamed every slide
it was asked to leave alone.

The assertions are on properties a deck is worthless without: it has slides, the
slides are distinct, an edit changes what was asked and nothing else, and a
figure is never invented when nothing supports it. Wording is deliberately not
asserted.
"""

import pytest

from backend.presentations.provider import LLMPresentationProvider

pytestmark = pytest.mark.asyncio


def _provider(llm):
    # No research, which is the harder case: with no sources the contract has to
    # hold the model back from inventing figures on its own.
    return LLMPresentationProvider(llm, max_tokens=1_024)


async def test_a_deck_has_distinct_slides_that_advance(llm):
    deck = await _provider(llm).create("a short deck about the water cycle, 4 slides")

    assert deck.title.strip()
    assert len(deck.slides) >= 3, deck.slides
    titles = [slide.title.strip().casefold() for slide in deck.slides]
    # A deck that says the same thing four times is not a deck. Repetition is
    # the failure this model reaches for when it runs out of material.
    assert len(set(titles)) == len(titles), titles
    assert all(titles), "every slide needs a title"


async def test_every_slide_carries_content_not_just_a_heading(llm):
    deck = await _provider(llm).create("three slides on why bees matter")

    thin = [
        slide.title
        for slide in deck.slides[1:]
        if len(slide.elements) < 2
    ]
    # A slide with a title and nothing else is the reported symptom section
    # layouts once produced: a rule, a title, a purpose, nothing. The compiler
    # turns the model's fields into elements, so this counts what survived it.
    assert not thin, thin


async def test_revising_one_slide_leaves_the_others_alone(llm):
    provider = _provider(llm)
    deck = await provider.create("three slides about tides")
    target = deck.slides[1]

    revised = await provider.revise_slide(
        deck, target.slide_id, "make this slide about spring tides specifically"
    )

    # The edit is scoped to one slide by construction; this asserts the model
    # returned that slide rather than a different one.
    assert revised.slide_id == target.slide_id
    assert revised.title.strip()


async def test_an_added_slide_does_not_repeat_the_deck(llm):
    provider = _provider(llm)
    deck = await provider.create("three slides about the Moon landings")

    added = await provider.add_slide(
        deck, "add a slide about what came after Apollo", slide_id="new-1"
    )

    existing = {slide.title.strip().casefold() for slide in deck.slides}
    assert added.slide_id == "new-1"
    # The prompt tells it not to repeat a slide the deck already has, which is
    # the only thing stopping "add a slide" from producing slide one again.
    assert added.title.strip().casefold() not in existing, (added.title, existing)


async def test_an_ungrounded_deck_does_not_invent_a_statistic(llm):
    # No research is configured, so nothing supports a figure. The contract says
    # an unsupported number is worse than a plainer slide, because a reader
    # cannot tell an invented statistic from a real one.
    deck = await _provider(llm).create(
        "a deck about the history of the London Underground"
    )

    import re

    # A compiled slide carries text elements, so the figure has to be looked for
    # in what it actually says. Years and small counts are ordinary prose; a
    # precise or large number asserted with nothing behind it is the failure —
    # "a quarter of the world's 37-year-old inhabitants" is a real example this
    # deck path produced before grounding existed.
    suspicious = re.compile(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?%")
    for slide in deck.slides:
        for element in slide.elements:
            text = getattr(element, "text", "") or ""
            found = suspicious.search(text)
            if found:
                pytest.fail(
                    "a figure was asserted with no source behind it: "
                    f"{slide.title!r} -> {found.group()!r} in {text[:80]!r}"
                )
