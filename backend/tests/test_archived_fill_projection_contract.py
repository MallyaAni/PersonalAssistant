"""Archived fill projections retain original identities, multiplicity and actual prices."""

import json
from copy import deepcopy

import pytest

from backend.agents.trading.desk import decision_history
from backend.market import deskrecord


# Write an ordinary original desk record without invoking planners or account clients.
def write_record(root, session, rows):
    folder = deskrecord.folder(root, session)
    folder.mkdir(parents=True)
    path = folder / "desk.json"
    raw = json.dumps(
        {"session": session, "paper": {"settled": rows}}, indent=2, allow_nan=False
    ).encode()
    path.write_bytes(raw)
    return path, raw


# Supply an actual recorded aggregate fill with its original precise price and timestamp.
def fill(identity, *, quantity=2, price=101.123456789):
    return {
        "client_order_id": identity,
        "symbol": "AAA",
        "side": "buy",
        "qty": 8,
        "filled": quantity,
        "filled_price": price,
        "status": "partial",
        "terminal": True,
        "kind": "redeploy",
        "completion_session": "2026-10-14",
        "execution": {"filled_at": "2026-10-14T13:31:00.123456789Z"},
    }


# Two distinct original orders remain distinct even when every displayed trade value matches.
def test_original_ids_preserve_same_tuple_fill_multiplicity_and_full_price(tmp_path):
    identities = ["anios-2026-10-13-buy-aaa-7", "anios-2026-10-13-buy-aaa-8"]
    rows = [fill(identity) for identity in identities]
    before = deepcopy(rows)
    path, raw = write_record(tmp_path, "2026-10-15", rows)
    actual = decision_history.fills(tmp_path, "AAA")
    assert len(actual) == 2
    assert [row["client_order_id"] for row in actual] == identities
    for row in actual:
        assert row["price"] == rows[0]["filled_price"]
        assert row["price"] != round(rows[0]["filled_price"], 4)
        assert row["qty"] == 2
        assert row["date"] == "2026-10-14"
        assert row["filled_at"] == rows[0]["execution"]["filled_at"]
        assert row["kind"] == "redeploy"
    assert rows == before
    assert path.read_bytes() == raw


# A later receipt replaces the same original order's aggregate instead of summing partials.
def test_later_same_id_uses_original_terminal_quantity_price_and_clock(tmp_path):
    identity = "anios-2026-10-13-buy-aaa-7"
    first = fill(identity)
    first["terminal"] = False
    final = fill(identity, quantity=5, price=102.987654321)
    final["execution"]["filled_at"] = "2026-10-14T15:45:00.987654321Z"
    originals = [
        write_record(tmp_path, "2026-10-14", [first]),
        write_record(tmp_path, "2026-10-15", [final]),
    ]
    assert decision_history.fills(tmp_path, "AAA") == [{
        "date": "2026-10-14",
        "side": "buy",
        "qty": 5,
        "price": final["filled_price"],
        "client_order_id": identity,
        "kind": "redeploy",
        "filled_at": final["execution"]["filled_at"],
    }]
    for path, raw in originals:
        assert path.read_bytes() == raw


# Missing or nonstring IDs stay unknown and cannot collide with an original string identity.
@pytest.mark.parametrize("unknown", [None, "", 7, False])
def test_legacy_unknown_identity_is_not_invented_or_coerced(tmp_path, unknown):
    rows = [fill(unknown), fill("7")]
    path, raw = write_record(tmp_path, "2026-10-15", rows)
    actual = decision_history.fills(tmp_path, "AAA")
    assert len(actual) == 2
    assert sum("client_order_id" not in row for row in actual) == 1
    assert [row["client_order_id"] for row in actual if "client_order_id" in row] == [
        "7"
    ]
    assert all(row["price"] == rows[0]["filled_price"] for row in actual)
    assert path.read_bytes() == raw
