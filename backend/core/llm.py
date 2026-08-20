import json
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal, cast

import httpx

logger = logging.getLogger(__name__)

InferenceProviderKind = Literal["openai_compatible"]


class InferenceProvider(ABC):
    """Provider-neutral contract for text, streaming, and tool inference."""

    @abstractmethod
    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str: ...

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
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


class OpenAICompatibleInferenceProvider(InferenceProvider):
    """Use an OpenAI-compatible chat-completions endpoint for inference."""

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
        # Keep one client instance's request order deterministic across providers.
        self._request_lock = threading.Lock()

    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str:
        result = self.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return cast(str, result["content"])

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        payload = self._build_payload(
            messages, max_tokens, response_schema, temperature
        )
        with self._request_lock:
            response = self._post(payload)
            response.raise_for_status()
            result = cast(dict[str, Any], response.json())
        choices = cast(list[dict[str, Any]], result.get("choices", []))
        content_value = (
            choices[0].get("message", {}).get("content", "") if choices else ""
        )
        if not isinstance(content_value, str) or not content_value.strip():
            raise ValueError("Inference provider did not contain a message output")

        return {**result, "content": content_value.strip()}

    # Return one reproducible native-tool decision for application routing.
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
            # Tool selection is a bounded application decision, not creative
            # prose. Leaving this unset used the runtime's sampling default and
            # made one unchanged request alternate among search, delegation and
            # no tool across repeated calls.
            "temperature": 0.0,
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
            raise ValueError("Inference provider did not contain a tool decision")
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
            raise ValueError(
                "Inference provider stream did not contain a message output"
            )
        if not saw_done:
            raise ValueError("Inference provider stream ended before [DONE]")

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        if not any(message.get("role") == "user" for message in messages):
            raise ValueError("Inference request requires at least one user message")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        # Engines disagree about this parameter's domain. ds4-server accepts
        # "none"; vLLM accepts only low, medium or high and rejects anything
        # else with a 400, so sending the configured default at a vLLM backend
        # failed every request rather than one. "none" means "do not ask for
        # reasoning", which is what omitting the field already says, so the
        # request stays valid whichever engine receives it.
        if self.reasoning_effort and self.reasoning_effort.strip().lower() != "none":
            payload["reasoning_effort"] = self.reasoning_effort
        # Omitted, the runtime samples at its own default. Callers that parse the
        # reply as a decision rather than prose pass 0 for a reproducible answer.
        if temperature is not None:
            payload["temperature"] = temperature
        # A caller-supplied schema is decoded as a grammar, so a violating field
        # name or type becomes unrepresentable rather than a post-hoc retry.
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": str(response_schema.get("title") or "response"),
                    "schema": response_schema,
                },
            }
        return payload

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


# Construct a supported inference adapter without exposing provider details upstream.
def create_inference_provider(
    adapter: str,
    base_url: str,
    model: str,
    api_key: str | None = None,
    timeout_seconds: float = 120.0,
    reasoning_effort: str = "none",
    client: httpx.Client | None = None,
) -> InferenceProvider:
    if adapter != "openai_compatible":
        raise ValueError(f"Unsupported inference adapter: {adapter}")
    return OpenAICompatibleInferenceProvider(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        reasoning_effort=reasoning_effort,
        client=client,
    )


class FallbackInferenceProvider(InferenceProvider):
    """Serve from a primary provider, or a standby when it cannot be reached.

    The main model runs on a separate machine that is not always powered on.
    Without this, every reply, routing decision and classification raises the
    moment that host is unreachable and the whole assistant is simply down -
    even though a smaller model is running healthily on this box the entire
    time. Degrading to the smaller model is far better than serving nothing.

    Only transport failures fall back. A model that answers with an error is
    answering, and hiding that behind a second model would mask real faults;
    what is caught here is the case where no answer was obtainable at all.
    """

    def __init__(self, primary: InferenceProvider, standby: InferenceProvider) -> None:
        self.primary = primary
        self.standby = standby

    # The primary's identity, so callers that record which model answered are
    # not silently told the standby's name for work the primary did.
    @property
    def model(self) -> str:
        return getattr(self.primary, "model", "")

    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str:
        try:
            return self.primary.generate_text(prompt, max_tokens)
        except httpx.TransportError:
            _log_fallback("generate_text")
            return self.standby.generate_text(prompt, max_tokens)

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        try:
            return self.primary.chat(messages, max_tokens, response_schema, temperature)
        except httpx.TransportError:
            _log_fallback("chat")
            return self.standby.chat(messages, max_tokens, response_schema, temperature)

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 256,
    ) -> dict[str, Any]:
        try:
            return self.primary.chat_with_tools(messages, tools, max_tokens)
        except httpx.TransportError:
            _log_fallback("chat_with_tools")
            return self.standby.chat_with_tools(messages, tools, max_tokens)

    # Switch only before the first token reaches the caller.
    #
    # A stream that fails midway has already put words on the user's screen;
    # restarting on the standby there would append a second, unrelated answer
    # to the first half of one the primary began. So the first chunk is pulled
    # inside the guard and the rest is relayed outside it.
    def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        try:
            stream = self.primary.stream_chat(messages, max_tokens)
            first = next(stream, None)
        except httpx.TransportError:
            _log_fallback("stream_chat")
            yield from self.standby.stream_chat(messages, max_tokens)
            return
        if first is not None:
            yield first
        yield from stream


def _log_fallback(operation: str) -> None:
    logger.warning(
        "Primary inference host unreachable; serving %s from the standby model",
        operation,
    )


# Preserve the established type name while callers migrate to the neutral contract.
LLMClient = InferenceProvider

# Preserve the historical import name without coupling assembly to that runtime.
LMStudioLLM = OpenAICompatibleInferenceProvider
