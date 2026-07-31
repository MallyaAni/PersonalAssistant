"""Hand the GPU from local inference to another resident model and take it back."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from backend.artifacts.types import (
    GeneratedImage,
    ImageEditRequest,
    ImageGenerationRequest,
)
from backend.core.interfaces import ImageEditProvider, ImageProvider

logger = logging.getLogger(__name__)


class InferenceGpuHandoff:
    """Release local inference GPU memory for one foreign model job.

    A single-GPU workstation cannot hold a generation model and a diffusion
    model at once. Without an explicit handoff the diffusion runtime streams its
    weights from system RAM for every step, which turned an 18-second image into
    several minutes. Sleeping the inference server offloads its weights instead,
    so exactly one of the two is resident at a time.
    """

    # Configure the sleep-capable endpoint and how long a handoff may take.
    def __init__(
        self,
        base_url: str,
        enabled: bool,
        sleep_level: int = 1,
        timeout_seconds: float = 120.0,
        wake_attempts: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.enabled = enabled
        self.sleep_level = sleep_level
        self.timeout_seconds = timeout_seconds
        self.wake_attempts = wake_attempts

    # Yield with inference asleep, then wake it however the body finished.
    @asynccontextmanager
    async def released(self) -> AsyncIterator[bool]:
        if not self.enabled:
            yield False
            return

        released = await self._sleep()
        try:
            yield released
        finally:
            # Never leave the server asleep: a failed wake would break every
            # later chat, which is worse than the slow image this avoided.
            if released:
                await self._wake()

    # Ask the server to offload its weights, reporting whether it complied.
    async def _sleep(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/sleep",
                    params={"level": str(self.sleep_level)},
                )
                response.raise_for_status()
        except Exception:
            # A refused handoff is a slow image, not a failed one.
            logger.warning("Inference GPU handoff failed to sleep", exc_info=True)
            return False
        return True

    # Restore the weights, retrying because chat cannot proceed without them.
    async def _wake(self) -> None:
        for attempt in range(self.wake_attempts):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(f"{self.base_url}/wake_up")
                    response.raise_for_status()
                return
            except Exception:
                if attempt == self.wake_attempts - 1:
                    logger.error(
                        "Inference GPU handoff could not wake the server; "
                        "chat will fail until it is restarted",
                        exc_info=True,
                    )
                    return
                await asyncio.sleep(2.0 * (attempt + 1))

    # Report whether the server currently holds its weights on the GPU.
    async def is_sleeping_state(self) -> bool | None:
        if not self.enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(f"{self.base_url}/is_sleeping")
                response.raise_for_status()
                return bool(response.json().get("is_sleeping"))
        except Exception:
            logger.warning("Could not read inference sleep state", exc_info=True)
            return None


class GpuHandoffImageProvider(ImageProvider):
    """Run one image generation with local inference weights offloaded."""

    # Wrap the real provider so no caller needs to know about the handoff.
    def __init__(self, provider: ImageProvider, handoff: InferenceGpuHandoff) -> None:
        self.provider = provider
        self.handoff = handoff

    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        async with self.handoff.released():
            return await self.provider.generate(request)


class GpuHandoffImageEditProvider(ImageEditProvider):
    """Run one image edit with local inference weights offloaded."""

    # Editing loads the same diffusion weights, so it needs the same handoff.
    def __init__(
        self, provider: ImageEditProvider, handoff: InferenceGpuHandoff
    ) -> None:
        self.provider = provider
        self.handoff = handoff

    async def edit(self, request: ImageEditRequest) -> GeneratedImage:
        async with self.handoff.released():
            return await self.provider.edit(request)
