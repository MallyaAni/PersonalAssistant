"""Eight fixed property tests against the real runtime, not a mocked LLM."""

import os
from pathlib import Path

import pytest

from backend.agents.trading.grounded_release_cases import CASES
from backend.cli.market_grounded_release import evaluate, write_report
from backend.core.llm import OpenAICompatibleInferenceProvider


# Run one bounded batch and optionally archive every actual answer, even on failure.
@pytest.fixture(scope="module")
def pilot():
    url = os.environ.get("GROUNDED_RELEASE_URL")
    model = os.environ.get("GROUNDED_RELEASE_MODEL")
    if not url or not model:
        pytest.skip(
            "Set GROUNDED_RELEASE_URL and GROUNDED_RELEASE_MODEL for the real pilot"
        )
    output = os.environ.get("GROUNDED_RELEASE_REPORT")
    if output and Path(output).exists():
        pytest.fail("Refusing to overwrite an existing pilot report")
    client = OpenAICompatibleInferenceProvider(
        url, model, timeout_seconds=120, reasoning_effort=""
    )
    report = evaluate(client, model)
    if output:
        write_report(Path(output), report)
    return report


# Match the preregistered meaning and prove every asserted feature has a source span.
@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_release_feature_meaning_and_grounding(pilot, case):
    row = next(row for row in pilot["cases"] if row["id"] == case["id"])
    assert row["passed"], row
    assert row["observed"] == case["expected"]
    for feature in row["result"]["features"].values():
        if feature["value"] != "not_stated":
            assert case["text"][feature["start"] : feature["end"]] == feature["quote"]
    assert row["result"]["usable_after"] >= row["result"]["extracted_at"]
