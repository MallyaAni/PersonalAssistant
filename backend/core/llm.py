import json
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import httpx


class LLMClient(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str: ...

    @abstractmethod
    def chat(
        self, messages: list[dict[str, str]], max_tokens: int = 1024
    ) -> dict[str, Any]: ...

    @abstractmethod
    def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> Iterator[str]: ...

    # Ask a compatible model to choose from bounded application-supplied tools.
    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 256,
    ) -> dict[str, Any]:
        raise NotImplementedError("This LLM provider does not support tool calling")


# Example of a concrete implementation for LM Studio / OpenAI compatible APIs
class LMStudioLLM(LLMClient):
    """Client for LM Studio's OpenAI-compatible chat completions API."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        reasoning_effort: str = "none",
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.reasoning_effort = reasoning_effort
        self.client = client
        # LM Studio may terminate an in-flight generation when another request
        # reaches the same loaded local model, so this process queues calls.
        self._request_lock = threading.Lock()

    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str:
        result = self.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return cast(str, result["content"])

    def chat(
        self, messages: list[dict[str, str]], max_tokens: int = 1024
    ) -> dict[str, Any]:
        payload = self._build_payload(messages, max_tokens)
        with self._request_lock:
            response = self._post(payload)
            response.raise_for_status()
            result = cast(dict[str, Any], response.json())
        choices = cast(list[dict[str, Any]], result.get("choices", []))
        content_value = (
            choices[0].get("message", {}).get("content", "") if choices else ""
        )
        if not isinstance(content_value, str) or not content_value.strip():
            raise ValueError("LM Studio response did not contain a message output")

        return {**result, "content": content_value.strip()}

    # Return the provider message so the application can inspect native tool calls.
    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 256,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": max_tokens,
            "reasoning_effort": self.reasoning_effort,
        }
        with self._request_lock:
            response = self._post(payload)
            response.raise_for_status()
            result = cast(dict[str, Any], response.json())
        choices = cast(list[dict[str, Any]], result.get("choices", []))
        message = choices[0].get("message") if choices else None
        if not isinstance(message, dict):
            raise ValueError("LM Studio response did not contain a tool decision")
        return cast(dict[str, Any], message)

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        payload = {**self._build_payload(messages, max_tokens), "stream": True}
        saw_message = False
        saw_done = False

        with self._request_lock, self._stream(payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    saw_done = True
                    continue
                event = cast(dict[str, Any], json.loads(data))
                if event.get("error"):
                    raise RuntimeError(event["error"])
                choices = event.get("choices", [])
                content = (
                    choices[0].get("delta", {}).get("content") if choices else None
                )
                if content:
                    saw_message = True
                    yield content

        if not saw_message:
            raise ValueError("LM Studio stream did not contain a message output")
        if not saw_done:
            raise ValueError("LM Studio stream ended before [DONE]")

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> dict[str, Any]:
        if not any(message.get("role") == "user" for message in messages):
            raise ValueError("LM Studio chat requires at least one user message")

        return {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "reasoning_effort": self.reasoning_effort,
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        if self.client is not None:
            return self.client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json=payload,
            )
        with httpx.Client(timeout=self.timeout_seconds) as client:
            return client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json=payload,
            )

    @contextmanager
    def _stream(self, payload: dict[str, Any]) -> Iterator[httpx.Response]:
        if self.client is not None:
            with self.client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as response:
                yield response
            return

        with (
            httpx.Client(timeout=self.timeout_seconds) as client,
            client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as response,
        ):
            yield response
