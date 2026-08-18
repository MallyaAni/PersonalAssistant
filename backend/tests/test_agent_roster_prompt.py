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
