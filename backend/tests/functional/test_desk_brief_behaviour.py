"""Does the desk brief say what the desk measured, and only that?

The prompt claims three things, and each is a case here:

- **The stance follows the grade.** An A+ name with three bullish analysts
  must come back "own"; a C name with bearish filings and a bearish tape
  must come back "avoid"; a B name "wait". The narrator drops a brief whose
  stance disagrees, so a wrong stance shows as None.
- **The evidence is said in plain words.** The brief must not leak the
  desk's measurement vocabulary — no field name such as "revenue_yoy" or
  "ema21_distance", and no raw signed figure such as "+0.194" or "-0.311".
  A user reads "revenue is up year over year", not a parameter list.
- **The analysts are named by stance.** The reasoning for the A+ name must
  mention the release (sentiment) and the filings (fundamental); the
  reasoning for the C name must say what is bearish.

The evidence texts are shaped exactly as `brief_text` writes them.
"""

# ruff: noqa: E501
import re

import pytest

from backend.agents.trading.desk.narrative import AVOID, OWN, WAIT, DeskNarrator

pytestmark = pytest.mark.asyncio

_A_PLUS = """Name: SNDK (ai side). Session: 2026-09-04.
Grade: A+. Votes: +3.0.
fundamental analyst: stance +1; revenue_yoy +1.551, revenue_qoq +0.410, gross_margin +0.846, revenue_acceleration +0.295, eps_change_yoy +5.000, net_margin +0.770, sessions_since_earnings +21.000.
technical analyst: stance +1; ema21_distance +0.126, stack_order +3.000, weekly_trend +1.000, daily_trend +1.000, range_position_60 +0.547, support_distance +0.125, momentum_120 +0.692.
sentiment analyst: stance +1; tone_guidance +1.000, tone_demand +1.000, tone_guidance_change +0.000, tone_pricing +1.000, tone_capex +0.000.
rotation analyst: stance +0; no data for this name.
Regime: AI participation percentile 0.00, AI-vs-software correlation -0.52, novelty z +4.8, rotation leader software, AI basket drawdown -0.223, selection confidence 0.50, exposure 1.00.
Regime flags: participation below its two-year median; AI-vs-software co-movement far from its history; theme co-movement structure has changed shape.
In today's book at weight 0.076."""

_C = """Name: IREN (ai side). Session: 2026-09-04.
Grade: C. Votes: -2.0.
fundamental analyst: stance -1; revenue_yoy -0.311, revenue_qoq -0.054, gross_margin +0.000, revenue_acceleration -0.311, eps_change_yoy -3.458, net_margin -4.984, sessions_since_earnings +5.000.
technical analyst: stance -1; ema21_distance +0.097, stack_order -1.000, weekly_trend -1.000, daily_trend -1.000, range_position_60 +0.310, support_distance +0.041, momentum_120 -0.054.
sentiment analyst: stance +0; tone_guidance +1.000, tone_demand +1.000, tone_guidance_change +0.000, tone_pricing +1.000, tone_capex +1.000.
rotation analyst: stance +0; no data for this name.
Regime: AI participation percentile 0.00, AI-vs-software correlation -0.52, novelty z +4.8, rotation leader software, AI basket drawdown -0.223, selection confidence 0.50, exposure 1.00.
Regime flags: participation below its two-year median.
Not in today's book."""

_B = """Name: CRWD (software side). Session: 2026-09-04.
Grade: B. Votes: +1.0.
fundamental analyst: stance +0; revenue_yoy +0.212, revenue_qoq +0.048, gross_margin +0.751, revenue_acceleration -0.012, sessions_since_earnings +8.000.
technical analyst: stance +1; ema21_distance +0.031, stack_order +3.000, weekly_trend +1.000, daily_trend +1.000, range_position_60 +0.880, support_distance +0.062, momentum_120 +0.180.
sentiment analyst: stance +0; tone_guidance +0.000, tone_demand +1.000, tone_guidance_change +0.000, tone_pricing +0.000, tone_capex +0.000.
rotation analyst: stance +0; no data for this name.
Regime: AI participation percentile 0.00, AI-vs-software correlation -0.52, novelty z +4.8, rotation leader software, AI basket drawdown -0.223, selection confidence 0.50, exposure 1.00.
Not in today's book."""

# The desk's measurement vocabulary must not leak into the brief: a field
# name (an identifier of words joined by underscores, digits allowed) or a
# raw signed figure. A bare count like "three analysts" or "21-day" is
# words, not a leak.
_FIELD = re.compile(r"\b[a-zA-Z]+\d*_[a-zA-Z]+(?:_[a-zA-Z]+)*\b")
_RAW_FIGURE = re.compile(r"(?<![A-Za-z_])[+-]\d+\.\d+")


def _plain_words(text: str) -> list[str]:
    """Return the field names and raw signed figures leaking into `text`."""
    return _FIELD.findall(text) + _RAW_FIGURE.findall(text)


@pytest.fixture(scope="module")
def narrator(structured_llm):
    return DeskNarrator(structured_llm)


# An A+ name with three bullish analysts is owned, for the reasons given.
async def test_a_plus_reads_as_own(narrator):
    brief = narrator.brief_sync(_A_PLUS, "A+")
    assert brief is not None
    assert brief.stance == OWN
    text = " ".join([brief.verdict, brief.reasoning, brief.risks, brief.watch])
    assert _plain_words(text) == [], text
    low = brief.reasoning.lower()
    assert "sentiment" in low or "release" in low or "guidance" in low, brief
    assert "fundamental" in low or "revenue" in low or "filing" in low, brief


# A C name with bearish filings and a bearish tape is avoided, and the brief
# says what is bearish.
async def test_c_reads_as_avoid(narrator):
    brief = narrator.brief_sync(_C, "C")
    assert brief is not None
    assert brief.stance == AVOID
    text = " ".join([brief.verdict, brief.reasoning, brief.risks, brief.watch])
    assert _plain_words(text) == [], text
    assert "bearish" in brief.reasoning.lower() or "negative" in brief.reasoning.lower()


# A B name is a wait, and the watch line names an analyst.
async def test_b_reads_as_wait(narrator):
    brief = narrator.brief_sync(_B, "B")
    assert brief is not None
    assert brief.stance == WAIT
    text = " ".join([brief.verdict, brief.reasoning, brief.risks, brief.watch])
    assert _plain_words(text) == [], text
    low = brief.watch.lower()
    assert any(
        w in low for w in ("fundamental", "sentiment", "technical", "release", "filing")
    )
