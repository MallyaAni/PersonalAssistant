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
  acquiring, because an interactive request can arrive in that gap.

The presence counter carries an expiry so a process that dies mid-request cannot
hold background work off forever.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from redis.asyncio import Redis
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
    ) -> None:
        self.enabled = enabled
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        # Held only by background work, so two microtasks do not compete.
        self.lock_name = "anios:model:exclusive"
        # How many interactive requests are in flight. Background work waits
        # while this is above zero.
        self.active_name = "anios:model:interactive_active"

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

    # Lease one background microtask only when no interactive request is active.
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
        acquired = False
        while not acquired:
            if await self._interactive_in_flight():
                await asyncio.sleep(self.poll_seconds)
                continue
            acquired = bool(await lock.acquire())
            if not acquired:
                await asyncio.sleep(self.poll_seconds)
                continue
            # An interactive request can arrive between the check and the
            # acquire. Yield the lease rather than competing with it.
            if await self._interactive_in_flight():
                with suppress(LockError):
                    await lock.release()
                acquired = False
                await asyncio.sleep(self.poll_seconds)
        try:
            yield
        finally:
            with suppress(LockError):
                await lock.release()

    # Whether any user-facing request is currently running.
    async def _interactive_in_flight(self) -> bool:
        return int(await self.redis.get(self.active_name) or 0) > 0
