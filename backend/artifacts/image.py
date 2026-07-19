import asyncio
import io
import time
import warnings
from contextlib import suppress
from typing import Any, cast

import httpx
from PIL import Image, UnidentifiedImageError

from backend.artifacts.types import (
    GeneratedImage,
    ImageGenerationRequest,
    ValidatedImage,
)
from backend.core.interfaces import ImageProvider

_FORMAT_DETAILS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


# Decode image headers and enforce bounded, single-frame supported media.
def validate_image_bytes(
    content: bytes,
    declared_mime_type: str | None,
    max_bytes: int,
    max_pixels: int,
) -> ValidatedImage:
    if not content or len(content) > max_bytes:
        raise ValueError("Image size is outside the accepted limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                image_format = str(image.format or "").upper()
                details = _FORMAT_DETAILS.get(image_format)
                if details is None:
                    raise ValueError("Image format is not supported")
                mime_type, extension = details
                if declared_mime_type and declared_mime_type.lower() != mime_type:
                    raise ValueError("Declared image type does not match its content")
                if int(getattr(image, "n_frames", 1)) != 1:
                    raise ValueError("Animated images are not supported")
                width, height = image.size
                if width < 1 or height < 1 or width * height > max_pixels:
                    raise ValueError("Image dimensions are outside the accepted limit")
                image.verify()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise ValueError("Image content could not be validated") from exc
    return ValidatedImage(
        mime_type=mime_type,
        extension=extension,
        width=width,
        height=height,
    )


class ComfyUIImageProvider(ImageProvider):
    # Configure one bounded local ComfyUI provider and its shared concurrency gate.
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float,
        poll_seconds: float,
        max_concurrency: int,
        max_output_bytes: int,
        max_pixels: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self.max_output_bytes = max_output_bytes
        self.max_pixels = max_pixels
        self._semaphore = asyncio.Semaphore(max_concurrency)

    # Submit, monitor, fetch, and validate one local HiDream image job.
    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        async with self._semaphore:
            started_at = time.monotonic()
            prompt_id: str | None = None
            timeout = httpx.Timeout(self.timeout_seconds)
            async with httpx.AsyncClient(timeout=timeout) as client:
                try:
                    response = await client.post(
                        f"{self.base_url}/prompt",
                        json={"prompt": self._workflow(request)},
                    )
                    response.raise_for_status()
                    submitted = cast(dict[str, Any], response.json())
                    prompt_id = str(submitted.get("prompt_id") or "")
                    if not prompt_id or submitted.get("node_errors"):
                        raise RuntimeError("ComfyUI rejected the image workflow")
                    output = await self._wait_for_output(client, prompt_id)
                    image_response = await client.get(
                        f"{self.base_url}/view",
                        params=output,
                    )
                    image_response.raise_for_status()
                    content = image_response.content
                    validated = validate_image_bytes(
                        content,
                        image_response.headers.get("content-type", "").split(";")[0],
                        self.max_output_bytes,
                        self.max_pixels,
                    )
                except asyncio.CancelledError:
                    if prompt_id:
                        await self._interrupt(client, prompt_id)
                    raise
            return GeneratedImage(
                content=content,
                mime_type=validated.mime_type,
                width=validated.width,
                height=validated.height,
                provider_job_id=prompt_id,
                metadata={
                    "seed": request.seed,
                    "steps": 28,
                    "elapsed_seconds": round(time.monotonic() - started_at, 3),
                },
            )

    # Poll one ComfyUI job until it exposes a successful output or terminal error.
    async def _wait_for_output(
        self,
        client: httpx.AsyncClient,
        prompt_id: str,
    ) -> dict[str, str]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = await client.get(f"{self.base_url}/history/{prompt_id}")
            response.raise_for_status()
            history = cast(dict[str, Any], response.json())
            entry = history.get(prompt_id)
            if entry:
                status = cast(dict[str, Any], entry.get("status", {}))
                if status.get("status_str") == "error":
                    raise RuntimeError("ComfyUI image generation failed")
                if status.get("completed"):
                    return self._extract_output(cast(dict[str, Any], entry))
            await asyncio.sleep(self.poll_seconds)
        raise TimeoutError("ComfyUI image generation timed out")

    # Extract one saved output descriptor from a completed ComfyUI history record.
    def _extract_output(self, entry: dict[str, Any]) -> dict[str, str]:
        outputs = cast(dict[str, Any], entry.get("outputs", {}))
        for node_output in outputs.values():
            images = (
                node_output.get("images", []) if isinstance(node_output, dict) else []
            )
            if images and isinstance(images[0], dict):
                first = images[0]
                return {
                    "filename": str(first.get("filename", "")),
                    "subfolder": str(first.get("subfolder", "")),
                    "type": str(first.get("type", "output")),
                }
        raise RuntimeError("ComfyUI completed without an image output")

    # Ask ComfyUI to interrupt only the cancelled provider job.
    async def _interrupt(self, client: httpx.AsyncClient, prompt_id: str) -> None:
        with suppress(httpx.HTTPError):
            await client.post(
                f"{self.base_url}/interrupt",
                json={"prompt_id": prompt_id},
            )

    # Build the pinned minimal HiDream Dev API workflow.
    def _workflow(self, request: ImageGenerationRequest) -> dict[str, Any]:
        return {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": self.model},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": request.prompt, "clip": ["1", 1]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "", "clip": ["1", 1]},
            },
            "4": {
                "class_type": "ModelNoiseScale",
                "inputs": {"model": ["1", 0], "noise_scale": 7.6},
            },
            "5": {
                "class_type": "BasicScheduler",
                "inputs": {
                    "model": ["4", 0],
                    "scheduler": "normal",
                    "steps": 28,
                    "denoise": 1.0,
                },
            },
            "6": {
                "class_type": "SamplerLCM",
                "inputs": {
                    "s_noise": 1.0,
                    "s_noise_end": 1.0,
                    "noise_clip_std": 2.5,
                },
            },
            "7": {
                "class_type": "EmptyHiDreamO1LatentImage",
                "inputs": {
                    "width": request.width,
                    "height": request.height,
                    "batch_size": 1,
                },
            },
            "8": {
                "class_type": "SamplerCustom",
                "inputs": {
                    "model": ["4", 0],
                    "add_noise": True,
                    "noise_seed": request.seed,
                    "cfg": 1.0,
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "sampler": ["6", 0],
                    "sigmas": ["5", 0],
                    "latent_image": ["7", 0],
                },
            },
            "9": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["8", 0], "vae": ["1", 2]},
            },
            "10": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["9", 0],
                    "filename_prefix": "anios_generated",
                },
            },
        }
