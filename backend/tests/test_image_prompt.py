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
        text_encoder="qwen_3_4b.safetensors",
        vae="flux2-vae.safetensors",
        steps=4,
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
    assert workflow["4"]["inputs"]["text"] == "a dog, photorealistic"
    assert workflow["1"]["class_type"] == "UNETLoader"
    assert workflow["2"]["inputs"]["type"] == "flux2"
    assert workflow["6"]["class_type"] == "EmptyFlux2LatentImage"
    assert workflow["7"]["inputs"]["steps"] == 4
    assert workflow["8"]["inputs"]["noise_seed"] == 1


def _provider_with_writing(text_suffix: str) -> ComfyUIImageProvider:
    return ComfyUIImageProvider(
        base_url="http://localhost:8188",
        model="m",
        timeout_seconds=1.0,
        poll_seconds=0.1,
        max_concurrency=1,
        max_output_bytes=1024,
        max_pixels=4096,
        text_encoder="qwen_3_4b.safetensors",
        vae="flux2-vae.safetensors",
        steps=4,
        style_suffix="photorealistic",
        portrait_suffix="natural skin",
        text_suffix=text_suffix,
    )


# The language of any writing rides last on every prompt, after the style
# steer and the portrait wording, so it reads as a condition on the picture.
def test_writing_language_clause_is_appended_last() -> None:
    provider = _provider_with_writing("any writing is in English")
    assert provider._positive_prompt("a shop sign", depicts_a_person=False) == (
        "a shop sign, photorealistic, any writing is in English"
    )
    assert provider._positive_prompt("a shopkeeper", depicts_a_person=True) == (
        "a shopkeeper, photorealistic, natural skin, any writing is in English"
    )


def test_writing_language_clause_is_not_duplicated_or_forced() -> None:
    provider = _provider_with_writing("any writing is in English")
    assert provider._positive_prompt("a poster, ANY WRITING IS IN ENGLISH") == (
        "a poster, ANY WRITING IS IN ENGLISH, photorealistic"
    )
    assert _provider_with_writing("")._positive_prompt("a cat") == "a cat, photorealistic"
