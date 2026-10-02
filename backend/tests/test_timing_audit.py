"""Keep archived timing diagnostics causal, separated and honest about missingness."""

from copy import deepcopy

import pytest

from backend.market.timing_audit import audit


# Supply two retained stock observations and a final-session latch with a later trigger.
def fixture():
    return {
        "schema": "recorded-timing-audit/1",
        "price_basis": "raw",
        "opening_evidence": "recorded_only",
        "data_as_of": "2026-09-28T21:00:00Z",
        "records": [
            {
                "as_of": "2026-09-28T14:00:10Z",
                "bar": "2026-09-28T13:45:00Z",
                "valid_until": "2026-09-28T14:15:00Z",
                "version": "original/1",
                "policy_sha256": "a" * 64,
                "source_sha256": "b" * 64,
                "grades": {"AAA": {"grade_live": "A"}, "BBB": {"grade_live": "B"}},
                "nightly_grades": {"AAA": {"grade": "A"}},
                "prices": {"AAA": 106, "BBB": 100},
            }
        ],
        "latches": {
            "2026-09-28": {
                "session": "2026-09-28",
                "symbols": {
                    "AAA": {
                        "open": 100,
                        "open_seen_at": "2026-09-28T13:45:00Z",
                        "first_bar": {"bar": "2026-09-28T13:30:00Z"},
                        "buy_trigger": {
                            "bar": "2026-09-28T15:00:00Z",
                            "seen_at": "2026-09-28T15:15:10Z",
                            "price": 98,
                        },
                    }
                },
            }
        },
    }


# A final latch cannot create a historical trigger before it was published.
def test_final_latch_does_not_leak_into_prefix_and_missing_stock_is_retained():
    result = audit(fixture())
    assert result["coverage"]["observations"] == 2
    assert result["coverage"]["statuses"] == {
        "prefix_indeterminate": 1,
        "missing_latch": 1,
    }
    assert "buy_state" not in result["rows"][0]
    group = next(iter(result["policy_groups"].values()))
    assert group["triggered_buy_observations"] == 0


# Measure price recovery without treating a permission as profit or a fill.
def test_observed_recovery_is_measured_and_input_is_not_rewritten():
    payload = fixture()
    trigger = payload["latches"]["2026-09-28"]["symbols"]["AAA"]["buy_trigger"]
    trigger.update(bar="2026-09-28T13:30:00Z", seen_at="2026-09-28T13:45:10Z")
    original = deepcopy(payload)
    result = audit(payload)
    assert payload == original
    group = next(iter(result["policy_groups"].values()))
    assert group["eligible_grade_recovered_stock_sessions"] == 1
    assert group["maximum_recovery_bp"] == pytest.approx((106 / 99 - 1) * 10000)
    assert "profitability" in result["scope"]


# Keep original policy groups separate even when the stock and candle match.
def test_policy_groups_are_not_pooled_and_duplicates_are_rejected():
    payload = fixture()
    row = deepcopy(payload["records"][0])
    row["policy_sha256"] = "c" * 64
    payload["records"].append(row)
    assert len(audit(payload)["policy_groups"]) == 2
    payload["records"].append(deepcopy(row))
    with pytest.raises(ValueError, match="Duplicate"):
        audit(payload)


# Observations unavailable at the declared clock remain in the common denominator.
@pytest.mark.parametrize(
    ("field", "value", "status"),
    [
        ("as_of", "2026-09-28T13:40:00Z", "unavailable_at_publication"),
        ("valid_until", "2026-09-28T13:59:00Z", "unavailable_at_publication"),
        ("as_of", "2026-09-29T14:00:00Z", "after_data_as_of"),
    ],
)
def test_unavailable_observations_are_retained(field, value, status):
    payload = fixture()
    payload["records"][0][field] = value
    assert audit(payload)["coverage"]["statuses"] == {status: 2}


# Missing opening receipts require an explicit assumption for a conditional diagnostic.
def test_missing_opening_receipt_requires_an_explicit_assumption():
    payload = fixture()
    latch = payload["latches"]["2026-09-28"]["symbols"]["AAA"]
    latch["buy_trigger"] = None
    del latch["open_seen_at"]
    assert audit(payload)["rows"][0]["status"] == "opening_receipt_unrecorded"
    payload["opening_evidence"] = "assume_known_after_first_bar"
    assert audit(payload)["rows"][0]["status"] == "conditional_open"
    latch["first_bar"]["seen_at"] = "2026-09-28T16:00:00Z"
    assert audit(payload)["rows"][0]["status"] == "opening_not_observed"


# Stocks with missing marks still belong to the supplied observation denominator.
def test_grade_only_stock_is_not_silently_dropped():
    payload = fixture()
    payload["records"][0]["nightly_grades"]["CCC"] = {"grade": "A"}
    result = audit(payload)
    assert result["coverage"]["observations"] == 3
    assert {row["symbol"] for row in result["rows"]} == {"AAA", "BBB", "CCC"}


# Upgrading a legacy latch cannot prove a waiting state before revision capture began.
def test_partial_legacy_history_does_not_invent_a_waiting_prefix():
    payload = fixture()
    latch = payload["latches"]["2026-09-28"]["symbols"]["AAA"]
    latch["history_started_at"] = "2026-09-28T16:00:00Z"
    latch["buy_trigger_versions"] = [deepcopy(latch["buy_trigger"])]
    assert audit(payload)["rows"][0]["status"] == "prefix_indeterminate"
    latch["history_started_at"] = "2026-09-28T13:45:00Z"
    assert audit(payload)["rows"][0]["buy_state"] == "waiting"
