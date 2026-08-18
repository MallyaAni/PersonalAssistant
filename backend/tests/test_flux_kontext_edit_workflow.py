"""The Kontext editor is a different graph, and the differences are the point.

FLUX.2 Klein conditions on the source and is trained to preserve it: measured
against the shipped 4B model, an instruction requiring anything to be added left
the picture unchanged at 4 steps and at 20, at CFG 3.0, and under true img2img
at denoise 0.70. Kontext is trained to follow an editing instruction. Getting
its wiring subtly wrong would look like the same failure, so the pieces that
make it Kontext rather than plain image-to-image are asserted here.
"""

from typing import Any

import pytest

from backend.artifacts.image import FluxKontextImageEditProvider
from backend.artifacts.types import ImageEditRequest

_ONE_PIXEL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100fdff03fa0000000049454e44ae426082"
)


def _provider(**overrides: Any) -> FluxKontextImageEditProvider:
    settings: dict[str, Any] = {
        "base_url": "http://comfy.invalid:8188",
        "model": "flux1-dev-kontext_fp8_scaled.safetensors",
        "clip_name": "clip_l.safetensors",
        "t5_name": "t5xxl_fp8_e4m3fn_scaled.safetensors",
        "vae": "ae.safetensors",
        "timeout_seconds": 60.0,
        "poll_seconds": 0.5,
        "max_concurrency": 1,
        "max_output_bytes": 10_000_000,
        "max_pixels": 4_000_000,
        "steps": 20,
        "guidance": 2.5,
    }
    settings.update(overrides)
    return FluxKontextImageEditProvider(**settings)


def _graph(**overrides: Any) -> dict[str, Any]:
    request = ImageEditRequest(
        instruction="put it in its original packaging",
        source_content=_ONE_PIXEL_PNG,
        source_mime_type="image/png",
        seed=7,
    )
    return _provider(**overrides)._edit_workflow(request, "source.png")


def _node(graph: dict[str, Any], class_type: str) -> dict[str, Any]:
    found = [n for n in graph.values() if n.get("class_type") == class_type]
    assert found, f"{class_type} missing from the workflow"
    return found[0]


# FLUX.1 conditions on CLIP-L plus T5, not on the single Qwen encoder FLUX.2
# uses. Loading the wrong pair produces noise rather than an error.
def test_the_flux1_text_encoders_are_loaded_as_a_pair():
    loader = _node(_graph(), "DualCLIPLoader")

    assert loader["inputs"]["clip_name1"] == "clip_l.safetensors"
    assert loader["inputs"]["clip_name2"] == "t5xxl_fp8_e4m3fn_scaled.safetensors"
    assert loader["inputs"]["type"] == "flux"


# What separates Kontext from ordinary image-to-image: the source latent is
# attached to the conditioning so the instruction is read against the picture.
def test_the_source_latent_conditions_the_instruction():
    graph = _graph()
    reference = _node(graph, "ReferenceLatent")
    encoded = _node(graph, "VAEEncode")

    encode_id = next(k for k, v in graph.items() if v is encoded)
    assert reference["inputs"]["latent"] == [encode_id, 0]
    # And the sampler starts from that same latent rather than from noise.
    assert _node(graph, "KSampler")["inputs"]["latent_image"] == [encode_id, 0]


# FLUX.1 is guidance-distilled: strength is carried on the conditioning, and
# the CFG scale stays at 1.0. Raising CFG instead degrades the image, which is
# what happened when it was tried on the FLUX.2 editor.
def test_instruction_strength_is_carried_as_guidance_not_cfg():
    graph = _graph(guidance=3.5)

    assert _node(graph, "FluxGuidance")["inputs"]["guidance"] == 3.5
    assert _node(graph, "KSampler")["inputs"]["cfg"] == 1.0


@pytest.mark.parametrize("steps", [12, 28])
def test_the_configured_step_count_reaches_the_sampler(steps: int):
    assert _node(_graph(steps=steps), "KSampler")["inputs"]["steps"] == steps


# Four is Klein's operating point and far too few here, which is why the two
# editors take their step counts from different settings.
def test_the_instruction_is_sent_verbatim():
    graph = _graph()

    assert (
        _node(graph, "CLIPTextEncode")["inputs"]["text"]
        == "put it in its original packaging"
    )
