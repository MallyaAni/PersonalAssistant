"""Give interactive work priority over background work on a shared model.

The runtime already serves several requests at once — vLLM is configured with a
sequence limit and batches within it — so the job here is not to make model use
single-file. It is to stop a background microtask from taking capacity while
somebody is waiting on a reply.

That distinction was previously wrong. `interactive()` held a single global
exclusive lock for a whole chat lifecycle, which was invisible while one person
used the machine and became serialisation *between people* the moment a second
account existed: one person's turn held the lock and everyone else's waited. It
also discarded the concurrency the inference server was configured to provide.

So:

- **interactive work is concurrent.** It registers its presence and proceeds.
  Bounding it is the runtime's job, and the runtime queues past its own limit;
- **background work waits for quiet**, then takes an exclusive lease so two
  microtasks do not compete with each other either. It re-checks after
  acquiring, because an interactive request can arrive in that gap;
- **but it only waits for so long.** Waiting for a moment with *zero*
  interactive requests in flight is a priority rule on a quiet machine and a
  starvation rule on a busy one. On 2026-09-02 a deck spent 7m09s on its
  outline while chat ran at 17-27 calls a minute and the engine sat at
  `Waiting: 0 reqs`, 0.5% KV cache — the deck was not queued behind anything,
  it was refusing to start. After `max_wait_seconds` the task takes its lease
  anyway and joins the batch the runtime already knows how to share.

That bound is the same correction `interactive()` needed, applied to the other
half: exclusivity that was invisible with one user and wrong with two.

The presence counter carries an expiry so a process that dies mid-request cannot
hold background work off forever, and a held lease is renewed so work that
outlives one lease is not evicted halfway through.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from time import monotonic

from redis.asyncio import Redis
from redis.asyncio.lock import Lock
from redis.exceptions import LockError


class ModelExecutionGate:
    """Prioritize interactive model lifecycles over background microtasks."""

    # Configure one Redis-backed lease shared by API and worker processes.
    def __init__(
        self,
        redis_url: str,
        enabled: bool,
        lease_seconds: float,
        poll_seconds: float,
        max_wait_seconds: float = 20.0,
        namespace: str = "anios:model",
    ) -> None:
        self.enabled = enabled
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds
        self.max_wait_seconds = max_wait_seconds
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        # Namespaced so a test can exercise the real Redis paths without
        # touching the keys the running system schedules itself with: these are
        # process-wide names, and a test that pins `interactive_active` would
        # hold off a live deck rather than its own.
        self.lock_name = f"{namespace}:exclusive"
        # How many interactive requests are in flight. Background work waits
        # while this is above zero.
        self.active_name = f"{namespace}:interactive_active"

    # Run one user-facing request, concurrently with other user-facing requests.
    @asynccontextmanager
    async def interactive(self) -> AsyncIterator[None]:
        if not self.enabled:
            yield
            return
        await self.redis.incr(self.active_name)
        # Expiry is a safety net rather than correctness: a crashed process must
        # not hold background work off indefinitely.
        await self.redis.expire(self.active_name, int(self.lease_seconds))
        try:
            yield
        finally:
            remaining = await self.redis.decr(self.active_name)
            if remaining <= 0:
                await self.redis.delete(self.active_name)

    # Lease one background task, yielding to interactive work for a bounded wait.
    @asynccontextmanager
    async def background(self) -> AsyncIterator[None]:
        if not self.enabled:
            yield
            return
        lock = self.redis.lock(
            self.lock_name,
            timeout=self.lease_seconds,
            blocking_timeout=self.poll_seconds,
        )
        await self._acquire_when_quiet(lock)
        # One lease was sized for one microtask. A caller may now hold this
        # across a whole deck, which outlives it, so renew rather than let it
        # lapse and admit a second background task alongside this one.
        renewal = asyncio.create_task(self._renew(lock))
        try:
            yield
        finally:
            renewal.cancel()
            with suppress(asyncio.CancelledError):
                await renewal
            with suppress(LockError):
                await lock.release()

    # Take the exclusive lease once the machine is quiet, or once the wait is spent.
    async def _acquire_when_quiet(self, lock: Lock) -> None:
        deadline = monotonic() + self.max_wait_seconds
        while True:
            if await self._still_yielding(deadline):
                await asyncio.sleep(self.poll_seconds)
                continue
            if not bool(await lock.acquire()):
                await asyncio.sleep(self.poll_seconds)
                continue
            # An interactive request can arrive between the check and the
            # acquire. Yield the lease rather than competing with it - until the
            # wait is spent, after which competing is the whole point.
            if await self._still_yielding(deadline):
                with suppress(LockError):
                    await lock.release()
                await asyncio.sleep(self.poll_seconds)
                continue
            return

    # Whether to keep giving way: interactive work is running and time remains.
    async def _still_yielding(self, deadline: float) -> bool:
        if monotonic() >= deadline:
            return False
        return await self._interactive_in_flight()

    # Keep a held lease alive so work longer than one lease is not evicted.
    async def _renew(self, lock: Lock) -> None:
        interval = max(self.lease_seconds / 3.0, 1.0)
        while True:
            await asyncio.sleep(interval)
            with suppress(LockError):
                await lock.extend(self.lease_seconds, replace_ttl=True)

    # Whether any user-facing request is currently running.
    async def _interactive_in_flight(self) -> bool:
        return int(await self.redis.get(self.active_name) or 0) > 0
