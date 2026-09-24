"""Pin scored-versus-context meaning without changing analyst decisions."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import fundamental, grading, plainly, sentiment
from backend.agents.trading.desk.opinions import Opinion
from backend.market import challenger


# The explanation registry must include the active nontechnical scoring inputs.
def test_explanations_cover_active_growth_tone_and_augmented_value_inputs():
    assert plainly.SCORED_BY_ANALYST["fundamental"] == fundamental.SCORED
    assert plainly.SCORED_BY_ANALYST["sentiment"] == sentiment.SCORED
    assert "price_sales" in plainly.SCORED_BY_ANALYST["value"]
    assert "expectations_gap" in plainly.SCORED_BY_ANALYST["value"]
    assert "price_book" not in plainly.SCORED_BY_ANALYST["value"]


# Correlated context cannot remove a scored reading before attribution is chosen.
@pytest.mark.parametrize(
    ("analyst", "scored", "context"),
    [
        ("fundamental", "revenue_yoy", "net_margin"),
        ("sentiment", "tone_demand", "tone_capex"),
        ("value", "expectations_gap", "price_book"),
    ],
)
def test_scored_reading_precedes_context_that_happens_to_agree_with_vote(
    analyst, scored, context
):
    cited = {scored: -2.0, context: 8.0}
    scale = {
        (analyst, scored): (0.0, 1.0, 1),
        (analyst, context): (0.0, 1.0, 1),
    }
    picked = plainly._notable(analyst, cited, scale, stance=1)
    assert [name for name, _value in picked] == [scored]


# A fallback reading must not masquerade as a direct score contribution.
@pytest.mark.parametrize(
    ("analyst", "context"),
    [
        ("fundamental", "net_margin"),
        ("sentiment", "tone_capex"),
        ("value", "price_book"),
    ],
)
def test_context_only_reason_is_explicitly_not_scored(analyst, context):
    text = plainly._clause(analyst, 1, 0.9, {context: 1.0})
    assert "context" in text.lower()
    assert "not scored" in text.lower()
    assert "by this analyst" in text.lower()


# Full evidence may retain unscored measurements only with their role made explicit.
@pytest.mark.parametrize(
    ("analyst", "scored", "context"),
    [
        ("fundamental", "revenue_yoy", "net_margin"),
        ("sentiment", "tone_demand", "tone_capex"),
        ("value", "expectations_gap", "price_book"),
    ],
)
def test_full_nontechnical_readings_distinguish_scored_and_context(
    analyst, scored, context
):
    view = {"evidence": {analyst: {scored: 1.0, context: 1.0}}}
    lines = plainly.reads(view)[analyst]
    assert len(lines) == 2
    assert "not scored" not in lines[0].lower()
    assert "context" in lines[1].lower()
    assert "not scored" in lines[1].lower()
    assert "by this analyst" in lines[1].lower()


# The growth gap is named as a proxy difference, not intrinsic cheapness or consensus.
def test_growth_gap_label_does_not_claim_fair_value_or_market_expectations():
    text = plainly._figure("value", "expectations_gap", 0.5, None).lower()
    assert "revenue growth" in text
    assert "valuation proxy" in text
    assert "cheapness" not in text
    assert "price-implied" not in text
    assert "consensus" not in text


# Missing peer distributions cannot turn a value's sign into a relative rank.
@pytest.mark.parametrize("value", [-0.5, 0.0, 0.5])
@pytest.mark.parametrize(
    ("analyst", "measure"),
    [("fundamental", "revenue_yoy"), ("value", "expectations_gap")],
)
def test_missing_comparison_is_not_reported_as_high_or_low_in_book(
    analyst, measure, value
):
    text = plainly._figure(analyst, measure, value, None).lower()
    assert "comparison unavailable" in text
    assert "high in book" not in text
    assert "low in book" not in text


# Corrected financial fields need ordinary names even when they are contextual.
def test_every_corrected_fundamental_field_has_an_english_name():
    assert set(fundamental.CITED_CORRECTED) <= plainly.LABELS.keys()
    text = plainly.reads({"evidence": {"fundamental": {"ocf_to_revenue": 0.2}}})
    line = text["fundamental"][0]
    assert "operating cash flow" in line
    assert "not scored by this analyst" in line
    assert "ocf_to_revenue" not in line


# Missing growth forecasts preserve plain Value and never invent a gap explanation.
def test_missing_gap_keeps_plain_value_and_does_not_get_cited():
    scores = np.tile(np.linspace(0.1, 0.9, 8), (4, 1))
    plain = Opinion("value", scores, {"price_sales": -scores, "price_book": scores})
    blended = challenger.with_gap({"value": plain}, np.full_like(scores, np.nan))[
        "value"
    ]
    np.testing.assert_array_equal(blended.ranks(), plain.ranks())
    np.testing.assert_array_equal(blended.stances(), plain.stances())
    view = {"stances": {"value": 1}, "evidence": {"value": blended.cite(3, 7)}}
    assert "expectations_gap" not in view["evidence"]["value"]
    assert "valuation proxy" not in plainly.reason(view)
    assert "valuation proxy" not in " ".join(plainly.reads(view)["value"])


# Rendering reasons and full readings cannot mutate scores, evidence, votes or grades.
def test_explanatory_rendering_preserves_augmented_analyst_decisions():
    base = np.tile(np.linspace(0.1, 0.9, 8), (4, 1))
    base[-1] = base[-1, ::-1]
    opinions = {
        "fundamental": Opinion(
            "fundamental",
            base.copy(),
            {"revenue_yoy": base.copy(), "net_margin": -base.copy()},
        ),
        "technical": Opinion(
            "technical", base.copy(), {"weekly_trend": np.ones_like(base)}
        ),
        "sentiment": Opinion(
            "sentiment",
            base.copy(),
            {"tone_demand": np.ones_like(base), "tone_capex": -np.ones_like(base)},
        ),
        "value": Opinion(
            "value",
            base.copy(),
            {"price_sales": -base.copy(), "price_book": base.copy()},
        ),
    }
    augmented = challenger.with_gap(opinions, base.copy())
    saved = deepcopy(augmented)
    before = grading.grade(
        augmented["fundamental"],
        augmented["technical"],
        augmented["sentiment"],
        value=augmented["value"],
    )
    assert augmented["value"].ranks()[3, 7] < 0.3
    assert before.stances["value"][3, 7] == 1
    report = SimpleNamespace(
        panel=SimpleNamespace(
            dates=np.arange(4), tickers=tuple(f"N{i}" for i in range(8))
        ),
        sides={f"N{i}": "ai" for i in range(8)},
        opinions=augmented,
    )
    scale = plainly.spreads(report)
    for column in range(8):
        view = {
            "grade": before.letter(3, column),
            "stances": {
                name: int(values[3, column]) for name, values in before.stances.items()
            },
            "ranks": {
                name: float(opinion.ranks()[3, column])
                for name, opinion in augmented.items()
            },
            "evidence": {
                name: opinion.cite(3, column) for name, opinion in augmented.items()
            },
        }
        original = deepcopy(view)
        assert plainly.reason(view, scale)
        assert plainly.reads(view, scale)
        assert view == original
    for name, opinion in augmented.items():
        np.testing.assert_array_equal(opinion.scores, saved[name].scores)
        assert opinion.meta == saved[name].meta
        assert opinion.evidence.keys() == saved[name].evidence.keys()
        for key, values in opinion.evidence.items():
            np.testing.assert_array_equal(values, saved[name].evidence[key])
    after = grading.grade(
        augmented["fundamental"],
        augmented["technical"],
        augmented["sentiment"],
        value=augmented["value"],
    )
    np.testing.assert_array_equal(after.grades, before.grades)
    np.testing.assert_array_equal(after.votes, before.votes)
    np.testing.assert_array_equal(after.conviction, before.conviction)
    for name in before.stances:
        np.testing.assert_array_equal(after.stances[name], before.stances[name])
