import math
from time import perf_counter
from typing import Any

from backend.services.postgres_memory_service import PostgresMemoryService


class MemoryRetrievalEvaluator:
    """Measure end-to-end semantic retrieval quality and latency."""

    # Store the memory service used for benchmark queries.
    def __init__(self, memory: PostgresMemoryService) -> None:
        self.memory = memory

    # Measure retrieval hit rate and latency over repeated queries.
    async def evaluate(
        self,
        *,
        user_id: str,
        query: str,
        expected_content: str,
        iterations: int = 25,
        warmups: int = 3,
        top_k: int = 5,
    ) -> dict[str, Any]:
        if iterations < 1 or iterations > 1_000:
            raise ValueError("Iterations must be between 1 and 1000")
        if warmups < 0 or warmups > 100:
            raise ValueError("Warmups must be between 0 and 100")
        if top_k < 1 or top_k > 20:
            raise ValueError("top_k must be between 1 and 20")

        for _ in range(warmups):
            await self.memory.get_semantic_memory(user_id, query, top_k)

        latencies: list[float] = []
        hits = 0
        result_counts: list[int] = []
        for _ in range(iterations):
            started = perf_counter()
            results = await self.memory.get_semantic_memory(user_id, query, top_k)
            latencies.append((perf_counter() - started) * 1_000)
            result_counts.append(len(results))
            if any(expected_content in item["content"] for item in results):
                hits += 1

        ordered = sorted(latencies)
        return {
            "user_id": user_id,
            "query": query,
            "expected_content": expected_content,
            "iterations": iterations,
            "warmups": warmups,
            "top_k": top_k,
            "hit_rate": hits / iterations,
            "result_count_min": min(result_counts),
            "result_count_max": max(result_counts),
            "latency_ms": {
                "p50": round(self._percentile(ordered, 0.50), 3),
                "p95": round(self._percentile(ordered, 0.95), 3),
                "max": round(max(ordered), 3),
            },
        }

    # Return a nearest-rank percentile from ordered latency samples.
    @staticmethod
    def _percentile(ordered: list[float], percentile: float) -> float:
        index = max(0, math.ceil(len(ordered) * percentile) - 1)
        return ordered[index]
