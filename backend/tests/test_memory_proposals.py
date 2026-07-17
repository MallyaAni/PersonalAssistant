import pytest

from backend.memory.proposals import propose_preferred_name


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
