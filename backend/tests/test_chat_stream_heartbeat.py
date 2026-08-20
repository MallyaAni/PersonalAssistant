"""A long silence must not be mistaken for a dead connection.

Generating or editing a picture takes one to two minutes, and the turn has
nothing to say for all of it. Public access is a Cloudflare tunnel, which
closes a proxied request that has sent nothing for roughly a hundred seconds.
A real edit took 116 seconds: the backend fetched the finished image
successfully and the user was told "DeepMatter did not respond", because the
connection had been closed out from under a request that was working fine.
"""

import asyncio
from collections.abc import AsyncGenerator

import pytest

from backend.api.v1.api import _with_heartbeat

pytestmark = pytest.mark.asyncio


async def _frames(*items: str, pause: float = 0.0) -> AsyncGenerator[str, None]:
    for item in items:
        if pause:
            await asyncio.sleep(pause)
        yield item


async def test_a_silent_stretch_sends_a_comment_rather_than_nothing():
    produced = [
        frame
        async for frame in _with_heartbeat(
            _frames("event: start\ndata: {}\n\n", pause=0.25), interval=0.05
        )
    ]

    assert produced[-1] == "event: start\ndata: {}\n\n"
    keepalives = [frame for frame in produced if frame.startswith(":")]
    assert keepalives, "a silence longer than the interval sent nothing"
    # A comment carries no event and no data, so no reader can act on it.
    assert all(frame == ": keepalive\n\n" for frame in keepalives)


async def test_events_are_passed_through_unchanged_and_in_order():
    original = [
        "event: start\ndata: {}\n\n",
        'event: delta\ndata: {"content": "hi"}\n\n',
        "event: done\ndata: {}\n\n",
    ]

    produced = [
        frame
        async for frame in _with_heartbeat(_frames(*original), interval=30.0)
        if not frame.startswith(":")
    ]

    assert produced == original


async def test_a_stream_with_nothing_to_say_still_ends():
    produced = [frame async for frame in _with_heartbeat(_frames(), interval=0.05)]

    assert produced == []


# A browser tab closing abandons the generator mid-flight. The pull that was
# outstanding has to be cancelled with it rather than left to resolve into
# nothing, or the request's work carries on with no reader.
async def test_abandoning_the_stream_does_not_leave_a_pull_running():
    started = asyncio.Event()
    released = asyncio.Event()

    async def _slow() -> AsyncGenerator[str, None]:
        started.set()
        await released.wait()
        yield "event: done\ndata: {}\n\n"

    stream = _with_heartbeat(_slow(), interval=0.05)
    first = await anext(stream)
    assert first == ": keepalive\n\n"
    await started.wait()

    await stream.aclose()

    # Nothing is left waiting on the released event.
    released.set()
    await asyncio.sleep(0.05)
    assert not [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]


# The turn keeps working after its last event - persisting, updating memory -
# and heart-beating through that window put comments after `done`. The browser
# had stopped expecting anything, so a stream closing mid-comment left a
# partial frame in its buffer and it reported "ended with an incomplete event"
# under a complete answer. Worst on image generation, where the tail is long.
async def test_no_keepalive_is_sent_after_the_turn_has_finished():
    async def with_work_after_done():
        yield "event: start\ndata: {}\n\n"
        yield "event: done\ndata: {}\n\n"
        await asyncio.sleep(0.2)

    produced = [
        frame async for frame in _with_heartbeat(with_work_after_done(), interval=0.02)
    ]

    assert produced[-1] == "event: done\ndata: {}\n\n"
    assert not [frame for frame in produced if frame.startswith(":")]


# The silence before the answer still has to be held open, or a long image
# generation loses its connection.
async def test_a_silence_before_the_answer_is_still_held_open():
    async def slow_answer():
        await asyncio.sleep(0.15)
        yield "event: done\ndata: {}\n\n"

    produced = [frame async for frame in _with_heartbeat(slow_answer(), interval=0.02)]

    assert [frame for frame in produced if frame.startswith(":")]
    assert produced[-1] == "event: done\ndata: {}\n\n"
