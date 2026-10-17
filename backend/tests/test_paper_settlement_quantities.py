"""Synthetic receipts exercise quantity persistence without broker/model calls."""

import copy
import tempfile
import unittest
from dataclasses import asdict, fields

from backend.agents.trading.desk import paper


# Build a detached original intent and broker observation with separate quantities.
def receipts(desired=8, submitted="5", sender=5, filled="5", status="filled"):
    pending = {
        "client_order_id": "synthetic-quantity-domain",
        "symbol": "SYNTHETIC",
        "side": "sell",
        "qty": desired,
        "session": "2019-03-01",
        "sent": {"qty": sender, "at": "2019-03-04T09:30:31-05:00"},
    }
    order = {
        "client_order_id": pending["client_order_id"],
        "qty": submitted,
        "filled_qty": filled,
        "filled_avg_price": "99",
        "status": status,
        "submitted_at": "2019-03-04T14:30:31.200000Z",
        "filled_at": "2019-03-04T14:30:31.333000Z",
    }
    return pending, order


# Exercise the real settlement fold and durable state readback in a private root.
def persisted(pending, orders, **controls):
    state = paper.PaperState(pending=[copy.deepcopy(pending)], **controls)
    original = copy.deepcopy(asdict(state))
    settled = paper.settle(state.pending, orders)
    result = paper.apply_settlements(state, settled)
    with tempfile.TemporaryDirectory(prefix="synthetic-settlement-") as root:
        paper.save_state(root, result)
        result = paper.load_state(root)
    assert asdict(state) == original
    return result, settled


# Verify retained metadata never changes the established terminal/control rules.
class SettlementQuantityTests(unittest.TestCase):
    # A coverage-capped sell retains desired, sender, broker and actual fill domains.
    def test_terminal_capped_sell_survives_pending_removal(self):
        pending, order = receipts()
        result, settled = persisted(pending, [order])
        self.assertEqual(result.pending, [])
        row = result.journal[0]
        self.assertEqual(
            (row["qty"], row["submitted_qty"], row["sender_qty"], row["filled_qty"]),
            (8, 5, 5, 5),
        )
        self.assertEqual((settled[0].status, settled[0].terminal), ("partial", True))
        self.assertEqual(row["execution"]["submitted_at"], order["submitted_at"])
        self.assertEqual(row["execution"]["filled_at"], order["filled_at"])

    # A venue partial keeps original accepted quantity and expires the remainder.
    def test_partial_buy_and_expired_zero_keep_independent_quantities(self):
        for fill in ("4", "0"):
            with self.subTest(fill=fill):
                pending, order = receipts(9, "9", 9, fill, "expired")
                pending["side"] = "buy"
                result, settled = persisted(pending, [order])
                self.assertEqual(result.pending, [])
                row = result.journal[0]
                self.assertEqual((row["submitted_qty"], row["sender_qty"]), (9, 9))
                self.assertEqual(
                    settled[0].status, "partial" if fill == "4" else "dead"
                )

    # Missing source fields stay unknown rather than borrowing another domain.
    def test_missing_domains_are_not_inferred(self):
        for missing in ("sender", "broker", "both"):
            with self.subTest(missing=missing):
                pending, order = receipts()
                if missing in ("sender", "both"):
                    pending.pop("sent")
                if missing in ("broker", "both"):
                    order.pop("qty")
                result, settled = persisted(pending, [order])
                row = result.journal[0]
                self.assertEqual(
                    settled[0].sender_qty,
                    None if missing in ("sender", "both") else 5,
                )
                self.assertEqual(
                    settled[0].submitted_qty,
                    None if missing in ("broker", "both") else 5,
                )
                self.assertEqual("sender_qty" in row, missing == "broker")
                self.assertEqual("submitted_qty" in row, missing == "sender")

    # Broker adjustments remain observable without rejecting or relabeling outcomes.
    def test_adjusted_and_disagreeing_quantities_are_evidence_not_guards(self):
        pending, order = receipts(8, "16", 8, "16")
        result, settled = persisted(pending, [order])
        row = result.journal[0]
        self.assertEqual(
            (row["submitted_qty"], row["sender_qty"], row["filled_qty"]), (16, 8, 16)
        )
        self.assertEqual((settled[0].status, settled[0].terminal), ("filled", True))
        self.assertIn(
            "broker_sender_disagreement", row["quantity_evidence"]["anomalies"]
        )
        self.assertIn("broker_exceeds_desired", row["quantity_evidence"]["anomalies"])
        self.assertEqual(row["quantity_evidence"]["broker_qty"], "16")

    # Fractional broker metadata is retained without whole-share truncation.
    def test_fractional_broker_quantity_is_not_truncated(self):
        pending, order = receipts(8, "2.5", 2, "2", "expired")
        result, _ = persisted(pending, [order])
        self.assertEqual(result.journal[0]["submitted_qty"], 2.5)

    # Pending replacement remains working even when quantities temporarily disagree.
    def test_pending_replace_retains_pending_and_observed_domains(self):
        pending, order = receipts(8, "6", 5, "2", "pending_replace")
        result, settled = persisted(pending, [order])
        self.assertEqual((settled[0].status, settled[0].terminal), ("partial", False))
        self.assertEqual(len(result.pending), 1)
        row = result.journal[0]
        self.assertEqual((row["submitted_qty"], row["sender_qty"]), (6, 5))

    # Malformed metadata is evidence without changing legacy settlement status.
    def test_invalid_quantity_metadata_is_not_promoted(self):
        for bad in (True, "NaN", "-2", "0", "not-a-number"):
            with self.subTest(bad=bad):
                pending, order = receipts(submitted=bad)
                result, settled = persisted(pending, [order])
                row = result.journal[0]
                self.assertNotIn("submitted_qty", row)
                self.assertIsNone(settled[0].submitted_qty)
                self.assertEqual(row["quantity_evidence"]["broker_qty"], bad)
                self.assertIn(
                    "invalid_broker_qty", row["quantity_evidence"]["anomalies"]
                )

    # A fill larger than the observed order is preserved as an explicit anomaly.
    def test_fill_exceeds_observed_broker_quantity_is_not_truncated(self):
        pending, order = receipts(8, "4", 4, "5")
        result, settled = persisted(pending, [order])
        self.assertEqual(settled[0].filled_qty, 5)
        self.assertIn(
            "fill_exceeds_broker", result.journal[0]["quantity_evidence"]["anomalies"]
        )

    # Existing unannotated terminal history remains exact and is not backfilled.
    def test_old_journal_and_duplicate_fold_are_unchanged(self):
        legacy = {
            "client_order_id": "original", "qty": 8, "filled_qty": 5, "terminal": True
        }
        state = paper.PaperState(journal=[legacy])
        self.assertEqual(asdict(paper.apply_settlements(state, [])), asdict(state))
        pending, order = receipts()
        result, settled = persisted(pending, [order])
        self.assertEqual(
            asdict(paper.apply_settlements(result, settled)), asdict(result)
        )

    # Terminal partials preserve the existing desired-relative rebalance rollback.
    def test_terminal_partial_preserves_rebalance_controls(self):
        pending, order = receipts()
        result, _ = persisted(
            pending, [order], unconfirmed_rebalance="2019-03-01",
            last_rebalance="2019-03-01", previous_rebalance="2019-02-01",
        )
        self.assertIsNone(result.unconfirmed_rebalance)
        self.assertEqual(result.last_rebalance, "2019-02-01")
        self.assertEqual(result.sessions_since_rebalance, paper.REBALANCE_EVERY)

    # Later incomplete receipts cannot erase already recorded independent observations.
    def test_later_partial_receipt_omitting_metadata_keeps_known_values(self):
        pending, order = receipts(8, "6", 5, "2", "pending_replace")
        result, _ = persisted(pending, [order])
        original = copy.deepcopy(result.journal[0]["quantity_evidence"])
        result.pending[0].pop("sent")
        order.pop("qty")
        order.update(status="expired", filled_qty="3")
        result = paper.apply_settlements(result, paper.settle(result.pending, [order]))
        self.assertEqual(result.pending, [])
        row = result.journal[0]
        self.assertEqual((row["submitted_qty"], row["sender_qty"]), (6, 5))
        self.assertEqual(result.journal[0]["quantity_evidence"], original)

    # Old positional construction continues to describe unknown submission domains.
    def test_original_positional_settled_construction_remains_compatible(self):
        settled = paper.Settled(
            "legacy", "SYNTHETIC", "sell", 8, "2019-03-01", "partial",
            5, 99, True, {}, "trim",
        )
        result = paper.apply_settlements(paper.PaperState(), [settled])
        self.assertIsNone(settled.submitted_qty)
        self.assertIsNone(settled.sender_qty)
        self.assertNotIn("submitted_qty", result.journal[0])
        self.assertNotIn("sender_qty", result.journal[0])

    # Submission observations belong only to settlement receipts, never planned orders.
    def test_planned_order_schema_unchanged_and_settled_keywords_supported(self):
        self.assertEqual(
            [item.name for item in fields(paper.PaperOrder)],
            ["symbol", "side", "qty", "reason", "client_order_id", "event_id",
             "priority", "execution_timing", "kind"],
        )
        settled = paper.Settled(
            "new", "SYNTHETIC", "sell", 8, "2019-03-01", "partial", 5,
            submitted_qty=5, sender_qty=5,
        )
        self.assertEqual((settled.submitted_qty, settled.sender_qty), (5, 5))

    # Huge Decimal exponents remain raw invalid evidence without integer allocation.
    def test_unrepresentable_quantity_remains_unknown_with_evidence(self):
        pending, order = receipts(submitted="1e100000000")
        result, settled = persisted(pending, [order])
        self.assertIsNone(settled[0].submitted_qty)
        self.assertNotIn("submitted_qty", result.journal[0])
        self.assertEqual(
            result.journal[0]["quantity_evidence"]["broker_qty"], "1e100000000"
        )

    # Sender-only observations remain available even when no broker order exists.
    def test_missing_broker_receipt_keeps_sender_observation_only(self):
        pending, _ = receipts()
        result, settled = persisted(pending, [])
        self.assertEqual((settled[0].status, settled[0].terminal), ("missing", True))
        self.assertNotIn("submitted_qty", result.journal[0])
        self.assertEqual(result.journal[0]["sender_qty"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
