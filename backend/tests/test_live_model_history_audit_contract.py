"""Independent full-account evidence must preserve exact cohort and order receipts."""

import gzip
import json
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from types import SimpleNamespace

import pytest

from backend.cli import verify_live_model_history as verifier
from backend.market import live_model_history_projection as projection
from backend.market.grade_led_policy import POLICY
from backend.tests.test_live_model_history_verification import receipts


# Reject an oversized attempted request even when its fill remains under the intent.
def test_attempt_quantity_cannot_exceed_original_funded_intent():
    value, intents = receipts()
    value["attempts"][0]["qty"] = 99
    with pytest.raises(ValueError, match="attempt|Attempt|funded"):
        verifier.order_receipts(value, intents, {})


# Preserve every original durable identity rather than accepting an empty saved state.
def test_known_intent_cannot_disappear_from_pending_and_journal():
    value, intents = receipts()
    value["attempts"] = []
    value["fills"] = []
    value["paper_state"] = {"pending": [], "journal": []}
    with pytest.raises(ValueError, match="durable|Durable|missing|Missing"):
        verifier.order_receipts(value, intents, {})


# An exact-sized but substituted cohort cannot inherit an independent account proof.
def test_projection_rejects_same_count_substituted_untraded_stock(tmp_path):
    tickers = [f"TEST{index:02}" for index in range(94)]
    changed = [*tickers[:-1], "ROGUE"]
    account = {
        "policy": POLICY,
        "real_orders": False,
        "basis": "fixed_current_models_applied_retrospectively",
        "base_models_fitted": 0,
        "cost_bps": 10,
        "first": "2019-03-01",
        "through": "2026-10-12",
        "sessions": [],
        "grade_overlay": {"histories": dict.fromkeys(changed, "a" * 64)},
        "original_holding_publication": "2026-10-04T18:35:30-04:00",
        "original_holding_fit_date": "2026-10-01",
        "source_sha256": {},
        **dict.fromkeys(
            (
                "holding_config_sha256",
                "timing_config_sha256",
                "model_receipt_sha256",
                "risk_receipt_sha256",
                "timing_model_receipt_sha256",
                "timing_residual_receipt_sha256",
                "capture_sha256",
            ),
            "a" * 64,
        ),
    }
    raw = json.dumps(account).encode()
    (tmp_path / "completion.json").write_bytes(raw)
    (tmp_path / "initial.json.gz").write_bytes(
        gzip.compress(
            json.dumps(
                {
                    "nightly": {
                        "status": "unavailable",
                        "session": "2019-02-28",
                    },
                    "intents": [],
                }
            ).encode()
        )
    )
    proof = {
        "status": "VERIFIED_CURRENT_MODEL_HISTORICAL_ACCOUNT",
        "account_sha256": sha256(raw).hexdigest(),
        "filled_receipts": 0,
        "verified_tickers": tickers,
        "grade_overlay_content_sha256": projection.overlay_digest(
            {"histories": dict.fromkeys(tickers, "a" * 64)}
        ),
    }
    with pytest.raises(ValueError, match="cohort|Cohort"):
        projection.project(tmp_path, proof)


# Bind the entire overlay and every untraded history digest to the source cohort.
@pytest.mark.parametrize("change", [None, "substitute", "digest", "metadata", "omit"])
def test_completion_cohort_matches_authenticated_frozen_overlay(change):
    tickers = [f"TEST{index:02}" for index in range(94)]
    overlay = {"asof": "2026-10-12", "histories": dict.fromkeys(tickers, "a" * 64)}
    completion = {"grade_overlay": deepcopy(overlay)}
    if change == "substitute":
        completion["grade_overlay"]["histories"]["ROGUE"] = completion["grade_overlay"][
            "histories"
        ].pop(tickers[-1])
    elif change == "digest":
        completion["grade_overlay"]["histories"][tickers[-1]] = "b" * 64
    elif change == "metadata":
        completion["grade_overlay"]["asof"] = "2026-10-11"
    elif change == "omit":
        completion["grade_overlay"]["histories"].pop(tickers[-1])
    panel = SimpleNamespace(tickers=tuple([*tickers, "SPY", "QQQ"]))
    before = deepcopy(overlay)
    if change is None:
        assert verifier.complete_cohort(completion, overlay, panel) == tickers
    else:
        with pytest.raises(ValueError, match="overlay"):
            verifier.complete_cohort(completion, overlay, panel)
    assert overlay == before


# Correct stock counts alone cannot admit a mismatch with the frozen model bank.
def test_authenticated_overlay_still_requires_the_exact_model_cohort():
    overlay = {
        "histories": dict.fromkeys([f"TEST{index:02}" for index in range(94)], "a" * 64)
    }
    panel = SimpleNamespace(
        tickers=tuple([*overlay["histories"], "UNREVIEWED", "SPY", "QQQ"])
    )
    with pytest.raises(ValueError, match="cohort"):
        verifier.complete_cohort({"grade_overlay": overlay}, overlay, panel)


# Check submissions against the completed raw close rather than their future fill open.
def test_attempt_uses_original_completed_raw_close(tmp_path, monkeypatch):
    start = datetime.fromisoformat("2021-01-05T09:30:00-05:00")
    found = (
        [SimpleNamespace(start=start, open=100, close=99)],
        None,
        {"complete": "true"},
    )
    monkeypatch.setattr(verifier.intraday_sip, "read_session_full", lambda *_: found)
    attempt = {
        "symbol": "AAA",
        "at": "2021-01-05T09:45:00-05:00",
        "observed_price": 99,
        "reason": None,
    }
    assert verifier.physical_attempt(tmp_path, attempt, None, None)
    with pytest.raises(ValueError, match="observed raw"):
        verifier.physical_attempt(
            tmp_path, {**attempt, "observed_price": 100}, None, None
        )


# A zero receipt must preserve whether the exact original execution price was absent.
@pytest.mark.parametrize("present", [True, False])
def test_zero_execution_refusal_matches_original_raw_bar(
    tmp_path, monkeypatch, present
):
    at = datetime.fromisoformat("2021-01-05T09:45:00-05:00")
    found = (
        ([SimpleNamespace(start=at, open=100)], None, {"complete": "true"})
        if present
        else None
    )
    monkeypatch.setattr(verifier.intraday_sip, "read_session_full", lambda *_: found)
    fill = {
        "symbol": "AAA",
        "at": at.isoformat(),
        "filled_qty": 0,
        "price": None,
        "fee": 0,
        "reason": "partial_cash_or_coverage" if present else "missing_execution_price",
    }
    assert verifier.physical_fill(tmp_path, fill, 10) is False
    changed = {
        **fill,
        "reason": "missing_execution_price" if present else "partial_cash_or_coverage",
    }
    with pytest.raises(ValueError, match="missing-price"):
        verifier.physical_fill(tmp_path, changed, 10)
