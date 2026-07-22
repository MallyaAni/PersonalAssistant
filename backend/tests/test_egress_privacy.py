import pytest

from backend.core.egress import OutboundPrivacyPolicy


@pytest.fixture
def policy() -> OutboundPrivacyPolicy:
    return OutboundPrivacyPolicy()


@pytest.mark.parametrize(
    ("query", "category"),
    [
        ("is sk-abc123def456ghi789jkl a valid key", "credential"),
        ("check tvly-dev-45DZQY-SOCxoLmvPSCcFg", "credential"),
        ("is ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123 leaked", "credential"),
        ("look up AKIA1234567890ABCDEF", "credential"),
        ("what is my api key worth", "credential"),
        ("who owns ani96bob@gmail.com", "account_identifier"),
        ("whose number is 555-123-4567", "account_identifier"),
        ("is 123-45-6789 a valid ssn", "account_identifier"),
        ("check card 4111 1111 1111 1111", "account_identifier"),
        ("what is near 221 Baker Street", "precise_location"),
        ("what is at 47.6205, -122.3493", "precise_location"),
    ],
)
def test_secrets_and_identifiers_are_never_sent(policy, query, category):
    result = policy.sanitize(query)

    # No rewrite makes these safe, so nothing leaves the machine.
    assert result.allowed is False
    assert result.query == ""
    assert category in result.categories


@pytest.mark.parametrize(
    ("query", "topic", "category"),
    [
        ("what should i do about my psoriasis flare-up", "psoriasis", "medical"),
        ("how do i treat my child's asthma", "asthma", "medical"),
        ("is my mortgage rate competitive", "mortgage", "financial"),
        ("should i settle my lawsuit", "lawsuit", "legal"),
        ("my diabetes is getting worse", "diabetes", "medical"),
    ],
)
def test_personal_framing_is_minimized_not_blocked(policy, query, topic, category):
    result = policy.sanitize(query)

    # The topic is public; only attaching it to the user identified them, so
    # the subject survives while the personal framing does not.
    assert result.allowed is True
    assert topic in result.query.lower()
    assert category in result.categories
    assert result.was_rewritten is True
    possessives = {"my", "our", "my child's", "i"}
    assert not possessives & set(result.query.lower().split())


@pytest.mark.parametrize(
    "query",
    [
        "what is the latest python version",
        "who won the 2026 super bowl",
        "weather in Lisbon",
        "psoriasis treatment options",
        "current mortgage rates in the US",
    ],
)
def test_ordinary_queries_pass_through_unchanged(policy, query):
    result = policy.sanitize(query)

    assert result.allowed is True
    assert result.query == query
    assert result.was_rewritten is False
    assert result.categories == ()


def test_empty_query_is_refused(policy):
    result = policy.sanitize("   ")

    assert result.allowed is False
    assert result.categories == ("empty",)


def test_minimization_removes_the_identifying_part(policy):
    # What leaves the machine is the public topic, never the user's framing.
    result = policy.sanitize("my symptoms")

    assert result.allowed is True
    assert result.query == "symptoms"
    assert "medical" in result.categories


def test_a_secret_outranks_an_otherwise_minimizable_query(policy):
    result = policy.sanitize("my diagnosis and my password is hunter2")

    # The credential decides the outcome regardless of the rest.
    assert result.allowed is False
    assert "credential" in result.categories
