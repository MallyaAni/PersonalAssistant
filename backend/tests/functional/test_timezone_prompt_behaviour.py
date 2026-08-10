"""Does the model actually place a city in the right zone?

The validation tests prove an invented zone is discarded. They cannot tell you
whether anything survives validation at all — a resolver that refuses every
answer passes them and leaves every account on the fallback zone. That is what
these measure, against the running model.

The places are chosen to be the ones that get this wrong in practice: zones
whose name is not the nearest big city, countries that span several zones, and
one deliberately unanswerable place.
"""

import pytest

from backend.agents.scout.timezones import TimezoneResolver

pytestmark = pytest.mark.asyncio


# The zone the place observes, which is the thing a schedule needs — not the
# zone named after the nearest famous city.
@pytest.mark.parametrize(
    ("place", "expected"),
    [
        ("Canggu, Bali, Indonesia", "Asia/Makassar"),
        ("Arlington, Virginia", "America/New_York"),
        ("London, United Kingdom", "Europe/London"),
        ("Mumbai, India", "Asia/Kolkata"),
        ("Brisbane, Australia", "Australia/Brisbane"),
        ("Phoenix, Arizona", "America/Phoenix"),
        ("São Paulo, Brazil", "America/Sao_Paulo"),
        ("Vancouver, Canada", "America/Vancouver"),
    ],
)
async def test_a_named_place_resolves_to_the_zone_it_observes(
    llm: object, place: str, expected: str
) -> None:
    assert await TimezoneResolver(llm).resolve(place) == expected


async def test_a_place_too_vague_to_place_resolves_to_nothing(llm: object) -> None:
    # Several zones, no way to choose. Storing any one of them would be a guess
    # presented as a fact.
    assert await TimezoneResolver(llm).resolve("the countryside") is None


# A bare city name that exists in several countries is the failure this whole
# resolver is for. "Alexandria" resolved to Africa/Cairo for an account in
# Alexandria, Virginia — a confident, plausible, eight-hour error that no part
# of the product would have contradicted.
@pytest.mark.parametrize(
    "ambiguous",
    ["Alexandria", "Arlington", "Springfield", "Cambridge", "Richmond"],
)
async def test_a_name_that_belongs_to_several_places_is_refused(
    llm: object, ambiguous: str
) -> None:
    assert await TimezoneResolver(llm).resolve(ambiguous) is None


# ...and the same name resolves once the region that disambiguates it is
# passed, which is what the locality's `region` column is for.
@pytest.mark.parametrize(
    ("place", "region", "expected"),
    [
        ("Alexandria", "Virginia", "America/New_York"),
        ("Alexandria", "Egypt", "Africa/Cairo"),
        ("Arlington", "Texas", "America/Chicago"),
        ("Cambridge", "United Kingdom", "Europe/London"),
    ],
)
async def test_a_region_settles_an_otherwise_ambiguous_name(
    llm: object, place: str, region: str, expected: str
) -> None:
    assert await TimezoneResolver(llm).resolve(place, region) == expected
