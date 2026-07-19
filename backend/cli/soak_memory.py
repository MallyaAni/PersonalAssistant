import argparse
import asyncio
import json
import math
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import Any

import httpx


@dataclass
class SoakStats:
    """Collect operation counts and latency without retaining request content."""

    started_at: float = field(default_factory=time.perf_counter)
    latencies_ms: list[float] = field(default_factory=list)
    operations: dict[str, int] = field(default_factory=dict)
    failures: list[dict[str, str]] = field(default_factory=list)

    # Record one successful operation and its elapsed time.
    def success(self, operation: str, elapsed_ms: float) -> None:
        self.operations[operation] = self.operations.get(operation, 0) + 1
        self.latencies_ms.append(elapsed_ms)

    # Record a sanitized failure without request or memory content.
    def failure(self, operation: str, message: str) -> None:
        self.failures.append({"operation": operation, "message": message[:300]})

    # Produce a stable monitoring summary for the completed run.
    def report(self, duration_target: float, concurrency: int) -> dict[str, Any]:
        ordered = sorted(self.latencies_ms)
        p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return {
            "status": "passed" if not self.failures else "failed",
            "duration_target_seconds": duration_target,
            "duration_actual_seconds": round(time.perf_counter() - self.started_at, 3),
            "concurrency": concurrency,
            "operations": self.operations,
            "operations_total": sum(self.operations.values()),
            "failures_total": len(self.failures),
            "failures": self.failures[:20],
            "latency_ms": {
                "median": round(median(ordered), 3) if ordered else None,
                "p95": round(ordered[p95_index], 3) if ordered else None,
                "maximum": round(ordered[-1], 3) if ordered else None,
            },
        }


# Define bounded, repeatable mixed chat and memory load options.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a mixed chat/memory soak against a live AniOS backend.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--chat-every",
        type=int,
        default=20,
        help="Issue one chat for every N scheduled operations.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--keep-data", action="store_true")
    return parser


# Validate numeric arguments before any requests are sent.
def _validate_args(args: argparse.Namespace) -> None:
    if not 1 <= args.concurrency <= 100:
        raise ValueError("concurrency must be between 1 and 100")
    if not 1 <= args.chat_every <= 10_000:
        raise ValueError("chat-every must be between 1 and 10000")
    if not 1 <= args.duration_seconds <= 86_400:
        raise ValueError("duration-seconds must be between 1 and 86400")
    if not 1 <= args.timeout_seconds <= 600:
        raise ValueError("timeout-seconds must be between 1 and 600")


# Require an HTTP success response and return its JSON body.
def _json_response(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object response")
    return value


# Run one chat stream and require both content and terminal completion.
async def _chat(
    client: httpx.AsyncClient,
    user_id: str,
    conversation_id: uuid.UUID,
    sequence: int,
) -> None:
    response = await client.post(
        "/api/v1/chat",
        json={
            "user_id": user_id,
            "conversation_id": str(conversation_id),
            "query": f"Reply with exactly: soak ok {sequence}",
            "metadata": {"source": "memory_soak"},
        },
    )
    response.raise_for_status()
    body = response.text
    if "event: error" in body:
        raise RuntimeError("Chat stream returned an error event")
    if "event: delta" not in body or "event: done" not in body:
        raise RuntimeError("Chat stream did not emit content and terminal done")


# Upsert one expiring working-memory value through the public API.
async def _write_working(
    client: httpx.AsyncClient,
    user_id: str,
    conversation_id: uuid.UUID,
    sequence: int,
) -> None:
    expires_at = "2099-01-01T00:00:00Z"
    response = await client.put(
        f"/api/v1/memory/{user_id}/agent/working",
        json={
            "conversation_id": str(conversation_id),
            "memory_key": f"worker_{sequence % 25}",
            "value": f"soak-value-{sequence}",
            "purpose": "memory_soak",
            "expires_at": expires_at,
        },
    )
    _json_response(response)


# Read active working memory through the public API.
async def _read_working(
    client: httpx.AsyncClient,
    user_id: str,
    conversation_id: uuid.UUID,
) -> None:
    response = await client.get(
        f"/api/v1/memory/{user_id}/agent/working/{conversation_id}"
    )
    value = _json_response(response)
    if not isinstance(value.get("items"), list):
        raise ValueError("Working-memory response omitted its items list")


# Inspect public memory operations and require a usable database response.
async def _inspect_operations(
    client: httpx.AsyncClient,
    user_id: str,
) -> None:
    response = await client.get(f"/api/v1/memory/{user_id}/agent/operations")
    value = _json_response(response)
    if value.get("database", {}).get("query_ok") is not True:
        raise RuntimeError("Operations report marked the database unavailable")


# Execute one operation and collect bounded monitoring evidence.
async def _execute_operation(
    operation: str,
    client: httpx.AsyncClient,
    user_id: str,
    conversation_id: uuid.UUID,
    sequence: int,
    stats: SoakStats,
) -> None:
    started = time.perf_counter()
    try:
        if operation == "chat":
            await _chat(client, user_id, conversation_id, sequence)
        elif operation == "working_write":
            await _write_working(client, user_id, conversation_id, sequence)
        elif operation == "working_read":
            await _read_working(client, user_id, conversation_id)
        else:
            await _inspect_operations(client, user_id)
        stats.success(operation, (time.perf_counter() - started) * 1_000)
    except Exception as exc:
        stats.failure(operation, f"{type(exc).__name__}: {exc}")


# Generate mixed operations until the shared soak deadline passes.
async def _worker(
    worker_id: int,
    client: httpx.AsyncClient,
    user_id: str,
    deadline: float,
    chat_every: int,
    counter: list[int],
    stats: SoakStats,
) -> None:
    conversation_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}:{worker_id}")
    while time.perf_counter() < deadline:
        sequence = counter[0]
        counter[0] += 1
        if sequence % chat_every == 0:
            operation = "chat"
        else:
            operation = (
                "working_write",
                "working_read",
                "operations",
            )[sequence % 3]
        await _execute_operation(
            operation,
            client,
            user_id,
            conversation_id,
            sequence,
            stats,
        )


# Run the configured live soak and clean its isolated user afterward.
async def _run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_args(args)
    user_id = f"soak_{uuid.uuid4().hex}"
    stats = SoakStats()
    deadline = stats.started_at + args.duration_seconds
    counter = [0]
    timeout = httpx.Timeout(args.timeout_seconds)
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"),
        timeout=timeout,
    ) as client:
        try:
            await asyncio.gather(
                *(
                    _worker(
                        worker_id,
                        client,
                        user_id,
                        deadline,
                        args.chat_every,
                        counter,
                        stats,
                    )
                    for worker_id in range(args.concurrency)
                )
            )
        finally:
            if not args.keep_data:
                response = await client.delete(f"/api/v1/memory/{user_id}")
                if response.status_code != 200:
                    stats.failure("cleanup", f"HTTP {response.status_code}")
    report = stats.report(args.duration_seconds, args.concurrency)
    report["user_id"] = user_id
    report["cleaned_up"] = not args.keep_data
    return report


# Run the soak command and return a monitoring-friendly exit code.
def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except ValueError as exc:
        print(json.dumps({"status": "invalid", "message": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
