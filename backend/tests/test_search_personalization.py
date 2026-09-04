"""A search that should be tailored is tailored, in code, not by suggestion.

Asked "fun things to do in the area this week" on 2026-09-04, an account with
twenty interests on file - salsa, bachata, east and west coast swing, line
dancing, live music, karaoke, board games, breweries, wineries, hiking,
thrifting, farmers markets - was searched with:

    fun events things to do this weekend September 5-6 2026 Arlington Virginia

Place carried, dates carried, not one interest. Four listings came back from a
town two hours away and the reply had a single recommendation in it. The
interests were advice to a prompt that "decides when to use them", and it
decided not to.
"""
from backend.services.conversation_service import _hold_to_interests, _interests_for

LIKES = (
    "line dancing", "vintage shops/thrifting", "hiking", "dancing",
    "unique local events", "live music", "salsa", "swing dancing",
    "breweries", "board games",
)


def test_the_interests_reach_the_query():
    query = _hold_to_interests("events this weekend Arlington Virginia", ("salsa", "breweries"))
    assert "salsa" in query and "breweries" in query
    # Appended, never replacing what the query already got right.
    assert query.startswith("events this weekend Arlington Virginia")


def test_nothing_judged_relevant_leaves_the_query_alone():
    asked = "how much does a PS5 cost now"
    assert _hold_to_interests(asked, ()) == asked


def test_an_interest_the_query_already_carries_is_not_repeated():
    query = _hold_to_interests("live music this weekend Arlington", ("live music", "breweries"))
    assert query.count("live music") == 1
    assert "breweries" in query


def test_at_most_six_go_in_however_many_are_named():
    # Ten named; a query is a query, not a profile dump. Counted by how much
    # was appended rather than by substring, since "dancing" sits inside both
    # "line dancing" and "swing dancing" and matching text over-counts.
    added = _hold_to_interests("things on in Arlington", LIKES).replace(
        "things on in Arlington", ""
    ).strip()
    assert added
    dropped = [like for like in LIKES if like not in added]
    assert dropped, "ten interests must not all land in one query"
    assert len(added) < sum(len(like) + 1 for like in LIKES)
