import pytest

from backend.memory.proposals import (
    propose_entity,
    propose_knowledge,
    propose_preferred_name,
    propose_procedure,
    propose_response_style,
)


# Verify preferred-name proposals only match explicit user statements.
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("My name is Ani.", "Ani"),
        ("My preferred name is Ani Mallya!", "Ani Mallya"),
        ("Please call me BrowserName123.", "BrowserName123"),
        ("What is my name?", None),
        ("My name is Ani, and I like tea.", "Ani"),
        ("My name is one two three four five six seven.", None),
        ("My name is <script>.", None),
    ],
)
def test_propose_preferred_name_is_narrow_and_non_executing(query, expected):
    assert propose_preferred_name(query) == expected


# Verify response-style proposals only match explicit user preferences.
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Please be concise.", "concise"),
        ("I prefer responses to be detailed.", "detailed"),
        ("Keep your responses concise", "concise"),
        ("Can you explain what concise means?", None),
        ("Summarize this concisely", None),
    ],
)
def test_propose_response_style_is_narrow_and_non_executing(query, expected):
    assert propose_response_style(query) == expected


# Verify explicit relationship statements become non-persisted entity proposals.
def test_propose_entity_requires_explicit_remember_language() -> None:
    assert propose_entity("Remember that Avery Chen is my dentist.") == {
        "entity_type": "person",
        "canonical_name": "Avery Chen",
        "attributes": {"relationship": "dentist"},
    }
    assert propose_entity("Avery Chen is my dentist.") is None


# Verify explicit workflows require at least two semicolon-delimited steps.
def test_propose_procedure_requires_a_reusable_multistep_workflow() -> None:
    assert propose_procedure(
        "Remember this workflow: Morning launch. "
        "Steps: Open dashboard; review alerts; start focus timer."
    ) == {
        "name": "Morning launch",
        "description": "User-approved workflow: Morning launch",
        "steps": [
            {"order": 1, "instruction": "Open dashboard"},
            {"order": 2, "instruction": "review alerts"},
            {"order": 3, "instruction": "start focus timer"},
        ],
    }
    assert propose_procedure("Remember procedure: One. Steps: only one") is None


# Verify explicitly titled reference text becomes a non-persisted proposal.
def test_propose_knowledge_requires_title_content_separator() -> None:
    assert propose_knowledge(
        "Remember this reference: Studio door code | The code is violet seven."
    ) == {
        "title": "Studio door code",
        "content": "The code is violet seven.",
    }
    assert propose_knowledge("Remember that the code is violet seven.") is None
