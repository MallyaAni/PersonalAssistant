"""Delegation policies as a listable, ordered set rather than a chain of ifs."""

import os

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.agents.delegation import (
    DEFAULT_POLICIES,
    DelegationPolicy,
    DelegationRegistry,
)
from backend.agents.supervisor import MainSupervisorAgent


def _registry() -> DelegationRegistry:
    return DelegationRegistry(DEFAULT_POLICIES)


@pytest.mark.parametrize(
    "query",
    [
        "make me a presentation about electric cars",
        "build a slide deck for tomorrow",
        "can you put together a powerpoint",
        "generate slides on our roadmap",
    ],
)
def test_explicit_deck_requests_route_to_the_presentation_agent(query: str):
    matched = _registry().select(query)
    assert matched is not None
    assert matched.capability_id == "presentation_agent"


@pytest.mark.parametrize(
    "query",
    [
        "show me the deck",
        "what did the presentation say",
        "delete slide 3",
        "how many slides are there",
    ],
)
def test_talking_about_a_deck_is_not_asking_for_one(query: str):
    # Separating the noun from the verb is what keeps an ordinary question from
    # queueing a job the user did not ask for.
    assert _registry().select(query) is None


@pytest.mark.parametrize(
    "query",
    [
        "set up my weekly digest",
        "configure the events feed",
        "schedule the discovery sweep",
    ],
)
def test_configuring_discovery_routes_to_the_discovery_agent(query: str):
    matched = _registry().select(query)
    assert matched is not None
    assert matched.capability_id == "discovery_agent"


@pytest.mark.parametrize(
    "query",
    [
        "what's on this weekend",
        "any jazz gigs near me",
        "tell me about local events",
    ],
)
def test_asking_what_is_on_is_answered_rather_than_delegated(query: str):
    # A question about events is the assistant's job. Delegating it would send
    # the user to a configuration flow when they wanted an answer.
    assert _registry().select(query) is None


def test_the_highest_priority_policy_wins_a_tie():
    low = DelegationPolicy(
        id="low",
        capability_id="low_agent",
        reason="low",
        required=(__import__("re").compile("thing"),),
        priority=1,
    )
    high = DelegationPolicy(
        id="high",
        capability_id="high_agent",
        reason="high",
        required=(__import__("re").compile("thing"),),
        priority=9,
    )

    # Registration order must not decide the outcome.
    assert DelegationRegistry((low, high)).select("thing").capability_id == "high_agent"
    assert DelegationRegistry((high, low)).select("thing").capability_id == "high_agent"


def test_duplicate_policy_identifiers_are_refused():
    policy = DEFAULT_POLICIES[0]
    with pytest.raises(ValueError, match="unique"):
        DelegationRegistry((policy, policy))


def test_the_registry_can_be_listed():
    # Enumerability is the point: a set of rules that cannot be described is a
    # set of rules nobody can review.
    described = _registry().describe()
    assert {item["id"] for item in described} == {
        "presentation_creation",
        "discovery_configuration",
    }


@pytest.mark.asyncio
async def test_the_supervisor_routes_through_the_registry():
    agent = MainSupervisorAgent()

    delegated = await agent.decide("build me a deck about jazz")
    ordinary = await agent.decide("what is jazz")

    assert delegated.action == "delegate_agent"
    assert delegated.capability_id == "presentation_agent"
    assert delegated.reason == "explicit_presentation_creation"
    assert ordinary.action == "respond"
    assert ordinary.capability_id is None


@pytest.mark.asyncio
async def test_a_custom_registry_replaces_the_default_routing():
    import re

    registry = DelegationRegistry(
        (
            DelegationPolicy(
                id="only",
                capability_id="finance_agent",
                reason="explicit_budget_request",
                required=(re.compile(r"budget", re.IGNORECASE),),
            ),
        )
    )
    agent = MainSupervisorAgent(registry)

    routed = await agent.decide("review my budget")
    deck = await agent.decide("build me a deck")

    assert routed.capability_id == "finance_agent"
    # The default presentation policy is not present in this registry.
    assert deck.action == "respond"
