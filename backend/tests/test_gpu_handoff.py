import functools

import httpx
import pytest

from backend.artifacts.types import GeneratedImage, ImageGenerationRequest
from backend.core import gpu_handoff
from backend.core.gpu_handoff import GpuHandoffImageProvider, InferenceGpuHandoff
from backend.core.interfaces import ImageProvider


class RecordingProvider(ImageProvider):
    """Record that the wrapped image job actually ran."""

    def __init__(self, observed: list[str]) -> None:
        self.observed = observed

    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        self.observed.append("generate")
        return GeneratedImage(
            content=b"png",
            mime_type="image/png",
            width=request.width,
            height=request.height,
            provider_job_id="job",
            metadata={},
        )


class FailingProvider(ImageProvider):
    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        raise RuntimeError("diffusion runtime failed")


def _request() -> ImageGenerationRequest:
    return ImageGenerationRequest(prompt="a mug", width=2048, height=2048, seed=1)


# Route every handoff request into a recorder instead of the network.
def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    failing: set[str] | None = None,
) -> None:
    refused = failing or set()

    def route(request: httpx.Request) -> httpx.Response:
        name = request.url.path.strip("/")
        calls.append(name)
        return httpx.Response(500 if name in refused else 200, json={})

    transport = httpx.MockTransport(route)
    monkeypatch.setattr(
        gpu_handoff.httpx,
        "AsyncClient",
        functools.partial(httpx.AsyncClient, transport=transport),
    )


# The GPU is released before the image runs and reclaimed after it finishes.
@pytest.mark.asyncio
async def test_generation_sleeps_then_wakes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _install_transport(monkeypatch, calls)
    observed: list[str] = []
    provider = GpuHandoffImageProvider(
        RecordingProvider(observed),
        InferenceGpuHandoff(base_url="http://inference:8000", enabled=True),
    )

    await provider.generate(_request())

    assert calls == ["sleep", "wake_up"]
    assert observed == ["generate"]


# A failed image must still return the GPU, or every later chat would break.
@pytest.mark.asyncio
async def test_wake_runs_even_when_generation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install_transport(monkeypatch, calls)
    provider = GpuHandoffImageProvider(
        FailingProvider(),
        InferenceGpuHandoff(base_url="http://inference:8000", enabled=True),
    )

    with pytest.raises(RuntimeError):
        await provider.generate(_request())

    assert calls == ["sleep", "wake_up"]


# A refused handoff degrades to a slow image rather than a failed one, and must
# not then issue a wake for weights it never put to sleep.
@pytest.mark.asyncio
async def test_refused_sleep_still_generates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _install_transport(monkeypatch, calls, failing={"sleep"})
    observed: list[str] = []
    provider = GpuHandoffImageProvider(
        RecordingProvider(observed),
        InferenceGpuHandoff(
            base_url="http://inference:8000", enabled=True, wake_attempts=1
        ),
    )

    await provider.generate(_request())

    assert calls == ["sleep"]
    assert observed == ["generate"]


# Disabling the handoff leaves the provider untouched and issues no requests.
@pytest.mark.asyncio
async def test_disabled_handoff_makes_no_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install_transport(monkeypatch, calls)
    observed: list[str] = []
    provider = GpuHandoffImageProvider(
        RecordingProvider(observed),
        InferenceGpuHandoff(base_url="http://inference:8000", enabled=False),
    )

    await provider.generate(_request())

    assert calls == []
    assert observed == ["generate"]
