"""What people actually say, by the route it took - the corpus tests should
be written from.

    docker compose exec backend python -m backend.cli.real_utterances --days 14

Every incident this week was a phrasing the tests had not imagined: "DC"
where the tests said "Arlington", "adjust this" where they said "move the
stretch reminder", "does only one person win at the end?" where they named
the show. This prints the last days' user messages, decrypted, grouped by
the route recorded in each turn's trace (or "no trace" for older turns),
deduplicated, with the users that said them - so a matrix case, a sweep
journey or a functional test starts from a real sentence. Written
2026-08-27 after a weather question failed on the first spelling a person
here uses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from backend.core.crypto import get_field_cipher
from backend.database.session import AsyncSessionLocal


async def utterances(days: int, exclude_users: set[str]) -> int:
    cipher = get_field_cipher()
    # conversations.created_at is a naive UTC timestamp; asyncpg refuses an
    # aware bound against it.
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "select user_id, created_at, query, extra_data::text from conversations "
                    "where created_at >= :since order by created_at"
                ),
                {"since": since},
            )
        ).all()
    by_route: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for user_id, created_at, query, extra in rows:
        if user_id in exclude_users or str(user_id).startswith(("sweep_", "search_e2e_", "image_e2e_", "functional_", "tool_selection")):
            continue
        meta = json.loads(extra) if extra else {}
        if meta.get("scheduled_task"):
            continue
        route = ((meta.get("trace") or {}).get("route") or {}).get("label") or ("no tool" if meta.get("trace") else "no trace")
        said = " ".join(cipher.decrypt(query).split())[:160]
        if said:
            by_route[route][said.casefold()].add(str(user_id))
    total = sum(len(v) for v in by_route.values())
    print(f"{total} distinct user messages in the last {days} days, by route:\n")
    for route in sorted(by_route, key=lambda r: -len(by_route[r])):
        print(f"[{route}] {len(by_route[route])}")
        for said, users in sorted(by_route[route].items()):
            print(f"  - {said!r}  ({', '.join(sorted(users))})")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--exclude", default="", help="comma-separated user ids to leave out")
    args = parser.parse_args(argv)
    return asyncio.run(utterances(args.days, set(u for u in args.exclude.split(",") if u)))


if __name__ == "__main__":
    raise SystemExit(main())
