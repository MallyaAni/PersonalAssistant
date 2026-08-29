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
    async def consume(self, *, count: int = 1) -> None:
        self.calls += count
        if self.failure is not None:
            raise self.failure

    # Record one reservation returned after a failed attempt.
    async def release(self, *, count: int = 1) -> None:
        self.releases += count

    # Replace a reservation with the provider's observed billable usage.
    async def reconcile(self, reserved_count: int, actual_count: int) -> None:
        self.calls += actual_count - reserved_count


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
        web_search_queries=["current Python release", "python stable release"],
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

    assert quota.calls == 2
    assert quota.releases == 0
    assert found.provider == "google"
    assert found.results[0].provider == "google"
    assert found.results[0].content == "Python 3.x is current."
    assert runner.session_service.calls[0]["user_id"] == "public-research"
    sent = runner.calls[0]["new_message"]
    assert sent.parts[0].text == "latest Python release"
    assert runner.calls[0]["user_id"] == "public-research"
    assert runner.closed is True


# Verify empty query entries are ignored while an unknown count stays safe.
def test_billable_search_query_count_matches_google_metadata() -> None:
    from backend.search.google_adk import _billable_search_query_count

    metadata = SimpleNamespace(web_search_queries=["one", "", "  ", "two"])

    assert _billable_search_query_count(metadata) == 2
    assert _billable_search_query_count(SimpleNamespace(web_search_queries=[])) == 1


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

    assert quota.calls == 10
    assert runner.session_service.calls == []
    assert runner.calls == []


# A failure before the provider request must return the full reservation.
@pytest.mark.asyncio
async def test_a_failed_search_returns_its_quota_reservation(tmp_path):
    from backend.search.quota import SQLiteDailySearchQuota

    quota = SQLiteDailySearchQuota(
        path=str(tmp_path / "quota.sqlite3"), provider="google", daily_limit=20
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


# A failure after the request starts keeps a conservative billable reservation.
@pytest.mark.asyncio
async def test_an_uncertain_provider_failure_keeps_its_reservation() -> None:
    class FailingRunner(RecordingRunner):
        # Fail after the provider has started the external model request.
        async def run_async(self, **kwargs: Any):
            self.calls.append(kwargs)
            raise RuntimeError("connection lost after request")
            yield  # pragma: no cover

    runner = FailingRunner(FakeEvent("", None))
    quota = RecordingQuota()

    with pytest.raises(RuntimeError, match="connection lost"):
        await _provider(runner, quota).search("latest Python release")

    assert quota.calls == 10
    assert quota.releases == 0


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
        model="gemini-3.1-flash-lite",
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
        model="gemini-3.1-flash-lite",
        timeout_seconds=5.0,
        max_results=3,
        max_content_chars=100,
        quota=quota,
        enabled=False,
    )

    with pytest.raises(RuntimeError, match="not configured"):
        await disabled.search("anything")


# Findings from the merge review on 2026-08-29. Each of these was a real path
# through the spend gate that nothing asserted on, and two of them charged the
# wrong way round.


class _LedgerQuota:
    """Records the ordered calls, so a reservation can be told from a charge."""

    def __init__(self, exhausted: bool = False) -> None:
        self.log: list[tuple] = []
        self.exhausted = exhausted
        self.reconcile_fails = False

    async def consume(self, count: int = 1) -> None:
        self.log.append(("consume", count))
        if self.exhausted:
            raise SearchQuotaExceededError("google", 0)

    async def reconcile(self, reserved: int, actual: int) -> None:
        self.log.append(("reconcile", reserved, actual))
        if self.reconcile_fails:
            raise RuntimeError("database is locked")

    async def release(self, count: int = 1) -> None:
        self.log.append(("release", count))

    # The charge the ledger settles on, for readable assertions.
    @property
    def charged(self) -> int:
        held = 0
        for entry in self.log:
            if entry[0] == "consume":
                held += entry[1]
            elif entry[0] == "reconcile":
                held += entry[2] - entry[1]
            elif entry[0] == "release":
                held -= entry[1]
        return held


# A runner that yields several events, the way the agentic ADK loop does when
# a follow-up search lands in a second model turn.
class _MultiEventRunner(RecordingRunner):
    def __init__(self, events: list[FakeEvent]) -> None:
        super().__init__(events[-1])
        self.events = events

    async def run_async(self, **kwargs: Any):
        self.calls.append(kwargs)
        for event in self.events:
            yield event


def _metadata_with(queries: list[str]) -> SimpleNamespace:
    metadata = _grounding_metadata()
    metadata.web_search_queries = queries
    return metadata


@pytest.mark.asyncio
async def test_an_answer_with_no_grounding_costs_one_query_not_ten():
    # Gemini answering from what it already knows runs no search, so Google
    # bills nothing. Retaining the whole ten-query reservation for it burned
    # the month in 480 such turns and left the meter permanently wrong.
    quota = _LedgerQuota()
    provider = _provider(RecordingRunner(FakeEvent("Paris.", None)), quota)
    with pytest.raises(RuntimeError):
        await provider.search("capital of France")
    assert quota.charged == 1, quota.log


@pytest.mark.asyncio
async def test_a_locked_counter_never_costs_the_answer_it_already_paid_for():
    # The counter is one SQLite file shared by three containers, so a locked
    # database is ordinary. Losing a grounded answer that was already requested
    # and billed, because the bookkeeping write lost a race, is the worst of
    # both outcomes.
    quota = _LedgerQuota()
    quota.reconcile_fails = True
    runner = RecordingRunner(FakeEvent("Python 3.x is current.", _grounding_metadata()))
    found = await _provider(runner, quota).search("python release")
    assert found.results, found
    assert ("reconcile", 10, 2) in quota.log


@pytest.mark.asyncio
async def test_several_searches_in_one_prompt_are_all_charged():
    # The ADK loop is agentic: a follow-up search lands in a second event with
    # its own metadata. Keeping only the newest charged one query for four -
    # the direction that costs money.
    quota = _LedgerQuota()
    runner = _MultiEventRunner(
        [
            FakeEvent("partial", _metadata_with(["one", "two", "three"])),
            FakeEvent("Both.", _metadata_with(["four"])),
        ]
    )
    await _provider(runner, quota).search("two things")
    assert quota.charged == 4, quota.log


def test_one_response_cannot_charge_a_whole_month():
    from backend.search.google_adk import (
        _MAX_OBSERVED_QUERIES,
        _billable_search_query_count,
    )

    class _Absurd:
        web_search_queries = [f"q{index}" for index in range(9_999)]

    assert _billable_search_query_count(_Absurd()) == _MAX_OBSERVED_QUERIES
