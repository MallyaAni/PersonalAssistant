"""The request has to stay valid whichever engine receives it.

`reasoning_effort` was sent on every request with whatever the role was
configured to. ds4-server accepts "none"; vLLM accepts only low, medium or
high and answers anything else with a 400. `MAIN_LLM_REASONING_EFFORT`
defaults to "none" in compose, so pointing the main role at a vLLM backend
would not have degraded - it would have failed every single request, before
a single reply was generated.

Found by measurement rather than by reading, while collecting answers from a
vLLM-served candidate. That is the whole argument for running a candidate
against the real client before promoting it.
"""

import pytest

from backend.core.llm import create_inference_provider


def _payload(effort: str, **kwargs):
    client = create_inference_provider(
        adapter="openai_compatible",
        base_url="http://inference.test",
        model="candidate",
        api_key="",
        timeout_seconds=5.0,
        reasoning_effort=effort,
    )
    return client._build_payload([{"role": "user", "content": "hello"}], 128, **kwargs)


# "none" is not a value any engine has to accept, because it is the absence of
# a request. Omitting it says the same thing everywhere.
@pytest.mark.parametrize("effort", ["none", "None", " NONE ", ""])
def test_no_reasoning_request_is_expressed_by_omitting_the_field(effort: str):
    assert "reasoning_effort" not in _payload(effort)


# A real request still has to reach the engine, or turning reasoning on in
# settings would silently do nothing - the mirror-image defect.
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_a_real_reasoning_level_is_still_sent(effort: str):
    assert _payload(effort)["reasoning_effort"] == effort


# The values vLLM's schema accepts. A configured level outside this set is the
# thing that 400s, so it is worth stating what the safe set actually is.
def test_the_levels_sent_are_ones_a_vllm_backend_accepts():
    accepted = {"low", "medium", "high"}
    for effort in accepted:
        assert _payload(effort)["reasoning_effort"] in accepted


def test_the_rest_of_the_payload_is_untouched():
    payload = _payload("none")
    assert payload["model"] == "candidate"
    assert payload["max_tokens"] == 128
    assert payload["messages"][0]["content"] == "hello"
