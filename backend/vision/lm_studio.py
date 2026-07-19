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

    # Send one validated image and bounded prompt to the configured local VLM.
    async def analyze(
        self,
        prompt: str,
        content: bytes,
        mime_type: str,
    ) -> VisionAnalysis:
        encoded = base64.b64encode(content).decode("ascii")
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
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
