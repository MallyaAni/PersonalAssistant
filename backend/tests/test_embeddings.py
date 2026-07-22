import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

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
                "input": ["search_document: The user likes jasmine tea."],
            },
        },
        {
            "url": "http://127.0.0.1:1234/v1/embeddings",
            "authorization": "Bearer test-token",
            "payload": {
                "model": "text-embedding-nomic-embed-text-v1.5",
                "input": ["search_query: preferred drink"],
            },
        },
    ]


# Verify a batch embeds every document in one request and preserves input order.
def test_lm_studio_embedding_provider_batches_documents_in_order() -> None:
    observed: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        observed.append(payload)
        rows = [
            {"index": position, "embedding": [float(position), 0.0]}
            for position, _ in enumerate(payload["input"])
        ]
        # Return the rows out of order to prove index-based reassembly.
        return httpx.Response(200, json={"data": list(reversed(rows))})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = LMStudioEmbeddingProvider(
            base_url="http://127.0.0.1:1234",
            model="test-model",
            dimension=2,
            client=client,
        )
        vectors = provider.embed_texts(["first", "second", "third"])

    assert vectors == [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]
    assert len(observed) == 1
    assert observed[0]["input"] == [
        "search_document: first",
        "search_document: second",
        "search_document: third",
    ]
    assert provider.embed_texts([]) == []


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


# Verify one shared provider limits concurrent LM Studio embedding requests.
def test_lm_studio_embedding_provider_bounds_concurrency() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    # Hold each mock provider request long enough to observe overlap.
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return httpx.Response(200, json={"data": [{"embedding": [1.0]}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = LMStudioEmbeddingProvider(
            base_url="http://127.0.0.1:1234",
            model="test-model",
            dimension=1,
            max_concurrency=1,
            client=client,
        )
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(provider.embed_query, map(str, range(6))))

    assert results == [[1.0]] * 6
    assert peak == 1
    assert active == 0
