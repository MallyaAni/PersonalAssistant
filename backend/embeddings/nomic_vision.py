import threading
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from backend.core.interfaces import VisionEmbeddingProvider

# CLIPImageProcessor constants taken from the model's preprocessor_config.json.
# These must match exactly: a wrong normalization still produces vectors, but
# they land in the wrong region of the space and retrieve silently bad results.
_IMAGE_SIZE = 224
_RESCALE = 1.0 / 255.0
_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


class NomicVisionEmbeddingProvider(VisionEmbeddingProvider):
    """Local ONNX image embedder aligned to nomic-embed-text-v1.5.

    Runs in-process on CPU. Weights are loaded lazily so an unconfigured
    deployment never pays the load cost, and a missing file disables the
    provider instead of failing application startup.
    """

    # Configure the local weights path; absence disables image embedding.
    def __init__(
        self,
        model_path: str,
        dimension: int,
        intra_op_threads: int = 1,
    ) -> None:
        self.model_path = Path(model_path)
        self.dimension = dimension
        self.intra_op_threads = intra_op_threads
        self._session: Any | None = None
        self._input_name: str | None = None
        self._lock = threading.Lock()

    # Indexing is skipped entirely when local weights are not present.
    def is_enabled(self) -> bool:
        return self.model_path.is_file()

    # Load the ONNX session once, under a lock, on first use.
    def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        with self._lock:
            if self._session is None:
                import onnxruntime

                options = onnxruntime.SessionOptions()
                options.intra_op_num_threads = self.intra_op_threads
                session = onnxruntime.InferenceSession(
                    str(self.model_path),
                    sess_options=options,
                    providers=["CPUExecutionProvider"],
                )
                self._input_name = session.get_inputs()[0].name
                self._session = session
        return self._session

    # Reproduce CLIPImageProcessor: RGB, bicubic 224x224, rescale, normalize, NCHW.
    def _preprocess(self, content: bytes) -> np.ndarray:
        with Image.open(BytesIO(content)) as image:
            rgb = image.convert("RGB")
            resized = rgb.resize((_IMAGE_SIZE, _IMAGE_SIZE), Image.Resampling.BICUBIC)
            pixels = np.asarray(resized, dtype=np.float32)
        normalized = (pixels * _RESCALE - _MEAN) / _STD
        return np.expand_dims(normalized.transpose(2, 0, 1), axis=0)

    # Embed one image into a unit-length vector in the shared text/image space.
    def embed_image(self, content: bytes) -> list[float]:
        if not self.is_enabled():
            raise RuntimeError(
                "Image embedding is not configured; local ONNX weights are missing."
            )
        session = self._ensure_session()
        outputs = session.run(None, {self._input_name: self._preprocess(content)})
        embedding = np.asarray(outputs[0], dtype=np.float32)
        # The export returns token states; the CLS token carries the embedding.
        if embedding.ndim == 3:
            embedding = embedding[:, 0, :]
        vector = embedding.reshape(-1)
        if vector.shape[0] != self.dimension:
            raise ValueError(
                f"Image embedding dimension {vector.shape[0]} does not match the "
                f"configured shared-space dimension {self.dimension}."
            )
        # L2 normalize so cosine distance against text vectors is meaningful.
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            raise ValueError("Image embedding collapsed to a zero vector.")
        return [float(value) for value in (vector / norm)]
