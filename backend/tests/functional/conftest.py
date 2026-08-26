"""Functional tests: what the models actually say, not whether they are wired.

Everything else in this suite proves structure — that a call is made, that a
schema is shaped a certain way, that a failure degrades safely. None of it would
notice a prompt that had quietly stopped working, which is the failure that
reaches a user. These tests send the real prompts to the real local model and
assert on the behaviour of the answer.

They are skipped, not failed, when the runtime is unreachable, so a laptop
without vLLM still runs the rest of the suite. Every prompt under test is
greedy, so an assertion here is reproducible rather than a coin flip.

That skip is right for a laptop and wrong for a gate. Set
`ANIOS_REQUIRE_FUNCTIONAL=1` and every skip in this directory becomes a
failure, because a deploy gate wired on exit code alone reports green when the
Sparks are simply down - which is the one moment it most needs to say no.
"""

import asyncio
import os

import pytest

# Keep direct functional-suite collection independent of generic host DEBUG modes.
os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")


# A skipped functional test is a pass to every runner that reads an exit code.
# For a laptop that is the point; for the deploy gate it is the failure mode -
# "the model was unreachable" and "the prompt still works" become the same
# green. Under ANIOS_REQUIRE_FUNCTIONAL the skip budget is zero, and anything
# genuinely not runnable in a container is deselected by path in scripts/gate.sh
# where the omission is visible.
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if not os.getenv("ANIOS_REQUIRE_FUNCTIONAL"):
        return
    report = outcome.get_result()
    # An xfail also arrives here as `skipped`, and it is not the thing this
    # guard exists to catch. A skip is the environment saying "could not run";
    # an xfail is a person saying "measured, understood, not fixed yet", with
    # the reason in the source next to the assertion. Treating them alike made
    # `xfail` unusable in this suite: a deliberately documented limitation
    # reported as a hard failure, which is how a real regression gets lost
    # among expected ones.
    if getattr(report, "wasxfail", None) is not None:
        return
    if report.skipped:
        report.outcome = "failed"
        report.longrepr = (
            f"skipped under ANIOS_REQUIRE_FUNCTIONAL, which a gate treats as a "
            f"failure: {report.longrepr}"
        )


# Being *permitted* to call search is not the same as search resolving. The
# selector catches MCPInvocationError and simply omits search_web from the
# offer, so a stdio server that fails to spawn inside the test container makes
# the routing floors fail in a way that reads exactly like a prompt regression.
# Fail here instead, naming the real reason.
@pytest.fixture(scope="session")
def resolved_search_tool():
    from backend.config.settings import settings
    from backend.core.dependencies import get_mcp_invocation_service

    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        pytest.skip(
            f"{settings.SEARCH_MCP_SERVER_ID} is not configured as auto-invocable"
        )
    try:
        return asyncio.run(
            invocation.resolve_tool(
                settings.SEARCH_MCP_SERVER_ID, settings.SEARCH_MCP_TOOL_NAME
            )
        )
    except Exception as exc:  # pragma: no cover - depends on the host
        pytest.fail(
            f"the search server is configured but did not resolve "
            f"{settings.SEARCH_MCP_TOOL_NAME}: {type(exc).__name__}: {exc}"
        )


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


# The engine that enforces schemas, which is what every schema-answering
# prompt runs against in production. Testing those prompts on `llm` proved
# the wrong thing once: the describer passed here against an enforcing host
# default while the deployed prose writer ignored the schema entirely.
@pytest.fixture(scope="session")
def structured_llm():
    from backend.core.dependencies import get_structured_llm_client

    client = get_structured_llm_client()
    try:
        client.chat([{"role": "user", "content": "ok"}], 8, None, 0.0)
    except Exception as exc:  # pragma: no cover - depends on the host
        pytest.skip(f"structured inference runtime unreachable: {type(exc).__name__}")
    return client


@pytest.fixture(scope="session")
def cross_encoder():
    from backend.core.dependencies import get_cross_encoder

    encoder = get_cross_encoder()
    if encoder is None or not encoder.is_enabled():
        pytest.skip("cross-encoder weights are not present")
    return encoder
