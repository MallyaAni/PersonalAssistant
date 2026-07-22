from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from backend.embeddings.nomic_vision import NomicVisionEmbeddingProvider


def _png(colour: str = "red", size: int = 64) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (size, size), colour).save(buffer, format="PNG")
    return buffer.getvalue()


class StubSession:
    """Return a fixed tensor so embedding maths can be asserted without weights."""

    def __init__(self, output: np.ndarray) -> None:
        self.output = output
        self.seen: list[np.ndarray] = []

    def run(self, _outputs, feed):
        self.seen.append(next(iter(feed.values())))
        return [self.output]


def _provider(tmp_path, dimension: int = 4) -> NomicVisionEmbeddingProvider:
    weights = tmp_path / "model.onnx"
    weights.write_bytes(b"not-a-real-model")
    return NomicVisionEmbeddingProvider(str(weights), dimension=dimension)


def test_provider_is_disabled_when_weights_are_absent(tmp_path):
    provider = NomicVisionEmbeddingProvider(str(tmp_path / "missing.onnx"), 768)

    assert provider.is_enabled() is False
    with pytest.raises(RuntimeError, match="not configured"):
        provider.embed_image(_png())


def test_preprocessing_matches_the_clip_processor_contract(tmp_path):
    provider = _provider(tmp_path)

    tensor = provider._preprocess(_png("white", size=32))

    # NCHW, resized to the model's fixed 224x224 input.
    assert tensor.shape == (1, 3, 224, 224)
    assert tensor.dtype == np.float32
    # Pure white rescales to 1.0 then normalizes to (1 - mean) / std per channel.
    expected_r = (1.0 - 0.48145466) / 0.26862954
    assert tensor[0, 0].max() == pytest.approx(expected_r, rel=1e-4)


def test_embedding_is_l2_normalized_from_the_cls_token(tmp_path):
    provider = _provider(tmp_path)
    # Token states: CLS first, then a decoy token that must be ignored.
    provider._session = StubSession(
        np.array([[[3.0, 4.0, 0.0, 0.0], [99.0, 99.0, 99.0, 99.0]]], dtype=np.float32)
    )
    provider._input_name = "pixel_values"

    vector = provider.embed_image(_png())

    assert len(vector) == 4
    # 3-4-0-0 normalizes to 0.6-0.8-0-0, proving CLS selection and unit length.
    assert vector == pytest.approx([0.6, 0.8, 0.0, 0.0])
    assert np.linalg.norm(vector) == pytest.approx(1.0)


def test_two_dimensional_output_is_used_directly(tmp_path):
    provider = _provider(tmp_path)
    provider._session = StubSession(np.array([[0.0, 5.0, 0.0, 0.0]], dtype=np.float32))
    provider._input_name = "pixel_values"

    assert provider.embed_image(_png()) == pytest.approx([0.0, 1.0, 0.0, 0.0])


def test_dimension_mismatch_is_rejected_rather_than_stored(tmp_path):
    provider = _provider(tmp_path, dimension=768)
    provider._session = StubSession(np.ones((1, 4), dtype=np.float32))
    provider._input_name = "pixel_values"

    # A wrong-width vector would corrupt the shared space, so it must not pass.
    with pytest.raises(ValueError, match="does not match"):
        provider.embed_image(_png())


def test_zero_vector_is_rejected(tmp_path):
    provider = _provider(tmp_path)
    provider._session = StubSession(np.zeros((1, 4), dtype=np.float32))
    provider._input_name = "pixel_values"

    with pytest.raises(ValueError, match="zero vector"):
        provider.embed_image(_png())
