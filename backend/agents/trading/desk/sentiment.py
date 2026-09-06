"""The sentiment analyst: what the company said in its last release.

Reads the release-tone layer the DeepSeek reader produced from earnings
press releases (guidance, demand, and the change in guidance tone from the
prior release), with pricing tone added as a fourth field on 2026-09-05
because the reader returns -1/0/1 per field and three fields left too many
names tied. A name with no scored release gets no view, not a neutral one,
so its absence is visible to the grade.

What it is worth, and where
---------------------------
Tone alone carries a beta-adjusted rank IC of 0.039 (t 3.0) at twenty
sessions and 0.029 (t 1.3) at sixty. The twenty-session number is the real
one; the sixty-session claim this file used to make does not survive a
careful measurement, and tone is not significant at sixty in any subset of
the book. That is a fit, not a limitation: the book rebalances every
twenty sessions.

Taken out of the desk entirely, the summed conviction drops from 0.046
(t 3.2) to 0.038 (t 2.6) at twenty sessions and its net Sharpe from 0.79
to 0.51. Tone earns its place.

The liquidity question
----------------------
Avramov, Cheng and Metzker report that machine predictability in equities
concentrates in names nobody can trade. Tone does decay with liquidity,
measured inside each third of the book so the cross-section size is held
equal, at twenty sessions:

| the least traded third | +0.048 (t +2.5) |
| the middle third       | +0.031 (t +1.6) |
| the most traded third  | +0.026 (t +1.3) |

Three things say to accept this rather than correct for it. Coverage is
not the cause: 92-96% of the names in every third carry a scored release.
The decay is gentle and tone stays positive everywhere, never turning
against the desk. And reweighting does not pay — tilting tone's weight
toward the thinner names, at five strengths, moves the desk's own score
from 0.0459 to at best 0.0470 while lowering its net Sharpe, and tilting
the other way is worse. The gradient is written down here rather than
coded around.

The desk as a whole passes the same test cleanly, which is the point that
matters: its rank IC is 0.058, 0.054 and 0.051 across the three liquidity
thirds at twenty sessions. It is not being paid in illiquidity.
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
