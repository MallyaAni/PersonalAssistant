"""One model call completes a stored locality with its city.

A locality stored as a neighbourhood against a bare state searches a whole
state, so a listing in some other town in that state was judged near the
person. This pins the prompt that names the containing city: a real model
answers real localities, and the assertion is on the property - that the
returned region carries the city when the label is a known neighbourhood, that
it never repeats the label (the label is stored separately and joined to the
region, so echoing it duplicates the place), and that an uncertain label keeps
what was written - not on wording, so a reworded prompt survives. The
deliberately conservative cases are pinned too: a wrong city would anchor
every future search to the wrong place.
"""

from __future__ import annotations

import pytest

from backend.discovery.locality_city import LocalityCityResolver

pytestmark = pytest.mark.asyncio


async def test_a_known_neighbourhood_gains_its_city(llm):
    resolved = await LocalityCityResolver(llm).resolve("Greenpoint", "New York")
    assert resolved is not None
    lowered = resolved.casefold()
    assert "brooklyn" in lowered, resolved
    assert "new york" in lowered, resolved


async def test_a_region_that_already_names_a_city_is_unchanged(llm):
    resolved = await LocalityCityResolver(llm).resolve(
        "Old Town", "Alexandria, Virginia"
    )
    assert resolved is not None
    lowered = resolved.casefold()
    assert "alexandria" in lowered, resolved
    assert "virginia" in lowered, resolved


async def test_a_city_label_is_never_repeated_in_the_region(llm):
    # "Arlington" is the city itself; the region must not echo it back as
    # "Arlington, Virginia", which would duplicate the label when stored.
    resolved = await LocalityCityResolver(llm).resolve("Arlington", "Virginia")
    assert resolved is None or "arlington" not in resolved.casefold(), resolved


async def test_a_label_that_is_itself_a_place_is_not_inflated(llm):
    # "Bali" is the place the label needs; the region must not invent a
    # smaller neighbourhood on top of it, and must not repeat the label.
    resolved = await LocalityCityResolver(llm).resolve("Bali", "Indonesia")
    if resolved is None:
        return  # refused as a label echo - the caller keeps the original
    lowered = resolved.casefold()
    assert "bali" not in lowered, resolved
    assert "indonesia" in lowered, resolved


async def test_an_uncertain_locality_does_not_invent_a_different_city(llm):
    # A made-up label has no real containing city; the safe answers are the
    # region unchanged or a refusal. Introducing some unrelated real city
    # would anchor searches to the wrong place.
    resolved = await LocalityCityResolver(llm).resolve("Zzqxville", "Virginia")
    assert resolved is None or resolved.casefold() == "virginia", resolved
