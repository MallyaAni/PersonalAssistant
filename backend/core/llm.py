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
            # One call, decided by the engine's grammar rather than by us
            # throwing the rest away. The server defaults this to true, and
            # `_extract_call` reads `tool_calls[0]` and drops the remainder
            # silently (main_action_selector.py) - so a turn where the model
            # asked for two things quietly did one of them, with nothing in
            # any log to say so. This turn is a single routing decision; if
            # multi-step work is ever wanted here it needs a design, not a
            # default. (2026-08-29, found by reading the engine's own request
            # schema rather than from an incident, which is the cheaper way.)
            "parallel_tool_calls": False,
            # Tool selection is a bounded application decision, not creative
            # prose. Leaving this unset used the runtime's sampling default and
            # made one unchanged request alternate among search, delegation and
            # no tool across repeated calls.
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        # The same guard `_build_payload` applies. Sent unconditionally, an
        # instance that has withdrawn the parameter (reasoning_effort == "")
        # would put an empty value back on every tool call and pay the 400 and
        # retry each time - or fail outright on an engine whose rejection does
        # not name the field.
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        with self._request_lock:
            response = self._post(payload)
            response.raise_for_status()
            result = cast(dict[str, Any], response.json())
        choices = cast(list[dict[str, Any]], result.get("choices", []))
        message = choices[0].get("message") if choices else None
        if not isinstance(message, dict):
            raise ValueError("Inference provider did not contain a tool decision")
        return cast(dict[str, Any], message)

    # One server-sent line, as (content, was_terminal).
    #
    # Only `delta.content` is rendered. A reasoning model also emits
    # `reasoning_content`, which is its private working and not an answer, so a
    # stream carrying nothing else legitimately produces no output.
    def _stream_event(self, line: str) -> tuple[str | None, bool]:
        if not line.startswith("data: "):
            return None, False
        data = line[6:]
        if data == "[DONE]":
            return None, True
        event = cast(dict[str, Any], json.loads(data))
        if event.get("error"):
            raise RuntimeError(event["error"])
        choices = event.get("choices", [])
        return (choices[0].get("delta", {}).get("content") if choices else None), False

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        payload = {**self._build_payload(messages, max_tokens), "stream": True}
        saw_message = False
        saw_done = False

        # The same withdrawal the buffered path does, decided inside the one
        # request rather than by probing first: a pre-flight would cost every
        # caller a wasted round trip to catch a rejection that happens once.
        retry = False

        with self._request_lock, self._stream(payload) as response:
            if response.status_code == 400:
                response.read()
                retry = self._retry_without_reasoning(response, payload)
            if not retry:
                response.raise_for_status()
                for line in response.iter_lines():
                    content, done = self._stream_event(line)
                    saw_done = saw_done or done
                    if content:
                        saw_message = True
                        yield content

        # The body was consumed to read the rejection, so this asks again with
        # the parameter withdrawn rather than validating an empty stream.
        if retry:
            yield from self.stream_chat(messages, max_tokens)
            return

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
        # Engines disagree about this parameter's domain, and "none" is not a
        # synonym for omitting it.
        #
        # On ds4-server "none" genuinely suppresses reasoning: the same
        # one-word reply costs 3 completion tokens with it and 60 without,
        # because omitting it lets the model think first. On vLLM the value is
        # rejected outright with a 400, so sending it there fails every request
        # rather than one.
        #
        # So it is sent as configured, and `_without_reasoning_effort` drops it
        # only for an engine that refuses it. Dropping it unconditionally was
        # tried and silently turned reasoning back on for every caller,
        # including the ones whose token budgets assume there is none.
        if self.reasoning_effort:
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

    # Drop a reasoning level this engine will not accept, once, and remember.
    #
    # The two engines used here disagree about the value "none": one treats it
    # as "do not think", the other rejects it outright. Neither can be detected
    # ahead of time, and choosing wrong fails every request. So the value is
    # sent as configured and withdrawn only when the engine says no, after
    # which this instance stops sending it at all.
    def _retry_without_reasoning(
        self, response: httpx.Response, payload: dict[str, Any]
    ) -> bool:
        if response.status_code != 400 or "reasoning_effort" not in payload:
            return False
        if "reasoning_effort" not in response.text:
            return False
        logger.warning(
            "Inference engine rejected reasoning_effort=%r; retrying without it "
            "and omitting it from now on",
            payload["reasoning_effort"],
        )
        self.reasoning_effort = ""
        payload.pop("reasoning_effort", None)
        return True

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        response = self._send(payload)
        if self._retry_without_reasoning(response, payload):
            response = self._send(payload)
        return response

    def _send(self, payload: dict[str, Any]) -> httpx.Response:
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


# Preserve the established type name while callers migrate to the neutral contract.
LLMClient = InferenceProvider

# Preserve the historical import name without coupling assembly to that runtime.
LMStudioLLM = OpenAICompatibleInferenceProvider
