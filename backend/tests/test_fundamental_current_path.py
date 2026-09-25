"""The versioned reporting-period policy reaches votes and saved evidence."""

import json
from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from backend.agents.trading.desk import desk, fundamental, grading
from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_daily, market_desk
from backend.market import fundamental_features as ff
from backend.market import fundamentals_asof as fa
from backend.market.store import MarketStore
from backend.tests.test_fundamental_period_eligibility import (
    ALTERNATIVE,
    _history,
    _panel,
    _version,
)
from backend.tests.test_market_daily import _report

DAYS = (
    "2026-04-27",
    "2026-04-28",
    "2026-04-29",
    "2026-05-04",
    "2026-05-05",
    "2026-05-06",
)


# Supply the second scored company required for cross-sectional ranks.
def _inputs(versions):
    peer = [replace(v, value=100.0 if v.name == "revenue" else 5.0) for v in _history()]
    return {"TEST": versions, "PEER": peer}


# Keep the two stock columns separate from the unscored benchmark.
def _score_panel(days=DAYS):
    return _panel(days, tickers=("TEST", "PEER", "SPY"))


# Keep technical votes fixed to isolate the grade effect of a changed F vote.
def _graded(opinion):
    shape = opinion.scores.shape
    technical = Opinion("technical", np.tile([1.0, 0.0, np.nan], (shape[0], 1)))
    sentiment = Opinion("sentiment", np.full(shape, np.nan))
    return grading.grade(opinion, technical, sentiment)


# Losing one scored margin resets a vote even with three valid growth legs left.
def test_rejected_scored_leg_resets_finite_score_vote_and_grade():
    versions = _history() + [
        _version("revenue", "2026-01-01", "2026-03-31", 150.0, filed="2026-05-01")
    ]
    features = ff.current_features(_score_panel(), _inputs(versions))
    opinion = fundamental.opine_current(features)
    assert np.isfinite(opinion.scores[:, 0]).all()
    assert opinion.stance_resets[:, 0].tolist() == [
        False,
        False,
        False,
        True,
        False,
        False,
    ]
    assert opinion.stances()[:, 0].tolist() == [1, 1, 1, 0, 0, 1]
    assert [_graded(opinion).letter(t, 0) for t in range(6)] == [
        "A",
        "A",
        "A",
        "B",
        "B",
        "A",
    ]
    assert np.isnan(opinion.evidence["gross_margin"][3:, 0]).all()
    assert opinion.meta["source"] == "fundamentals-features/3"
    # This remains a deliberate behavior difference from the previous source.
    previous = fundamental.opine_corrected(
        ff.features(_score_panel(), _inputs(versions))
    )
    assert previous.stances()[:, 0].tolist() == [1] * 6


# Newer revenue evidence invalidates old metrics without borrowing its amounts.
def test_unscored_name_immediately_has_no_fundamental_vote():
    versions = _history() + [
        _version(
            "revenue",
            "2026-01-01",
            "2026-03-31",
            150.0,
            filed="2026-05-01",
            tag=ALTERNATIVE,
        )
    ]
    current = fundamental.opine_current(
        ff.current_features(_score_panel(), _inputs(versions))
    )
    assert np.isnan(current.scores[3:, 0]).all()
    assert current.stances()[:, 0].tolist() == [1, 1, 1, 0, 0, 0]
    assert current.stance_resets[:, 0].tolist() == [
        False,
        False,
        False,
        True,
        True,
        True,
    ]
    assert [_graded(current).letter(t, 0) for t in range(6)] == [
        "A",
        "A",
        "A",
        "B",
        "B",
        "B",
    ]


# Losing a cited-only margin does not reset a vote with four eligible scored legs.
def test_cited_only_rejection_does_not_reset_a_valid_score():
    versions = _history() + [
        _version("revenue", "2026-01-01", "2026-03-31", 150.0, filed="2026-05-01"),
        _version("gross_profit", "2026-01-01", "2026-03-31", 45.0, filed="2026-05-01"),
    ]
    current = fundamental.opine_current(
        ff.current_features(_score_panel(), _inputs(versions))
    )
    assert np.isnan(current.evidence["net_margin"][3:, 0]).all()
    assert not current.stance_resets[:, 0].any()
    assert current.stances()[:, 0].tolist() == [1] * 6


# Refuse unchecked features rather than label them as period-checked inputs.
def test_current_analyst_requires_reporting_period_evidence():
    features = ff.features(_panel(), {"TEST": _history()})
    with pytest.raises(ValueError, match="eligibility"):
        fundamental.opine_current(features)


# Passing checks preserves ranking, evidence and ordinary persistence.
def test_accepted_features_preserve_scores_and_votes():
    panel = _score_panel()
    previous = fundamental.opine_corrected(ff.features(panel, _inputs(_history())))
    current = fundamental.opine_current(ff.current_features(panel, _inputs(_history())))
    np.testing.assert_array_equal(current.scores, previous.scores)
    np.testing.assert_array_equal(current.stances(), previous.stances())
    for key in previous.evidence:
        np.testing.assert_array_equal(current.evidence[key], previous.evidence[key])
    assert previous.meta["source"] == "fundamentals-features/2"
    assert previous.stance_resets is None


# A real store read selects the explicit policy without altering old /2 callers.
def test_store_to_desk_opinion_keeps_current_and_corrected_sources_separate(tmp_path):
    store = MarketStore(tmp_path)
    asof = date(2026, 5, 4)
    versions = _history() + [
        _version(
            "revenue",
            "2026-01-01",
            "2026-03-31",
            150.0,
            filed="2026-05-01",
            tag=ALTERNATIVE,
        )
    ]
    for ticker, values in _inputs(versions).items():
        store.write_frame(
            fa.KIND, asof, ticker, fa.frame(values), {"source": "synthetic"}
        )
    panel = _score_panel(("2026-05-04",))
    current = desk._fundamental_opinion(store, panel, asof, "current")
    previous = desk._fundamental_opinion(store, panel, asof, "corrected")
    assert np.isnan(current.scores[0, 0])
    assert current.stances()[0, 0] == 0
    assert np.isfinite(previous.scores[0, 0])
    assert (
        desk._fundamental_source_id("current")
        == current.meta["source"]
        == "fundamentals-features/3"
    )
    assert (
        desk._fundamental_source_id("corrected")
        == previous.meta["source"]
        == "fundamentals-features/2"
    )
    assert desk.run.__defaults__[-1] == "corrected"


# Preserve unscored names and rejected input dates through disk save and reload.
def test_nightly_record_preserves_unscored_names_and_original_periods(tmp_path):
    report = _report()
    versions = _history() + [
        _version(
            "revenue",
            "2026-01-01",
            "2026-03-31",
            150.0,
            filed="2026-05-01",
            tag=ALTERNATIVE,
        )
    ]
    opinion = fundamental.opine_current(
        ff.current_features(report.panel, {"SNDK": versions})
    )
    report = replace(
        report,
        opinions={fundamental.NAME: opinion},
        fundamentals_source="fundamentals-features/3",
    )
    data = market_daily.record(report)
    block = data["fundamental"]
    assert set(block["eligibility"]) == {"SNDK", "IREN"}
    assert set(block["dates"]) == {"SNDK", "IREN"}
    assert block["dates"]["SNDK"]["gross_margin"] == ""
    sndk = block["eligibility"]["SNDK"]
    assert sndk["revenue_period_end"] == "2026-03-31"
    assert sndk["score_available"] is False
    assert sndk["vote_reset"] is True
    assert sndk["features"]["gross_margin"] == {
        "status": "older_revenue_period",
        "input_period_end": "2025-12-31",
    }
    assert block["eligibility"]["IREN"]["features"]["gross_margin"] == {
        "status": "no_revenue_period",
        "input_period_end": "",
    }
    path = market_daily.save(tmp_path, data)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["fundamental"] == block
    assert saved["provenance"]["data"]["fundamentals"] == "fundamentals-features/3"


# A mismatched report must not publish a /3 label over another calculation's evidence.
def test_record_refuses_mismatched_current_source():
    report = _report()
    opinion = fundamental.opine_corrected(
        ff.features(report.panel, {"SNDK": _history()})
    )
    report = replace(
        report,
        opinions={fundamental.NAME: opinion},
        fundamentals_source="fundamentals-features/3",
    )
    with pytest.raises(ValueError, match="fundamental source"):
        market_daily.record(report)


# Expose the new CLI mode without changing its historical default.
def test_read_only_cli_accepts_current_mode_and_preserves_default():
    parser = market_desk.build_parser()
    assert parser.parse_args([]).fundamentals == "corrected"
    assert parser.parse_args(["--fundamentals", "current"]).fundamentals == "current"
