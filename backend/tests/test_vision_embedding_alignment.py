"""Regression guard for the real vision encoder.

Every other vision-embedding test injects a stub ONNX session, which proves the
maths but not that the model produces semantically correct vectors. A wrong
preprocessing constant would still yield unit-length 768-dim output and pass
those tests while retrieval silently returned nonsense. This test exercises the
real weights and asserts semantic ordering, so such a regression fails loudly.

Skipped when the weights or the local text embedder are unavailable, so it never
blocks a checkout that has not downloaded them.
"""

from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageDraw

from backend.config.settings import settings
from backend.embeddings.nomic_vision import NomicVisionEmbeddingProvider

WEIGHTS = Path(settings.VISION_EMBEDDING_MODEL_PATH)
pytestmark = pytest.mark.skipif(
    not WEIGHTS.is_file(),
    reason="vision embedding weights are not present",
)


# Draw a large unambiguous red circle on white.
def _red_circle() -> bytes:
    image = Image.new("RGB", (512, 512), "white")
    ImageDraw.Draw(image).ellipse((64, 64, 448, 448), fill="red")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _embed_text(query: str) -> list[float] | None:
    try:
        response = httpx.post(
            f"{settings.LLM_BASE_URL}/v1/embeddings",
            json={
                "model": settings.EMBEDDING_MODEL,
                # Nomic requires this prefix for multimodal retrieval queries.
                "input": [f"search_query: {query}"],
            },
            timeout=30,
        )
        response.raise_for_status()
    except Exception:
        return None
    return list(response.json()["data"][0]["embedding"])


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    return dot / (norm_a * norm_b)


def test_real_weights_produce_a_unit_length_vector_of_configured_width():
    provider = NomicVisionEmbeddingProvider(
        str(WEIGHTS),
        dimension=settings.VISION_EMBEDDING_DIMENSION,
    )

    vector = provider.embed_image(_red_circle())

    assert len(vector) == settings.VISION_EMBEDDING_DIMENSION
    assert sum(value * value for value in vector) ** 0.5 == pytest.approx(1.0, abs=1e-5)


def test_matching_text_ranks_above_unrelated_text_in_the_shared_space():
    provider = NomicVisionEmbeddingProvider(
        str(WEIGHTS),
        dimension=settings.VISION_EMBEDDING_DIMENSION,
    )
    image_vector = provider.embed_image(_red_circle())

    matching = _embed_text("a large red circle on a white background")
    unrelated = _embed_text("a quarterly financial report about tax policy")
    if matching is None or unrelated is None:
        pytest.skip("local text embedding endpoint is unavailable")

    matching_score = _cosine(image_vector, matching)
    unrelated_score = _cosine(image_vector, unrelated)

    # Absolute cross-modal scores are small; only the ordering is meaningful.
    assert matching_score > unrelated_score
