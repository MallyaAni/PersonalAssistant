"""Functional tests: what the models actually say, not whether they are wired.

Everything else in this suite proves structure — that a call is made, that a
schema is shaped a certain way, that a failure degrades safely. None of it would
notice a prompt that had quietly stopped working, which is the failure that
reaches a user. These tests send the real prompts to the real local model and
assert on the behaviour of the answer.

They are skipped, not failed, when the runtime is unreachable, so a laptop
without vLLM still runs the rest of the suite. Every prompt under test is
greedy, so an assertion here is reproducible rather than a coin flip.
"""

import os

import pytest

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")


# Reach the configured runtime once. A skip here means "no model", which is a
# different thing from a prompt behaving badly and must not read as a pass.
@pytest.fixture(scope="session")
def llm():
    from backend.core.dependencies import get_llm_client

    client = get_llm_client()
    try:
        client.chat([{"role": "user", "content": "ok"}], 8, None, 0.0)
    except Exception as exc:  # pragma: no cover - depends on the host
        pytest.skip(f"local inference runtime unreachable: {type(exc).__name__}")
    return client


@pytest.fixture(scope="session")
def cross_encoder():
    from backend.core.dependencies import get_cross_encoder

    encoder = get_cross_encoder()
    if encoder is None or not encoder.is_enabled():
        pytest.skip("cross-encoder weights are not present")
    return encoder
