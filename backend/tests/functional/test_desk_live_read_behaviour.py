"""Does the live technical read say what the analyst measured, and only that?

The live read is the drill-down's plain-language version of the technical
analyst's reading at the live price, and the prompt claims the same three
things as the nightly read, each a case here:

- **Nothing is left out.** The read must cover the short, medium and long
  horizons, not just the loudest line.
- **The levels are named, not only distanced.** The read must say what the
  nearest support is (the 200-day average here) and what the nearest
  resistance is (a swing high), each with how far away.
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

_SYSTEM = render("trading/desk_live_read")

_FEATURES = {
    "short": [
        "the 21/50 EMAs are squeezing upward (a bullish cross is forming)",
        "12.5% below nearest support — the 200-day average",
        "15.0% above nearest resistance — a swing high",
        "12.6% above the 21-day EMA",
        "daily trend up",
        "full bullish EMA stack (9 > 21 > 50 > 200)",
        "4.9% below the 50-day EMA",
        "sitting 55% up in its 60-day range",
    ],
    "medium": ["weekly trend up", "the weekly 9 EMA is above the 21"],
    "long": [
        "3.1% above its 52-week high · 12.5% below its 52-week low",
        "2.3% below the 200-day EMA",
        "slow momentum positive",
    ],
}

_FIELD = re.compile(r"\b[a-zA-Z]+\d*_[a-zA-Z]+(?:_[a-zA-Z]+)*\b")
_RAW_FIGURE = re.compile(r"(?<![A-Za-z_])[+-]\d+\.\d+")


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
