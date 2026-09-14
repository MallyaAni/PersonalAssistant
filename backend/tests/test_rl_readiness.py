"""The RL audit counts independent dates and does not invent historical states."""

from backend.market import rl_readiness
from backend.tests.test_forward_evidence import observations
from backend.tests.test_recommendation_history import archive


# Many symbols or changed policies do not manufacture more independent trading days.
def test_audit_preserves_missing_state_and_counts_dates(tmp_path):
    rows = observations()
    rows[0]["learning_state"] = {"schema": "desk-state/1"}
    rows.append({**rows[0], "policy_sha256": "other-policy"})
    archive(tmp_path, rows)
    result = rl_readiness.report(tmp_path)
    assert result["observations"] == 4
    assert result["distinct_market_sessions"] == 2  # Two candles share September 14.
    assert result["state_snapshots"] == 2
    assert result["missing_state_snapshots"] == 2
    assert result["quote_feeds"] == {"missing": 4}
    assert result["status"] == "research_only_not_training_approved"
