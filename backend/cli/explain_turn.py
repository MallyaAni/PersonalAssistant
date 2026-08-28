"""Why did it do that? The last turns of one person, decrypted, with what
each turn decided and did: the route the router chose, what the task picker
was shown and picked, which memory proposals were saved, the task and Scout
outcomes, and whether a search ran.

    docker compose exec backend python -m backend.cli.explain_turn --user ani.mallya --last 6

Written 2026-08-26 after reconstructing a chain of three wrong turns by
decrypting rows by hand. The trace is saved with each turn as
extra_data["trace"] (backend/services/conversation_service.py: _trace).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime

from sqlalchemy import text

from backend.core.crypto import get_field_cipher
from backend.database.session import AsyncSessionLocal


async def explain(user_id: str, last: int, since: datetime | None) -> int:
    cipher = get_field_cipher()
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "select created_at, conversation_id, query, response, extra_data::text "
                    "from conversations where user_id = :u "
                    + ("and created_at >= :since " if since else "")
                    + "order by created_at desc limit :n"
                ),
                {"u": user_id, "n": last, **({"since": since} if since else {})},
            )
        ).all()
    for created_at, conversation_id, query, response, extra in reversed(rows):
        meta = json.loads(extra) if extra else {}
        trace = meta.get("trace") or {}
        print(f"=== {created_at:%Y-%m-%d %H:%M:%S} UTC  conversation {str(conversation_id)[:8]}  channel={meta.get('channel', '?')}"
              + ("  [scheduled firing]" if meta.get("scheduled_task") else ""))
        print(f"Q: {cipher.decrypt(query)[:400]}")
        print(f"A: {cipher.decrypt(response)[:600]}")
        if not trace:
            print("   trace: (none recorded - turn predates the trace, or nothing was decided)")
            continue
        route = trace.get("route")
        print(f"   route: {route['label']}{' - ' + route['detail'] if route and route.get('detail') else ''}" if route else "   route: none (answered directly)")
        if "picker" in trace:
            p = trace["picker"]
            print(f"   picker: which={p.get('which')!r} chosen={p.get('chosen')} hint={p.get('hint')!r}")
        if trace.get("group"):
            g = trace["group"]
            print(f"   group: spoken by {g.get('speaker')} among {g.get('members')} members")
        if trace.get("proposals_saved"):
            print(f"   memory saved: {', '.join(trace['proposals_saved'])}")
        if trace.get("outcomes"):
            print(f"   outcomes: {', '.join(trace['outcomes'])}")
        if "search" in trace:
            print(f"   search: {trace['search']}")
        if "ms" in trace:
            print(f"   timing: routed at {trace.get('route_ms', '?')} ms, finished at {trace['ms']} ms")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--user", required=True)
    parser.add_argument("--last", type=int, default=8)
    parser.add_argument("--since", type=datetime.fromisoformat, default=None, help="UTC, e.g. 2026-08-26T21:00")
    args = parser.parse_args(argv)
    return asyncio.run(explain(args.user, args.last, args.since))


if __name__ == "__main__":
    raise SystemExit(main())
