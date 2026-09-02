"""Priority is a rule about who waits, and a rule with no bound is starvation.

The gate had no coverage at all, and the defect it shipped was the kind that
only appears with two kinds of load at once: `background()` waited for a moment
with *zero* interactive requests in flight, which is instant on a quiet machine
and never on a busy one. On 2026-09-02 a deck spent 7m09s on one outline call
while chat ran at 17-27 calls a minute and the inference engine sat idle
(`Waiting: 0 reqs`, 0.5% KV cache). Nothing was queued; the deck was declining
to start.

These tests are about the property, not the timings: background work yields
while interactive work is running, and stops yielding once it has waited long
enough. Every test uses its own Redis namespace so it cannot schedule - or
stall - the running system.
"""

import asyncio
import os
import uuid

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.core.model_gate import ModelExecutionGate

# The compose Redis when the gate runs the suite; localhost for a developer with
# one running. These tests assert on real Redis behaviour - an exclusive lock, a
# counter with an expiry - so a stub would measure the stub.
_REDIS = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

pytestmark = pytest.mark.asyncio


# Build one gate on its own keys, so a run cannot disturb the live scheduler.
def _gate(
    max_wait_seconds: float = 20.0,
    poll_seconds: float = 0.05,
) -> ModelExecutionGate:
    return ModelExecutionGate(
        _REDIS,
        enabled=True,
        lease_seconds=30.0,
        poll_seconds=poll_seconds,
        max_wait_seconds=max_wait_seconds,
        namespace=f"anios:test:model:{uuid.uuid4().hex[:12]}",
    )


async def test_background_work_starts_immediately_on_a_quiet_machine() -> None:
    gate = _gate()

    started = asyncio.get_running_loop().time()
    async with gate.background():
        waited = asyncio.get_running_loop().time() - started

    # The bound must not cost anything when nothing is competing: this is the
    # common case and it should not wait for the deadline it never needs.
    assert waited < 1.0, waited


async def test_background_work_gives_way_while_interactive_work_runs() -> None:
    gate = _gate(max_wait_seconds=30.0)
    order: list[str] = []

    async def interactive() -> None:
        async with gate.interactive():
            await asyncio.sleep(0.4)
            order.append("interactive")

    async def background() -> None:
        async with gate.background():
            order.append("background")

    holder = asyncio.create_task(interactive())
    await asyncio.sleep(0.05)
    await asyncio.wait_for(asyncio.gather(holder, background()), timeout=10)

    # Yielding is still the rule; the bound only decides how long it holds.
    assert order == ["interactive", "background"], order


async def test_background_work_stops_waiting_once_its_patience_is_spent() -> None:
    gate = _gate(max_wait_seconds=0.3)
    order: list[str] = []

    async def interactive() -> None:
        # Longer than the bound, and continuous: the quiet moment the old rule
        # waited for does not arrive inside this test at all.
        async with gate.interactive():
            await asyncio.sleep(2.0)
            order.append("interactive")

    async def background() -> None:
        async with gate.background():
            order.append("background")

    holder = asyncio.create_task(interactive())
    await asyncio.sleep(0.05)
    await asyncio.wait_for(asyncio.gather(background(), holder), timeout=10)

    # This is the whole fix: the deck goes ahead rather than waiting out a
    # busy machine forever. Before the bound, `background` appeared second or
    # not at all.
    assert order == ["background", "interactive"], order


async def test_two_background_tasks_still_do_not_run_together() -> None:
    gate = _gate(max_wait_seconds=0.1)
    running = 0
    peak = 0

    async def background() -> None:
        nonlocal running, peak
        async with gate.background():
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.2)
            running -= 1

    await asyncio.wait_for(
        asyncio.gather(background(), background(), background()),
        timeout=15,
    )

    # The bound relaxes what background work waits for, never the exclusivity
    # between two background tasks: those still take turns.
    assert peak == 1, peak


async def test_a_disabled_gate_schedules_nothing() -> None:
    gate = ModelExecutionGate(
        _REDIS,
        enabled=False,
        lease_seconds=30.0,
        poll_seconds=0.05,
        namespace=f"anios:test:model:{uuid.uuid4().hex[:12]}",
    )

    async with gate.background():
        pass
    async with gate.interactive():
        pass

    # Disabled means absent, not permissive-but-present: no key is written, so
    # a machine running without Redis is not quietly depending on it.
    assert await gate.redis.get(gate.active_name) is None
    assert await gate.redis.get(gate.lock_name) is None
