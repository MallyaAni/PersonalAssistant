"""When the roster states an agent's requirements, and when it stays quiet.

Both directions were live defects. Listed unconditionally, an account with
seven interests, a locality and a subscriber was asked for all three again in
the same breath as the line reporting it had them. Hidden on any status but
`needs_setup`, an entry that carried no status lost its requirements entirely
and the assistant improvised inputs for a feature the user already owns.
"""

from backend.agents.graph import _render_agent_context


def _scout(**overrides: str) -> dict[str, str]:
    agent = {
        "name": "Scout",
        "role": "Finds things happening near you",
        "setup_needs": "interests, a home locality, and a cadence",
    }
    agent.update(overrides)
    return agent


def test_requirements_are_stated_while_setup_is_outstanding():
    rendered = _render_agent_context([_scout(status="needs_setup")])

    assert "still needs interests, a home locality, and a cadence" in rendered


def test_requirements_are_stated_when_the_state_is_unknown():
    # No status at all: the renderer knows nothing about this agent's state, so
    # it must not imply the agent is ready by omitting what it takes to run.
    rendered = _render_agent_context([_scout()])

    assert "needs interests, a home locality, and a cadence" in rendered


def test_a_running_agent_is_not_asked_for_what_it_already_has():
    for status in ("idle", "working", "scheduled"):
        rendered = _render_agent_context([_scout(status=status)])

        assert "needs" not in rendered, status
        assert f"right now: {status}" in rendered


def test_an_agent_with_no_requirements_never_renders_an_empty_ask():
    rendered = _render_agent_context([_scout(setup_needs="")])

    assert "needs" not in rendered
    assert "Scout" in rendered


# Asked "what are my interests?", the assistant answered "I don't actually have
# a list of your interests" and in the same reply reported that Scout tracks
# ten of them. It had the count and no way to read the labels, so the honest
# answer was also a useless one.
def test_the_agents_line_names_the_interests_it_follows():
    from backend.agents.scout.card import _following

    detail = _following(["Books", "Theater", "Horses"])

    assert "Following: Books, Theater, Horses." == detail.strip()


# This reaches every reply's prompt, so it is bounded: enough to answer with,
# not the whole table.
def test_a_long_list_is_summarised_rather_than_dumped():
    from backend.agents.scout.card import _NAMED_INTERESTS, _following

    detail = _following([f"interest {n}" for n in range(_NAMED_INTERESTS + 5)])

    assert "and 5 more" in detail
    assert detail.count(",") <= _NAMED_INTERESTS


def test_no_interests_adds_nothing_to_the_line():
    from backend.agents.scout.card import _following

    assert _following([]) == ""
