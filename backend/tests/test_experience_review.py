"""The experience review's stages, its evidence check, and what it may put
right - pinned without a model, on the two exchanges that prompted it.

The bird photo: a picture shared in a room without addressing the assistant
was dropped, and "a bird" three turns later meant nothing. The reminder: a
weekly firing was read back as the person's habit. A scripted judge returns
findings about them; the world keeps only those whose quote is in the
exchange, corrects a cause the record contradicts, proposes forgetting what
the misread turn saved, and never forgets without the person's yes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.agents.experience.prompts import Finding, Judgement
from backend.agents.experience.sources import Saved, Turn, render_turns, saved_window
from backend.agents.experience.world import (
    ExperienceWorld,
    ForgetMemory,
    Judge,
    ReadTurns,
    WriteReport,
    since_of,
)
from backend.services.turn_steps import Act, Done

pytestmark = pytest.mark.asyncio

_WHEN = datetime(2026, 9, 5, 22, 4, tzinfo=UTC)


def _turn(number: int, said: str, replied: str, *, minutes: int, trace: dict | None = None, metadata: dict | None = None, addressed: bool = True) -> Turn:
    return Turn(
        number=number, id=f"t{number}", when=_WHEN + timedelta(minutes=minutes), owner="group:c1", speaker="ani",
        channel="imessage_group", said=said, replied=replied, addressed=addressed, metadata=metadata or {}, trace=trace or {},
    )


TURNS = [
    _turn(1, "i'm with gubacchi", "", minutes=0, addressed=False, trace={"proposals_saved": ["semantic_fact"]}),
    _turn(2, "Scout i'm with gubacchi", "Noted! You're with Gubacchi - saved. So it's just the two of you tonight?", minutes=4, trace={"followup": {"refers_to": "none"}, "proposals_saved": ["semantic_fact"]}),
    _turn(3, "yeah i'm going line dancing with a bird", "Ha, got it - saved that you're line dancing tonight with Gubacchi.", minutes=8, trace={"followup": {"refers_to": "subject", "subject": "line dancing with Gubacchi"}, "proposals_saved": ["semantic_fact"]}),
    _turn(4, "Remind me about salsa at Don Tito's", "Salsa night at Don Tito's is today.", minutes=-60, metadata={"scheduled_task": {"id": "s1"}}),
    _turn(5, "what do i do this evening? i'm bored", "Salsa at Don Tito's is your usual move.", minutes=20),
    _turn(6, "shut it with don titos, i don't care about that", "Fine, Don Tito's is dead to me.", minutes=25),
]

SAVED = {
    "t3": [Saved("m3", "group:c1", "Ani is going line dancing with a bird on the evening of Saturday 5 September 2026.", "user_explicit", _WHEN + timedelta(minutes=8, seconds=20))],
    "t2": [Saved("m2", "group:c1", "Ani is with Gubacchi (said by Ani)", "user_explicit", _WHEN + timedelta(minutes=4, seconds=30))],
}


class _Judge:
    def __init__(self, judgement: Judgement | None) -> None:
        self.judgement = judgement
        self.shown: list[str] = []

    async def judge(self, rendered: str):
        self.shown.append(rendered)
        return self.judgement


@asynccontextmanager
async def _no_session():
    yield None


def _world(judgement: Judgement | None, turns: list[Turn] = TURNS, forgotten: list[str] | None = None) -> ExperienceWorld:
    world = ExperienceWorld({"id": "r1", "user_id": "ani", "objective": "review experience for ani since 2026-09-05T20:00:00+00:00"}, _no_session, _Judge(judgement))  # type: ignore[arg-type]
    # The reads are stubbed: the world is under test, not the database.
    world.state.turns = list(turns)
    world.state.rooms = ("group:c1",)
    world.state.read = True

    async def forgettable(kept):
        proposals = []
        for finding in kept:
            for saved in SAVED.get(f"t{finding.turn}", []):
                proposals.append(ForgetMemory(saved.id, saved.owner, saved.content, f"saved from exchange {finding.turn}: {finding.kind}"))
        return proposals

    world._forgettable = forgettable  # type: ignore[method-assign]
    return world


def test_the_window_comes_from_the_objective_or_defaults_to_a_day():
    assert since_of("review experience for ani since 2026-09-05T20:00:00+00:00") == datetime(2026, 9, 5, 20, tzinfo=UTC)
    now = datetime(2026, 9, 6, 11, tzinfo=UTC)
    assert since_of("review experience for ani", now) == now - timedelta(hours=24)


def test_the_judge_is_shown_numbered_exchanges_with_their_record():
    shown = render_turns(TURNS)
    assert "[1]" in shown and "(not addressed to the assistant)" in shown
    assert "'reminder_firing': True" in shown
    assert "'picture_in_view': False" in shown


async def test_the_stages_run_in_order_and_a_finding_must_quote_the_exchange():
    judgement = Judgement(
        (
            Finding(3, "unresolved_reference", "line dancing with a bird", "missing_attachment", "the bird was a picture the assistant never had"),
            Finding(5, "wrong_subject", "your usual move", "reminder_read_as_habit", "a weekly reminder read as a habit"),
            Finding(6, "correction", "these words were never said", "memory_wrong", "invented"),
            Finding(9, "repeat", "x", "unknown", "no such exchange"),
        ),
        "The assistant never saw the bird and mistook a reminder for a habit.",
    )
    world = _world(judgement)
    assert (await world.decide([])) == Act(Judge(world.since.isoformat()))
    kind, outcome = await world.apply(Judge(world.since.isoformat()))
    assert kind == "analysis"
    assert [f["turn"] for f in outcome["findings"]] == [3, 5]
    assert [r["rejected"] for r in outcome["rejected"]] == [
        "quotes words that are not in that exchange",
        "names an exchange that was not read",
    ]
    # The bird finding's cause stands: no picture was in view. The reminder
    # cause stands: a firing is in the window.
    assert outcome["findings"][0]["cause"] == "missing_attachment"
    assert outcome["findings"][1]["cause"] == "reminder_read_as_habit"
    # What the misread exchange saved is proposed for forgetting.
    assert [p["memory_id"] for p in outcome["proposals"]] == ["m3"]
    world.observe(Judge(world.since.isoformat()), kind, outcome)
    # Forgetting needs the person's yes; then the report; then done.
    forget = await world.decide([])
    assert isinstance(forget, Act) and isinstance(forget.action, ForgetMemory)
    assert world.needs_approval(forget.action) is True
    assert "line dancing with a bird" in world.approval_summary(forget.action)
    world.observe(forget.action, "write", {"kind": "done", "memory_id": "m3"})
    report = await world.decide([])
    assert report == Act(WriteReport(world.since.isoformat()))
    kind, outcome = await world.apply(report.action)
    assert "1 wrong memory forgotten" in outcome["summary"]
    world.observe(report.action, kind, outcome)
    assert isinstance(await world.decide([]), Done)
    verification = await world.verify(None, {})
    assert verification.accepted
    assert verification.evidence["fixes"][0]["status"] == "done"
    assert verification.evidence["turns_reviewed"] == 6


async def test_a_cause_the_record_contradicts_is_corrected_not_trusted():
    with_picture = [_turn(1, "what is this?", "A bowl of pho.", minutes=0, trace={"image_matches": [{"id": "a1"}]})]
    judgement = Judgement((Finding(1, "unresolved_reference", "what is this?", "missing_attachment", "guessing"),), "s")
    world = _world(judgement, with_picture)
    _, outcome = await world.apply(Judge(world.since.isoformat()))
    assert outcome["findings"][0]["cause"] == "model"
    no_firing = [_turn(1, "what do i do tonight?", "Don Tito's is your usual.", minutes=0)]
    judgement = Judgement((Finding(1, "wrong_subject", "your usual", "reminder_read_as_habit", "guessing"),), "s")
    world = _world(judgement, no_firing)
    _, outcome = await world.apply(Judge(world.since.isoformat()))
    assert outcome["findings"][0]["cause"] == "unknown"


async def test_an_empty_reply_finding_needs_an_addressed_turn_that_got_nothing():
    judgement = Judgement(
        (
            Finding(1, "empty_reply", "i'm with gubacchi", "routing", "nothing came back"),
            Finding(2, "empty_reply", "Scout i'm with gubacchi", "routing", "nothing came back"),
        ),
        "s",
    )
    world = _world(judgement)
    _, outcome = await world.apply(Judge(world.since.isoformat()))
    assert outcome["findings"] == []
    assert len(outcome["rejected"]) == 2


async def test_a_judge_that_does_not_answer_is_a_failed_step_not_a_clean_day():
    world = _world(None)
    kind, outcome = await world.apply(Judge(world.since.isoformat()))
    assert outcome["kind"] == "failed"
    world.observe(Judge(world.since.isoformat()), kind, outcome)
    assert world.state.judgement is None


async def test_no_exchanges_is_a_clean_review_with_nothing_to_forget():
    world = _world(Judgement((), "unused"), turns=[])
    _, outcome = await world.apply(Judge(world.since.isoformat()))
    assert outcome["findings"] == [] and outcome["proposals"] == []
    assert "nothing to review" in outcome["summary"].lower()


def test_the_world_names_its_tools_and_only_forgetting_needs_a_yes():
    world = _world(None)
    assert world.tool_name(ReadTurns("x")) == "turns_read"
    assert world.tool_name(Judge("x")) == "experience_judge"
    assert world.tool_name(ForgetMemory("m", "u", "c", "b")) == "memory_forget"
    assert world.tool_name(WriteReport("x")) == "experience_report"
    assert world.needs_approval(Judge("x")) is False
    assert world.creates(ForgetMemory("m", "u", "c", "b")) is False
    from backend.workers.run_worker import GRANTS

    assert GRANTS["experience_review"].tools == {"turns_read", "experience_judge", "memory_forget", "experience_report"}


# The classifier writes its rows during the turn and the turn's row lands
# when the reply is done, so what a turn saved sits before its timestamp.
def test_the_saved_window_opens_before_the_turn_and_closes_after():
    turn = _turn(1, "x", "y", minutes=0)
    start, end = saved_window(turn)
    assert start == _WHEN.replace(tzinfo=None) - timedelta(seconds=420)
    assert end == _WHEN.replace(tzinfo=None) + timedelta(seconds=180)
    assert saved_window(Turn(1, "t", None, "u", "u", "web", "x", "y", True)) is None


# A picture's own description is never a forget candidate, and a routing
# fault proposes nothing: only what the person stated may be forgotten.
async def test_only_a_persons_own_stated_facts_are_proposed_for_forgetting():
    from backend.agents.experience.world import FORGETTABLE_KINDS, FORGETTABLE_PURPOSES

    assert "wrong_subject" not in FORGETTABLE_KINDS
    assert "visual_artifact_analysis" not in FORGETTABLE_PURPOSES
    world = _world(Judgement((Finding(2, "wrong_subject", "try again", "routing", "misrouted"),), "s"))

    async def saved(db, turn, owners):
        return [
            Saved("v1", "ani", "A chessboard close-up showing the castle move", "visual_artifact_analysis", _WHEN),
            Saved("f1", "ani", "Ani is with Gubacchi", "user_explicit", _WHEN),
        ]

    import backend.agents.experience.world as module

    original = module.saved_after
    module.saved_after = saved  # type: ignore[assignment]
    try:
        # Restore the real method: the stub in _world is what this test is about.
        world._forgettable = ExperienceWorld._forgettable.__get__(world)  # type: ignore[method-assign]
        proposals = await world._forgettable([Finding(2, "wrong_subject", "try again", "routing", "misrouted")])
        assert proposals == []
        proposals = await world._forgettable([Finding(2, "wrong_memory", "try again", "memory_wrong", "a passing state saved")])
        assert [p.memory_id for p in proposals] == ["f1"]
    finally:
        module.saved_after = original
