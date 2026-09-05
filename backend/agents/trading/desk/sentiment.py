"""The sentiment analyst: what the company said in its last release.

Reads the release-tone layer the DeepSeek reader produced from earnings
press releases (guidance, demand, and the change in guidance tone from the
prior release). This is the strongest signal on the book: beta-adjusted rank
IC 0.035 (t 2.7) at 20 sessions and 0.071 (t 3.1) at 60 on the 90 names,
with pricing tone added as a fourth field on 2026-09-05 because the reader
returns -1/0/1 per field and three fields left too many names tied. A name
with no scored release gets no view, not a neutral one, so its absence is
visible to the grade.
"""

import numpy as np

from backend.agents.trading.desk.opinions import Opinion
from backend.market import baselines, language

NAME = "sentiment"
SCORED = ("tone_guidance", "tone_demand", "tone_guidance_change", "tone_pricing")
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
