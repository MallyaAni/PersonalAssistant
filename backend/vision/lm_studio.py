import base64
from typing import Any, cast

import httpx

from backend.agents.vision.upload import (
    UPLOAD_INSPECTION_SCHEMA,
    UploadInspectionDecision,
    build_upload_inspection_prompt,
)
from backend.artifacts.types import (
    VisionAnalysis,
    VisionUploadInspection,
    VisualIdentification,
)
from backend.core.interfaces import VisionProvider


# A full-size phone photo is more than the model can hold: a 4032x3024 JPEG
# became about 12,000 image tokens on Qwen3-VL (one token per 32x32 pixels)
# and, with the inspection prompt, 16,809 against a 16,384 context - a 400
# from the server and "I hit a problem" to the person (Caroline, 2026-09-02).
# Nothing about describing a picture needs that many pixels, so anything
# over the cap is scaled down here, once, before it is encoded; orientation
# is applied first because re-encoding drops the EXIF that carried it.
# Bytes the image library cannot read (HEIC without a decoder, a broken
# file) are sent as they are and the server says what it thinks.
MAX_IMAGE_PIXELS = 2_000_000
MAX_IMAGE_SIDE = 2048
_WEB_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF"})


def fit_for_model(content: bytes, mime_type: str) -> tuple[bytes, str]:
    try:
        import io

        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(content)) as opened:
            # exif_transpose returns a copy even when nothing was rotated,
            # so "unchanged" is judged by the tag, not by identity.
            rotated = opened.getexif().get(0x0112, 1) not in (1, None)
            # A phone's HEIC (Caroline's was one) reaches here labelled as
            # whatever the worker guessed; the server may not decode it at
            # all. Anything that is not a web format is re-encoded even
            # when it is small enough.
            foreign = (opened.format or "").upper() not in _WEB_FORMATS
            image = ImageOps.exif_transpose(opened) or opened
            width, height = image.size
            scale = min(
                1.0,
                (MAX_IMAGE_PIXELS / float(width * height)) ** 0.5,
                MAX_IMAGE_SIDE / float(max(width, height)),
            )
            if scale >= 1.0 and not rotated and not foreign:
                return content, mime_type
            if scale < 1.0:
                image = image.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    Image.LANCZOS,
                )
            out = io.BytesIO()
            if image.mode in ("RGBA", "LA", "P"):
                image.convert("RGBA").save(out, format="PNG", optimize=True)
                return out.getvalue(), "image/png"
            image.convert("RGB").save(out, format="JPEG", quality=90)
            return out.getvalue(), "image/jpeg"
    except Exception:
        return content, mime_type


class OpenAICompatibleVisionProvider(VisionProvider):
    # Configure the local OpenAI-compatible vision-language endpoint.
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_seconds: float,
        reasoning_effort: str,
        max_tokens: int = 512,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens

    # Build the multimodal user message that anchors one image to a prompt.
    def _image_message(
        self,
        prompt: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        content, mime_type = fit_for_model(content, mime_type)
        encoded = base64.b64encode(content).decode("ascii")
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                },
            ],
        }

    # Send one validated image and bounded prompt to the configured local VLM.
    async def analyze(
        self,
        prompt: str,
        content: bytes,
        mime_type: str,
    ) -> VisionAnalysis:
        return await self._complete([self._image_message(prompt, content, mime_type)])

    # Inspect a new upload once under the strict application-owned JSON schema.
    async def inspect_upload(
        self,
        question: str,
        content: bytes,
        mime_type: str,
    ) -> VisionUploadInspection:
        messages = [
            self._image_message(
                build_upload_inspection_prompt(question),
                content,
                mime_type,
            )
        ]
        payload = await self._post(
            messages,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "vision_upload_inspection",
                    "strict": True,
                    "schema": UPLOAD_INSPECTION_SCHEMA,
                },
            },
        )
        choices = cast(list[dict[str, Any]], payload.get("choices", []))
        output = choices[0].get("message", {}).get("content") if choices else None
        if not isinstance(output, str) or not output.strip():
            raise ValueError("Vision provider did not return an upload inspection")
        decision = UploadInspectionDecision.model_validate_json(output)
        usage = payload.get("usage", {})
        return VisionUploadInspection(
            intent=decision.intent,
            observation=decision.observation.strip(),
            answer=decision.answer.strip(),
            grounding=decision.grounding,
            search_query=decision.search_query.strip(),
            needs_reasoning=decision.needs_reasoning,
            unsupported_reason=decision.unsupported_reason,
            model=str(payload.get("model") or self.model),
            metadata={"usage": usage if isinstance(usage, dict) else {}},
            identified_items=tuple(
                VisualIdentification(
                    label=item.label.strip(),
                    confidence=item.confidence,
                    basis=item.basis.strip(),
                )
                for item in decision.identified_items
            ),
        )

    # Answer a new question about one image given prior question/answer context.
    async def analyze_thread(
        self,
        content: bytes,
        mime_type: str,
        history: list[dict[str, str]],
        prompt: str,
    ) -> VisionAnalysis:
        anchor_prompt = (
            "The following image is the subject of this conversation. "
            "Answer questions about it using only what is visible."
        )
        messages: list[dict[str, Any]] = [
            self._image_message(anchor_prompt, content, mime_type)
        ]
        for pair in history:
            question = pair.get("prompt", "").strip()
            answer = pair.get("answer", "").strip()
            if question:
                messages.append({"role": "user", "content": question})
            if answer:
                messages.append({"role": "assistant", "content": answer})
        messages.append({"role": "user", "content": prompt})
        return await self._complete(messages)

    # Post one prepared message list to the local VLM and return grounded text.
    async def _complete(self, messages: list[dict[str, Any]]) -> VisionAnalysis:
        result = await self._post(messages)
        choices = cast(list[dict[str, Any]], result.get("choices", []))
        output = choices[0].get("message", {}).get("content") if choices else None
        if not isinstance(output, str) or not output.strip():
            raise ValueError("Vision provider did not return grounded text")
        usage = result.get("usage", {})
        return VisionAnalysis(
            content=output.strip(),
            model=str(result.get("model") or self.model),
            metadata={"usage": usage if isinstance(usage, dict) else {}},
        )

    # Post prepared multimodal messages with an optional structured grammar.
    async def _post(
        self,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
            "temperature": 0.0,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())


# Construct a vision adapter without exposing its wire protocol to services.
def create_vision_provider(
    adapter: str,
    base_url: str,
    model: str,
    api_key: str | None,
    timeout_seconds: float,
    reasoning_effort: str,
    max_tokens: int = 512,
) -> VisionProvider:
    if adapter != "openai_compatible":
        raise ValueError(f"Unsupported vision inference adapter: {adapter}")
    return OpenAICompatibleVisionProvider(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
    )


# Preserve the established import while dependency assembly uses the neutral name.
LMStudioVisionProvider = OpenAICompatibleVisionProvider
