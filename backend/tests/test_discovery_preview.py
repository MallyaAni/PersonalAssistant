"""The preview must show the message delivery would send, not a cousin of it.

Preview exists so an outbound feature can be checked without sending. That only
works if it reads the same record delivery reads: rebuilding from the seen store
renders every find as a matched one and drops the unusual section, so the
preview looked fine while the real digest differed.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.api.v1.discovery import preview_digest
from backend.database.session import AsyncSessionLocal
from backend.discovery.events import DiscoveredEvent
from backend.discovery.novelty import ScoredCandidate, SeenItemRepository
from backend.discovery.relevance import RankedCandidate
from backend.discovery.runner import SweepResult
from backend.discovery.runs import DiscoveryRunRepository
from backend.discovery.schedule import Cadence
from backend.discovery.subscribers import SubscriberRepository
from backend.discovery.types import DiscoveryProfile
from backend.models.discovery import DiscoveryInterest
from backend.models.discovery_run import DiscoveryRun, DiscoverySchedule
from backend.models.discovery_source import DiscoverySeenItem
from backend.models.discovery_subscriber import DiscoverySubscriber

_NOW = datetime.now(UTC)


class _ProfileStub:
    """The only thing the preview asks a profile for."""

    async def get_profile(self, user_id: str) -> DiscoveryProfile:
        return DiscoveryProfile(interests=(), localities=())


def _ranked(title: str, score: float, interest: str | None) -> RankedCandidate:
    event = DiscoveredEvent(
        source_id="src-1",
        external_id=f"evt-{title}",
        title=title,
        starts_at=_NOW + timedelta(days=10),
        ends_at=None,
        place="New Haven, CT",
        url="https://example.org/e",
        summary=None,
    )
    return RankedCandidate(ScoredCandidate(event, None), score, interest)


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        schedules = (
            (
                await session.execute(
                    select(DiscoverySchedule).where(
                        DiscoverySchedule.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for schedule in schedules:
            await session.execute(
                delete(DiscoveryRun).where(DiscoveryRun.schedule_id == schedule.id)
            )
            await session.delete(schedule)
        await session.execute(
            delete(DiscoverySeenItem).where(DiscoverySeenItem.user_id == user_id)
        )
        await session.execute(
            delete(DiscoverySubscriber).where(DiscoverySubscriber.user_id == user_id)
        )
        await session.execute(
            delete(DiscoveryInterest).where(DiscoveryInterest.user_id == user_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_preview_renders_the_saved_digest_with_its_unusual_section():
    user_id = f"prv_{uuid.uuid4().hex[:12]}"
    digest = SweepResult(
        selected=(_ranked("Jazz at the Green", 0.9, "jazz"),),
        candidate_count=2,
        novel_count=2,
        requests_spent=1,
        failed_sources=(),
        notable=(_ranked("Hot-air balloon rally", 0.2, None),),
    ).to_digest_json()

    try:
        async with AsyncSessionLocal() as session:
            runs = DiscoveryRunRepository(session)
            await runs.upsert_schedule(
                user_id,
                Cadence(
                    cadence="daily", hour=9, weekday=0, timezone="America/New_York"
                ),
            )
            schedule = (
                (
                    await session.execute(
                        select(DiscoverySchedule).where(
                            DiscoverySchedule.user_id == user_id
                        )
                    )
                )
                .scalars()
                .one()
            )
            session.add(
                DiscoveryRun(
                    schedule_id=schedule.id,
                    user_id=user_id,
                    status="ready",
                    scheduled_for=_NOW,
                    digest_json=digest,
                )
            )
            await session.commit()

            response = await preview_digest(
                user_id=user_id,
                profile_service=_ProfileStub(),
                runner=None,
                subscribers=SubscriberRepository(session),
                seen=SeenItemRepository(session),
                runs=runs,
            )

        message = response["message"]
        assert isinstance(message, str)
        assert "Jazz at the Green" in message
        assert "Also worth knowing:" in message
        assert "Hot-air balloon rally" in message
        # Both sections are what would be sent, so both count.
        assert response["event_count"] == 2
        # Nothing is approved, so preview says so rather than implying a send.
        assert response["would_send"] is False
    finally:
        await _cleanup(user_id)
