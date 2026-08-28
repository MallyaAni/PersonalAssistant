"""Whose memory a fact said in a group lands in.

The rule under test: a member's own statement is theirs (and the room's,
with its source); anything about the group or about another member is the
room's only, with its source; nobody's memory is written on somebody
else's word.
"""

from backend.memory.attribution import Owner, owners_for, with_provenance
from backend.services.conversation_service import _owned_copies

ROSTER = {"Ani": "u-ani", "Jen": "u-jen", "Sam": "u-sam"}
GROUP = "group:abc"


def _owners(about):
    return owners_for(about, ROSTER, "u-ani", "Ani", GROUP)


def test_a_statement_about_oneself_is_ones_own_and_the_rooms_with_a_source():
    assert _owners(["Ani"]) == (Owner("u-ani", None), Owner(GROUP, "said by Ani"))
    assert _owners(["me"]) == (Owner("u-ani", None), Owner(GROUP, "said by Ani"))
    assert _owners(["ani"]) == (Owner("u-ani", None), Owner(GROUP, "said by Ani"))


def test_nothing_named_reads_as_the_speaker():
    assert _owners([]) == (Owner("u-ani", None), Owner(GROUP, "said by Ani"))
    assert _owners(["", "  "]) == (Owner("u-ani", None), Owner(GROUP, "said by Ani"))


def test_about_another_member_never_writes_their_memory():
    assert _owners(["Jen"]) == (Owner(GROUP, "said by Ani"),)
    assert _owners(["jen", "Sam"]) == (Owner(GROUP, "said by Ani"),)


def test_the_speakers_share_of_jen_and_i_is_theirs_and_jens_is_the_rooms():
    assert _owners(["Ani", "Jen"]) == (Owner("u-ani", None), Owner(GROUP, "said by Ani"))
    assert _owners(["Ani", "the group"]) == (Owner("u-ani", None), Owner(GROUP, "said by Ani"))


def test_the_group_alone_is_the_rooms():
    assert _owners(["the group"]) == (Owner(GROUP, "said by Ani"),)
    assert _owners(["us"]) == (Owner(GROUP, "said by Ani"),)


def test_an_outsider_is_the_rooms_knowledge_with_a_source():
    assert _owners(["Mum"]) == (Owner(GROUP, "said by Ani"),)


def test_provenance_rides_in_the_words():
    assert with_provenance("Jen hates cilantro", "said by Ani") == "Jen hates cilantro (said by Ani)"
    assert with_provenance("  I  love hiking ", None) == "I love hiking"
    assert with_provenance("", "said by Ani") == ""


ROOM = {
    "speaker_user_id": "u-ani",
    "speaker_name": "Ani",
    "members": [{"user_id": "u-ani", "name": "Ani"}, {"user_id": "u-jen", "name": "Jen"}],
}


def test_a_direct_turn_has_one_owner_and_the_candidate_unchanged():
    candidate = {"kind": "semantic_fact", "content": "My dog is Biscuit"}
    assert _owned_copies(candidate, "u-ani", None) == [("u-ani", candidate)]


def test_a_members_own_fact_goes_to_them_plain_and_to_the_room_with_its_source():
    candidate = {"kind": "semantic_fact", "content": "I love hiking", "about": ["Ani"]}
    assert _owned_copies(candidate, "group:abc", ROOM) == [
        ("u-ani", candidate),
        ("group:abc", {**candidate, "content": "I love hiking (said by Ani)"}),
    ]


def test_a_fact_about_another_member_goes_only_to_the_room():
    candidate = {"kind": "semantic_fact", "content": "Jen hates cilantro", "about": ["Jen"]}
    assert _owned_copies(candidate, "group:abc", ROOM) == [
        ("group:abc", {**candidate, "content": "Jen hates cilantro (said by Ani)"}),
    ]


def test_profile_fields_are_only_ever_the_speakers():
    name = {"kind": "preferred_name", "value": "Jenny", "about": ["Jen"]}
    assert _owned_copies(name, "group:abc", ROOM) == []
    own = {"kind": "preferred_name", "value": "Ani", "about": ["Ani"]}
    assert _owned_copies(own, "group:abc", ROOM) == [("u-ani", own)]
    locality = {"kind": "discovery_locality", "label": "Arlington", "region": "VA", "about": ["the group"]}
    assert _owned_copies(locality, "group:abc", ROOM) == []


def test_interests_go_to_the_speaker_or_when_shared_to_the_group():
    own = {"kind": "discovery_interests", "labels": ["hiking"], "about": ["Ani"]}
    assert _owned_copies(own, "group:abc", ROOM) == [("u-ani", own)]
    shared = {"kind": "discovery_interests", "labels": ["climbing"], "about": ["the group"]}
    assert _owned_copies(shared, "group:abc", ROOM) == [("group:abc", shared)]
    theirs = {"kind": "discovery_interests", "labels": ["knitting"], "about": ["Jen"]}
    assert _owned_copies(theirs, "group:abc", ROOM) == []


def test_a_group_plan_is_the_groups_fact_with_its_source():
    plan = {"kind": "semantic_fact", "content": "Thai on Friday at 7", "about": ["the group"]}
    assert _owned_copies(plan, "group:abc", ROOM) == [
        ("group:abc", {**plan, "content": "Thai on Friday at 7 (said by Ani)"}),
    ]


def test_a_room_without_a_speaker_falls_back_to_the_one_owner():
    candidate = {"kind": "semantic_fact", "content": "x", "about": ["Jen"]}
    assert _owned_copies(candidate, "group:abc", {"members": ROOM["members"]}) == [("group:abc", candidate)]
