"""The request has to stay valid on either engine without losing what it does.

Two engines, two meanings for the same value, and the first attempt to
reconcile them made things worse.

`reasoning_effort="none"` is not a synonym for omitting the field. On
ds4-server it genuinely suppresses reasoning: the same one-word reply costs
3 completion tokens with it and 60 without, because omitting it lets the model
think first. On vLLM the value is rejected outright with a 400, and
`MAIN_LLM_REASONING_EFFORT` defaults to "none" in compose, so sending it at a
vLLM backend fails every request rather than one.

The first fix dropped "none" unconditionally, on the theory that it meant
nothing. That kept vLLM working and silently turned reasoning back on for every
caller against ds4-server - including the ones whose token budgets assume there
is none, which is how a 16-token classifier ends up parsing a model's internal
monologue.

So the value is sent as configured, and withdrawn only by an engine that
refuses it, once, after which that client stops sending it.
"""

import httpx
import pytest

from backend.core.llm import create_inference_provider


def _provider(effort: str):
    return create_inference_provider(
        adapter="openai_compatible",
        base_url="http://inference.test",
        model="candidate",
        api_key="",
        timeout_seconds=5.0,
        reasoning_effort=effort,
    )


def _payload(effort: str, **kwargs):
    return _provider(effort)._build_payload(
        [{"role": "user", "content": "hello"}], 128, **kwargs
    )


# The regression the first fix introduced: "none" carries meaning and has to
# reach an engine that understands it.
@pytest.mark.parametrize("effort", ["none", "low", "medium", "high"])
def test_the_configured_level_is_sent_as_configured(effort: str):
    assert _payload(effort)["reasoning_effort"] == effort


# Nothing configured is the only case that omits it.
def test_an_unset_level_is_omitted():
    assert "reasoning_effort" not in _payload("")


def _rejection() -> httpx.Response:
    return httpx.Response(
        400,
        json={
            "error": {
                "message": "1 validation error:\n  {'loc': ('body', "
                "'reasoning_effort'), 'msg': \"Input should be 'low', "
                "'medium' or 'high'\"}"
            }
        },
        request=httpx.Request("POST", "http://inference.test/v1/chat/completions"),
    )


# An engine that refuses the value gets a request without it, and this client
# stops sending it rather than failing every later turn the same way.
def test_a_refused_level_is_withdrawn_and_stays_withdrawn():
    provider = _provider("none")
    payload = {"model": "candidate", "reasoning_effort": "none"}

    assert provider._retry_without_reasoning(_rejection(), payload) is True
    assert "reasoning_effort" not in payload
    assert provider.reasoning_effort == ""
    # Later requests are built without it, so the rejection costs one retry.
    assert "reasoning_effort" not in provider._build_payload(
        [{"role": "user", "content": "hello"}], 128
    )


# A 400 about something else must not be silently rewritten as this problem.
def test_an_unrelated_rejection_is_not_treated_as_this_one():
    provider = _provider("none")
    payload = {"model": "candidate", "reasoning_effort": "none"}
    unrelated = httpx.Response(
        400,
        json={"error": {"message": "max_tokens exceeds context length"}},
        request=httpx.Request("POST", "http://inference.test/v1/chat/completions"),
    )

    assert provider._retry_without_reasoning(unrelated, payload) is False
    assert payload["reasoning_effort"] == "none"
    assert provider.reasoning_effort == "none"


def test_a_request_that_never_sent_it_is_not_retried():
    provider = _provider("")
    assert provider._retry_without_reasoning(_rejection(), {"model": "x"}) is False


def test_the_rest_of_the_payload_is_untouched():
    payload = _payload("none")
    assert payload["model"] == "candidate"
    assert payload["max_tokens"] == 128
    assert payload["messages"][0]["content"] == "hello"
