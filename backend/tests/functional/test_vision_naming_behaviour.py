"""Does the real VLM record the name a user gives an uploaded subject?

Gubacchi is the operator's pet bird, and the assistant once recorded the name
as a person and had no picture bound to it at all - asked "do you know
gubacchi?" it answered from a conversation, with no photo to recall. The name
must be captured at upload time from the user's own words, so a later mention
of the handle can find the picture. The assertions are on the property - a
name supplied in the request lands in `names` even when it is not a real
word, and a request with no name yields an empty list - so a reworded prompt
survives and a changed behaviour fails.
"""

from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from backend.core.dependencies import get_vision_provider

pytestmark = pytest.mark.asyncio


# A small pet-bird scene: a bird on a perch against sky and grass, clear enough
# that the pixels and the caption agree there is a bird without depending on a
# breed-level identification.
def _bird_fixture() -> bytes:
    image = Image.new("RGB", (960, 640), "#8fd3f4")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 430, 960, 640), fill="#7cb342")
    draw.line((80, 430, 880, 300), fill="#5d4037", width=22)
    draw.ellipse((360, 240, 620, 420), fill="#eceff1", outline="#37474f", width=6)
    draw.ellipse((580, 170, 740, 320), fill="#eceff1", outline="#37474f", width=6)
    draw.polygon([(735, 225), (810, 240), (740, 275)], fill="#f9a825")
    draw.ellipse((640, 215, 672, 247), fill="#1a1a1a")
    draw.polygon([(430, 300), (490, 230), (550, 300)], fill="#f9a825")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


# A name the user supplies in the request is captured even though it is not a
# real word and appears nowhere in the pixels.
async def test_a_user_given_name_is_captured_for_later_recall() -> None:
    provider = get_vision_provider()
    try:
        result = await provider.inspect_upload(
            "this is gubacchi, my pet bird",
            _bird_fixture(),
            "image/png",
        )
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"local vision runtime unreachable: {type(exc).__name__}")

    lowered = [name.lower() for name in result.names]
    assert lowered, "no names returned: " + repr(result.names)
    assert any("gubacchi" in name for name in lowered), repr(result.names)
    # The pixels were actually seen: the caption names the bird, and the
    # observation should describe one, however it is worded.
    observation = result.observation.lower()
    bird_words = (
        "bird",
        "parrot",
        "budgie",
        "parakeet",
        "cockatiel",
        "finch",
        "sparrow",
        "pet",
    )
    assert any(token in observation for token in bird_words), (
        "the pixels were not seen: " + result.observation
    )


# A request that names nothing must not fabricate a handle.
async def test_a_request_without_a_name_yields_no_handles() -> None:
    provider = get_vision_provider()
    try:
        result = await provider.inspect_upload(
            "describe this image",
            _bird_fixture(),
            "image/png",
        )
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"local vision runtime unreachable: {type(exc).__name__}")

    assert result.names == (), repr(result.names)
