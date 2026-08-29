"""Remove the accounts the harnesses left behind, and nothing else.

    docker compose exec backend python -m backend.cli.purge_test_accounts
    docker compose exec backend python -m backend.cli.purge_test_accounts --apply

Written on 2026-08-29, after the operator noticed a row of unfamiliar profiles
sitting beside their own. They were the journey sweep's: it made a fresh random
account per run, and any run that did not reach its cleanup - a killed
`timeout`, a crash, the deploy's single-journey retry, which opened an account
of its own - left one behind for good. Ten had accumulated, with sixty-three
turns and two group rooms.

The harnesses now draw their ids from one namespace and purge before each run
(`backend/core/harness_identity.py`), so this is a broom for what came before
and a net for whatever leaks next. It is deliberately not wired into the
deploy: something has to notice that a harness is leaking, and a cleaner that
runs silently every time is how nobody ever notices again.

The property that matters is that it cannot delete a person. Three independent
checks, because a prefix is a convention and conventions get broken:

  1. the id is in the harness namespace, or one of the closed set of shapes
     that predate it;
  2. the account has no consented delivery address - a harness never enrols a
     real phone or mailbox, and a real account almost always has one;
  3. a group room goes only when every one of its members is a harness
     account. A room with one real member is reported and left, because that
     is a mess for a person to look at, not something a script should resolve.

Dry run unless `--apply`, and it prints what it would remove either way.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field

from sqlalchemy import text

from backend.api.v1.admin import purge_owned_rows
from backend.core.harness_identity import is_harness_id
from backend.database.session import AsyncSessionLocal
from backend.groups.repository import ConversationGroupRepository


@dataclass
class Survey:
    """What may go, what stays, and why - so a dry run reads as an argument."""

    accounts: list[str] = field(default_factory=list)
    rooms: list[str] = field(default_factory=list)
    spared: list[str] = field(default_factory=list)


# Accounts that carry a real delivery address. Checked rather than assumed: an
# id is a naming convention, and a consented address is evidence that somebody
# expects messages at this account.
async def _addressed(db) -> set[str]:
    rows = (
        await db.execute(
            text(
                "select distinct user_id from discovery_subscribers "
                "where consented_at is not null"
            )
        )
    ).all()
    return {row[0] for row in rows}


async def survey(db) -> Survey:
    found = Survey()
    addressed = await _addressed(db)
    rows = (await db.execute(text("select user_id from user_accounts"))).all()
    for (user_id,) in rows:
        if not is_harness_id(user_id):
            continue
        if user_id in addressed:
            found.spared.append(f"{user_id} - has a consented delivery address")
            continue
        found.accounts.append(user_id)
    found.accounts.sort()

    repository = ConversationGroupRepository(db)
    for group in await repository.list_all():
        members = await repository.members(group.user_id)
        if not members:
            found.spared.append(f"{group.user_id} - a room with no members; left for a person to read")
            continue
        synthetic = [member for member in members if is_harness_id(member)]
        if len(synthetic) == len(members):
            found.rooms.append(group.user_id)
        elif synthetic:
            found.spared.append(
                f"{group.user_id} - room mixing real and harness members ({', '.join(members)})"
            )
    return found


async def run(apply: bool) -> int:
    async with AsyncSessionLocal() as db:
        found = await survey(db)
        for room in found.rooms:
            print(f"room     {room}")
        for account in found.accounts:
            print(f"account  {account}")
        for note in found.spared:
            print(f"SPARED   {note}")
        if not found.accounts and not found.rooms:
            print("nothing to remove")
            return 0
        if not apply:
            print(
                f"\ndry run: {len(found.accounts)} accounts and {len(found.rooms)} rooms "
                "would be removed; re-run with --apply"
            )
            return 0
        # Rooms first: their rows reference the members removed below.
        for room in found.rooms:
            await purge_owned_rows(db, room)
            await db.commit()
            await ConversationGroupRepository(db).delete(room)
            await db.commit()
            print(f"removed room     {room}")
        for account in found.accounts:
            removed = await purge_owned_rows(db, account)
            await db.commit()
            touched = {table: count for table, count in removed.items() if count}
            print(f"removed account  {account} {touched or '(no rows)'}")
        print(f"\nremoved {len(found.accounts)} accounts and {len(found.rooms)} rooms")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="actually remove them")
    return asyncio.run(run(parser.parse_args(argv).apply))


if __name__ == "__main__":
    sys.exit(main())
