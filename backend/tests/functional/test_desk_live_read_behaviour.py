"""Does the live technical read say what the analyst measured, and only that?

The live read is the drill-down's plain-language version of the technical
analyst's reading at the live price, and the prompt claims the same three
things as the nightly read, each a case here:

- **Nothing is left out.** The read must cover the short, medium and long
  horizons, not just the loudest line.
- **The levels are named, not only distanced.** The read must say what the
  nearest support is (the 200-day average here) and what the nearest
  resistance is (a swing high), each with how far away.
- **The 200-day simple average is its own line.** The long horizon names
  both the 200-day EMA and the 200-day SMA, and the read must not fold the
  two into one.
- **A named daily candle is read as a signal.** A bearish engulfing at the
  close is a reversal cue for the weekly turn, and the read must say what
  it argues rather than list the pattern.
- **The desk's vocabulary does not leak.** No field name and no raw signed
  figure; a user reads "12.6% above the 21-day average", not a parameter
  list.

The features are the deterministic lines `live_technical.lines` renders for
a name — the same text the model is given.
"""

# ruff: noqa: E501
import re

from backend.api.v1.market import _model_live_read
from backend.core.prompts import render
from backend.market import live_technical

_SYSTEM = render("trading/desk_live_read")

_FEATURES = {
    "short": [
        "the 21/50 EMAs are squeezing upward (a bullish cross is forming)",
        "nearest support is 12.5% below the price — the 200-day average",
        "nearest resistance is 15.0% above the price — a swing high",
        "12.6% above the 21-day EMA",
        "daily trend up",
        "full bullish EMA stack (9 > 21 > 50 > 200)",
        "4.9% below the 50-day EMA",
        "sitting 55% up in its 60-day range",
        "today's daily candle is a bearish engulfing, 2.1x the prior session's body",
    ],
    "medium": ["weekly trend up", "the weekly 9 EMA is above the 21"],
    "long": [
        "3.1% below its 52-week high · 12.5% above its 52-week low",
        "2.3% below the 200-day EMA",
        "2.3% below the 200-day simple average",
        "slow momentum positive",
    ],
}

_FIELD = re.compile(r"\b[a-zA-Z]+\d*_[a-zA-Z]+(?:_[a-zA-Z]+)*\b")
_RAW_FIGURE = re.compile(r"(?<![A-Za-z_])[+-]\d+\.\d+")


# The model preserves the evidence and distinguishes the levels from the averages.
def test_live_read_covers_horizons_and_levels(llm):
    read = _model_live_read(_FEATURES, llm, _SYSTEM)
    assert read is not None
    assert len(read) > 120
    assert not _FIELD.findall(read), read
    assert not _RAW_FIGURE.findall(read), read
    low = read.lower()
    # The nearest support is the 200-day average; the nearest resistance is
    # a swing point. Both are named as such, each with a distance.
    assert re.search(r"support.{0,60}200.{0,20}day", low) is not None, read
    assert re.search(r"resistance.{0,60}(swing|high)", low) is not None, read
    # The medium and long horizons are read too, not just the short term.
    assert "week" in low, read
    assert any(word in low for word in ("52", "momentum", "200-day")), read
    # The 200-day simple average is named as its own line, not only the EMA.
    assert re.search(r"200.{0,20}simple.{0,20}average", low) is not None, read
    # The named daily candle is covered and read as a signal, not skipped:
    # a bearish engulfing at today's close is the daily evidence for the
    # weekly turn, and the read must say what it argues.
    assert "engulf" in low, read
    assert re.search(r"(revers|turn|bearish|lower|down)", low) is not None, read
    assert "monthly chart" not in low, read
    assert "hourly chart" not in low, read


# The real model preserves converted distances from the actual feature-to-text path.
def test_live_read_preserves_converted_price_distances(llm):
    features = live_technical.lines(
        {
            "short": {
                "support_distance": 0.2,
                "support_kind": 3,
                "resistance_distance": 0.25,
                "resistance_kind": 1,
            },
            "medium": {"weekly_trend": -1},
            "long": {"high_52w_distance": -0.796, "low_52w_distance": 1.7402},
        }
    )
    read = _model_live_read(features, llm, _SYSTEM)
    assert read is not None
    assert "54.9%" in read, read
    assert "469.8%" in read, read
    assert "79.6%" not in read, read
    assert "174.0%" not in read, read
    assert re.search(
        r"(resistance.{0,100}above|below.{0,100}resistance)", read.lower()
    ), read
