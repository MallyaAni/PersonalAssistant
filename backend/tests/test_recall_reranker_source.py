"""Recall reordering uses the cross-encoder already deployed for Scout.

Measured 2026-09-03 over five recall questions on the same six turns: the
served Qwen3-Reranker-0.6B was right twice at 67.6 ms and held about 3.6 GB;
the local ms-marco cross-encoder was right five times at 39.6 ms on the CPU.
The served model ranked the one turn naming the trip last for "what did we
say about the Amalfi trip?".
"""
import pytest

from backend.config.settings import settings
from backend.core import reranker


class _Encoder:
    def __init__(self, scores: list[float] | None = None, works: bool = True) -> None:
        self.scores = scores if scores is not None else [0.9, 0.1]
        self.works = works
        self.calls = 0

    def is_enabled(self) -> bool:
        return self.works

    def score(self, pairs):
        self.calls += 1
        if not self.works:
            raise RuntimeError("weights are missing")
        return self.scores[: len(pairs)]


@pytest.fixture(autouse=True)
def _forget_encoder():
    reranker._local_encoder.cache_clear()
    yield
    reranker._local_encoder.cache_clear()


@pytest.mark.asyncio
async def test_recall_scores_with_the_local_cross_encoder(monkeypatch):
    encoder = _Encoder([0.95, -9.1])
    monkeypatch.setattr(reranker, "_local_encoder", lambda: encoder)
    monkeypatch.setattr(settings, "RECALL_RERANKER_SOURCE", "local")
    assert reranker.reranker_enabled() is True
    scores = await reranker.rerank("what did we say about the Amalfi trip?", ["the tour", "a couch"])
    assert scores == [0.95, -9.1] and encoder.calls == 1


@pytest.mark.asyncio
async def test_an_absent_or_broken_encoder_keeps_the_first_pass_order(monkeypatch):
    monkeypatch.setattr(settings, "RECALL_RERANKER_SOURCE", "local")
    monkeypatch.setattr(reranker, "_local_encoder", lambda: None)
    assert reranker.reranker_enabled() is False
    assert await reranker.rerank("q", ["a", "b"]) is None

    broken = _Encoder(works=False)
    monkeypatch.setattr(reranker, "_local_encoder", lambda: broken)
    # is_enabled is what the caller asks; a raising score must not cost the turn.
    broken.works = True
    monkeypatch.setattr(broken, "score", _raises)
    assert await reranker.rerank("q", ["a", "b"]) is None


def _raises(pairs):
    raise RuntimeError("onnx session died")


@pytest.mark.asyncio
async def test_nothing_to_rank_and_the_service_setting_still_works(monkeypatch):
    monkeypatch.setattr(settings, "RECALL_RERANKER_SOURCE", "local")
    monkeypatch.setattr(reranker, "_local_encoder", lambda: _Encoder())
    assert await reranker.rerank("q", []) is None
    # The switch back to the served model is still there and still gated on its URL.
    monkeypatch.setattr(settings, "RECALL_RERANKER_SOURCE", "service")
    monkeypatch.setattr(settings, "RERANKER_BASE_URL", "")
    assert reranker.reranker_enabled() is False
    monkeypatch.setattr(settings, "RERANKER_BASE_URL", "http://vllm-reranker:8000")
    assert reranker.reranker_enabled() is True
