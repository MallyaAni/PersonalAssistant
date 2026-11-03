"""The Scout record judgement: a schema answer, and fail-open when unreadable."""

from backend.services.scout_route import parse_scout_record


def test_a_preference_answer_is_false():
    assert (
        parse_scout_record(
            {"content": '{"about_scout_record": false, "reason": "preference"}'}
        )
        is False
    )


def test_a_sent_record_answer_is_true():
    assert (
        parse_scout_record(
            {"content": '{"about_scout_record": true, "reason": "sent record"}'}
        )
        is True
    )


# An unreadable answer must not lose a legitimate digest or schedule question,
# so the router's choice stands.
def test_an_unreadable_answer_keeps_the_router_choice():
    for answer in (
        {"content": "not json"},
        {},
        None,
        {"content": '{"reason": "no verdict"}'},
    ):
        assert parse_scout_record(answer) is True, answer
