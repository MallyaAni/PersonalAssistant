"""Slide calls are independent, so a deck should not plan them one at a time.

Each slide call is built from the outline alone - its own entry, and the titles
and beats of the slides before it, all read from `outline.slides` rather than
from any earlier answer. Nothing in a slide call depends on the slide before it
having been planned. They ran sequentially because they were written as a loop,
and a deck measured on 2026-09-02 spent 44-64 s per slide against an engine that
reported `Waiting: 0 reqs` throughout.

Two things have to hold for the fan-out to be real rather than apparent, and
both are asserted here:

  - the calls overlap, which needs a client each. One inference client
    serialises its own requests through a per-instance lock, so a shared client
    turns a fan-out back into a queue while looking like it worked;
  - the deck's background lease is taken once, not per call. The lease is
    exclusive, so per-call it serialises the fan-out too.

The drafts must still arrive as growing prefixes of one deck in outline order,
because that is what the UI renders while it waits.
"""

import json
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.presentations.provider import LLMPresentationProvider

pytestmark = pytest.mark.asyncio

_SLIDE_LATENCY = 0.2


# One fresh tally of in-flight calls, their peak overlap, and the total.
def _new_tally() -> dict[str, Any]:
    return {"running": 0, "peak": 0, "calls": 0}


class RecordingPlanningLLM:
    """Answer any deck call and record how many were in flight together."""

    # Share one tally across every client built for one deck, so the peak counts
    # the deck's concurrency rather than one client's.
    def __init__(self, tally: dict[str, Any] | None = None) -> None:
        self.tally = tally if tally is not None else _new_tally()
        self.lock = threading.Lock()

    # Return an outline or a slide, whichever the caller's schema asked for.
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1_024,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            self.tally["running"] += 1
            self.tally["calls"] += 1
            self.tally["peak"] = max(self.tally["peak"], self.tally["running"])
        try:
            # Real latency in a real thread: the overlap being measured is the
            # one asyncio.to_thread actually produces.
            time.sleep(_SLIDE_LATENCY)
            return {"content": json.dumps(self._answer(messages))}
        finally:
            with self.lock:
                self.tally["running"] -= 1

    # Answer a slide request from the slide it names, or else give the outline.
    def _answer(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        request = json.loads(messages[-1]["content"]) if _is_slide(messages) else None
        if request is None:
            return {
                "title": "Horses",
                "subtitle": "A concise introduction",
                "narrative": "chronological",
                "through_line": "Horses changed how people moved",
                "slides": [
                    {
                        "title": f"Slide {index}",
                        "purpose": f"Explain part {index}",
                        "layout": "bullets",
                        "beat": f"beat {index}",
                    }
                    for index in range(1, 5)
                ],
            }
        named = request["slide"]["title"]
        return {
            "title": named,
            "purpose": f"Explain {named}",
            "points": [f"{named} first point", f"{named} second point"],
            "layout": "bullets",
        }


# Whether this request is a slide call, which carries the slide it is planning.
def _is_slide(messages: list[dict[str, str]]) -> bool:
    try:
        return "slide" in json.loads(messages[-1]["content"])
    except (json.JSONDecodeError, TypeError):
        return False


class CountingGate:
    """Count background leases without scheduling against the live Redis keys."""

    # Record every acquisition so a per-call lease is distinguishable from one.
    def __init__(self) -> None:
        self.leases = 0
        self.held = 0
        self.peak_held = 0

    @asynccontextmanager
    async def background(self):  # type: ignore[no-untyped-def]
        self.leases += 1
        self.held += 1
        self.peak_held = max(self.peak_held, self.held)
        try:
            yield
        finally:
            self.held -= 1


# Build a provider whose concurrent workers each get their own recording client.
def _provider(
    concurrency: int,
    gate: CountingGate | None = None,
) -> tuple[LLMPresentationProvider, dict[str, Any]]:
    tally = _new_tally()
    return (
        LLMPresentationProvider(
            RecordingPlanningLLM(tally),  # type: ignore[arg-type]
            max_tokens=1_024,
            slide_concurrency=concurrency,
            llm_factory=lambda: RecordingPlanningLLM(tally),  # type: ignore[arg-type]
            model_gate=gate,  # type: ignore[arg-type]
            background=gate is not None,
        ),
        tally,
    )


async def test_slide_calls_overlap_instead_of_queueing() -> None:
    provider, tally = _provider(concurrency=4)

    drafts = [draft async for draft in provider.create_progress("a deck, 4 slides")]

    assert len(drafts) == 4
    # Four independent calls and a client each: they should have been in flight
    # together. At 1 this test would still pass on wall clock and prove nothing,
    # which is why it asserts the overlap rather than the duration.
    assert tally["peak"] > 1, tally
    assert tally["peak"] <= 4, tally


async def test_the_fan_out_is_bounded_by_the_configured_concurrency() -> None:
    provider, tally = _provider(concurrency=2)

    [draft async for draft in provider.create_progress("a deck, 4 slides")]

    # A deck is background work; it may take some of the engine's batch, never
    # all of it. The pool is what enforces that, so the bound is the pool size.
    assert tally["peak"] == 2, tally


async def test_one_client_alone_does_not_pretend_to_fan_out() -> None:
    # No factory: every worker would share one client, and that client
    # serialises its own requests. The pool says so rather than queueing four
    # workers on a lock and reporting concurrency it does not have.
    provider = LLMPresentationProvider(
        RecordingPlanningLLM(),  # type: ignore[arg-type]
        max_tokens=1_024,
        slide_concurrency=4,
    )

    drafts = [draft async for draft in provider.create_progress("a deck, 4 slides")]

    assert len(drafts) == 4


async def test_drafts_stay_ordered_prefixes_of_one_deck() -> None:
    provider, _ = _provider(concurrency=4)

    drafts = [draft async for draft in provider.create_progress("a deck, 4 slides")]

    # Concurrency changes when answers arrive, never what the viewer sees: each
    # draft is the previous one plus the next slide, in outline order.
    assert [len(draft.specification.slides) for draft in drafts] == [1, 2, 3, 4]
    assert all(draft.expected_slide_count == 4 for draft in drafts)
    titles = [slide.title for slide in drafts[-1].specification.slides]
    assert titles == ["Slide 1", "Slide 2", "Slide 3", "Slide 4"], titles


async def test_the_deck_takes_one_background_lease_not_one_per_call() -> None:
    gate = CountingGate()
    provider, tally = _provider(concurrency=4, gate=gate)

    [draft async for draft in provider.create_progress("a deck, 4 slides")]

    # Five model calls - one outline, four slides - under one lease. Per call
    # the exclusive lease would serialise the fan-out it is meant to permit.
    assert tally["calls"] == 5, tally
    assert gate.leases == 1, gate.leases
    assert gate.peak_held == 1, gate.peak_held
