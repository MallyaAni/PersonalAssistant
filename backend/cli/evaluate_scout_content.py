"""Judge what Scout selected for a person against what they actually like.

    docker compose exec backend python -m backend.cli.evaluate_scout_content \\
        --user <user_id> [--runs 3]

The reranker orders candidates and the digest writes the message, and until
now nobody scored either against the interests they exist to serve. This
pulls a user's stated interests and their latest digest runs, and has the
judge - Claude, headless, on the operator's subscription, never a model in
this stack - score every selected find: how well it serves a stated interest,
whether it is still upcoming rather than already over, and whether it was
worth sending at all. The delivery message, when one was composed, is judged
against the digest prompt's own standard.

Today's date goes into the instruction because the first real specimen made
it necessary: a run selected a county fair five days after it ended, matched
to "farmers markets". Relevance scoring without a calendar cannot see that.

Verdicts persist under data/model_evaluations/ - user content stays out of
anything committed or published. Calibrate with --calibrate before trusting a
new judge model: it scores three synthetic finds with known right answers
(a clear match, an ended event, an unrelated item) and prints whether the
judge agrees.
"""

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from backend.evals.judge import run_judge

_RUBRIC = (
    "Today's date is {today}. A person told a local-discovery agent what they "
    "like; the agent searched, ranked, and selected the finds below to send "
    "them. Judge each find on its own merits against the stated interests.\n\n"
    "Their stated interests: {interests}\n\n"
    "For each find return one object:\n"
    '{{"find": <int>, "relevance": 0-5, "serves_interest": "<label or none>", '
    '"timely": true|false, "worth_sending": true|false, "why": "<one clause>"}}\n'
    "relevance is how well this find serves one of the stated interests - a "
    "stretch match through a vaguely related interest scores low, and an item "
    "serving none of them scores 0 however locally notable it is. timely is "
    "false when the event has already ended by today's date, or when no date "
    "can be established at all - an undatable event cannot be planned for. "
    "worth_sending is the overall call: would a person with these interests "
    "be glad this arrived on their phone.\n"
    "Return ONLY a JSON array with one object per find, in order.\n\n"
    "{finds}"
)

_CALIBRATION = [
    {
        "title": "Sunset Jazz in the Park",
        "summary": "An outdoor jazz quartet series, next session two days "
        "from today, free entry.",
        "starts_at": "in two days",
        "expected": {"relevance_high": True, "timely": True},
    },
    {
        "title": "Spring Craft Fair",
        "summary": "A large craft and food fair which ran for one weekend "
        "and ended nine days ago.",
        "starts_at": "ended nine days ago",
        "expected": {"timely": False},
    },
    {
        "title": "Regional Truck Parts Expo",
        "summary": "A trade exhibition of commercial vehicle components, next month.",
        "starts_at": "next month",
        "expected": {"relevance_low": True},
    },
]


def _render_finds(finds: list[dict]) -> str:
    lines = []
    for index, find in enumerate(finds, start=1):
        lines.append(
            f"=== FIND {index} ===\n"
            f"title: {find.get('title')}\n"
            f"summary: {find.get('summary')}\n"
            f"starts_at: {find.get('starts_at') or 'not stated'}\n"
            f"ends_at: {find.get('ends_at') or 'not stated'}\n"
            f"ranker matched it to: {find.get('matched_interest') or 'nothing'}\n"
        )
    return "\n".join(lines)


def _judge_finds(
    interests: list[str], finds: list[dict], model: str, timeout: int
) -> list[dict]:
    instruction = _RUBRIC.format(
        today=datetime.now(UTC).strftime("%Y-%m-%d"),
        interests=", ".join(f'"{label}"' for label in interests) or "none stated",
        finds=_render_finds(finds),
    )
    return run_judge(instruction, model=model, timeout=timeout)


def calibrate(model: str, timeout: int) -> int:
    interests = ["live music", "hiking"]
    verdicts = _judge_finds(interests, _CALIBRATION, model, timeout)
    passed = 0
    for spec, verdict in zip(_CALIBRATION, verdicts, strict=False):
        expected = spec["expected"]
        ok = True
        if expected.get("relevance_high"):
            ok &= verdict.get("relevance", 0) >= 4 and verdict.get("timely") is True
        if expected.get("timely") is False:
            ok &= verdict.get("timely") is False
        if expected.get("relevance_low"):
            ok &= verdict.get("relevance", 5) <= 1
        passed += ok
        print(f"  {'OK  ' if ok else 'MISS'} {spec['title']}: {verdict}")
    print(f"calibration: {passed}/{len(_CALIBRATION)}")
    return 0 if passed == len(_CALIBRATION) else 1


async def _load(user_id: str, runs: int) -> tuple[list[str], list[dict]]:
    from backend.database.session import AsyncSessionLocal
    from backend.models.discovery import DiscoveryInterest
    from backend.models.discovery_run import DiscoveryRun

    async with AsyncSessionLocal() as session:
        labels = [
            str(row.label)
            for row in (
                await session.execute(
                    select(DiscoveryInterest).where(
                        DiscoveryInterest.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        ]
        rows = (
            (
                await session.execute(
                    select(DiscoveryRun)
                    .where(
                        DiscoveryRun.user_id == user_id,
                        DiscoveryRun.digest_json.is_not(None),
                    )
                    .order_by(DiscoveryRun.started_at.desc())
                    .limit(runs)
                )
            )
            .scalars()
            .all()
        )
        finds: list[dict] = []
        for run in rows:
            digest = json.loads(run.digest_json)
            for item in digest.get("selected") or []:
                item["run_started_at"] = str(run.started_at)
                item["delivery_message"] = run.delivery_message
                finds.append(item)
        return labels, finds


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--judge-model", default="fable")
    parser.add_argument("--judge-timeout", type=int, default=600)
    parser.add_argument("--calibrate", action="store_true")
    args = parser.parse_args(argv)

    if args.calibrate:
        return calibrate(args.judge_model, args.judge_timeout)
    if not args.user:
        parser.error("--user is required unless --calibrate")

    interests, finds = asyncio.run(_load(args.user, args.runs))
    print(f"interests: {interests}")
    if not finds:
        print("no digested finds to judge for this user")
        return 1
    print(f"judging {len(finds)} selected find(s) from the latest runs")

    verdicts = _judge_finds(interests, finds, args.judge_model, args.judge_timeout)
    worth = 0
    for find, verdict in zip(finds, verdicts, strict=False):
        worth += bool(verdict.get("worth_sending"))
        print(
            f"  [{verdict.get('relevance')}/5"
            f"{' timely' if verdict.get('timely') else ' NOT TIMELY'}"
            f"{' SEND' if verdict.get('worth_sending') else ' hold'}] "
            f"{str(find.get('title'))[:48]} - {verdict.get('why')}"
        )
    print(f"\nworth sending: {worth} of {len(finds)}")

    out = Path("data/model_evaluations")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    target = out / f"scout-content-{args.user}-{stamp}.json"
    target.write_text(
        json.dumps(
            {
                "user": args.user,
                "interests": interests,
                "finds": finds,
                "verdicts": verdicts,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"verdicts saved to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
