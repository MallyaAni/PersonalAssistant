import json
from pathlib import Path

import pytest

from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.models.memory import SemanticMemory

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "memory_retrieval_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_semantic_retrieval_quality_fixture(case):
    matches = []
    for index, distance in enumerate(case["distances"]):
        content = case["name"] if index == 0 else f"candidate {index}"
        matches.append(
            (
                SemanticMemory(
                    user_id="evaluation_user",
                    content=content,
                    embedding=[0.0] * 768,
                    extra_data={"fixture": case["name"]},
                ),
                distance,
            )
        )

    selected = SemanticRetrievalPolicy().select(matches, requested_results=20)

    assert [memory["content"] for memory in selected] == case["expected_contents"]
    assert all(memory["retrieval"]["cosine_distance"] <= 0.35 for memory in selected)


def test_semantic_retrieval_evaluation_fixture_covers_required_boundaries():
    names = {case["name"] for case in CASES}

    assert names == {
        "relevant exact match",
        "threshold edge included",
        "all irrelevant",
        "result count bounded",
    }
