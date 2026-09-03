import functools
import json

import httpx
import pytest

from backend.agents.vision.upload import UploadInspectionDecision
from backend.vision.lm_studio import (
    OpenAICompatibleVisionProvider,
    create_vision_provider,
)


# Verify the configured adapter constructs the neutral vision implementation.
def test_vision_factory_selects_openai_compatible_adapter():
    provider = create_vision_provider(
        adapter="openai_compatible",
        base_url="http://provider.local",
        model="vision-model",
        api_key=None,
        timeout_seconds=30,
        reasoning_effort="none",
    )

    assert isinstance(provider, OpenAICompatibleVisionProvider)
    assert provider.base_url == "http://provider.local"
    assert provider.model == "vision-model"


# Verify unknown vision adapters fail closed during dependency construction.
def test_vision_factory_rejects_unknown_adapter():
    with pytest.raises(
        ValueError,
        match="Unsupported vision inference adapter: unknown",
    ):
        create_vision_provider(
            adapter="unknown",
            base_url="http://provider.local",
            model="vision-model",
            api_key=None,
            timeout_seconds=30,
            reasoning_effort="none",
        )


# Verify one upload produces one strict multimodal request and typed decisions.
@pytest.mark.asyncio
async def test_structured_upload_inspection_uses_one_provider_call(monkeypatch):
    requests: list[dict] = []

    # Return one grammar-constrained OpenAI-compatible completion.
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        content = json.dumps(
            {
                "intent": "ask",
                "observation": "Several processed fish portions with no labels.",
                "answer": "The exact species cannot be identified from these cuts.",
                "grounding": "unsupported",
                "search_query": "",
                "needs_reasoning": False,
                "unsupported_reason": "missing_visual_evidence",
                "identified_items": [
                    {
                        "label": "Indian major carp",
                        "confidence": "medium",
                        "basis": "suggested only by regional context",
                    }
                ],
            }
        )
        return httpx.Response(
            200,
            json={
                "model": "vision-model",
                "choices": [{"message": {"content": content}}],
                "usage": {"total_tokens": 42},
            },
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "backend.vision.lm_studio.httpx.AsyncClient",
        functools.partial(httpx.AsyncClient, transport=transport),
    )
    provider = OpenAICompatibleVisionProvider(
        "http://provider.local",
        "vision-model",
        None,
        30,
        "none",
    )

    result = await provider.inspect_upload(
        "Identify these fish",
        b"image-bytes",
        "image/jpeg",
    )

    assert len(requests) == 1
    schema = requests[0]["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["required"] == [
        "intent",
        "observation",
        "answer",
        "grounding",
        "search_query",
        "needs_reasoning",
        "unsupported_reason",
        "identified_items",
    ]
    assert result.grounding == "unsupported"
    assert result.needs_reasoning is False
    assert len(result.identified_items) == 1
    assert result.identified_items[0].confidence == "medium"


# Recover a shape-valid cross-field contradiction instead of failing the upload.
def test_unsupported_reason_is_inferred_from_item_uncertainty() -> None:
    decision = UploadInspectionDecision.model_validate(
        {
            "intent": "ask",
            "observation": "One clear item and one uncertain item.",
            "answer": "One item remains uncertain.",
            "grounding": "unsupported",
            "search_query": "",
            "needs_reasoning": False,
            "unsupported_reason": "not_applicable",
            "identified_items": [
                {
                    "label": "possible device",
                    "confidence": "medium",
                    "basis": "some controls are visible",
                }
            ],
        }
    )

    assert decision.unsupported_reason == "model_uncertain"


# A phone photo is scaled to fit the model before it is encoded; a small one
# is untouched; bytes the library cannot read pass through for the server
# to judge. Caroline's 4032x3024 photo was 16,809 tokens against a 16,384
# context on 2026-09-02, and the reply was "I hit a problem".
def _image_bytes(size, mode="RGB", fmt="JPEG"):
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new(mode, size, "gray").save(buffer, format=fmt)
    return buffer.getvalue()


def test_a_phone_photo_is_scaled_to_fit_the_model():
    import io

    from PIL import Image

    from backend.vision.lm_studio import MAX_IMAGE_PIXELS, MAX_IMAGE_SIDE, fit_for_model

    fitted, mime = fit_for_model(_image_bytes((4032, 3024)), "image/jpeg")
    with Image.open(io.BytesIO(fitted)) as image:
        assert image.size[0] * image.size[1] <= MAX_IMAGE_PIXELS
        assert max(image.size) <= MAX_IMAGE_SIDE
        assert abs(image.size[0] / image.size[1] - 4032 / 3024) < 0.01
    assert mime == "image/jpeg"


def test_a_small_picture_and_unreadable_bytes_pass_through():
    from backend.vision.lm_studio import fit_for_model

    small = _image_bytes((640, 480), fmt="PNG")
    assert fit_for_model(small, "image/png") == (small, "image/png")
    assert fit_for_model(b"not an image", "image/heic") == (b"not an image", "image/heic")


def test_transparency_survives_the_fit_as_png():
    import io

    from PIL import Image

    from backend.vision.lm_studio import fit_for_model

    fitted, mime = fit_for_model(_image_bytes((3000, 3000), mode="RGBA", fmt="PNG"), "image/png")
    assert mime == "image/png"
    with Image.open(io.BytesIO(fitted)) as image:
        assert image.mode == "RGBA" and image.size[0] * image.size[1] <= 2_000_000


def test_a_format_the_server_may_not_read_is_re_encoded_even_when_small():
    import io

    from PIL import Image

    from backend.vision.lm_studio import fit_for_model

    # TIFF stands in for a phone's HEIC: readable here, not a web format.
    fitted, mime = fit_for_model(_image_bytes((400, 300), fmt="TIFF"), "image/jpeg")
    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(fitted)) as image:
        assert image.format == "JPEG" and image.size == (400, 300)
