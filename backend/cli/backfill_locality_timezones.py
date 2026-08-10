"""Correct localities that were stored in the hardcoded zone.

    python -m backend.cli.backfill_locality_timezones          # report only
    python -m backend.cli.backfill_locality_timezones --apply

Every place saved through a chat approval before the resolver existed was
written as America/New_York regardless of where it is, and any schedule created
from one inherited that zone. Fixing the code does not move the rows, so an
account living in Bali keeps receiving its morning digest at 23:15 until this
runs.

Only rows still holding the hardcoded default are touched, and only when the
resolver names a different zone — a place genuinely in America/New_York is left
exactly as it is, and so is a zone somebody set deliberately.
"""

import argparse
import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select

from backend.agents.scout.timezones import TimezoneResolver
from backend.core.dependencies import get_llm_client
from backend.database.session import AsyncSessionLocal
from backend.discovery.projection import DEFAULT_TIMEZONE
from backend.discovery.schedule import Cadence, next_run_at
from backend.models.discovery import DiscoveryLocality
from backend.models.discovery_run import DiscoverySchedule


async def run(apply: bool) -> int:
    resolver = TimezoneResolver(get_llm_client())
    moved = 0
    async with AsyncSessionLocal() as session:
        localities = (
            (
                await session.execute(
                    select(DiscoveryLocality).where(
                        DiscoveryLocality.timezone == DEFAULT_TIMEZONE
                    )
                )
            )
            .scalars()
            .all()
        )
        for locality in localities:
            resolved = await resolver.resolve(locality.label, locality.region)
            if resolved is None or resolved == locality.timezone:
                print(f"  keep  {locality.label!r} -> {locality.timezone}")
                continue
            print(f"  MOVE  {locality.label!r} {locality.timezone} -> {resolved}")
            moved += 1
            if not apply:
                continue
            locality.timezone = resolved
            # A schedule is only meaningful in its place's zone, so a corrected
            # place has to carry its schedule with it — otherwise the digest
            # keeps firing at the old local hour.
            schedules = (
                (
                    await session.execute(
                        select(DiscoverySchedule).where(
                            DiscoverySchedule.user_id == locality.user_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for schedule in schedules:
                if schedule.timezone != DEFAULT_TIMEZONE:
                    continue
                schedule.timezone = resolved
                # The armed instant was computed from the old zone, so moving
                # the zone alone leaves the sweep firing at the hour the wrong
                # zone implied — which is the bug, not a smaller version of it.
                schedule.next_run_at = next_run_at(
                    Cadence(
                        cadence=schedule.cadence,
                        hour=schedule.hour,
                        weekday=schedule.weekday,
                        timezone=resolved,
                        minute=schedule.minute,
                    ),
                    datetime.now(UTC),
                )
                print(
                    f"        schedule {schedule.hour:02d}:{schedule.minute:02d}"
                    f" -> {resolved}, next run {schedule.next_run_at}"
                )
        if apply:
            await session.commit()
    print(
        f"{moved} localit{'y' if moved == 1 else 'ies'} "
        f"{'moved' if apply else 'would move'} of {len(localities)} on the default"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the changes.")
    return asyncio.run(run(parser.parse_args(argv).apply))


if __name__ == "__main__":
    raise SystemExit(main())
