"""Measure current chart judgments against distinct trading setups on the real model."""

from backend.agents.trading import current_setup


# Supply distinct bullish, failed-rebound and forbidden-entry observations.
def cases():
    levels = {
        "vwap": {"label": "session VWAP", "price": 100},
        "support": {"label": "daily support", "price": 98},
        "session_low": {"label": "session low", "price": 97},
    }
    common = {
        "decision_session": "2026-10-13",
        "bar": "2026-10-14T15:45:00Z",
        "valid_until": "2026-10-14T16:15:00Z",
        "levels": levels,
        "other_votes_as_of": "2026-10-13",
        "volume_scope": "IEX only",
    }
    return [
        {
            **common,
            "ticker": "UP",
            "grade": "A+",
            "entry_permitted": True,
            "price": 103,
            "session_open": 104,
            "technical": {
                "short": [
                    "daily uptrend; rising averages; "
                    "orderly pullback held daily support"
                ],
                "medium": ["weekly trend up"],
                "long": ["positive momentum"],
            },
            "candles": [{"close": 99}, {"close": 101}, {"close": 102}, {"close": 103}],
            "observed_structure": (
                "Higher lows; reclaimed VWAP and held the retest; "
                "no overhead resistance nearby"
            ),
        },
        {
            **common,
            "ticker": "DOWN",
            "grade": "A",
            "entry_permitted": True,
            "price": 90,
            "session_open": 99,
            "technical": {
                "short": [
                    "daily downtrend; price below falling averages; "
                    "broken daily support"
                ],
                "medium": ["weekly trend down"],
                "long": ["negative momentum"],
            },
            "candles": [
                {"close": 94},
                {"close": 97},
                {"close": 92},
                {"close": 94},
                {"close": 90},
            ],
            "observed_structure": (
                "Gap down; repeated weaker rebounds; VWAP not reclaimed; "
                "new session lows"
            ),
        },
        {
            **common,
            "ticker": "BLOCKED",
            "grade": "C",
            "entry_permitted": False,
            "price": 103,
            "session_open": 101,
            "technical": {
                "short": ["daily trend up"],
                "medium": ["weekly trend up"],
                "long": [],
            },
            "candles": [{"close": 101}, {"close": 102}, {"close": 103}],
        },
    ]


# Distinguish defended pullbacks from failed rebounds and blocked entries.
def test_current_setup_distinguishes_entries_and_exit_risk(structured_llm):
    facts = cases()
    rows = current_setup.assess(facts, structured_llm)
    assert len(rows) == len(facts), rows
    by_name = {row["ticker"]: row for row in rows}
    assert by_name["UP"]["entry"] == "ready", rows
    assert by_name["DOWN"]["entry"] in ("wait", "avoid"), rows
    assert by_name["DOWN"]["exit"] == "review", rows
    assert by_name["DOWN"]["exit_priority"] == "high", rows
    assert by_name["UP"]["entry_priority"] == "high", rows
    assert by_name["BLOCKED"]["entry"] != "ready", rows
    assert by_name["UP"]["confirmation_ref"] != "none", rows
    assert by_name["DOWN"]["invalidation_ref"] != "none", rows


# Do not borrow a strong daily trend to invent missing intraday confirmation.
def test_current_setup_waits_when_chart_confirmation_is_missing(structured_llm):
    fact = cases()[0]
    fact.update(
        ticker="MISSING",
        candles=[],
        observed_structure="Current-session candles unavailable; no observed retest",
        price=100,
    )
    rows = current_setup.assess([fact], structured_llm)
    assert len(rows) == 1, rows
    assert rows[0]["entry"] in ("wait", "unavailable"), rows
