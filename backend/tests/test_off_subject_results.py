"""Results about a different subject become a disclosure, not an answer."""

from __future__ import annotations

import json

from backend.agents.graph import _render_search_state
from backend.core.result_ranking import Ranking, _parse_flag


def test_the_flag_defaults_to_on_subject_when_missing_or_unreadable():
    assert _parse_flag({"content": json.dumps({"order": [1], "events": False, "travel": False})}, "on_subject", default=True) is True
    assert _parse_flag({"content": "not json"}, "on_subject", default=True) is True
    assert _parse_flag({"content": json.dumps({"on_subject": False})}, "on_subject", default=True) is False
    assert Ranking(None).on_subject is True


def test_off_subject_state_is_a_disclosure_and_forbids_the_facts():
    text = _render_search_state({"ran": True, "off_subject": True})
    assert "different subject" in text and "from memory, not checked" in text
    assert "Never present those results' facts" in text
    ran = _render_search_state({"ran": True})
    assert "different subject" not in ran and "lead with what was found" in ran
