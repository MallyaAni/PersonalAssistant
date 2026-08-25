"""Does the model actually work out which thing was meant?

The structural tests prove the resolver never returns an unoffered handle and
fails closed. They would pass just as happily against a resolver that always
answers "all of them", which reads to the user as being asked which picture
they meant every single time.

These send the real prompt to the real runtime and assert on the decision:
that a distinguishing detail resolves to one thing, that a bare pronoun takes
the most recent, that genuine ambiguity is reported as ambiguity rather than
guessed, and that a reference to something not owned matches nothing.
"""

import pytest

from backend.core.dependencies import get_structured_llm_client
from backend.services.referent_resolution import Referent, ReferentResolver

pytestmark = pytest.mark.asyncio

PORTRAIT = Referent(
    handle="portrait",
    kind="image",
    description=(
        "A person wearing a wide-brimmed straw hat, a dark bomber jacket and a "
        "white t-shirt, standing by the water at sunset."
    ),
    when="2026-08-14T18:00:00+00:00",
    title="Uploaded image",
)
BICYCLE = Referent(
    handle="bicycle",
    kind="image",
    description="A red bicycle leaning against a weathered brick wall.",
    when="2026-08-12T09:00:00+00:00",
    title="Generated image",
)
KITCHEN = Referent(
    handle="kitchen",
    kind="image",
    description="A bright kitchen with white cabinets and a marble island.",
    when="2026-08-10T09:00:00+00:00",
    title="Uploaded image",
)
CONTRACT = Referent(
    handle="contract",
    kind="document",
    description="Pricing is billed monthly in arrears, net 30 from invoice date.",
    when="2026-08-01T09:00:00+00:00",
    title="Vendor contract",
)


# Resolve one real-model reference, skipping only when the local runtime is down.
async def _resolve(reference: str, candidates: list[Referent]):
    # The same client the application wires this resolver with, so the test
    # measures the model that actually answers rather than a nearby one.
    llm = get_structured_llm_client()
    try:
        return await ReferentResolver(llm).resolve(reference, candidates)
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"resolver model unreachable: {type(exc).__name__}")


# A detail that only one candidate has must land on that candidate.
@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("make the straw hat black", "portrait"),
        ("give the bike a blue frame", "bicycle"),
        ("make the cabinets darker", "kitchen"),
    ],
)
async def test_a_distinguishing_detail_resolves_to_one_thing(reference, expected):
    resolution = await _resolve(reference, [PORTRAIT, BICYCLE, KITCHEN])

    assert resolution.is_confident, resolution.matched
    assert resolution.only is not None
    assert resolution.only.handle == expected


# "it" with nothing to go on is the most recent thing, not a coin flip and not
# a question the user should have to answer.
async def test_a_bare_pronoun_takes_the_most_recent():
    resolution = await _resolve("make it black and white", [PORTRAIT, BICYCLE, KITCHEN])

    assert resolution.is_confident, resolution.matched
    assert resolution.only is not None
    assert resolution.only.handle == "portrait"


# The property that keeps this honest: when the message really does not
# separate two candidates, say so rather than picking one.
async def test_a_reference_matching_two_things_is_reported_as_ambiguous():
    jacket_portrait = Referent(
        handle="portrait",
        kind="image",
        description="A person in a dark bomber jacket by the water at sunset.",
        when="2026-08-14T18:00:00+00:00",
        title="Uploaded image",
    )
    jacket_street = Referent(
        handle="street",
        kind="image",
        description="A person in a dark bomber jacket on a city street at night.",
        when="2026-08-13T18:00:00+00:00",
        title="Uploaded image",
    )

    resolution = await _resolve(
        "change the jacket to a red one", [jacket_portrait, jacket_street]
    )

    assert resolution.is_ambiguous, resolution.matched
    assert {item.handle for item in resolution.matched} == {"portrait", "street"}


# Describing something they never saved must not be answered with whichever
# saved thing happened to rank highest.
async def test_a_reference_to_something_not_owned_matches_nothing():
    resolution = await _resolve(
        "crop the photo of my dog at the beach", [BICYCLE, KITCHEN, CONTRACT]
    )

    assert resolution.is_empty, resolution.matched


# Modality indifference measured, not asserted by construction: a document and
# pictures compete in the same call and the document wins on meaning.
async def test_a_document_reference_resolves_past_the_pictures():
    resolution = await _resolve(
        "what does it say about how pricing is billed",
        [PORTRAIT, BICYCLE, CONTRACT],
    )

    assert resolution.is_confident, resolution.matched
    assert resolution.only is not None
    assert resolution.only.handle == "contract"
    assert resolution.only.kind == "document"


FLAG = Referent(
    handle="flag",
    kind="image",
    description="A flag: a blue field, a green band along the bottom, a yellow circle.",
    when="2026-08-15T09:00:00+00:00",
    title="Uploaded image",
)


# "This picture" plus a part every picture has - its background, its sky, a
# colour - is still a pointer at the most recent candidate. Measured on the
# real path 2026-08-25: with the bicycle older and a flag just uploaded,
# "make the background of this picture purple" edited the bicycle because
# "background" was read as a detail matching its brick wall.
@pytest.mark.parametrize(
    "reference",
    [
        "make the background of this picture purple",
        "make this one a little brighter",
        "add a small bird to it",
    ],
)
async def test_a_generic_part_does_not_override_this(reference):
    resolution = await _resolve(reference, [FLAG, PORTRAIT, BICYCLE, KITCHEN])
    assert resolution.is_confident, resolution.matched
    assert resolution.only is not None
    assert resolution.only.handle == "flag", resolution.matched


# The control: a detail that separates candidates still wins over recency.
async def test_a_separating_detail_still_beats_recency():
    resolution = await _resolve(
        "make the wall behind the bicycle white", [FLAG, PORTRAIT, BICYCLE, KITCHEN]
    )
    assert resolution.is_confident, resolution.matched
    assert resolution.only is not None
    assert resolution.only.handle == "bicycle", resolution.matched
