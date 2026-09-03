"""Measure what the event extractor keeps from a live search, per setting.

    python -m backend.cli.measure_events_extraction --query "..." [--reps 1]

Runs the app's own search provider, then the extractor with the deployed
constants, and prints kept/undated/opening-hours/unsourced counts and the
events. Used on 2026-09-02 to find that ten of twelve Arlington events were
dropped as undated (the date parser wanted a year) and that 700 characters
per result hid most of ARLnow's page.
"""
import argparse
import asyncio
import time

from backend.core import event_extraction as extraction
from backend.core.dependencies import get_llm_client, get_search_provider


async def measure(query: str, reps: int) -> int:
    provider = get_search_provider()
    results = await provider.search(query, max_results=8)
    rows = [
        {"title": r.title, "url": r.url, "content": r.content, "provider": getattr(r, "provider", "")}
        for r in results.results
    ]
    print(f"results: {len(rows)} | chars per result: {[len(r['content']) for r in rows]}")
    llm = get_llm_client()
    for attr in ("timeout_seconds", "timeout"):
        if hasattr(llm, attr):
            try:
                setattr(llm, attr, 300.0)
            except Exception:
                pass
    for rep in range(reps):
        started = time.time()
        found = await extraction.extract_events(llm, rows)
        print(
            f"\nrep {rep + 1}: kept={len(found.events)} undated={found.undated} "
            f"opening_hours={found.opening_hours} unsourced={found.unsourced} "
            f"(chars={extraction._CONTENT_CHARS}, {time.time() - started:.0f}s)"
        )
        for event in found.events:
            print(f"  - {event.day} {event.name[:44]} @ {event.venue[:28]}, {event.area[:18]} | {event.source_url[:44]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--reps", type=int, default=1)
    arguments = parser.parse_args()
    return asyncio.run(measure(arguments.query, max(1, arguments.reps)))


if __name__ == "__main__":
    raise SystemExit(main())
