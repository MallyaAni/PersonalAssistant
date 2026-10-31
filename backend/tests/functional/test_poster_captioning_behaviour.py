"""A real poster is read by the real vision model, and its words reach the caption.

Scout fetches a selected find's poster because the listing's prose often omits
the date, venue or performers the poster states. Structural tests prove the
call happens; this one proves the answer carries what the picture said, which
is the only reason to spend the call. The fetch is stubbed - it is unit-tested
elsewhere - and everything after it is the runtime a sweep actually uses.
"""

import io

import pytest

from backend.agents.scout.seeing import PICTURE_PROMPT, PictureCaptioner
from backend.discovery.fetching import RequestBudget

pytestmark = pytest.mark.asyncio


# A deterministic poster carrying the three things a listing often leaves out:
# what it is, where, and when. The words are large enough to be read.
def _poster() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1200, 1600), "#f4ecd8")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 1180, 1200, 1600), fill="#2f4858")
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
    except OSError:
        font = ImageFont.load_default()
    draw.text((80, 120), "RIVERSIDE JAZZ NIGHT", fill="#1d1d1f", font=font)
    draw.text((80, 260), "The Wharf, Old Town", fill="#1d1d1f", font=font)
    draw.text((80, 400), "Saturday September 12", fill="#1d1d1f", font=font)
    draw.text((80, 540), "Doors 7:30pm", fill="#1d1d1f", font=font)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


# Serve the poster from the captioner's fetch step without touching the
# network, so the test measures the model's answer rather than a feed host.
def _serve_poster(monkeypatch, poster: bytes) -> None:
    async def fetch(url: str, **kwargs: object) -> tuple[bytes, str]:
        return poster, "image/png"

    monkeypatch.setattr("backend.agents.scout.seeing.fetch_bytes", fetch)


# The caption must state the poster's own words, not merely describe a picture.
async def test_a_poster_is_captioned_with_what_it_states(monkeypatch):
    from backend.core.dependencies import get_vision_provider

    poster = _poster()
    _serve_poster(monkeypatch, poster)
    provider = get_vision_provider()

    caption = await PictureCaptioner(provider).caption(
        "https://example.org/jazz-poster.png", RequestBudget()
    )

    if caption is None:
        # The captioner turns an unreachable runtime into "no caption" by
        # design, so probe once to tell a sleeping Spark from a real failure.
        try:
            await provider.analyze(PICTURE_PROMPT, poster, "image/png")
        except Exception as exc:  # pragma: no cover - depends on the host runtime
            pytest.skip(f"local vision runtime unreachable: {type(exc).__name__}")
        pytest.fail("the runtime answered, but the poster produced no caption")

    low = caption.lower()
    assert low.startswith("a picture published with this listing shows:")
    assert "jazz" in low
    assert "wharf" in low or "old town" in low
    assert "7:30" in low or "7.30" in low or "730" in low
    assert "?" not in caption
