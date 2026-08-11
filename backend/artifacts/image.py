import asyncio
import hashlib
import io
import time
import warnings
from contextlib import suppress
from typing import Any, cast
from uuid import uuid4

import httpx
from PIL import Image, UnidentifiedImageError

from backend.artifacts.image_subject import mentions_a_person
from backend.artifacts.types import (
    GeneratedImage,
    ImageEditRequest,
    ImageGenerationRequest,
    ValidatedImage,
)
from backend.core.interfaces import ImageEditProvider, ImageProvider

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
        style_suffix: str = "",
        portrait_suffix: str = "",
        negative_prompt: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.style_suffix = style_suffix.strip().strip(",").strip()
        self.portrait_suffix = portrait_suffix.strip().strip(",").strip()
        self.negative_prompt = negative_prompt.strip().strip(",").strip()
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
    # Append the realism suffix unless the prompt already carries it, so the
    # user's wording leads and the style steer follows.
    def _positive_prompt(self, prompt: str) -> str:
        text = prompt.strip()
        parts = [text] if text else []
        if self.style_suffix and self.style_suffix.lower() not in text.lower():
            parts.append(self.style_suffix)
        # Skin and hair wording only when a person was asked for. Applied
        # unconditionally it does not describe the subject, it invents one.
        if (
            self.portrait_suffix
            and mentions_a_person(text)
            and self.portrait_suffix.lower() not in text.lower()
        ):
            parts.append(self.portrait_suffix)
        return ", ".join(parts)

    def _workflow(self, request: ImageGenerationRequest) -> dict[str, Any]:
        return {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": self.model},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": self._positive_prompt(request.prompt),
                    "clip": ["1", 1],
                },
            },
            # The negative conditioning was empty, so nothing counterweighted
            # the checkpoint's own priors.
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": self.negative_prompt, "clip": ["1", 1]},
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


class ComfyUIImageEditProvider(ComfyUIImageProvider, ImageEditProvider):
    """Edit a source image with the native FLUX.2 Klein ComfyUI workflow."""

    # Configure FLUX.2 Klein's four-step editor on the shared ComfyUI runtime.
    def __init__(
        self,
        base_url: str,
        model: str,
        text_encoder: str,
        vae: str,
        timeout_seconds: float,
        poll_seconds: float,
        max_concurrency: int,
        max_output_bytes: int,
        max_pixels: int,
        steps: int,
        megapixels: float = 1.0,
        scale_method: str = "lanczos",
    ) -> None:
        super().__init__(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            max_concurrency=max_concurrency,
            max_output_bytes=max_output_bytes,
            max_pixels=max_pixels,
        )
        self.text_encoder = text_encoder
        self.vae = vae
        self.steps = steps
        self.megapixels = megapixels
        self.scale_method = scale_method

    # Upload the owned source, run the editor, and return one validated candidate.
    async def edit(self, request: ImageEditRequest) -> GeneratedImage:
        async with self._semaphore:
            started_at = time.monotonic()
            prompt_id: str | None = None
            timeout = httpx.Timeout(self.timeout_seconds)
            async with httpx.AsyncClient(timeout=timeout) as client:
                try:
                    source_name = await self._upload_source(client, request)
                    response = await client.post(
                        f"{self.base_url}/prompt",
                        json={"prompt": self._edit_workflow(request, source_name)},
                    )
                    response.raise_for_status()
                    submitted = cast(dict[str, Any], response.json())
                    prompt_id = str(submitted.get("prompt_id") or "")
                    if not prompt_id or submitted.get("node_errors"):
                        raise RuntimeError("ComfyUI rejected the image-edit workflow")
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
                    "steps": self.steps,
                    "source_sha256": hashlib.sha256(request.source_content).hexdigest(),
                    "elapsed_seconds": round(time.monotonic() - started_at, 3),
                },
            )

    # Place one source image in ComfyUI's temporary area for this edit workflow.
    async def _upload_source(
        self,
        client: httpx.AsyncClient,
        request: ImageEditRequest,
    ) -> str:
        extension = request.source_mime_type.removeprefix("image/").replace(
            "jpeg", "jpg"
        )
        filename = f"{uuid4().hex}.{extension}"
        response = await client.post(
            f"{self.base_url}/upload/image",
            data={
                "type": "temp",
                "subfolder": "anios_edits",
                "overwrite": "false",
            },
            files={
                "image": (
                    filename,
                    request.source_content,
                    request.source_mime_type,
                )
            },
        )
        response.raise_for_status()
        uploaded = cast(dict[str, Any], response.json())
        stored_name = str(uploaded.get("name") or "")
        stored_subfolder = str(uploaded.get("subfolder") or "")
        stored_type = str(uploaded.get("type") or "")
        if not stored_name or stored_type != "temp":
            raise RuntimeError("ComfyUI did not accept the image-edit source")
        relative_name = (
            f"{stored_subfolder}/{stored_name}" if stored_subfolder else stored_name
        )
        return f"{relative_name} [temp]"

    # Build ComfyUI's native FLUX.2 Klein source-conditioned workflow.
    def _edit_workflow(
        self,
        request: ImageEditRequest,
        source_name: str,
    ) -> dict[str, Any]:
        return {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": source_name},
            },
            "2": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": self.model,
                    "weight_dtype": "default",
                },
            },
            "3": {
                "class_type": "CLIPLoader",
                "inputs": {
                    "clip_name": self.text_encoder,
                    "type": "flux2",
                    "device": "default",
                },
            },
            "4": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": self.vae},
            },
            # The source is resampled here, and this node decides the quality
            # ceiling of the whole edit: the output is generated at whatever
            # size this produces. ComfyUI's own template uses `nearest-exact`,
            # which drops pixels instead of averaging them and stipples skin and
            # hair on any photograph.
            "5": {
                "class_type": "ImageScaleToTotalPixels",
                "inputs": {
                    "image": ["1", 0],
                    "upscale_method": self.scale_method,
                    "megapixels": self.megapixels,
                    "resolution_steps": 1,
                },
            },
            "6": {
                "class_type": "GetImageSize",
                "inputs": {"image": ["5", 0]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["3", 0],
                    "text": request.instruction.strip(),
                },
            },
            "8": {
                "class_type": "ConditioningZeroOut",
                "inputs": {"conditioning": ["7", 0]},
            },
            "9": {
                "class_type": "VAEEncode",
                "inputs": {
                    "pixels": ["5", 0],
                    "vae": ["4", 0],
                },
            },
            "10": {
                "class_type": "ReferenceLatent",
                "inputs": {
                    "conditioning": ["7", 0],
                    "latent": ["9", 0],
                },
            },
            "11": {
                "class_type": "ReferenceLatent",
                "inputs": {
                    "conditioning": ["8", 0],
                    "latent": ["9", 0],
                },
            },
            "12": {
                "class_type": "EmptyFlux2LatentImage",
                "inputs": {
                    "width": ["6", 0],
                    "height": ["6", 1],
                    "batch_size": 1,
                },
            },
            "13": {
                "class_type": "Flux2Scheduler",
                "inputs": {
                    "steps": self.steps,
                    "width": ["6", 0],
                    "height": ["6", 1],
                },
            },
            "14": {
                "class_type": "RandomNoise",
                "inputs": {"noise_seed": request.seed},
            },
            "15": {
                "class_type": "CFGGuider",
                "inputs": {
                    "model": ["2", 0],
                    "positive": ["10", 0],
                    "negative": ["11", 0],
                    "cfg": 1.0,
                },
            },
            "16": {
                "class_type": "KSamplerSelect",
                "inputs": {"sampler_name": "euler"},
            },
            "17": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {
                    "noise": ["14", 0],
                    "guider": ["15", 0],
                    "sampler": ["16", 0],
                    "sigmas": ["13", 0],
                    "latent_image": ["12", 0],
                },
            },
            "18": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["17", 0],
                    "vae": ["4", 0],
                },
            },
            "19": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["18", 0],
                    "filename_prefix": "anios_edited",
                },
            },
        }
