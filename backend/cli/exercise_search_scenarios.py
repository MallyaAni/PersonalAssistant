"""Run the search conversations a real person produces, as an attributed
account, against the live API - and exit non-zero on any wrong turn.

Written on 2026-08-26 after an evening in which every search defect reached
the operator through a sequence nobody had run: a what's-on question refused
for credits, then "try again" routed to the credit meter; a scheduled
reminder opening with the allowance line; an attributed account refused a
search a guest sailed through. Each part had passed its own test. This is
the whole conversation, run the way it is lived, before a deploy.

    docker compose exec backend python -m backend.cli.exercise_search_scenarios

The account is created for the run and removed afterwards, with its
conversations and profile.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

import httpx
from sqlalchemy import text

from backend.core.auth import issue_user_token
from backend.database.session import AsyncSessionLocal
from backend.services.auth_service import AuthService

TIMEOUT = 240.0


class Scenarios:
    def __init__(self, base_url: str, operator: bool) -> None:
        self.base = base_url.rstrip("/")
        self.user = f"search_e2e_{uuid.uuid4().hex[:8]}"
        self.operator = operator
        self.headers: dict[str, str] = {}
        self.conversation = str(uuid.uuid4())
        self.failures = 0

    async def create(self) -> None:
        async with AsyncSessionLocal() as db:
            await AuthService(db).create_account_with_hash(
                user_id=self.user, username=self.user, password_hash="$2b$12$" + "x" * 53
            )
            if self.operator:
                await db.execute(
                    text("update user_accounts set is_admin = true where user_id = :u"),
                    {"u": self.user},
                )
            await db.commit()
        self.headers = {"Authorization": f"Bearer {issue_user_token(self.user, ttl_seconds=1800)}"}

    async def remove(self, client: httpx.AsyncClient) -> None:
        try:
            await client.delete(f"{self.base}/memory/{self.user}", headers=self.headers)
        except httpx.HTTPError:
            pass
        async with AsyncSessionLocal() as db:
            for table in ("user_sessions", "user_profiles", "conversations", "user_accounts"):
                await db.execute(text(f"delete from {table} where user_id = :u"), {"u": self.user})
            await db.commit()

    # POST one turn, read the SSE stream, keep what matters.
    async def chat(self, client: httpx.AsyncClient, query: str, metadata: dict | None = None) -> dict:
        body: dict = {"user_id": self.user, "conversation_id": self.conversation, "query": query}
        if metadata:
            body["metadata"] = metadata
        seen: dict = {"action": None, "tools": [], "sources": 0, "text": "", "error": None}
        async with client.stream("POST", f"{self.base}/chat", json=body, headers=self.headers) as response:
            if response.status_code != 200:
                seen["error"] = f"HTTP {response.status_code}"
                return seen
            event = None
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event:
                    try:
                        data = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if event == "action":
                        seen["action"] = (data or {}).get("label")
                    elif event == "tool_finished":
                        seen["tools"].append(((data or {}).get("tool_name"), (data or {}).get("status")))
                    elif event == "search_results":
                        seen["sources"] = len((data or {}).get("sources") or [])
                    elif event == "delta":
                        seen["text"] += str(data.get("content") or "")
                    elif event == "error":
                        seen["error"] = data
        return seen

    def verdict(self, name: str, ok: bool, detail: str) -> None:
        if not ok:
            self.failures += 1
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}", flush=True)

    @staticmethod
    def trail(r: dict) -> str:
        return f"action={r['action']} tools={r['tools']} sources={r['sources']} text={r['text'][:100]!r} err={r['error']}"

    async def run(self) -> int:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            await self.create()
            print(f"user={self.user} operator={self.operator} conversation={self.conversation}", flush=True)
            try:
                lowered = ""
                r = await self.chat(client, "what events are happening in Arlington Virginia this weekend?")
                lowered = r["text"].lower()
                self.verdict(
                    "1 a what's-on question searches the web and answers from live results",
                    r["action"] == "Web search" and r["sources"] > 0 and "let me search" not in lowered
                    and "haven't checked live" not in lowered and not r["error"],
                    self.trail(r),
                )
                priced = any(mark in lowered for mark in ("price not listed", "free", "$"))
                self.verdict(
                    "1b events are presented in the What's on format",
                    "maps.google.com/?q=" in lowered and priced and "**" not in r["text"],
                    f"map={'maps.google.com/?q=' in lowered} price={priced} "
                    f"youtube={'youtube.com/results?search_query=' in lowered} bold={'**' in r['text']}",
                )

                r = await self.chat(client, "try again")
                self.verdict(
                    "2 'try again' redoes the search, never the meter",
                    r["action"] == "Web search" and r["sources"] > 0 and not r["error"],
                    self.trail(r),
                )

                r = await self.chat(client, "Remind me to stretch", metadata={"scheduled_task": True})
                lowered = r["text"].lower()
                self.verdict(
                    "3 a scheduled reminder is a reminder: no tool, no allowance line",
                    r["action"] is None and "allowance" not in lowered and "search" not in lowered and not r["error"],
                    self.trail(r),
                )

                r = await self.chat(client, "what's the capital of Peru?")
                self.verdict(
                    "4 a plain question takes no tool and is answered",
                    r["action"] is None and "lima" in r["text"].lower() and not r["error"],
                    self.trail(r),
                )

                if self.operator:
                    r = await self.chat(client, "how many search credits do we have left?")
                    self.verdict(
                        "5 the operator's meter question reads the meter and says who serves",
                        r["action"] == "Search credits" and ("brave" in r["text"].lower() or "tavily" in r["text"].lower())
                        and not r["error"],
                        self.trail(r),
                    )
            finally:
                await self.remove(client)
                print(f"cleanup: account {self.user} removed", flush=True)
        return 1 if self.failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--guest", action="store_true", help="run as a guest account instead of an operator")
    arguments = parser.parse_args(argv)
    return asyncio.run(Scenarios(arguments.base_url, operator=not arguments.guest).run())


if __name__ == "__main__":
    sys.exit(main())
