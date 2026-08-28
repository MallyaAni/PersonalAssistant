"""A group turn's place and clock are the speaker's; everyone else's are their own."""

import pytest

from backend.services.conversation_service import _place_owner, _speaker_of, _turn_speaker


def test_the_speaker_comes_from_group_metadata():
    assert _speaker_of({"channel": "imessage_group", "group": {"speaker_user_id": "ani"}}) == "ani"
    assert _speaker_of({"channel": "imessage", "group": {"speaker_user_id": "ani"}}) is None
    assert _speaker_of({"channel": "imessage_group", "group": {}}) is None
    assert _speaker_of({}) is None
    assert _speaker_of(None) is None


def test_a_groups_place_is_its_speakers_and_a_persons_is_their_own():
    token = _turn_speaker.set("ani")
    try:
        assert _place_owner("group:abc") == "ani"
        assert _place_owner("jen") == "jen"
    finally:
        _turn_speaker.reset(token)
    # No speaker on record (a task firing for the group): the group itself.
    assert _place_owner("group:abc") == "group:abc"


@pytest.mark.asyncio
async def test_a_groups_task_clock_is_its_speakers():
    from types import SimpleNamespace

    from backend.services.conversation_service import ConversationService

    asked: list[str] = []

    class _Scout:
        async def get_profile(self, user_id):
            asked.append(user_id)
            zone = "America/New_York" if user_id == "ani" else None
            locality = SimpleNamespace(timezone=zone, label="Arlington", is_primary=True, is_travel_active=False) if zone else None
            return SimpleNamespace(localities=(locality,) if locality else (), primary_locality=locality)

    fake = SimpleNamespace(discovery_profile=_Scout())
    token = _turn_speaker.set("ani")
    try:
        zone = await ConversationService._primary_timezone(fake, "group:abc")
    finally:
        _turn_speaker.reset(token)
    assert asked == ["ani"]
    assert zone == "America/New_York"
