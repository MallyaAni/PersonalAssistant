import base64
from typing import Any, cast

import httpx

from backend.artifacts.types import VisionAnalysis
from backend.core.interfaces import VisionProvider


class LMStudioVisionProvider(VisionProvider):
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
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
        }
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
        result = cast(dict[str, Any], response.json())
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
