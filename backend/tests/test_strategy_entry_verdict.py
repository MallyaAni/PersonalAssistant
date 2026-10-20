"""One realtime verdict per entry row, with a closed reason and a trade size."""

# ruff: noqa: PT009  # unittest-style assertions match the neighbouring strategy tests.

import base64
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.market import forward_probability_timing as inference
from backend.market import strategy_entries as entries
from backend.market import strategy_publication as publication
from backend.market import strategy_reference_book as ledger
from backend.market import strategy_reference_transition as transition
from backend.market import strategy_verdict as verdicts
from backend.tests.test_strategy_entries import NOW, fixture, timing_cache
from backend.tests.test_strategy_reference_entries import fixture as reference_fixture
from backend.tests.test_strategy_reference_transition import (
    book_for,
    distribution,
    snapshot_for,
)


# Require the published row to carry one closed verdict and a size matching it.
def assert_verdict_row(test, row, reason_key="reason"):
    test.assertIn(row["verdict"], verdicts.VERDICTS)
    test.assertIn(row["reason_code"], verdicts.REASON_CODES)
    test.assertIsInstance(row[reason_key], str)
    if row["verdict"] in ("buy", "sell"):
        test.assertEqual(row["state"], "execute")
        test.assertGreater(row["size_weight"], 0)
        test.assertGreaterEqual(row["model_position_weight"], 0)
    else:
        test.assertEqual(row["size_weight"], 0)


# Attach the native quote receipt before the unchanged publication writer.
def publish_value(root, snapshot, cache, quotes, page, now):
    publication.publish(root, snapshot, now)
    cache["stored_forecast"] = entries.store_forecast(root, cache["forecast"])
    value = entries.project(snapshot, cache, quotes, now)
    value["quote_receipt"] = {
        key: page[key]
        for key in ("url", "requested_at", "received_at", "status", "sha256")
    }
    value["quote_receipt"]["body_base64"] = base64.b64encode(page["body"]).decode()
    value["receipt_sha256"] = publication._digest(
        {k: v for k, v in value.items() if k != "receipt_sha256"}
    )
    entries.publish(root, value)
    return value


# Remove the new fields before resealing a legacy view.
def strip_verdicts(value, *, fresh=False):
    for row in value["rows"].values():
        for key in ("verdict", "reason_code", "reason"):
            row.pop(key, None)
        if fresh:
            row.pop("model_position_weight", None)
    calculation = value.get("reference_calculation")
    if calculation is not None:
        for row in calculation["rows"].values():
            for key in ("verdict", "reason_code", "verdict_reason", "size_weight"):
                row.pop(key, None)
        calculation["receipt_sha256"] = publication._digest(
            {k: v for k, v in calculation.items() if k != "receipt_sha256"}
        )
    value["receipt_sha256"] = publication._digest(
        {k: v for k, v in value.items() if k != "receipt_sha256"}
    )
    return value


# Map every closed reason code from the existing state and timing evidence.
class StrategyVerdictTests(unittest.TestCase):
    # A table with one case per code keeps the vocabulary closed and measured.
    def test_every_reason_code_has_a_case(self):
        cases = (
            (
                dict(state="execute", action="Buy", target_weight=0.17, held_weight=0),
                ("buy", "execute_now"),
            ),
            (
                dict(
                    state="execute", action="Sell", target_weight=0.17, held_weight=0.3
                ),
                ("sell", "execute_now"),
            ),
            (
                dict(state="wait", action="Buy", target_weight=0.17, held_weight=0),
                ("nothing", "waiting_better_price"),
            ),
            (
                dict(
                    state="no_trade",
                    action=None,
                    timing_reason="No funded model reference change",
                    target_weight=0.17,
                    held_weight=0.17,
                ),
                ("nothing", "at_target"),
            ),
            (
                dict(
                    state="no_trade",
                    action=None,
                    timing_reason="No new model allocation",
                    target_weight=0,
                    held_weight=0,
                ),
                ("nothing", "no_allocation"),
            ),
            (
                dict(
                    state="execute",
                    action="Sell",
                    timing_reason="mandatory_grade_exit",
                    target_weight=0,
                    held_weight=0.3,
                    mandatory=True,
                ),
                ("sell", "grade_below_a"),
            ),
            (
                dict(
                    state="unavailable",
                    action="Buy",
                    timing_reason="missing calibrated distribution",
                    distribution_available=False,
                ),
                ("nothing", "awaiting_candle"),
            ),
            (
                dict(
                    state="unavailable",
                    action="Buy",
                    timing_reason="published assessment expired",
                ),
                ("nothing", "publication_expired"),
            ),
            (
                dict(
                    state="unavailable",
                    action="Buy",
                    timing_reason="Fresh compatible IEX quote required",
                    quote_available=False,
                ),
                ("nothing", "quote_stale"),
            ),
            (
                dict(
                    state="unavailable",
                    action="Buy",
                    timing_reason="invalid moments, funding or cost",
                ),
                ("nothing", "price_unavailable"),
            ),
        )
        for arguments, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(verdicts.classify(**arguments), expected)
        self.assertEqual({code for _, (_, code) in cases}, set(verdicts.REASON_CODES))

    # A fresh buy is sized; wait and no-allocation rows are explicit do-nothing rows.
    def test_fresh_rows_carry_verdict_and_consistent_size(self):
        with TemporaryDirectory() as directory:
            snapshot, _, _ = fixture(Path(directory))
            cache, quotes, _ = timing_cache(snapshot, -0.01)
            row = entries.project(snapshot, cache, quotes, NOW)["rows"]["AAA"]
            self.assertEqual(
                (row["verdict"], row["reason_code"]), ("buy", "execute_now")
            )
            self.assertEqual(
                (row["size_weight"], row["model_position_weight"]), (0.17, 0.17)
            )
            assert_verdict_row(self, row)
            cache, quotes, _ = timing_cache(snapshot, 0.01)
            row = entries.project(snapshot, cache, quotes, NOW)["rows"]["AAA"]
            self.assertEqual(
                (row["verdict"], row["reason_code"]),
                ("nothing", "waiting_better_price"),
            )
            assert_verdict_row(self, row)
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {"AAA": 0.0})
            cache, quotes, _ = timing_cache(snapshot)
            row = entries.project(snapshot, cache, quotes, NOW)["rows"]["AAA"]
            self.assertEqual(
                (row["verdict"], row["reason_code"]), ("nothing", "no_allocation")
            )
            assert_verdict_row(self, row)
        with TemporaryDirectory() as directory:
            snapshot, _, _ = fixture(Path(directory))
            cache, quotes, _ = timing_cache(snapshot, -0.01)
            distributions = {name: None for name in cache["forecast"].distributions}
            receipt = {
                **cache["forecast"].receipt,
                "distributions": inference._forecast_identity(distributions),
            }
            cache["forecast"] = inference.ObservedForecast(
                distributions, receipt, inference._digest(receipt)
            )
            row = entries.project(snapshot, cache, quotes, NOW)["rows"]["AAA"]
            self.assertEqual(
                (row["verdict"], row["reason_code"]), ("nothing", "awaiting_candle")
            )
            assert_verdict_row(self, row)

    # Both reference sides keep their proposed size; only an execution is sized.
    def test_reference_rows_size_both_sides_and_map_nothing_reasons(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {"AAA": 0.0}, {"AAA": "B"})
            book = book_for(snapshot, {"AAA": 0.002}, 0.8)
            row = transition.project(
                transition.prepare(snapshot, book, NOW),
                {"AAA": 120.0},
                {},
                evidence_sha256="c" * 64,
                price_basis=transition.PRICE_BASIS,
            )["rows"]["AAA"]
            self.assertEqual(
                (row["verdict"], row["reason_code"], row["state"]),
                ("sell", "grade_below_a", "execute"),
            )
            self.assertGreater(row["size_weight"], 0)
            self.assertEqual(row["model_position_weight"], 0.0)
            assert_verdict_row(self, row, reason_key="verdict_reason")
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {"AAA": 0.17})
            book = book_for(snapshot, {"AAA": 0.0017}, 0.83)
            row = transition.project(
                transition.prepare(snapshot, book, NOW),
                {"AAA": 100.0},
                {"AAA": distribution(0.02)},
                evidence_sha256="c" * 64,
                price_basis=transition.PRICE_BASIS,
            )["rows"]["AAA"]
            self.assertEqual(
                (row["verdict"], row["reason_code"]), ("nothing", "at_target")
            )
            self.assertEqual(row["size_weight"], 0)
            assert_verdict_row(self, row, reason_key="verdict_reason")
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {"AAA": 0.17})
            book = book_for(snapshot, {"AAA": 0.001}, 0.9)
            row = transition.project(
                transition.prepare(snapshot, book, NOW),
                {"AAA": 100.0},
                {"AAA": distribution(0.02)},
                evidence_sha256="c" * 64,
                price_basis=transition.PRICE_BASIS,
            )["rows"]["AAA"]
            self.assertEqual(
                (row["verdict"], row["reason_code"]),
                ("nothing", "waiting_better_price"),
            )
            self.assertEqual(row["size_weight"], 0)
            self.assertGreater(row["trade_weight"], 0)
            assert_verdict_row(self, row, reason_key="verdict_reason")
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {"AAA": 0.0})
            book = book_for(snapshot, {}, 1.0)
            row = transition.project(
                transition.prepare(snapshot, book, NOW),
                {},
                {},
                evidence_sha256="c" * 64,
                price_basis=transition.PRICE_BASIS,
            )["rows"]["AAA"]
            self.assertEqual(
                (row["verdict"], row["reason_code"]), ("nothing", "no_allocation")
            )
            assert_verdict_row(self, row, reason_key="verdict_reason")
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {"AAA": 0.17})
            book = book_for(snapshot, {"AAA": 0.001}, 0.9)
            row = transition.project(
                transition.prepare(snapshot, book, NOW),
                {"AAA": 100.0},
                {"AAA": distribution(-1000)},
                evidence_sha256="c" * 64,
                price_basis=transition.PRICE_BASIS,
            )["rows"]["AAA"]
            self.assertEqual(
                (row["verdict"], row["reason_code"]), ("nothing", "price_unavailable")
            )
            assert_verdict_row(self, row, reason_key="verdict_reason")

    # A resolved observed-book attempt is nothing with no executable size.
    def test_observed_book_resolved_row_is_nothing(self):
        with TemporaryDirectory() as directory:
            snapshot, cache, _, _ = reference_fixture(Path(directory))
            book = ledger.initial(cache["reference_plan"], NOW.date().isoformat())
            resolved = replace(book, resolved=(("AAA", "a" * 64),), generation=1)
            _, value = ledger.project(
                resolved,
                {"AAA": 100.0},
                {},
                evidence_sha256="c" * 64,
            )
            row = value["rows"]["AAA"]
            self.assertEqual(
                (row["verdict"], row["reason_code"]), ("nothing", "at_target")
            )
            self.assertEqual(row["size_weight"], 0)
            assert_verdict_row(self, row, reason_key="verdict_reason")

    # A dashboard row reads back as nothing; the proposed size stays in the calculation.
    def test_reference_wait_row_is_nothing_and_still_reads(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, cache, quotes, page = reference_fixture(root, mean=-0.02)
            publish_value(root, snapshot, cache, quotes, page, NOW)
            reopened = entries.read(root, snapshot, NOW)
            row = reopened["rows"]["AAA"]
            self.assertEqual(reopened["status"], "available")
            self.assertEqual(
                (row["verdict"], row["reason_code"]),
                ("nothing", "waiting_better_price"),
            )
            self.assertEqual(row["size_weight"], 0)
            self.assertGreater(
                reopened["reference_calculation"]["rows"]["AAA"]["trade_weight"], 0
            )
            assert_verdict_row(self, row)

    # Stored fresh rows without verdict fields still read with their original size.
    def test_stored_fresh_row_without_verdict_still_reads(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, _, _ = fixture(root)
            cache, quotes, _ = timing_cache(snapshot)
            cache["stored_forecast"] = entries.store_forecast(root, cache["forecast"])
            value = strip_verdicts(
                entries.project(snapshot, cache, quotes, NOW), fresh=True
            )
            entries.publish(root, value)
            reopened = entries.read(root, snapshot, NOW)
            self.assertEqual(reopened["status"], "available")
            self.assertNotIn("verdict", reopened["rows"]["AAA"])
            self.assertEqual(reopened["rows"]["AAA"]["size_weight"], 0.17)

    # Stored reference rows without verdict fields still reconcile.
    def test_stored_reference_row_without_verdict_still_reads(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, cache, quotes, page = reference_fixture(root)
            publication.publish(root, snapshot, NOW)
            cache["stored_forecast"] = entries.store_forecast(root, cache["forecast"])
            value = entries.project(snapshot, cache, quotes, NOW)
            value["quote_receipt"] = {
                key: page[key]
                for key in ("url", "requested_at", "received_at", "status", "sha256")
            }
            value["quote_receipt"]["body_base64"] = base64.b64encode(
                page["body"]
            ).decode()
            value = strip_verdicts(value)
            entries.publish(root, value)
            reopened = entries.read(root, snapshot, NOW)
            self.assertEqual(reopened["status"], "available")
            self.assertNotIn("verdict", reopened["rows"]["AAA"])
            self.assertEqual(
                reopened["rows"]["AAA"]["size_weight"],
                value["reference_calculation"]["rows"]["AAA"]["trade_weight"],
            )


# Run the verdict vocabulary and size invariants in the bounded component process.
if __name__ == "__main__":
    unittest.main()
