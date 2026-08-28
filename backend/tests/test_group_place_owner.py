"""A group turn's place and clock are the speaker's; everyone else's are their own."""

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
