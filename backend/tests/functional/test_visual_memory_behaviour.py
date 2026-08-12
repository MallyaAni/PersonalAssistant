"""Measure whether the real local model understands visual-memory relevance."""

import pytest

from backend.agents.vision.memory import VisualMemorySelector

pytestmark = pytest.mark.asyncio


# A personal-style question should find the owned portrait without image keywords.
async def test_style_question_selects_the_relevant_portrait(llm: object) -> None:
    selected = await VisualMemorySelector(llm).select(
        "what do you think of my style?",
        [
            {
                "content": "A person wearing a tailored navy jacket and a straw hat.",
                "extra_data": {"artifact_id": "portrait"},
            },
            {
                "content": "A red bicycle leaning against a brick wall.",
                "extra_data": {"artifact_id": "bicycle"},
            },
        ],
    )

    assert selected == ("portrait",)


# Unrelated conversation must not pull private pictures into the model prompt.
async def test_unrelated_question_selects_no_visual_memory(llm: object) -> None:
    selected = await VisualMemorySelector(llm).select(
        "explain how a binary search works",
        [
            {
                "content": "A person wearing a tailored navy jacket and a straw hat.",
                "extra_data": {"artifact_id": "portrait"},
            }
        ],
    )

    assert selected == ()
