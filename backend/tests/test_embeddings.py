import json

import httpx
import pytest

from backend.embeddings.lm_studio import LMStudioEmbeddingProvider


def test_lm_studio_embedding_provider_uses_model_task_prefix_and_auth():
    observed = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(
            {
                "url": str(request.url),
                "authorization": request.headers.get("Authorization"),
                "payload": json.loads(request.content),
            }
        )
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2, 0.3]}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = LMStudioEmbeddingProvider(
            base_url="http://127.0.0.1:1234/",
            model="text-embedding-nomic-embed-text-v1.5",
            dimension=3,
            api_key="test-token",
            client=client,
        )
        document = provider.embed_text("The user likes jasmine tea.")
        query = provider.embed_query("preferred drink")

    assert document == [0.1, 0.2, 0.3]
    assert query == [0.1, 0.2, 0.3]
    assert observed == [
        {
            "url": "http://127.0.0.1:1234/v1/embeddings",
            "authorization": "Bearer test-token",
            "payload": {
                "model": "text-embedding-nomic-embed-text-v1.5",
                "input": "search_document: The user likes jasmine tea.",
            },
        },
        {
            "url": "http://127.0.0.1:1234/v1/embeddings",
            "authorization": "Bearer test-token",
            "payload": {
                "model": "text-embedding-nomic-embed-text-v1.5",
                "input": "search_query: preferred drink",
            },
        },
    ]


def test_lm_studio_embedding_provider_rejects_dimension_mismatch():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = LMStudioEmbeddingProvider(
            base_url="http://127.0.0.1:1234",
            model="text-embedding-nomic-embed-text-v1.5",
            dimension=3,
            client=client,
        )

        with pytest.raises(
            ValueError,
            match="LM Studio embedding dimension mismatch: expected 3, received 2",
        ):
            provider.embed_query("query")
