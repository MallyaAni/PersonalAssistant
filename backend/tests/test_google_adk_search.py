from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.search.google_adk import GoogleADKSearchProvider, _default_runner_factory
from backend.search.quota import SearchQuotaExceededError


class RecordingQuota:
    """Record quota reservations or raise a configured quota failure."""

    # Configure a successful or rejected quota reservation.
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls = 0
        self.releases = 0

    # Record one attempted provider call.
    async def consume(self) -> None:
        self.calls += 1
        if self.failure is not None:
            raise self.failure

    # Record one reservation returned after a failed attempt.
    async def release(self) -> None:
        self.releases += 1


class RecordingSessionService:
    """Record creation of isolated ADK sessions."""

    # Start with no recorded sessions.
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    # Capture the anonymous session identity supplied to ADK.
    async def create_session(self, **kwargs: str) -> None:
        self.calls.append(kwargs)


class FakeEvent:
    """Expose the small ADK event surface consumed by the provider."""

    # Configure terminal text and grounding metadata.
    def __init__(self, text: str, metadata: Any | None) -> None:
        self.content = SimpleNamespace(parts=[SimpleNamespace(text=text)])
        self.grounding_metadata = metadata

    # Mark the fake response as the terminal answer.
    def is_final_response(self) -> bool:
        return True


class RecordingRunner:
    """Yield one fixed research event and record the minimized message."""

    # Configure the terminal event returned by this runner.
    def __init__(self, event: FakeEvent) -> None:
        self.event = event
        self.session_service = RecordingSessionService()
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    # Yield the configured event for one isolated research invocation.
    async def run_async(self, **kwargs: Any):
        self.calls.append(kwargs)
        yield self.event

    # Record cleanup of transient ADK state.
    async def close(self) -> None:
        self.closed = True


# Build minimal Google grounding metadata with one attributable web source.
def _grounding_metadata() -> SimpleNamespace:
    return SimpleNamespace(
        grounding_chunks=[
            SimpleNamespace(
                web=SimpleNamespace(
                    title="Python releases",
                    uri="https://python.org/downloads/",
                )
            )
        ],
        grounding_supports=[
            SimpleNamespace(
                grounding_chunk_indices=[0],
                segment=SimpleNamespace(text="Python 3.x is current."),
            )
        ],
    )


# Build the provider around deterministic quota and runner doubles.
def _provider(
    runner: RecordingRunner,
    quota: RecordingQuota,
    *,
    api_key: str | None = "configured",
) -> GoogleADKSearchProvider:
    return GoogleADKSearchProvider(
        api_key=api_key,
        model="gemini-3.5-flash-lite",
        timeout_seconds=2,
        max_results=3,
        max_content_chars=100,
        quota=quota,  # type: ignore[arg-type]
        runner_factory=lambda _model, _tokens: runner,
    )


# Verify the real ADK runner uses its required root mode without retaining history.
@pytest.mark.asyncio
async def test_default_runner_uses_request_isolated_chat_mode() -> None:
    runner = _default_runner_factory("gemini-3.5-flash-lite", 128)

    assert runner.agent.mode == "chat"  # type: ignore[attr-defined]
    assert runner.agent.include_contents == "none"  # type: ignore[attr-defined]
    await runner.close()


# Verify Google receives only the minimized query in an anonymous one-turn session.
@pytest.mark.asyncio
async def test_google_research_is_isolated_and_returns_grounded_sources() -> None:
    runner = RecordingRunner(FakeEvent("Python 3.x is current.", _grounding_metadata()))
    quota = RecordingQuota()

    found = await _provider(runner, quota).search("latest Python release")

    assert quota.calls == 1
    assert found.provider == "google"
    assert found.results[0].provider == "google"
    assert found.results[0].content == "Python 3.x is current."
    assert runner.session_service.calls[0]["user_id"] == "public-research"
    sent = runner.calls[0]["new_message"]
    assert sent.parts[0].text == "latest Python release"
    assert runner.calls[0]["user_id"] == "public-research"
    assert runner.closed is True


# Verify unattributed Gemini output is rejected so the fallback can run.
@pytest.mark.asyncio
async def test_google_research_rejects_answers_without_grounding_metadata() -> None:
    runner = RecordingRunner(FakeEvent("An answer without sources.", None))

    with pytest.raises(RuntimeError, match="no grounding metadata"):
        await _provider(runner, RecordingQuota()).search("latest Python release")

    assert runner.closed is True


# Verify a disabled Google provider performs no quota or runner work.
@pytest.mark.asyncio
async def test_google_research_is_disabled_without_an_api_key() -> None:
    runner = RecordingRunner(FakeEvent("answer", _grounding_metadata()))
    quota = RecordingQuota()
    provider = _provider(runner, quota, api_key=None)

    assert provider.is_enabled() is False
    with pytest.raises(RuntimeError, match="not configured"):
        await provider.search("latest Python release")
    assert quota.calls == 0
    assert runner.calls == []


# Verify quota exhaustion prevents creating a cloud research session.
@pytest.mark.asyncio
async def test_google_research_stops_before_adk_when_quota_is_exhausted() -> None:
    runner = RecordingRunner(FakeEvent("answer", _grounding_metadata()))
    quota = RecordingQuota(
        SearchQuotaExceededError("google daily search budget is exhausted")
    )

    with pytest.raises(SearchQuotaExceededError, match="budget is exhausted"):
        await _provider(runner, quota).search("latest Python release")

    assert runner.session_service.calls == []
    assert runner.calls == []


# A failed provider call must not spend a slot from the daily budget.
@pytest.mark.asyncio
async def test_a_failed_search_returns_its_quota_reservation(tmp_path):
    from backend.search.quota import SQLiteDailySearchQuota

    quota = SQLiteDailySearchQuota(
        path=str(tmp_path / "quota.sqlite3"), provider="google", daily_limit=5
    )

    # Simulate the provider rejecting every request, as a 429 does.
    def failing_runner(model: str, max_output_tokens: int):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    provider = GoogleADKSearchProvider(
        api_key="test-key",
        model="gemini-3.5-flash-lite",
        timeout_seconds=5.0,
        max_results=3,
        max_content_chars=200,
        quota=quota,
        runner_factory=failing_runner,
    )

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await provider.search("anything")

    # Without release, a provider that rejects everything would still exhaust
    # the local budget and keep blocking after the provider recovered.
    import sqlite3

    connection = sqlite3.connect(tmp_path / "quota.sqlite3")
    used = connection.execute(
        "SELECT request_count FROM daily_search_quota WHERE provider = 'google'"
    ).fetchone()
    connection.close()
    assert used[0] == 0


# Releasing more than was reserved must never drive the counter negative.
@pytest.mark.asyncio
async def test_release_never_drives_the_counter_below_zero(tmp_path):
    from backend.search.quota import SQLiteDailySearchQuota

    quota = SQLiteDailySearchQuota(
        path=str(tmp_path / "q.sqlite3"), provider="google", daily_limit=5
    )
    await quota.consume()
    await quota.release()
    await quota.release()

    import sqlite3

    connection = sqlite3.connect(tmp_path / "q.sqlite3")
    used = connection.execute(
        "SELECT request_count FROM daily_search_quota WHERE provider = 'google'"
    ).fetchone()
    connection.close()
    assert used[0] == 0


# Holding a key is not evidence the project carries grounding entitlement.
def test_a_key_alone_does_not_enable_grounding():
    from backend.search.quota import SQLiteDailySearchQuota

    quota = SQLiteDailySearchQuota(path="unused", provider="google", daily_limit=1)
    disabled = GoogleADKSearchProvider(
        api_key="a-real-looking-key",
        model="gemini-3.6-flash",
        timeout_seconds=5.0,
        max_results=3,
        max_content_chars=100,
        quota=quota,
        enabled=False,
    )

    # Google Search grounding is billed separately, so a free-tier project with
    # a valid key still returns 429 on its first grounded request. Attempting it
    # would cost latency on every search for a call that cannot succeed.
    assert disabled.is_enabled() is False


@pytest.mark.asyncio
async def test_a_disabled_provider_refuses_before_spending_quota():
    from backend.search.quota import SQLiteDailySearchQuota

    quota = SQLiteDailySearchQuota(path="unused", provider="google", daily_limit=1)
    disabled = GoogleADKSearchProvider(
        api_key="a-real-looking-key",
        model="gemini-3.6-flash",
        timeout_seconds=5.0,
        max_results=3,
        max_content_chars=100,
        quota=quota,
        enabled=False,
    )

    with pytest.raises(RuntimeError, match="not configured"):
        await disabled.search("anything")
