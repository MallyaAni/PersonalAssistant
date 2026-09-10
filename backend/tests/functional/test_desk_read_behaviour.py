"""Does the desk's read say all of what the desk measured, and only that?

The read is the drill-down's plain-language version of the whole evidence,
and the prompt claims three things, each a case here:

- **Nothing is left out.** The read for a name with strong fundamentals, a
  rising daily tape and positive guidance must touch all three analysts,
  not just the loudest. An omitted analyst is a hidden trigger.
- **The levels are named, not only distanced.** The read must say what the
  nearest support is (the 200-day average here) and what the nearest
  resistance is (a swing high), each with how far away, rather than a bare
  "nearest support".
- **The desk's vocabulary does not leak.** No field name such as
  "revenue_yoy" or "support_kind", and no raw signed figure such as
  "+1.551" or "-3.000". A user reads "revenue grew 155%", not a parameter
  list.

The evidence texts are shaped exactly as `brief_text` writes them, with
the level kinds the technical analyst cites for the nearest support and
resistance.
"""

# ruff: noqa: E501
import re

import pytest

from backend.agents.trading.desk.narrative import DeskNarrator

pytestmark = pytest.mark.asyncio

_A_PLUS = """Name: SNDK (ai side). Session: 2026-09-04.
Grade: A+. Votes: +3.0.
fundamental analyst: stance +1; revenue_yoy +1.551, revenue_qoq +0.410, gross_margin +0.846, revenue_acceleration +0.295, eps_change_yoy +5.000, net_margin +0.770, sessions_since_earnings +21.000.
technical analyst: stance +1; ema21_distance +0.126, stack_order +3.000, weekly_trend +1.000, daily_trend +1.000, range_position_60 +0.547, support_distance +0.125, resistance_distance +0.150, momentum_120 +0.692, support_level +112.500, support_kind +3.000, resistance_level +137.000, resistance_kind +1.000.
sentiment analyst: stance +1; tone_guidance +1.000, tone_demand +1.000, tone_guidance_change +0.000, tone_pricing +1.000, tone_capex +0.000.
rotation analyst: stance +0; no data for this name.
Regime: AI participation percentile 0.00, AI-vs-software correlation -0.52, novelty z +4.8, rotation leader software, AI basket drawdown -0.223, selection confidence 0.50, exposure 1.00.
Regime flags: participation below its two-year median.
In today's book at weight 0.076."""

_C = """Name: IREN (ai side). Session: 2026-09-04.
Grade: C. Votes: -2.0.
fundamental analyst: stance -1; revenue_yoy -0.311, revenue_qoq -0.054, gross_margin +0.000, revenue_acceleration -0.311, eps_change_yoy -3.458, net_margin -4.984, sessions_since_earnings +5.000.
technical analyst: stance -1; ema21_distance +0.097, stack_order -1.000, weekly_trend -1.000, daily_trend -1.000, range_position_60 +0.310, support_distance +0.041, resistance_distance +0.032, momentum_120 -0.054, support_level +108.000, support_kind +2.000, resistance_level +114.000, resistance_kind +1.000.
sentiment analyst: stance +0; tone_guidance +1.000, tone_demand +1.000, tone_guidance_change +0.000, tone_pricing +1.000, tone_capex +1.000.
rotation analyst: stance +0; no data for this name.
Regime: AI participation percentile 0.00, AI-vs-software correlation -0.52, novelty z +4.8, rotation leader software, AI basket drawdown -0.223, selection confidence 0.50, exposure 1.00.
Not in today's book."""

# The desk's measurement vocabulary must not leak into the read: a field
# name (an identifier of words joined by underscores, digits allowed) or a
# raw signed figure. A bare count like "three analysts" or "21-day" is
# words, not a leak.
_FIELD = re.compile(r"\b[a-zA-Z]+\d*_[a-zA-Z]+(?:_[a-zA-Z]+)*\b")
_RAW_FIGURE = re.compile(r"(?<![A-Za-z_])[+-]\d+\.\d+")
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")

# A plain-word mention of each analyst with data, so a read that skips an
# analyst fails rather than passing on its own length.
_FUNDAMENTAL_WORDS = ("revenue", "sales", "growth", "grow", "margin", "earnings")
_TECHNICAL_WORDS = ("trend", "ema", "average", "stack", "momentum", "range")
_SENTIMENT_WORDS = ("guidance", "tone", "demand", "pricing")


@pytest.fixture(scope="module")
def narrator(llm):
    return DeskNarrator(llm)


# The read covers every analyst that has data, names the levels by what
# they are with their distances, and never leaks the desk's vocabulary.
async def test_read_covers_the_whole_evidence(narrator):
    read = narrator.read_sync(_A_PLUS)
    assert read is not None
    assert len(read) > 120
    assert not _FIELD.findall(read), read
    assert not _RAW_FIGURE.findall(read), read
    assert any(w in read.lower() for w in _FUNDAMENTAL_WORDS), read
    assert any(w in read.lower() for w in _TECHNICAL_WORDS), read
    assert any(w in read.lower() for w in _SENTIMENT_WORDS), read
    # The nearest support is the 200-day average (kind 3); the nearest
    # resistance is a swing point (kind 1). Both must be named as such,
    # each with a distance.
    assert re.search(r"support.{0,60}200.{0,20}day", read.lower()) is not None, read
    assert re.search(r"resistance.{0,60}(swing|high)", read.lower()) is not None, read
    assert len(_PERCENT.findall(read)) >= 2, read


# A bearish name reads bearish in plain words, with no field names and no
# raw figures, and its support is named by what it is (the 50-day average).
async def test_bearish_read_stays_in_plain_words(narrator):
    read = narrator.read_sync(_C)
    assert read is not None
    assert len(read) > 80
    assert not _FIELD.findall(read), read
    assert not _RAW_FIGURE.findall(read), read
    assert re.search(r"support.{0,60}50.{0,20}day", read.lower()) is not None, read
