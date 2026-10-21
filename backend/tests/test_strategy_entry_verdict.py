"""The one-word verdict vocabulary the dashboard shows, one case per reason code."""

import unittest

from backend.market import strategy_verdict as verdicts


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
                assert verdicts.classify(**arguments) == expected
        assert {code for _, (_, code) in cases} == set(verdicts.REASON_CODES)
