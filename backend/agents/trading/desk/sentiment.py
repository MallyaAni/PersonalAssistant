"""The sentiment analyst: what the company said in its last release.

Reads the release-tone layer the DeepSeek reader produced from earnings
press releases (guidance, demand, and the change in guidance tone from the
prior release). This is the strongest signal on the book: beta-adjusted rank
IC 0.048 at 20 sessions and 0.095 at 60 on the AI-and-software names. A name
with no scored release gets no view, not a neutral one, so its absence is
visible to the grade.
"""

import numpy as np

from backend.agents.trading.desk.opinions import Opinion
from backend.market import baselines, language

NAME = "sentiment"
SCORED = ("tone_guidance", "tone_demand", "tone_guidance_change")
CITED = SCORED + (
    "tone_pricing",
    "tone_capex",
    "tone_supply_constrained",
    "tone_demand_change",
)


# Score every name with a scored release from its tone; no view otherwise.
def opine(tone: np.ndarray) -> Opinion:
    """Return the sentiment analyst's Opinion from the tone feature block."""
    names = language.FEATURE_NAMES
    has = tone[:, :, names.index("has_tone")] > 0
    legs = [
        np.where(has, tone[:, :, names.index(n)].astype(float), np.nan) for n in SCORED
    ]
    scores = baselines.rank_blend(*legs)
    evidence = {
        n: np.where(has, tone[:, :, names.index(n)].astype(float), np.nan)
        for n in CITED
        if n in names
    }
    return Opinion(NAME, scores, evidence)
