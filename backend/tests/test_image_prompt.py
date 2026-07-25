from backend.artifacts.image import ComfyUIImageProvider
from backend.artifacts.types import ImageGenerationRequest


def _provider(style_suffix: str) -> ComfyUIImageProvider:
    return ComfyUIImageProvider(
        base_url="http://localhost:8188",
        model="m",
        timeout_seconds=1.0,
        poll_seconds=0.1,
        max_concurrency=1,
        max_output_bytes=1024,
        max_pixels=4096,
        style_suffix=style_suffix,
    )


def test_style_suffix_is_appended_for_realism() -> None:
    provider = _provider("photorealistic, sharp focus")
    assert (
        provider._positive_prompt("a cat on a sofa")
        == "a cat on a sofa, photorealistic, sharp focus"
    )


def test_style_suffix_is_not_duplicated_when_already_present() -> None:
    provider = _provider("photorealistic")
    # Case-insensitive, so a prompt already asking for realism is left alone.
    assert provider._positive_prompt("a Photorealistic portrait") == (
        "a Photorealistic portrait"
    )


def test_empty_suffix_sends_the_prompt_verbatim() -> None:
    provider = _provider("")
    assert provider._positive_prompt("a cat") == "a cat"


def test_workflow_positive_node_uses_the_composed_prompt() -> None:
    provider = _provider("photorealistic")
    workflow = provider._workflow(
        ImageGenerationRequest(prompt="a dog", width=1024, height=1024, seed=1)
    )
    assert workflow["2"]["inputs"]["text"] == "a dog, photorealistic"
    # The negative node stays empty: it is inert at the model's cfg=1.0.
    assert workflow["3"]["inputs"]["text"] == ""
