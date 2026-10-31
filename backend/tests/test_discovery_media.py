"""Scout reads the picture a listing published, within the sweep's bounds.

Feeds carry the event's poster, and the poster often states the date, venue or
performers the listing's prose omits. These tests pin the two things that make
reading it safe: only bytes that really are a picture reach the vision model,
and every failure is a missing caption rather than a lost find.
"""

import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.agents.scout.describing import Readable
from backend.agents.scout.seeing import (
    MAX_CAPTION_CHARS,
    PICTURE_PROMPT,
    PictureCaptioner,
    image_media_type,
)
from backend.database.session import AsyncSessionLocal
from backend.discovery.events import DiscoveredEvent
from backend.discovery.fetching import RequestBudget
from backend.discovery.novelty import (
    ScoredCandidate,
    SeenItemRepository,
    _event_from_payload,
    _payload,
)
from backend.discovery.relevance import RankedCandidate
from backend.discovery.runner import (
    DiscoveryRunner,
    SweepResult,
    candidates_from_digest,
)
from backend.discovery.sources_repository import DiscoverySourceRepository

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
_PNG = b"\x89PNG\r\n\x1a\n" + b"poster bytes"


# A vision provider that records what it was shown and answers with fixed text.
class _FakeVision:
    def __init__(
        self, answer: str = "A lantern poster for 12 October at Riverside Park."
    ) -> None:
        self.answer = answer
        self.calls: list[tuple[str, bytes, str]] = []

    async def analyze(self, prompt: str, content: bytes, mime_type: str):
        self.calls.append((prompt, content, mime_type))
        return SimpleNamespace(content=self.answer)


class _BrokenVision:
    async def analyze(self, prompt: str, content: bytes, mime_type: str):
        raise RuntimeError("vision runtime is down")


# A describer that records the source text it was given instead of calling a
# model, so the test asserts on what reached the description stage.
class _RecordingDescriber:
    def __init__(self) -> None:
        self.sources: list[str | None] = []

    async def describe(
        self,
        title: str,
        source: str | None,
        today=None,
        place=None,
        url=None,
        facts: str = "",
    ) -> Readable:
        self.sources.append(source)
        return Readable(title=title, description="Doors at seven.")


# Point the captioner's fetch at fixed bytes without touching the network.
def _serve(monkeypatch, content: bytes, declared: str) -> None:
    async def fake_fetch(url, budget=None, **kwargs):
        return content, declared

    monkeypatch.setattr("backend.agents.scout.seeing.fetch_bytes", fake_fetch)


@pytest.mark.asyncio
async def test_a_poster_is_shown_to_the_vision_model_and_captioned(monkeypatch):
    _serve(monkeypatch, _PNG, "image/png")
    vision = _FakeVision()
    budget = RequestBudget(limit=5)

    caption = await PictureCaptioner(vision).caption(
        "https://city.example/poster.png", budget
    )

    assert caption is not None
    assert caption.startswith("A picture published with this listing shows: ")
    assert "lantern poster" in caption
    # The shared picture instruction, and the type decided from the bytes.
    assert vision.calls == [(PICTURE_PROMPT, _PNG, "image/png")]


# The host's declared type is a claim. An HTML error page served as an image
# must never be encoded and sent to the model, even when the host labels it
# image/png to get past a type check.
@pytest.mark.parametrize("declared", ["text/html", "image/png"])
@pytest.mark.asyncio
async def test_an_html_error_page_is_never_shown_to_the_model(monkeypatch, declared):
    _serve(monkeypatch, b"<html>not found</html>", declared)
    vision = _FakeVision()

    caption = await PictureCaptioner(vision).caption(
        "https://city.example/poster.jpg", RequestBudget(limit=5)
    )

    assert caption is None
    assert vision.calls == []


def test_the_media_type_is_decided_from_the_bytes_not_the_claim():
    assert image_media_type(_PNG, "text/html") == "image/png"
    assert image_media_type(b"\xff\xd8\xffrest", "") == "image/jpeg"
    assert image_media_type(b"RIFF0000WEBPrest", "") == "image/webp"
    # A format with no signature is accepted only when the host declared it.
    assert image_media_type(b"....ftypavif", "image/avif") == "image/avif"
    assert image_media_type(b"....ftypavif", "application/octet-stream") is None
    # Text is refused whatever the host claims it is.
    assert image_media_type(b"<html>not found</html>", "image/png") is None
    assert image_media_type(b"  \n<svg xmlns='...'></svg>", "image/svg+xml") is None


@pytest.mark.asyncio
async def test_without_a_vision_provider_there_is_no_caption(monkeypatch):
    async def should_not_fetch(*args, **kwargs):
        raise AssertionError("a picture was fetched with nothing to read it")

    monkeypatch.setattr("backend.agents.scout.seeing.fetch_bytes", should_not_fetch)
    budget = RequestBudget(limit=5)

    caption = await PictureCaptioner(None).caption(
        "https://city.example/p.png", budget
    )
    assert caption is None
    assert budget.spent == 0


@pytest.mark.asyncio
async def test_a_spent_budget_means_no_caption(monkeypatch):
    async def should_not_fetch(*args, **kwargs):
        raise AssertionError("the sweep's budget was already spent")

    monkeypatch.setattr("backend.agents.scout.seeing.fetch_bytes", should_not_fetch)
    budget = RequestBudget(limit=1)
    budget.spend()

    assert (
        await PictureCaptioner(_FakeVision()).caption(
            "https://city.example/p.png", budget
        )
        is None
    )


@pytest.mark.asyncio
async def test_a_failed_vision_call_is_a_missing_caption(monkeypatch):
    _serve(monkeypatch, _PNG, "image/png")

    caption = await PictureCaptioner(_BrokenVision()).caption(
        "https://city.example/p.png", RequestBudget(limit=5)
    )

    assert caption is None


@pytest.mark.asyncio
async def test_the_caption_is_bounded_like_any_feed_text(monkeypatch):
    _serve(monkeypatch, _PNG, "image/png")
    vision = _FakeVision(answer="word " * 500)

    caption = await PictureCaptioner(vision).caption(
        "https://city.example/p.png", RequestBudget(limit=5)
    )

    assert caption is not None
    assert len(caption) <= MAX_CAPTION_CHARS + len(
        "A picture published with this listing shows: "
    )


# The caption reaches the describer ahead of the listing's own text, so the
# description is written from both.
@pytest.mark.asyncio
async def test_the_caption_reaches_the_describer_before_the_page_text():
    async with AsyncSessionLocal() as session:
        runner = DiscoveryRunner(
            sources=DiscoverySourceRepository(session),
            seen=SeenItemRepository(session),
            embeddings=SimpleNamespace(embed_texts=lambda texts: [[] for _ in texts]),
        )
        recorder = _RecordingDescriber()
        runner.describer = recorder

        async def fake_caption(url, budget=None):
            return "A picture published with this listing shows: a lantern poster."

        runner.pictures.caption = fake_caption
        event = DiscoveredEvent(
            source_id="src-1",
            external_id="evt-1",
            title="Lantern festival",
            starts_at=_NOW,
            ends_at=None,
            place=None,
            url="https://city.example/e/1",
            summary="Riverside Park",
            media_url="https://city.example/poster.png",
        )
        ranked = RankedCandidate(ScoredCandidate(event, None), 0.9, "festivals")

        result = await runner._make_readable(
            (ranked,), budget=RequestBudget(limit=5), now=_NOW
        )

    assert recorder.sources == [
        "A picture published with this listing shows: a lantern poster.\n\n"
        "Riverside Park"
    ]
    assert result[0].event.summary == "Doors at seven."


# A resumed run and a later preview rebuild from the saved digest, and a repeat
# fill rebuilds from the seen payload; both must keep the picture.
def test_the_media_url_survives_the_digest_and_the_seen_payload():
    event = DiscoveredEvent(
        source_id="src-1",
        external_id="evt-1",
        title="Lantern festival",
        starts_at=_NOW,
        ends_at=None,
        place=None,
        url="https://city.example/e/1",
        summary=None,
        media_url="https://city.example/poster.png",
    )
    result = SweepResult(
        selected=(RankedCandidate(ScoredCandidate(event, None), 0.9, "festivals"),),
        candidate_count=1,
        novel_count=1,
        requests_spent=1,
        failed_sources=(),
    )

    selected, _ = candidates_from_digest(result.to_digest_json())

    assert selected[0].event.media_url == "https://city.example/poster.png"
    rebuilt = _event_from_payload(json.dumps(_payload(event)))
    assert rebuilt is not None
    assert rebuilt.media_url == "https://city.example/poster.png"
