"""The characterization has to say what the list means, on the real model.

Twenty interests at equal strength could not say that seven of them meant
"social dancer", and the structural tests cannot tell whether this one does -
they would pass just as happily against a model that read the list back with
commas. These send the real prompt and assert on what came out.
"""
import pytest

from backend.core.persona import characterize, forget_personas

pytestmark = pytest.mark.asyncio

DANCER = (
    "line dancing", "vintage shops/thrifting", "hiking", "dancing",
    "unique local events", "farmers markets", "live music", "traveling",
    "exploring new places", "exploring new things", "east coast swing",
    "salsa", "west coast swing", "chess", "swing dancing", "bachata",
    "board games", "karaoke", "wineries", "breweries",
)
HOMEBODY = ("reading", "cooking at home", "the same neighbourhood cafe", "jigsaw puzzles", "gardening")


async def test_it_says_what_seven_dance_entries_mean(llm):
    forget_personas()
    written = (await characterize(llm, DANCER)).casefold()
    assert written
    # The fact the flat list could not hold: six or seven rows are one thing.
    assert "danc" in written
    # And the specifics survive, because "enjoys social activities" would have
    # thrown away everything worth recommending an evening from.
    assert sum(1 for name in ("salsa", "bachata", "swing") if name in written) >= 2
    # Short enough to sit in a prompt without being a thumb on the scale.
    assert len(written.split()) <= 60, written


async def test_it_reads_how_they_like_to_choose(llm):
    forget_personas()
    outgoing = (await characterize(llm, DANCER)).casefold()
    forget_personas()
    settled = (await characterize(llm, HOMEBODY)).casefold()
    # One list says novelty, the other says the same cafe every time, and the
    # description has to be able to tell them apart - that is the whole of
    # "some people like new things and some do not".
    assert any(word in outgoing for word in ("new", "explor", "tr"))
    assert any(word in settled for word in ("quiet", "home", "comfort", "same", "routine"))
    assert "danc" not in settled


async def test_it_invents_nothing_that_was_not_listed(llm):
    forget_personas()
    written = (await characterize(llm, ("chess", "reading"))).casefold()
    assert written
    for absent in ("salsa", "brewery", "hiking", "children", "engineer"):
        assert absent not in written, (absent, written)
