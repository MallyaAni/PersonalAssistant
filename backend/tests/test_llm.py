import json

import httpx
import pytest

from backend.core.llm import LMStudioLLM


def test_lm_studio_chat_uses_compatible_multiturn_contract():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("Authorization")
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "google/gemma-4-12b",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Gemma response",
                        }
                    },
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        llm = LMStudioLLM(
            base_url="http://127.0.0.1:1234/",
            model="google/gemma-4-12b",
            api_key="test-token",
            client=client,
        )
        result = llm.chat(
            [
                {"role": "system", "content": "System instructions"},
                {"role": "user", "content": "My name is Ani"},
                {"role": "assistant", "content": "Nice to meet you, Ani"},
                {"role": "user", "content": "What is my name?"},
            ],
            max_tokens=64,
        )

    assert result["content"] == "Gemma response"
    assert observed == {
        "url": "http://127.0.0.1:1234/v1/chat/completions",
        "authorization": "Bearer test-token",
        "payload": {
            "model": "google/gemma-4-12b",
            "messages": [
                {"role": "system", "content": "System instructions"},
                {"role": "user", "content": "My name is Ani"},
                {"role": "assistant", "content": "Nice to meet you, Ani"},
                {"role": "user", "content": "What is my name?"},
            ],
            "max_tokens": 64,
            "reasoning_effort": "none",
        },
    }


def test_lm_studio_chat_rejects_response_without_message_output():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": ""}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        llm = LMStudioLLM(
            base_url="http://127.0.0.1:1234",
            model="google/gemma-4-12b",
            client=client,
        )

        with pytest.raises(
            ValueError,
            match="LM Studio response did not contain a message output",
        ):
            llm.chat([{"role": "user", "content": "Hello"}])


def test_lm_studio_stream_chat_yields_only_content_deltas_and_requires_done():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"Gemma "}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"stream"}}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        llm = LMStudioLLM(
            base_url="http://127.0.0.1:1234",
            model="google/gemma-4-12b",
            client=client,
        )
        chunks = list(llm.stream_chat([{"role": "user", "content": "Hello"}]))

    assert chunks == ["Gemma ", "stream"]
    assert observed["payload"]["stream"] is True
    assert observed["payload"]["max_tokens"] == 1024
    assert observed["payload"]["reasoning_effort"] == "none"
    assert observed["payload"]["messages"] == [{"role": "user", "content": "Hello"}]


def test_lm_studio_stream_chat_rejects_truncated_stream():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        llm = LMStudioLLM(
            base_url="http://127.0.0.1:1234",
            model="google/gemma-4-12b",
            client=client,
        )

        with pytest.raises(
            ValueError,
            match=r"LM Studio stream ended before \[DONE\]",
        ):
            list(llm.stream_chat([{"role": "user", "content": "Hello"}]))
