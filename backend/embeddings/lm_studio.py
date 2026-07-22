import threading
from typing import Any, cast

import httpx

from backend.embeddings.base import EmbeddingProvider


class LMStudioEmbeddingProvider(EmbeddingProvider):
    """Generate embeddings through LM Studio's OpenAI-compatible endpoint."""

    # Configure one provider and its bounded concurrent request slots.
    def __init__(
        self,
        base_url: str,
        model: str,
        dimension: int,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        max_concurrency: int = 1,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimension = dimension
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.client = client
        self._request_slots = threading.BoundedSemaphore(max_concurrency)

    def embed_text(self, text: str) -> list[float]:
        return self._embed_batch([f"search_document: {text}"])[0]

    def embed_query(self, query: str) -> list[float]:
        return self._embed_batch([f"search_query: {query}"])[0]

    # Embed several documents in one request through the shared request slot.
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed_batch([f"search_document: {text}" for text in texts])

    # Post one bounded batch of prefixed inputs and validate every returned vector.
    def _embed_batch(self, inputs: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "input": inputs}

        with self._request_slots:
            if self.client is not None:
                response = self.client.post(
                    f"{self.base_url}/v1/embeddings",
                    headers=headers,
                    json=payload,
                )
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        f"{self.base_url}/v1/embeddings",
                        headers=headers,
                        json=payload,
                    )

        response.raise_for_status()
        result = cast(dict[str, Any], response.json())
        data = result.get("data") or []
        if len(data) != len(inputs):
            raise ValueError(
                "LM Studio returned " f"{len(data)} embeddings for {len(inputs)} inputs"
            )
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        return [self._validate(item.get("embedding")) for item in ordered]

    # Ensure one returned embedding matches the configured dimension and type.
    def _validate(self, embedding: Any) -> list[float]:
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("LM Studio response did not contain an embedding")
        if len(embedding) != self.dimension:
            raise ValueError(
                "LM Studio embedding dimension mismatch: "
                f"expected {self.dimension}, received {len(embedding)}"
            )
        if not all(isinstance(value, int | float) for value in embedding):
            raise ValueError("LM Studio embedding contained a non-numeric value")
        return [float(value) for value in embedding]
