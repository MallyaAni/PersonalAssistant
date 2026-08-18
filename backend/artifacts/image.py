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

from backend.artifacts.types import (
    GeneratedImage,
    ImageEditRequest,
    ImageGenerationRequest,
    ValidatedImage,
)
from backend.core.interfaces import ImageEditProvider, ImageProvider

_FORMAT_DETAILS = {
    "JPEG": ("image/jpeg", "jpg"),
    # Pillow reports a JPEG that carries a second embedded frame - the depth
    # map or wide-angle companion most phone cameras now write - as MPO rather
    # than JPEG. It is a JPEG container: the leading frame is a complete,
    # ordinary JPEG and the browser calls the file image/jpeg. Omitting it here
    # made "Image format is not supported" the response to a large share of
    # real photographs taken on a phone, while the same scene saved by any
    # desktop tool went through.
    "MPO": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}

# Formats whose extra frames are alternate stills, not animation. The frame
# check below exists to keep animated GIF/WEBP out; an MPO's second frame is a
# companion view of one moment, so counting it as animation rejects a still.
_MULTI_FRAME_STILL_FORMATS = {"MPO"}

# Browsers do not agree on what JPEG is called. Windows resolves a .jpg upload's
# type from the registry, which in some configurations says `image/jpg` or the
# legacy `image/pjpeg`, and Chrome forwards that verbatim - so a genuine JPEG
# arrived declared under a name this module did not recognise and was rejected
# as a content mismatch, with nothing in the message pointing at the real cause.
# Only true aliases of an already-supported decoded format belong here: the
# mismatch check below still rejects a declaration that actually contradicts the
# bytes, which is the case it exists to catch.
_MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/x-png": "image/png",
}


# Decode image headers and enforce bounded, single-frame supported media.
# Return an edit at exactly the dimensions it was given.
#
# The model works on a 16-pixel latent grid, so a 206x206 source comes back as
# 208x208 — near enough to be invisible, and still a different picture from the
# one handed over. An edit is a change to an image, not a change to its size, so
# the last step puts it back. Only ever a correction of a few pixels, because the
# target is already capped at the source's own resolution.
def _match_source_size(edited: bytes, source: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(source)) as original:
            wanted = original.size
        with Image.open(io.BytesIO(edited)) as result:
            if result.size == wanted:
                return edited
            resized = result.convert("RGB").resize(wanted, Image.LANCZOS)
            buffer = io.BytesIO()
            resized.save(buffer, format="PNG")
            return buffer.getvalue()
    except (UnidentifiedImageError, OSError):
        # An unreadable source is not worth failing a finished edit for.
        return edited


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
                    # Name the decoded format: the declared type is the
                    # browser's guess and says nothing about what the bytes
                    # actually are, which is what makes this class of rejection
                    # so slow to diagnose from a log.
                    raise ValueError(
                        "Image format is not supported: "
                        f"{image_format or 'unrecognised'}"
                    )
                mime_type, extension = details
                if declared_mime_type:
                    declared = declared_mime_type.strip().lower()
                    declared = _MIME_ALIASES.get(declared, declared)
                    if declared != mime_type:
                        raise ValueError(
                            "Declared image type does not match its content"
                        )
                if (
                    image_format not in _MULTI_FRAME_STILL_FORMATS
                    and int(getattr(image, "n_frames", 1)) != 1
                ):
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
    # Configure one bounded FLUX.2 Klein generator and its shared concurrency gate.
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float,
        poll_seconds: float,
        max_concurrency: int,
        max_output_bytes: int,
        max_pixels: int,
        text_encoder: str,
        vae: str,
        steps: int,
        style_suffix: str = "",
        portrait_suffix: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.style_suffix = style_suffix.strip().strip(",").strip()
        self.portrait_suffix = portrait_suffix.strip().strip(",").strip()
        # No negative prompt: FLUX.2 Klein runs distilled at cfg 1.0, where the
        # negative conditioning is inert, so the workflow zeroes it out rather
        # than carrying text nothing reads. Realism is steered by the positive
        # suffixes above instead.
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self.max_output_bytes = max_output_bytes
        self.max_pixels = max_pixels
        self.text_encoder = text_encoder
        self.vae = vae
        self.steps = steps
        self._semaphore = asyncio.Semaphore(max_concurrency)

    # Submit, monitor, fetch, and validate one local FLUX.2 Klein image job.
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

    # Build the native four-step FLUX.2 Klein text-to-image workflow.
    # Append the realism suffix unless the prompt already carries it, so the
    # user's wording leads and the style steer follows.
    def _positive_prompt(self, prompt: str, depicts_a_person: bool = False) -> str:
        text = prompt.strip()
        parts = [text] if text else []
        if self.style_suffix and self.style_suffix.lower() not in text.lower():
            parts.append(self.style_suffix)
        # Skin and hair wording only when a person was asked for. Applied
        # unconditionally it does not describe the subject, it invents one.
        if (
            self.portrait_suffix
            and depicts_a_person
            and self.portrait_suffix.lower() not in text.lower()
        ):
            parts.append(self.portrait_suffix)
        return ", ".join(parts)

    def _workflow(self, request: ImageGenerationRequest) -> dict[str, Any]:
        return {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": self.model, "weight_dtype": "default"},
            },
            "2": {
                "class_type": "CLIPLoader",
                "inputs": {
                    "clip_name": self.text_encoder,
                    "type": "flux2",
                    "device": "default",
                },
            },
            "3": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": self.vae},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": self._positive_prompt(
                        request.prompt, request.depicts_a_person
                    ),
                    "clip": ["2", 0],
                },
            },
            "5": {
                "class_type": "ConditioningZeroOut",
                "inputs": {"conditioning": ["4", 0]},
            },
            "6": {
                "class_type": "EmptyFlux2LatentImage",
                "inputs": {
                    "width": request.width,
                    "height": request.height,
                    "batch_size": 1,
                },
            },
            "7": {
                "class_type": "Flux2Scheduler",
                "inputs": {
                    "steps": self.steps,
                    "width": request.width,
                    "height": request.height,
                },
            },
            "8": {
                "class_type": "RandomNoise",
                "inputs": {"noise_seed": request.seed},
            },
            "9": {
                "class_type": "CFGGuider",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["4", 0],
                    "negative": ["5", 0],
                    "cfg": 1.0,
                },
            },
            "10": {
                "class_type": "KSamplerSelect",
                "inputs": {"sampler_name": "euler"},
            },
            "11": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {
                    "noise": ["8", 0],
                    "guider": ["9", 0],
                    "sampler": ["10", 0],
                    "sigmas": ["7", 0],
                    "latent_image": ["6", 0],
                },
            },
            "12": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["11", 0], "vae": ["3", 0]},
            },
            "13": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["12", 0],
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
            text_encoder=text_encoder,
            vae=vae,
            steps=steps,
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
                    content = _match_source_size(content, request.source_content)
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

    # Never ask for more pixels than the source actually has.
    #
    # This node scales *to* the target, so a small source is scaled up rather
    # than left alone. A 206x206 upload was being enlarged to 1440x1440 — a
    # sevenfold linear upscale — and no editor can invent that detail, so what
    # came back was a large blurry version of a thumbnail. Capping at the
    # source's own size means an edit is never worse than what it was given.
    def _target_megapixels(self, source_content: bytes) -> float:
        try:
            with Image.open(io.BytesIO(source_content)) as image:
                available = (image.width * image.height) / 1_000_000
        except (UnidentifiedImageError, OSError):
            return self.megapixels
        if available <= 0:
            return self.megapixels
        return round(min(self.megapixels, available), 4)

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
                    "megapixels": self._target_megapixels(request.source_content),
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
