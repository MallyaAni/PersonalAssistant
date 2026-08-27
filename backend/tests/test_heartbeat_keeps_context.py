"""The streaming wrapper keeps one context across pulls.

Every pull of the turn generator is its own task. A task starts with a copy
of the context, so a ContextVar the turn set during one pull was invisible
to the next - in production only, because an in-process test iterates the
generator in a single task and never sees the loss. On 2026-08-26 that
silently dropped the picker's previous-reply hint, the search identity and
limit, the events-format flag, and the turn trace between frames. This
test drives the real wrapper the way Starlette does and is the only layer
that can catch it.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar

import pytest

from backend.api.v1.api import _with_heartbeat

_seen: ContextVar[str] = ContextVar("seen", default="unset")


async def _turn():
    # First pull: set. Second pull: read. Third: read after a "done" frame.
    _seen.set("set during the first pull")
    yield "event: start\ndata: {}\n\n"
    yield f"event: delta\ndata: {_seen.get()}\n\n"
    yield "event: done\ndata: {}\n\n"
    yield f"event: after\ndata: {_seen.get()}\n\n"


@pytest.mark.asyncio
async def test_a_contextvar_set_in_one_pull_is_visible_in_the_next():
    frames = [frame async for frame in _with_heartbeat(_turn(), interval=5.0)]
    assert "data: set during the first pull" in frames[1], frames
    assert "data: set during the first pull" in frames[3], frames


@pytest.mark.asyncio
async def test_the_callers_own_context_is_left_alone():
    _seen.set("the caller's value")
    async for _ in _with_heartbeat(_turn(), interval=5.0):
        pass
    assert _seen.get() == "the caller's value"


@pytest.mark.asyncio
async def test_the_bare_task_boundary_really_loses_it():
    """The failure this guards, shown rather than assumed: pulled by fresh
    tasks, the second pull does not see the first pull's set."""
    iterator = _turn().__aiter__()
    await asyncio.ensure_future(anext(iterator))
    second = await asyncio.ensure_future(anext(iterator))
    assert "data: unset" in second, second
