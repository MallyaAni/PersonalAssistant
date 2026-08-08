"""One number, written the way people actually write numbers.

The failure this prevents is quiet and happens at the last hop: an address
stored as the user typed it did not match the one an operator typed into the
sending bridge's allowlist, so a digest was refused for a recipient who had done
everything right.
"""

import os

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

import pytest

from backend.discovery.addressing import normalize_address, same_address


# Every way a person writes their own number is the same subscription.
@pytest.mark.parametrize(
    "written",
    [
        "202-555-0143",
        "(202) 555-0143",
        "+1 202 555 0143",
        "+12025550143",
        "1-202-555-0143",
        " 202 555 0143 ",
    ],
)
def test_every_written_form_of_one_number_agrees(written):
    assert normalize_address(written) == "2025550143"
    assert same_address(written, "+12025550143")


# An Apple ID is an email, and case never distinguishes two of them.
def test_an_apple_id_normalizes_as_an_email():
    assert normalize_address("  Mallya.Ani96@Gmail.com ") == "mallya.ani96@gmail.com"
    assert same_address("A@B.com", "a@b.com")


# The country code is dropped only when what remains is a full ten-digit
# number, so an international number that legitimately begins with one survives.
def test_a_leading_one_is_only_dropped_for_a_ten_digit_number():
    assert normalize_address("+44 20 7946 0958") == "442079460958"
    # Eleven digits that are not a US number keep every digit.
    assert normalize_address("+81 3 1234 5678") == "81312345678"


# Two different numbers must never collapse into one.
def test_different_numbers_stay_different():
    assert not same_address("202-555-0143", "202-555-0144")
    assert not same_address("2025550143", "5135607051")


# Nothing recognizable is left as written rather than guessed at.
def test_an_unrecognized_address_is_left_alone():
    assert normalize_address("  handle  ") == "handle"
    assert normalize_address("") == ""


# The destination is kept as written while identity is normalized. Normalizing
# the stored value too would strip the leading + from an international number,
# and that + is part of how the address routes.
@pytest.mark.asyncio
async def test_the_address_is_stored_as_written_but_identified_normalized():
    import uuid as _uuid

    from sqlalchemy import delete

    from backend.database.session import AsyncSessionLocal
    from backend.discovery.subscribers import SubscriberRepository
    from backend.models.discovery_subscriber import DiscoverySubscriber

    user_id = f"addr_{_uuid.uuid4().hex[:8]}"
    try:
        async with AsyncSessionLocal() as session:
            people = SubscriberRepository(session)
            first = await people.enroll(user_id, "imessage", "+1 202-555-0143")
            # Written exactly as the user typed it, + and all.
            assert first.address == "+1 202-555-0143"

            # The same number in another form is the same subscription, not a
            # second one competing for the one-per-account slot.
            again = await people.enroll(user_id, "imessage", "2025550143")
            assert again.id == first.id
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(DiscoverySubscriber).where(
                    DiscoverySubscriber.user_id == user_id
                )
            )
            await session.commit()
