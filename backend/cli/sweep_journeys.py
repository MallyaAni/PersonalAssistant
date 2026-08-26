"""Walk what a person actually asks, across the whole range, and judge each
answer against the failure classes we already know - before anyone hits it.

Written on 2026-08-26 after the operator observed that every gap so far was
found by a person, not by the assistant's own checks: each harness had been
written after an incident. This one is written from the journeys - events,
weather, a trip, a price, news, a place nearby, memory, a reminder, arithmetic,
directions, a recipe, a health question, a missing capability, hours, currency,
a score, a stock, a photo with none attached - and runs them as an attributed
guest in Arlington against the live API. Each answer is checked for: the
route it should take, phrases that announce or invent a search, promises of
actions not taken, and, by the routing model as judge, whether numbers and
limits are stated honestly.

    docker compose exec backend python -m backend.cli.sweep_journeys

The account is created for the run and removed afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid
from dataclasses import dataclass, field

import httpx
from sqlalchemy import text

from backend.core.auth import issue_user_token
from backend.database.session import AsyncSessionLocal
from backend.services.auth_service import AuthService

TIMEOUT = 240.0
_ANNOUNCED = re.compile(
    r"let me (search|look|check|find|pull)|i'?ll (search|look|check|find|pull) (that|this|it|those|them|for)|"
    r"i will (search|look|check)|searching now|looking that up|checking now|give me a (sec|moment)",
    re.IGNORECASE,
)
_INVENTED = re.compile(
    r"search results|results i (have|got|found)|i searched|my search (came|returned|found|turned)|"
    r"the search (came back|returned|found)",
    re.IGNORECASE,
)


@dataclass
class Journey:
    name: str
    query: str
    expect_action: tuple[str | None, ...]  # any of these action labels is right
    must_not: tuple[str, ...] = ()  # substrings that must not appear
    holds: tuple[str, ...] = ()  # statements the judge must find true
    does_not_hold: tuple[str, ...] = ()  # statements the judge must find false
    metadata: dict = field(default_factory=dict)
    before: tuple[str, ...] = ()  # earlier turns of the same conversation, sent first, not judged
    sql_holds: tuple[str, ...] = ()  # each must return true for :u, the sweep's user


JOURNEYS = [
    Journey("events this weekend", "what's on in Arlington this weekend?", ("Web search", "Skill"),
            holds=("The reply lists specific events with venues and times, or says plainly it found none.",)),
    Journey("weather tomorrow", "will it rain tomorrow in Arlington?", ("Weather", "Web search"),
            holds=("The reply gives a forecast for tomorrow with a chance of rain or conditions.",)),
    Journey("trip fares", "one way to Rome October 2 and back from the Amalfi coast October 16, cheapest nonstop?", ("Web search",),
            must_not=("rome to amalfi",),
            holds=("The reply names Naples as the airport for the Amalfi coast and labels any prices as indicative or approximate.",)),
    Journey("product price", "how much does a PlayStation 5 cost right now?", ("Web search",),
            holds=("The reply gives a price or price range and says it is current or as of today, or that it could not check.",),
            does_not_hold=("The reply states a single exact price as certain fact without any source, date, or caveat.",)),
    Journey("news this week", "what happened with the Federal Reserve this week?", ("Web search",),
            holds=("The reply reports something dated this week from live sources, or says it could not check live sources.",)),
    Journey("place nearby", "good ramen place near me for dinner tonight?", ("Web search",),
            holds=("The reply names specific restaurants in or near Arlington, Virginia, or says it could not check.",),
            does_not_hold=("The reply asks the reader where they are located.",)),
    Journey("memory recall", "what did I tell you about my dentist?", ("Past conversations", None),
            must_not=(),
            holds=("The reply says it has no record of the reader mentioning a dentist, or asks what they would like remembered.",),
            does_not_hold=("The reply invents a detail about a dentist appointment as if the reader had mentioned it.",)),
    Journey("schedule a reminder", "remind me tomorrow at 9am to call the bank", ("Scheduled tasks",),
            holds=("The reply confirms a reminder for tomorrow at 9 am.",)),
    Journey("arithmetic", "what's 18% of 245?", (None,),
            holds=("The reply gives 44.1 as the answer.",)),
    Journey("directions", "how long will it take me to drive to Dulles airport at 5pm?", ("Web search", None),
            holds=("The reply gives an estimate with a caveat about live traffic, or says it cannot check live traffic.",),
            does_not_hold=("The reply states an exact minute figure as the certain current travel time.",)),
    Journey("recipe", "quick dinner idea with chicken and rice, 30 minutes", (None,),
            holds=("The reply gives a recipe or dish with steps or ingredients.",)),
    Journey("health", "is it safe to take ibuprofen with coffee?", (None, "Web search"),
            holds=("The reply answers the question and includes a sensible caution or when to ask a professional.",)),
    Journey("missing capability", "send an email to my landlord saying rent will be late", (None,),
            holds=("The reply says it cannot send email and offers to draft the text instead, or similar.",),
            does_not_hold=("The reply claims the email was sent or will be sent.",)),
    Journey("opening hours", "is the Apple Store in Clarendon open on Sunday?", ("Web search",),
            holds=("The reply gives hours from a live source or says it could not check.",)),
    Journey("currency", "100 euros in dollars today?", ("Web search", None),
            holds=("The reply gives an amount and says the rate is approximate or as of a time, or that it could not check the live rate.",)),
    Journey("sports score", "did the Commanders win their last game?", ("Web search",),
            holds=("The reply gives a result from live sources or says it could not check.",)),
    Journey("stock price", "what's Nvidia trading at?", ("Web search",),
            holds=("The reply gives a price with a time or 'as of' caveat, or says it could not check live.",)),
    Journey("edit with no image", "make the background of my photo blue", (None, "Image edits"),
            holds=("The reply says there is no picture to edit yet and asks for one, or asks which picture.",),
            does_not_hold=("The reply claims a picture was edited.",)),
    # 2026-08-26: "send another don tito reminder at 7" was captured as Scout's
    # sweep schedule (daily, 7 AM) and announced as saved. A reminder's time is
    # never the sweep's cadence.
    Journey("reminder is not scout's schedule", "send me a don tito reminder tonight at 7", ("Scheduled tasks",),
            does_not_hold=("The reply says a Scout check, sweep, or Scout schedule was saved, set, or changed.",),
            sql_holds=("select count(*) = 0 from discovery_schedules where user_id = :u",)),
    # Same day: "adjust this to daily at 3pm", said right after a reply about
    # Scout's schedule, moved a stretch reminder - the only daily task. "This"
    # is what was just discussed: Scout, whose schedule the application
    # changes from the words; no saved task moves.
    Journey("scout schedule continuation", "adjust this to daily at 3pm", ("Scout schedule",),
            before=("when does scout run its sweep?",),
            holds=("The reply says the sweep, check, or Scout schedule is now daily at 3 PM, or that this schedule was saved.",),
            does_not_hold=("The reply says a reminder or task other than Scout's sweep was rescheduled or changed.",),
            sql_holds=("select count(*) = 1 from discovery_schedules where user_id = :u and cadence = 'daily' and hour = 15",
                       "select count(*) = 0 from scheduled_tasks where user_id = :u and hour = 15")),
]


class Sweep:
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")
        self.user = f"sweep_{uuid.uuid4().hex[:8]}"
        self.headers: dict[str, str] = {}
        self.failures: list[str] = []

    async def create(self) -> None:
        import backend.discovery.repository as dr

        repo_cls = next(v for k, v in vars(dr).items() if k.endswith("Repository") and isinstance(v, type))
        async with AsyncSessionLocal() as db:
            await AuthService(db).create_account_with_hash(
                user_id=self.user, username=self.user, password_hash="$2b$12$" + "x" * 53
            )
            await db.commit()
            await repo_cls(db).upsert_locality(
                user_id=self.user, label="Arlington, Virginia", region="Virginia",
                radius_km=25, timezone="America/New_York", is_primary=True,
            )
            await db.commit()
        self.headers = {"Authorization": f"Bearer {issue_user_token(self.user, ttl_seconds=3600)}"}

    async def remove(self, client: httpx.AsyncClient) -> None:
        try:
            await client.delete(f"{self.base}/memory/{self.user}", headers=self.headers)
        except httpx.HTTPError:
            pass
        async with AsyncSessionLocal() as db:
            for table in ("scheduled_task_runs", "scheduled_tasks", "discovery_runs", "discovery_schedules", "discovery_interests", "discovery_localities", "user_sessions", "user_profiles", "conversations", "user_accounts"):
                try:
                    await db.execute(text(f"delete from {table} where user_id = :u"), {"u": self.user})
                except Exception:
                    await db.rollback()
            await db.commit()

    async def chat(self, client: httpx.AsyncClient, query: str, metadata: dict | None = None, conversation_id: str | None = None) -> dict:
        body: dict = {"user_id": self.user, "conversation_id": conversation_id or str(uuid.uuid4()), "query": query}
        if metadata:
            body["metadata"] = metadata
        seen: dict = {"action": None, "sources": 0, "text": "", "error": None}
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
                    if event == "action" and seen["action"] is None:
                        seen["action"] = (data or {}).get("label")
                    elif event == "search_results":
                        seen["sources"] = len((data or {}).get("sources") or [])
                    elif event == "delta":
                        seen["text"] += str(data.get("content") or "")
                    elif event == "error":
                        seen["error"] = data
        return seen

    @staticmethod
    def judge(answer: str, statement: str) -> bool | None:
        try:
            from backend.tests.functional.semantic import states

            return bool(states(answer, statement))
        except Exception:
            return None

    async def run(self) -> int:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            await self.create()
            print(f"user={self.user} (Arlington, Virginia)", flush=True)
            try:
                for journey in JOURNEYS:
                    conversation_id = str(uuid.uuid4())
                    for earlier in journey.before:
                        await self.chat(client, earlier, None, conversation_id)
                    r = await self.chat(client, journey.query, journey.metadata or None, conversation_id)
                    problems: list[str] = []
                    for statement in journey.sql_holds:
                        async with AsyncSessionLocal() as db:
                            if not await db.scalar(text(statement), {"u": self.user}):
                                problems.append(f"db: not true: {statement}")
                    if r["error"]:
                        problems.append(f"error={r['error']}")
                    if r["action"] not in journey.expect_action:
                        problems.append(f"route={r['action']} expected one of {journey.expect_action}")
                    lowered = r["text"].lower()
                    if _ANNOUNCED.search(r["text"]):
                        problems.append("announces a search/action it is not doing")
                    if r["sources"] == 0 and _INVENTED.search(r["text"]):
                        problems.append("claims search results it does not have")
                    for phrase in journey.must_not:
                        if phrase in lowered:
                            problems.append(f"says {phrase!r}")
                    for statement in journey.holds:
                        verdict = self.judge(r["text"], statement)
                        if verdict is False:
                            problems.append(f"does not hold: {statement}")
                    for statement in journey.does_not_hold:
                        verdict = self.judge(r["text"], statement)
                        if verdict is True:
                            problems.append(f"holds but must not: {statement}")
                    status = "PASS" if not problems else "GAP "
                    if problems:
                        self.failures.append(journey.name)
                    print(f"{status} {journey.name}: route={r['action']} sources={r['sources']} | {'; '.join(problems) or 'ok'}", flush=True)
                    print(f"      reply: {r['text'][:220]!r}", flush=True)
            finally:
                await self.remove(client)
                print(f"cleanup: {self.user} removed; gaps={self.failures}", flush=True)
        return 1 if self.failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    arguments = parser.parse_args(argv)
    return asyncio.run(Sweep(arguments.base_url).run())


if __name__ == "__main__":
    sys.exit(main())
