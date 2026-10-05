"""Pin sign, missingness and identity boundaries in saved timing attribution."""

import unittest

from analyze_timing_sides import action, distribution, indexed, summarize


# Build a compact saved intent with explicit fill and side evidence.
def row(side="buy", price=100, initial=0, desired=1, filled=1):
    return dict(intent_id="0/2026-09-01/ABC", date="2026-09-01", side=side,
                initial_shares=initial, desired_shares=desired, filled_delta=filled,
                realized_price=price, fee=0, outcome="completed", attempt_clock=0)


class TimingSidesTest(unittest.TestCase):
    # Lower buys and higher sells must both produce positive price advantages.
    def test_price_sign_for_both_sides(self):
        for side, kind, pa, pb, initial, desired, fill in (
            ("buy", "entry", 99, 100, 0, 1, 1),
            ("sell", "exit", 101, 100, 1, 0, -1),
        ):
            phases = [{name: {"intent_trace": [row(side, price, initial, desired, fill)]}
                       for name, price in (("candidate", pa), ("control", pb))}]
            result = summarize(phases, "2026-01-01", "2026-12-31", kind)
            self.assertEqual(result["common_fill_price_advantage_bp"]["mean"], 100)

    # A missing fill remains in outcomes and never receives a fictional price effect.
    def test_unfilled_stays_in_denominator(self):
        a, b = row(price=None, filled=0), row()
        a["outcome"] = "unfilled"
        result = summarize([{"candidate": {"intent_trace": [a]},
                             "control": {"intent_trace": [b]}}],
                           "2026-01-01", "2026-12-31", "entry")
        self.assertEqual(result["counts"]["one_or_both_unfilled"], 1)
        self.assertIsNone(result["common_fill_price_advantage_bp"]["mean"])
        self.assertEqual(result["outcomes"]["candidate"]["unfilled"], 1)

    # Opening and closing intents cannot be conflated with additions and trims.
    def test_action_categories(self):
        self.assertEqual(action(row()), "entry")
        self.assertEqual(action(row(initial=1, desired=2)), "add")
        self.assertEqual(action(row("sell", initial=2, desired=1)), "trim")
        self.assertEqual(action(row("sell", initial=1, desired=0)), "exit")

    # Duplicate identities and nonzero fees must invalidate the diagnostic.
    def test_bad_source_rows_rejected(self):
        with self.assertRaises(ValueError):
            indexed([row(), row()])
        value = row()
        value["fee"] = 0.01
        with self.assertRaises(ValueError):
            indexed([value])
        self.assertIsNone(distribution([])["mean"])


if __name__ == "__main__":
    unittest.main()
