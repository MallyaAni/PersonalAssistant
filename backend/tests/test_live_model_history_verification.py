"""Independent historical audits retain original receipts and refuse hidden drift."""

import json
from copy import deepcopy

import numpy as np
import pytest

from backend.cli import verify_live_model_history as verifier


# Supply durable and attempted execution receipts for one original funded order.
def receipts():
    intent = {
        "client_order_id": "original-id",
        "symbol": "AAA",
        "side": "buy",
        "qty": 5,
    }
    value = {
        "attempts": [deepcopy(intent)],
        "fills": [{**intent, "filled_qty": 2}],
        "paper_state": {"pending": [deepcopy(intent)], "journal": [deepcopy(intent)]},
    }
    return value, {intent["client_order_id"]: intent}


# Accumulate partial receipts against the same original funded quantity.
def test_verifier_refuses_cumulative_overfill_and_changed_durable_receipts():
    value, intents = receipts()
    totals = {}
    verifier.order_receipts(value, intents, totals)
    verifier.order_receipts(value, intents, totals)
    assert totals == {"original-id": 4}
    with pytest.raises(ValueError, match="Cumulative"):
        verifier.order_receipts(value, intents, totals)
    for kind in ("pending", "journal"):
        changed = deepcopy(value)
        changed["paper_state"][kind][0]["qty"] = 6
        with pytest.raises(ValueError, match="funded intent"):
            verifier.order_receipts(changed, intents, {})
        changed = deepcopy(value)
        changed["paper_state"][kind].append(deepcopy(changed["paper_state"][kind][0]))
        with pytest.raises(ValueError, match="Duplicate"):
            verifier.order_receipts(changed, intents, {})


# Match old parity numbers while retaining the new independent verification clock.
def test_independent_parity_preserves_original_and_rejects_numeric_change(
    tmp_path, monkeypatch
):
    original = {
        "status": "verified",
        "targets": {"AAA": 0.1},
        "actual_verified_at": "old",
    }
    original_bytes = json.dumps(original).encode()
    path = tmp_path / "original.json"
    path.write_bytes(original_bytes)

    # Write only the caller's exclusive verification folder for this bounded harness.
    def produce(*args):
        (args[-1] / "installed-parity.json").write_text(
            json.dumps({**original, "actual_verified_at": "new"})
        )

    monkeypatch.setattr(verifier, "verify_installed_parity", produce)
    assert (
        len(
            verifier.independent_parity(
                None, None, None, None, None, original, tmp_path / "fresh"
            )
        )
        == 64
    )
    assert path.read_bytes() == original_bytes
    changed = deepcopy(original)
    changed["targets"]["AAA"] = 0.2
    with pytest.raises(ValueError, match="parity"):
        verifier.independent_parity(
            None, None, None, None, None, changed, tmp_path / "bad"
        )
    assert path.read_bytes() == original_bytes


# A missing held raw mark must remain unpriced rather than turning into a numeric NAV.
def test_independent_missing_mark_check_rejects_invented_nav():
    value = {
        "session": "2021-01-04",
        "nav": None,
        "price_nav": None,
        "status": "missing_held_close",
        "missing_symbols": ["AAA"],
    }
    data = {"names": ("AAA",), "close": np.array([[np.nan]]), "passive": None}
    records = {
        name: []
        for name in (
            "security_distributions",
            "share_consolidations",
            "security_exchanges",
            "cash_mergers",
        )
    }
    args = (
        data,
        0,
        verifier.ledger.aware("2021-01-04T16:01:00-05:00"),
        10,
        {"AAA": 2},
        [],
        records,
    )
    assert verifier.ledger.check_valuation(value, *args) == (1, 0)
    with pytest.raises(ValueError, match="Missing held NAV"):
        verifier.ledger.check_valuation({**value, "nav": 10}, *args)
