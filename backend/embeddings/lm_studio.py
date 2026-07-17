from typing import Any, cast

import httpx

from backend.embeddings.base import EmbeddingProvider


class LMStudioEmbeddingProvider(EmbeddingProvider):
    """Generate embeddings through LM Studio's OpenAI-compatible endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        dimension: int,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimension = dimension
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.client = client

    def embed_text(self, text: str) -> list[float]:
        return self._embed(f"search_document: {text}")

    def embed_query(self, query: str) -> list[float]:
        return self._embed(f"search_query: {query}")

    def _embed(self, text: str) -> list[float]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "input": text}

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
        embedding = data[0].get("embedding") if data else None
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
