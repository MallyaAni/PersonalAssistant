"""The real economist judges inflation evidence without claiming trading authority."""

import pytest

from backend.agents.trading.desk.economist import assess


# Interpret broad agreement using the supplied measurements.
@pytest.mark.parametrize(
    ("current", "previous", "expected"), [(2.5, 4.0, "easing"), (5.0, 3.0, "building")]
)
def test_inflation_direction_uses_supplied_evidence(
    structured_llm, current, previous, expected
):
    facts = [
        {
            "id": key,
            "label": key,
            "status": "available",
            "period": "2026-08-01",
            "year_change_pct": current,
            "previous_year_change_pct": previous,
            "month_change_pct": 0.1 if expected == "easing" else 0.8,
        }
        for key in ("CPI", "CORE_CPI", "PCE", "CORE_PCE", "PPI")
    ]
    result = assess(facts, structured_llm)
    assert result["status"] == "model_assessment", result
    assert result["pressure"] == expected, result
    assert len(result["evidence_ids"]) >= 2, result


# Missing and stale series cannot be interpreted as evidence that risk has disappeared.
def test_missing_economic_evidence_is_unknown(structured_llm):
    result = assess(
        [{"id": "CPI", "status": "stale"}, {"id": "PCE", "status": "missing"}],
        structured_llm,
    )
    assert result["status"] == "model_assessment", result
    assert result["pressure"] == "unknown", result
    assert result["evidence_ids"] == []
