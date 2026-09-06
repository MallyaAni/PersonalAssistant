"""The experience judge finds the two failures the operator reported by hand,
and leaves an ordinary day alone.

The exchanges are the real ones from 2026-09-05, as the review renders them:
a photo of a bird shared in a room and never seen, and a weekly reminder
read back as a habit until the person said to stop. Properties asserted on
the real structured model, over several passes:

- the bird exchanges yield a finding on the "line dancing with a bird" turn
  (or the one before it) whose quote is in the exchange;
- the Don Tito's exchanges yield a correction or wrong-subject finding on
  the "shut it" turn or the "usual move" turn;
- a plain, friendly day yields no finding at all in at least two of three.

pinned prompt: experience/judge.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.agents.experience.prompts import ExperiencePrompts
from backend.agents.experience.sources import Saved, Turn, render_turns

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_WHEN = datetime(2026, 9, 5, 21, 0, tzinfo=UTC)


def _turn(number, said, replied, minutes, *, addressed=True, trace=None, metadata=None, owner="ani", speaker="ani"):
    return Turn(number=number, id=f"t{number}", when=_WHEN + timedelta(minutes=minutes), owner=owner, speaker=speaker,
                channel="imessage", said=said, replied=replied, addressed=addressed, metadata=metadata or {}, trace=trace or {})


_DAY = [
    _turn(1, "Remind me about salsa at Don Tito's", "Salsa night at Don Tito's is today - it's on your Wednesday 5pm schedule. Have fun!", -4320, metadata={"scheduled_task": {"id": "s1"}}),
    _turn(2, "what do i do this evening? i'm bored", "Weather's not great tonight. So lean indoors: salsa at Don Tito's is your usual move - worth checking if it's on tonight.", 0, trace={"route": {"label": "Weather"}}),
    _turn(3, "its not going to rain according to forecast", "Never mind the drizzle then. Salsa at Don Tito's is still the usual move, or something chill outside nearby.", 4, trace={"route": {"label": "Weather"}}),
    _turn(4, "yes", "Alright, so patio it is. Don Tito's in Courthouse your typical go-to?", 26),
    _turn(5, "shut it with don titos , i don't care about that", "Fine, Don Tito's is dead to me. Here's tonight: Lubber Run Summer Concert, 8pm, free.", 35, trace={"route": {"label": "Web search"}}),
    _turn(9, "by the way i live in courthouse arlington, right by the metro", "Got it - Courthouse, Arlington, by the metro. Saved.", 50, trace={"proposals_saved": ["semantic_fact"]}),
    _turn(6, "i'm with gubacchi", "", 64, addressed=False, owner="group:c1", trace={"proposals_saved": ["semantic_fact"]}),
    _turn(7, "Scout i'm with gubacchi", "Noted! You're with Gubacchi - saved. So it's just the two of you tonight? What's on the agenda?", 68, owner="group:c1", trace={"followup": {"refers_to": "none", "subject": ""}, "proposals_saved": ["semantic_fact"]}),
    _turn(8, "yeah i'm going line dancing with a bird", "Ha, got it - saved that you're line dancing tonight with Gubacchi. Have fun out there! Where are you heading?", 72, owner="group:c1", trace={"followup": {"refers_to": "subject", "subject": "line dancing with Gubacchi"}, "proposals_saved": ["discovery_interests", "semantic_fact"]}),
]

_QUIET = [
    _turn(1, "when am i going to italy?", "You're flying out October 2, one-way to Rome, and flying home from the Amalfi side on October 18.", 0),
    _turn(2, "thanks! what's the weather there in october", "Mild - highs around 22C, some rain later in the month. Pack a light jacket.", 3, trace={"route": {"label": "Weather"}}),
    _turn(3, "perfect", "Enjoy the planning!", 5),
]


# The facts the day saved, beside their exchanges: the sarcastic line taken
# literally (must go), the passing state (may go), and a true durable fact
# saved the same evening (must stay).
_SAVED = {
    7: [Saved("m-with", "group:c1", "Ani is with Gubacchi (said by Ani)", "user_explicit", _WHEN + timedelta(minutes=68))],
    8: [Saved("m-bird", "group:c1", "Ani is going line dancing with a bird on the evening of Saturday 5 September 2026.", "user_explicit", _WHEN + timedelta(minutes=72))],
    9: [Saved("m-home", "ani", "Ani lives in Courthouse, Arlington, right by the metro.", "user_explicit", _WHEN + timedelta(minutes=50))],
}


async def _judge(structured_llm, turns, saved=None):
    return await ExperiencePrompts(structured_llm).judge(render_turns(turns, saved))


def _in_exchange(finding, turns) -> bool:
    turn = next((t for t in turns if t.number == finding.turn), None)
    return turn is not None and " ".join(finding.quote.split()).casefold() in " ".join(f"{turn.said} {turn.replied}".split()).casefold()


async def test_the_bird_and_the_reminder_are_both_found_with_words_from_the_exchanges(structured_llm):
    bird = habit = 0
    seen = []
    goes = stays = 0
    for _ in range(3):
        judgement = await _judge(structured_llm, _DAY, _SAVED)
        assert judgement is not None
        seen.append([f.as_dict() for f in judgement.findings] + [(v.memory_id, v.reason) for v in judgement.forget])
        named = {v.memory_id for v in judgement.forget}
        if "m-bird" in named:
            goes += 1
        if "m-home" not in named:
            stays += 1
        quoted = [f for f in judgement.findings if _in_exchange(f, _DAY)]
        if any(f.turn in (7, 8) and f.kind in ("unresolved_reference", "wrong_subject", "wrong_memory") for f in quoted):
            bird += 1
        if any(f.turn in (2, 3, 4, 5) and f.kind in ("correction", "wrong_subject", "repeat", "frustration") for f in quoted):
            habit += 1
    import json

    tallies = json.dumps({"bird": bird, "habit": habit, "goes": goes, "stays": stays}) + "\n" + json.dumps(seen, indent=1, default=str)
    assert bird >= 2, tallies
    assert habit >= 2, tallies
    # The judge names the sarcastic line's fact and leaves the true one.
    assert goes >= 2, tallies
    assert stays == 3, tallies


async def test_a_quiet_day_yields_no_findings(structured_llm):
    noisy = 0
    seen = []
    for _ in range(3):
        judgement = await _judge(structured_llm, _QUIET)
        assert judgement is not None
        seen.append([f.as_dict() for f in judgement.findings])
        if judgement.findings:
            noisy += 1
    assert noisy <= 1, seen
