from backend.artifacts.image import ComfyUIImageEditProvider
from backend.artifacts.types import ImageEditRequest


# Build the editor without contacting ComfyUI so workflow structure stays testable.
def _provider() -> ComfyUIImageEditProvider:
    return ComfyUIImageEditProvider(
        base_url="http://comfyui.test",
        model="flux2-klein.safetensors",
        text_encoder="qwen-3.safetensors",
        vae="flux2-vae.safetensors",
        timeout_seconds=10,
        poll_seconds=0.1,
        max_concurrency=1,
        max_output_bytes=10_000_000,
        max_pixels=4_000_000,
        steps=4,
    )


# The workflow must condition on source pixels instead of regenerating from text.
def test_edit_workflow_uses_source_image_and_exact_instruction() -> None:
    request = ImageEditRequest(
        instruction="make only the car red",
        source_content=b"pixels",
        source_mime_type="image/png",
        seed=42,
    )

    workflow = _provider()._edit_workflow(request, "source.png [temp]")

    assert workflow["1"]["class_type"] == "LoadImage"
    assert workflow["1"]["inputs"]["image"] == "source.png [temp]"
    assert workflow["3"]["inputs"]["type"] == "flux2"
    assert workflow["5"]["class_type"] == "ImageScaleToTotalPixels"
    assert workflow["7"]["inputs"]["text"] == "make only the car red"
    assert workflow["9"]["inputs"]["pixels"] == ["5", 0]
    assert workflow["10"]["class_type"] == "ReferenceLatent"
    assert workflow["10"]["inputs"]["latent"] == ["9", 0]
    assert workflow["13"]["inputs"]["steps"] == 4
    assert workflow["14"]["inputs"]["noise_seed"] == 42
    assert workflow["17"]["inputs"]["latent_image"] == ["12", 0]
