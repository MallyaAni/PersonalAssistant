import argparse
import asyncio
import json
from collections.abc import Sequence
from typing import Any

from backend.config.settings import settings
from backend.core.dependencies import get_embedding_provider
from backend.database.session import AsyncSessionLocal
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.services.memory_retrieval_evaluator import MemoryRetrievalEvaluator
from backend.services.postgres_memory_service import PostgresMemoryService


# Define command-line options for the retrieval benchmark.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate AniOS semantic-memory retrieval quality and latency.",
    )
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--expected-content", required=True)
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-hit-rate", type=float, default=1.0)
    parser.add_argument("--max-p95-ms", type=float, default=2_000.0)
    return parser


# Build the memory service and execute the retrieval benchmark.
async def _run(args: argparse.Namespace) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        memory = PostgresMemoryService(
            session,
            get_embedding_provider(),
            SemanticRetrievalPolicy(
                max_cosine_distance=settings.MEMORY_SEMANTIC_MAX_COSINE_DISTANCE,
                max_results=settings.MEMORY_SEMANTIC_MAX_RESULTS,
                max_content_chars=settings.MEMORY_SEMANTIC_MAX_CONTENT_CHARS,
            ),
            settings.EMBEDDING_MODEL_VERSION,
        )
        return await MemoryRetrievalEvaluator(memory).evaluate(
            user_id=args.user_id,
            query=args.query,
            expected_content=args.expected_content,
            iterations=args.iterations,
            warmups=args.warmups,
            top_k=args.top_k,
        )


# Evaluate benchmark thresholds and return a pass-or-fail exit code.
def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.min_hit_rate <= 1:
        raise SystemExit("--min-hit-rate must be between 0 and 1")
    if args.max_p95_ms <= 0:
        raise SystemExit("--max-p95-ms must be positive")
    result = asyncio.run(_run(args))
    passed = (
        float(result["hit_rate"]) >= args.min_hit_rate
        and float(result["latency_ms"]["p95"]) <= args.max_p95_ms
    )
    result["thresholds"] = {
        "min_hit_rate": args.min_hit_rate,
        "max_p95_ms": args.max_p95_ms,
    }
    result["passed"] = passed
    print(json.dumps(result, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
