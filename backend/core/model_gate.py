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
        self.lock_name = "anios:model:exclusive"
        self.waiting_name = "anios:model:interactive_waiting"

    # Hold the shared model for one complete user-facing request lifecycle.
    @asynccontextmanager
    async def interactive(self) -> AsyncIterator[None]:
        if not self.enabled:
            yield
            return
        await self.redis.incr(self.waiting_name)
        await self.redis.expire(self.waiting_name, int(self.lease_seconds))
        lock = self.redis.lock(
            self.lock_name,
            timeout=self.lease_seconds,
            blocking_timeout=self.lease_seconds,
        )
        acquired = False
        try:
            acquired = bool(await lock.acquire())
            if not acquired:
                raise TimeoutError("Timed out waiting for the interactive model lease")
        finally:
            remaining = await self.redis.decr(self.waiting_name)
            if remaining <= 0:
                await self.redis.delete(self.waiting_name)
        try:
            yield
        finally:
            if acquired:
                with suppress(LockError):
                    await lock.release()

    # Lease one background model microtask only when no chat is waiting.
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
            waiting = int(await self.redis.get(self.waiting_name) or 0)
            if waiting > 0:
                await asyncio.sleep(self.poll_seconds)
                continue
            acquired = bool(await lock.acquire())
            if not acquired:
                await asyncio.sleep(self.poll_seconds)
                continue
            waiting = int(await self.redis.get(self.waiting_name) or 0)
            if waiting > 0:
                with suppress(LockError):
                    await lock.release()
                acquired = False
                await asyncio.sleep(self.poll_seconds)
        try:
            yield
        finally:
            with suppress(LockError):
                await lock.release()
