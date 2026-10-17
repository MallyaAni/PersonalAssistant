"""Synthetic CURRENT native reconciliation; no account/model/provider operations."""

import hashlib
import json
import os
import unittest
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_conditional_settlement as adapter
from backend.market import replay_broker as native

START = "2019-03-01T14:45:31.200000+00:00"
END = "2019-03-01T14:45:33+00:00"
OUTCOME = hashlib.sha256(b"SYNTHETIC original conditional outcome").hexdigest()
CASES = []


# Construct only synthetic requests and outcomes through exact native broker methods.
def scenario(*, side="sell", desired=8, submitted=5, price=100, cash=1000):
    client = native.ReplayBroker(
        cash,
        10,
        initial_holdings={"AAPL": 5} if side == "sell" else {},
        initial_average_prices={"AAPL": 80} if side == "sell" else {},
    )
    client.observe(START, {"AAPL": 100}, True)
    order = client.submit_market("AAPL", submitted, side, "SYNTHETIC-original-CID")
    state = paper.PaperState(
        last_rebalance="2019-02-28",
        previous_rebalance="2019-02-01",
        sessions_since_rebalance=1,
        order_seq=7,
        pending=[
            {
                "client_order_id": order["client_order_id"],
                "symbol": "AAPL",
                "side": side,
                "qty": desired,
                "session": "2019-02-28",
                "execute_on": "2019-03-01",
                "execution_timing": "dip_or_close",
                "sent": {"qty": submitted, "at": START},
                "execution": {
                    "created_at": order["created_at"],
                    "submitted_at": order["submitted_at"],
                },
            }
        ],
    )
    client.flush(END, {"AAPL": price})
    return client, state


# Exercise only externally pinned actual CURRENT source, never a host stand-in.
class ConditionalSettlementTests(unittest.TestCase):
    # Keep absent native fixtures explicit and place all synthetic writes under /out.
    def setUp(self):
        if os.environ.get("ANIOS_SETTLEMENT_NATIVE_FIXTURE") != "1":
            pytest.skip("Exact CURRENT native fixture absent; skip is not proof")
        identity = json.loads(Path("/fixture/identities.json").read_bytes())["CURRENT"]
        self.pins = {"identity": identity, "identity_sha256": codec._digest(identity)}
        self.root = Path("/out") / ("synthetic-state-" + uuid4().hex)
        self.root.mkdir(mode=0o700)

    # Preserve original input and exact broker bytes around every accepted composition.
    def reconcile(self, client, state):
        before = codec.encode(client, **self.pins)
        prior = deepcopy(asdict(state))
        try:
            updated, receipt = adapter.reconcile(
                client,
                state,
                pins=self.pins,
                outcome_sha256=OUTCOME,
                observed_at=client._now.isoformat(),
            )
        finally:
            assert codec.encode(client, **self.pins) == before
            assert asdict(state) == prior
        assert receipt["durable_state_committed"] is False
        assert receipt["actual_execution_claim"] is False
        assert receipt["broker_checkpoint_sha256"] == hashlib.sha256(before).hexdigest()
        return updated, receipt, before

    # Fully filled submitted5 stays partial against desired8 after save/read.
    def test_capped_sell_metadata_save_read_and_byte_identical_broker(self):
        client, state = scenario()
        updated, receipt, raw = self.reconcile(client, state)
        row = updated.journal[0]
        assert (
            row["qty"],
            row["submitted_qty"],
            row["sender_qty"],
            row["filled_qty"],
        ) == (8, 5, 5, 5)
        assert row["status"] == "partial"
        assert row["terminal"] is True
        assert updated.pending == []
        assert client._cash == 1499.5
        assert client._held == {}
        paper.save_state(self.root, updated)
        restored_state = paper.load_state(self.root)
        assert asdict(restored_state) == asdict(updated)
        restored_client = codec.restore(
            raw, expected_sha256=hashlib.sha256(raw).hexdigest(), **self.pins
        )
        assert codec.encode(restored_client, **self.pins) == raw
        assert row["execution"]["filled_at"] == END
        assert row["execution"]["submitted_at"] == START
        CASES.append(
            {
                "kind": "SYNTHETIC_CAPPED_SELL_NATIVE_METADATA",
                "paper": asdict(updated),
                "receipt": receipt,
                "broker_checkpoint_sha256": hashlib.sha256(raw).hexdigest(),
                "broker_checkpoint_utf8": raw.decode(),
                "saved_state_sha256": hashlib.sha256(
                    paper.state_path(self.root).read_bytes()
                ).hexdigest(),
                "cash": client._cash,
                "held": client._held,
            }
        )

    # Partial3 and zero expired preserve actual fills and their terminal remainder.
    def test_partial_cash_and_zero_expired(self):
        for price, filled, status in ((250, 3, "partial"), (None, 0, "dead")):
            client, state = scenario(side="buy", desired=9, submitted=9, price=price)
            updated, receipt, raw = self.reconcile(client, state)
            row = updated.journal[0]
            assert (
                row["qty"],
                row["submitted_qty"],
                row["sender_qty"],
                row["filled_qty"],
            ) == (9, 9, 9, filled)
            assert row["status"] == status
            assert row["terminal"] is True
            assert updated.pending == []
            assert client._cash == (249.25 if filled else 1000)
            assert client._held == ({"AAPL": 3} if filled else {})
            CASES.append(
                {
                    "kind": "SYNTHETIC_PARTIAL_OR_ZERO",
                    "price": price,
                    "paper": asdict(updated),
                    "receipt": receipt,
                    "broker_checkpoint_utf8": raw.decode(),
                    "cash": client._cash,
                    "held": client._held,
                }
            )

    # Future auctions stay open after fresh marks reopen the batch flag.
    def test_known_open_future_auction_and_fresh_mark_flag(self):
        client = native.ReplayBroker(1000, 10)
        client.observe(START, {"AAPL": 100}, True)
        order = client.submit_market_on_close("AAPL", 2, "buy", "SYNTHETIC-auction")
        client.flush(END, {})
        client.observe(END, {"AAPL": 100}, True)
        state = paper.PaperState(
            pending=[
                {
                    "client_order_id": order["client_order_id"],
                    "symbol": "AAPL",
                    "side": "buy",
                    "qty": 2,
                    "session": "2019-02-28",
                }
            ]
        )
        updated, receipt, _ = self.reconcile(client, state)
        assert client._batch_open is True
        assert len(updated.pending) == 1
        assert updated.journal[0]["status"] == "open"
        assert updated.journal[0]["terminal"] is False
        assert receipt["settled"][0]["filled_qty"] == 0

    # Future unsent legs remain pending; expired unsent legs become only missing.
    def test_future_unsent_and_expired_unsent(self):
        client = native.ReplayBroker(1000, 10)
        client.observe(END, {"AAPL": 100}, True)
        state = paper.PaperState(
            pending=[
                {
                    "client_order_id": "SYNTHETIC-future",
                    "symbol": "AAPL",
                    "side": "buy",
                    "qty": 2,
                    "session": "2019-03-01",
                    "execute_on": "2019-03-04",
                }
            ]
        )
        updated, receipt, _ = self.reconcile(client, state)
        assert asdict(updated) == asdict(state)
        assert receipt["settled"] == []
        state.pending[0]["execute_on"] = "2019-02-28"
        expired, _, _ = self.reconcile(client, state)
        assert expired.pending == []
        assert expired.journal[0]["status"] == "missing"
        assert "submitted_qty" not in expired.journal[0]
        assert "sender_qty" not in expired.journal[0]

    # Missing native receipts leave sent or acknowledged requests uncertain.
    def test_acknowledged_or_sent_missing_receipt_refused(self):
        for field in ("sent", "execution"):
            client = native.ReplayBroker(1000, 10)
            client.observe(END, {"AAPL": 100}, True)
            row = {
                "client_order_id": "SYNTHETIC-absent",
                "symbol": "AAPL",
                "side": "buy",
                "qty": 2,
                "session": "2019-02-28",
                field: {"qty": 2} if field == "sent" else {"submitted_at": START},
            }
            with pytest.raises(
                ValueError, match="lacks original native broker receipt"
            ):
                self.reconcile(client, paper.PaperState(pending=[row]))

    # Pending CID/side/quantity corruption cannot redirect a genuine native outcome.
    def test_request_binding_and_duplicate_corruption(self):
        for field, value in (
            ("client_order_id", "SYNTHETIC-other"),
            ("symbol", "MSFT"),
            ("side", "buy"),
            ("side", "invalid"),
            ("qty", 4),
            ("qty", 0),
            ("qty", True),
            ("qty", 8.0),
        ):
            client, state = scenario()
            state.pending[0][field] = value
            with pytest.raises(ValueError, match="receipt|binding|side|quantity"):
                self.reconcile(client, state)
        for key in ("pending", "journal"):
            client, state = scenario()
            row = deepcopy(state.pending[0])
            setattr(state, key, [row, deepcopy(row)])
            with pytest.raises(ValueError, match="unique"):
                self.reconcile(client, state)

    # Accepted market requests are not completed resolver outcomes.
    def test_accepted_market_outcome_refused(self):
        client = native.ReplayBroker(1000, 10)
        client.observe(START, {"AAPL": 100}, True)
        client.submit_market("AAPL", 2, "buy", "SYNTHETIC-unresolved")
        with pytest.raises(ValueError, match="unresolved"):
            self.reconcile(client, paper.PaperState())

    # Reject wrong clocks, missing outcome digests and the original N2 profile.
    def test_clock_outcome_and_current_profile_refusals(self):
        client, state = scenario()
        for observed in (START, "2019-03-01T14:45:34+00:00", datetime(2019, 3, 1)):
            with pytest.raises(ValueError, match="clock"):
                adapter.reconcile(
                    client,
                    state,
                    pins=self.pins,
                    outcome_sha256=OUTCOME,
                    observed_at=observed,
                )
        for digest in ("", "x" * 64):
            with pytest.raises(ValueError, match="SHA256"):
                adapter.reconcile(
                    client,
                    state,
                    pins=self.pins,
                    outcome_sha256=digest,
                    observed_at=END,
                )
        pins = deepcopy(self.pins)
        pins["identity"]["source_revision"] = codec.N2
        pins["identity_sha256"] = codec._digest(pins["identity"])
        with pytest.raises(ValueError, match="Exact current"):
            adapter.reconcile(
                client, state, pins=pins, outcome_sha256=OUTCOME, observed_at=END
            )

    # Repeated reconciliation cannot duplicate fills or create followup quantities.
    def test_idempotence_and_native_rebalance_control(self):
        for side, desired, submitted in (("sell", 8, 5), ("buy", 2, 2)):
            client, state = scenario(side=side, desired=desired, submitted=submitted)
            state.unconfirmed_rebalance = "2019-02-28"
            once, _, raw = self.reconcile(client, state)
            twice, receipt, _ = self.reconcile(client, once)
            assert asdict(twice) == asdict(once)
            assert receipt["settled"] == []
            assert once.unconfirmed_rebalance is None
            assert once.last_rebalance == (
                "2019-02-01" if side == "sell" else "2019-02-28"
            )
            assert once.pending == []
            assert once.order_seq == state.order_seq
            assert codec.encode(client, **self.pins) == raw
