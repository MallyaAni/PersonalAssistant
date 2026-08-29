"""The broom, and the three things that stop it sweeping up a person.

On 2026-08-29 ten harness accounts were sitting in the database beside the
operator's own, left there by sweeps that died before their cleanup. Removing
them is easy; removing them *safely* is the whole design, because the tool
deletes accounts with no confirmation and one false positive is somebody's
data. So: a harness id, no consented delivery address, and - for a room -
every member synthetic. These tests are that guarantee.
"""

import uuid

import pytest
from sqlalchemy import text

from backend.cli.purge_test_accounts import run, survey
from backend.core.harness_identity import harness_id
from backend.database.session import AsyncSessionLocal
from backend.discovery.subscribers import SubscriberRepository
from backend.groups.repository import ConversationGroupRepository
from backend.services.auth_service import AuthService

_HASH = "$2b$12$" + "x" * 53


async def _account(user_id: str) -> None:
    # Purged first. These ids are fixed on purpose - that is the whole point of
    # the namespace - so one may already be sitting in the database, left by a
    # sweep that died before its cleanup. That is the exact condition this tool
    # exists for, and a test that fell over on it would be testing the tidiness
    # of the last run rather than the tool. (Seen 2026-08-29: the unit gate ran
    # minutes after a deploy whose retry had left `harness_journeys` behind.)
    await _forget(user_id)
    async with AsyncSessionLocal() as db:
        await AuthService(db).create_account_with_hash(
            user_id=user_id, username=user_id, password_hash=_HASH
        )
        await db.commit()


async def _forget(*user_ids: str) -> None:
    from backend.api.v1.admin import purge_owned_rows

    async with AsyncSessionLocal() as db:
        for user_id in user_ids:
            try:
                await purge_owned_rows(db, user_id)
                await db.commit()
            except Exception:
                await db.rollback()


async def _subscribe(user_id: str, consented: bool) -> None:
    async with AsyncSessionLocal() as db:
        await SubscriberRepository(db).enroll(
            user_id=user_id,
            channel="imessage",
            address=f"+1555{uuid.uuid4().int % 10**7:07d}",
            consented=consented,
        )
        await db.commit()


@pytest.mark.asyncio
async def test_a_leaked_harness_account_is_found():
    leaked = harness_id("journeys")
    try:
        await _account(leaked)
        async with AsyncSessionLocal() as db:
            found = await survey(db)
        assert leaked in found.accounts
    finally:
        await _forget(leaked)


@pytest.mark.asyncio
async def test_a_persons_account_is_never_a_candidate():
    person = f"person_{uuid.uuid4().hex[:8]}"
    try:
        await _account(person)
        async with AsyncSessionLocal() as db:
            found = await survey(db)
        assert person not in found.accounts
        assert not any(person in note for note in found.spared)
    finally:
        await _forget(person)


@pytest.mark.asyncio
async def test_a_harness_id_with_a_real_delivery_address_is_spared():
    # The second, behavioural check. A name is a convention; an address
    # somebody consented to is evidence that a person expects messages here.
    odd = harness_id("journeys", uuid.uuid4().hex[:6])
    try:
        await _account(odd)
        await _subscribe(odd, consented=True)
        async with AsyncSessionLocal() as db:
            found = await survey(db)
        assert odd not in found.accounts
        assert any(odd in note for note in found.spared)
    finally:
        await _forget(odd)


@pytest.mark.asyncio
async def test_a_room_of_only_harness_members_goes_and_a_mixed_room_stays():
    run_tag = uuid.uuid4().hex[:6]
    synthetic_a = harness_id("journeys", run_tag)
    synthetic_b = harness_id("journeys", f"{run_tag}_member")
    person = f"person_{uuid.uuid4().hex[:8]}"
    all_fake = f"imessage;+;chatfake{run_tag}"
    mixed = f"imessage;+;chatmixed{run_tag}"
    fake_room = real_room = None
    try:
        for user_id in (synthetic_a, synthetic_b, person):
            await _account(user_id)
        async with AsyncSessionLocal() as db:
            repository = ConversationGroupRepository(db)
            fake_room = (await repository.provision(all_fake, "Sweep crew", (synthetic_a, synthetic_b))).user_id
            real_room = (await repository.provision(mixed, "Real crew", (person, synthetic_a))).user_id
        async with AsyncSessionLocal() as db:
            found = await survey(db)
        assert fake_room in found.rooms
        assert real_room not in found.rooms
        assert any(real_room in note for note in found.spared)
    finally:
        await _forget(synthetic_a, synthetic_b, person, fake_room or "", real_room or "")


@pytest.mark.asyncio
async def test_a_dry_run_removes_nothing():
    leaked = harness_id("journeys")
    try:
        await _account(leaked)
        assert await run(apply=False) == 0
        async with AsyncSessionLocal() as db:
            still_there = await db.execute(
                text("select count(*) from user_accounts where user_id = :u"), {"u": leaked}
            )
            assert still_there.scalar() == 1
    finally:
        await _forget(leaked)


@pytest.mark.asyncio
async def test_applying_it_removes_the_account_and_its_rows():
    leaked = harness_id("journeys")
    await _account(leaked)
    assert await run(apply=True) == 0
    async with AsyncSessionLocal() as db:
        gone = await db.execute(
            text("select count(*) from user_accounts where user_id = :u"), {"u": leaked}
        )
        assert gone.scalar() == 0
