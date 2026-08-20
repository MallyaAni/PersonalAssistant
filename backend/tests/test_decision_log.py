"""Recording the decision, not just its outcome.

A reaction labels one item. Without the decision behind it — what that item beat,
how it scored, which interest matched it, where it sat in the message — a thumb
is a label with no features, and no ranking model can be built or evaluated from
a pile of those.

The shape is the one off-policy evaluation expects, so the assertions are about
the fields an estimator actually needs, including the propensity that says
plainly whether the data supports evaluation at all.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from backend.discovery.decision_log import (
    DETERMINISTIC_TOP_K,
    build_decision,
    to_json,
)

_MOMENT = datetime(2026, 8, 12, 1, 15, tzinfo=UTC)


@dataclass(frozen=True)
class FakeEvent:
    title: str


@dataclass(frozen=True)
class FakeCandidate:
    digest: str
    event: FakeEvent


@dataclass(frozen=True)
class FakeRanked:
    candidate: FakeCandidate
    score: float
    matched_interest: str | None


def _ranked(digest: str, score: float, interest: str | None = "Food") -> FakeRanked:
    return FakeRanked(
        candidate=FakeCandidate(
            digest=digest, event=FakeEvent(title=f"{digest} event")
        ),
        score=score,
        matched_interest=interest,
    )


def _decide(shortlist, selected):
    return build_decision(
        shortlist=tuple(shortlist),
        selected=tuple(selected),
        interests=("Food", "Live Music"),
        locality="Alexandria, Virginia",
        decided_at=_MOMENT,
    )


# The half a reaction can never supply. A rejected candidate is the only
# evidence that a rejection was wrong, and it was previously never written down.
def test_rejected_candidates_are_recorded_alongside_the_chosen() -> None:
    shortlist = [_ranked("a", 0.9), _ranked("b", 0.7), _ranked("c", 0.5)]
    decision = _decide(shortlist, shortlist[:2])

    rows = {row["digest"]: row for row in decision["considered"]}
    assert set(rows) == {"a", "b", "c"}
    assert rows["c"]["selected"] is False
    assert rows["c"]["score"] == 0.5


# Position bias is real and any model has to account for it, so the slot in the
# message is recorded rather than inferred from the order of a list later.
def test_the_slot_in_the_message_is_recorded_for_what_was_sent() -> None:
    shortlist = [_ranked("a", 0.9), _ranked("b", 0.7), _ranked("c", 0.5)]
    decision = _decide(shortlist, [shortlist[1], shortlist[0]])

    rows = {row["digest"]: row for row in decision["considered"]}
    assert rows["b"]["position"] == 0
    assert rows["a"]["position"] == 1
    # Not sent, so it occupied no slot — distinct from "sent in slot zero".
    assert rows["c"]["position"] is None


# The uncomfortable fact, recorded rather than glossed. A deterministic policy
# gives everything it rejected a propensity of zero, and an action with zero
# probability of being logged contributes nothing to the usual estimators — so
# this data cannot, by itself, measure an alternative ranker.
def test_a_deterministic_policy_records_degenerate_propensities() -> None:
    shortlist = [_ranked("a", 0.9), _ranked("b", 0.7)]
    decision = _decide(shortlist, shortlist[:1])

    rows = {row["digest"]: row for row in decision["considered"]}
    assert decision["policy"] == DETERMINISTIC_TOP_K
    assert rows["a"]["propensity"] == 1.0
    assert rows["b"]["propensity"] == 0.0


# Why it ranked where it did, not only that it did.
def test_the_reason_a_candidate_ranked_is_kept_with_it() -> None:
    music = _ranked("a", 0.81, "Live Music")
    decision = _decide([music], [music])

    row = decision["considered"][0]
    assert row["interest"] == "Live Music"
    assert row["score"] == 0.81
    assert row["shortlist_rank"] == 0


# The interests and place the run ran against — the context an estimator needs
# to tell "she dislikes dog events" from "she dislikes dog events in August".
def test_the_context_the_decision_was_made_in_is_recorded() -> None:
    decision = _decide([_ranked("a", 0.9)], [_ranked("a", 0.9)])

    assert decision["context"]["interests"] == ["Food", "Live Music"]
    assert decision["context"]["locality"] == "Alexandria, Virginia"
    assert decision["decided_at"] == _MOMENT.isoformat()


# An unusual find is chosen for being unlike anything seen, so it never enters
# the interest shortlist — but the person saw it and can react to it, so it is
# an action and has to be logged as one.
def test_something_sent_without_being_shortlisted_is_still_logged() -> None:
    shortlist = [_ranked("a", 0.9)]
    unusual = _ranked("z", 0.42, None)
    decision = _decide(shortlist, [shortlist[0], unusual])

    rows = {row["digest"]: row for row in decision["considered"]}
    assert rows["z"]["selected"] is True
    assert rows["z"]["position"] == 1
    assert rows["z"]["interest"] is None
    # Marked as never having been on the shortlist, so it is not mistaken for a
    # candidate the interest ranker approved.
    assert rows["z"]["shortlist_rank"] == -1


def test_a_sweep_that_selected_nothing_still_records_what_it_weighed() -> None:
    decision = _decide([_ranked("a", 0.3), _ranked("b", 0.2)], [])

    assert len(decision["considered"]) == 2
    assert all(row["selected"] is False for row in decision["considered"])
    assert all(row["propensity"] == 0.0 for row in decision["considered"])


# It goes into a sealed text column, so it has to survive a round trip.
def test_the_record_serializes_and_reads_back() -> None:
    decision = _decide([_ranked("a", 0.9), _ranked("b", 0.1)], [_ranked("a", 0.9)])

    restored = json.loads(to_json(decision))

    assert restored == decision
    assert restored["version"] == 1


# The column is sealed, like every other stored text here, and the record is
# JSON inside it. Encryption round trips are exactly where a nested payload
# quietly becomes a string of ciphertext nobody can read back.
@pytest.mark.asyncio
async def test_a_decision_survives_the_sealed_column() -> None:
    import uuid

    from sqlalchemy import select

    from backend.database.session import AsyncSessionLocal
    from backend.models.discovery_run import DiscoveryRun, DiscoverySchedule

    decision = _decide([_ranked("a", 0.9), _ranked("b", 0.4)], [_ranked("a", 0.9)])
    user_id = f"dec_{uuid.uuid4().hex[:12]}"

    async with AsyncSessionLocal() as session:
        try:
            schedule = DiscoverySchedule(
                user_id=user_id, timezone="UTC", next_run_at=_MOMENT
            )
            session.add(schedule)
            await session.flush()
            run = DiscoveryRun(
                schedule_id=schedule.id,
                user_id=user_id,
                status="ready",
                scheduled_for=_MOMENT,
                decision_json=to_json(decision),
            )
            session.add(run)
            await session.flush()
            session.expunge_all()

            stored = (
                (
                    await session.execute(
                        select(DiscoveryRun).where(DiscoveryRun.id == run.id)
                    )
                )
                .scalars()
                .one()
            )
            assert json.loads(stored.decision_json) == decision
        finally:
            # Nothing is committed, so the database is left exactly as found.
            await session.rollback()
