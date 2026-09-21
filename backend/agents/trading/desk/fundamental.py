"""The fundamental analyst: what the filings say.

Reads the point-in-time EDGAR layer. The score is the blend that measured
positive beta-adjusted (revenue growth, sequential growth, gross margin,
acceleration); the balance-sheet instants (share issuance, asset growth,
book-to-market) measured nothing on this universe and are cited, not scored.

Two data sources feed this analyst. `opine` reads the frozen EDGAR feature
block (`edgar.edgar_features`), which replaces any missing ratio with a zero
and then treats that fabricated zero as a valid leg whenever revenue is
known: a real correctness defect, kept only for explicit side-by-side
comparison and for the frozen callers. `opine_corrected` reads the corrected
feature adapter (`market/fundamental_features`), built from the stored
as-of filing versions, where a missing ratio stays NaN and a genuine zero
stays a valid zero. The desk runs the corrected path; `opine` remains for
comparisons.
"""

import numpy as np

from backend.agents.trading.desk.opinions import Opinion
from backend.market import baselines, edgar

NAME = "fundamental"
SCORED = ("revenue_yoy", "revenue_qoq", "gross_margin", "revenue_acceleration")
CITED = SCORED + (
    "eps_change_yoy",
    "net_margin",
    "capex_to_revenue",
    "share_issuance",
    "asset_growth",
    "book_to_market",
    "sessions_since_earnings",
)
# The corrected features carry the same economic names as the frozen path
# where they overlap; the EPS and balance-sheet metrics of the frozen block
# are not in the corrected adapter and are deliberately omitted rather than
# manufactured.
CITED_CORRECTED = (
    "revenue_yoy",
    "revenue_qoq",
    "revenue_acceleration",
    "gross_margin",
    "net_margin",
    "capex_to_revenue",
    "ocf_to_revenue",
)

# The data-source versions the two paths draw on, carried through the
# DeskReport and the nightly record so a figure is never presented under a
# source it was not measured with. These identify data; paper.POLICY_VERSION
# identifies execution, while report.inputs names analyst augmentations.
CORRECTED_SOURCE = "fundamentals-features/1"
LEGACY_SOURCE = "edgar-frozen"


class FundamentalSourceError(RuntimeError):
    """Raised when the corrected fundamental source is absent or unreadable.

    The desk must not write a book whose fundamental analyst silently lost
    its whole input: that would rank the remaining analysts on a name set
    they were never measured on. A caller that has no versions to read must
    say so before assembly rather than let the desk pretend otherwise.
    """


# Score every name from its filed fundamentals; no view where none are filed.
def opine(extra: np.ndarray) -> Opinion:
    """Return the fundamental analyst's Opinion from the EDGAR feature block."""
    names = edgar.FEATURE_NAMES
    has = extra[:, :, names.index("has_fundamentals")] > 0
    legs = [
        np.where(has, extra[:, :, names.index(n)].astype(float), np.nan) for n in SCORED
    ]
    # A young filer has no year-over-year figure for its first four
    # quarters; it still has sequential growth and margins. The blend is
    # the mean of the ranks that exist, with at least two of them.
    ranked = np.stack([baselines.percentile_rank(leg) for leg in legs], axis=0)
    known = np.isfinite(ranked).sum(axis=0)
    with np.errstate(all="ignore"):
        scores = np.where(known >= 2, np.nanmean(ranked, axis=0), np.nan)
    evidence = {
        n: np.where(has, extra[:, :, names.index(n)].astype(float), np.nan)
        for n in CITED
    }
    return Opinion(NAME, scores, evidence)


# Score every name from the corrected as-of feature adapter; a missing ratio
# stays missing and contributes no leg, while a genuine zero is a valid leg.
def opine_corrected(features) -> Opinion:
    """Return the fundamental Opinion from the corrected feature adapter.

    Only the finite scored legs are ranked, and a name needs at least two
    real legs to earn a score, exactly as the frozen rule requires. A name
    with no versions, or with fewer than two computable legs, gets no
    score (its stance is neutral) rather than a fabricated one. The cited
    values are the corrected ones, each with its reference fiscal period
    end carried in `meta` so a consumer can see which quarter a figure
    actually refers to. The mean is the sum of the finite ranks divided by
    their count, taken only where two or more real legs exist, so no empty
    slice ever reaches a reduction and nothing needs a suppressed warning.
    """
    legs = np.stack([features.feature(n) for n in SCORED], axis=0)
    ranked = np.stack([baselines.percentile_rank(leg) for leg in legs], axis=0)
    finite = np.isfinite(ranked)
    known = finite.sum(axis=0)
    scores = np.full(ranked.shape[1:], np.nan)
    enough = known >= 2
    with np.errstate(invalid="ignore", divide="ignore"):
        total = np.where(finite, ranked, 0.0).sum(axis=0)
        scores[enough] = total[enough] / known[enough]
    evidence = {n: features.feature(n) for n in CITED_CORRECTED}
    meta = {
        "source": CORRECTED_SOURCE,
        "period_ends": {n: features.feature_period(n) for n in CITED_CORRECTED},
    }
    return Opinion(NAME, scores, evidence, meta=meta)


# One name's cited fiscal period ends at one session, as plain date strings.
def cited_dates(opinion: Opinion, t: int, column: int) -> dict[str, str]:
    """Return {feature: "YYYY-MM-DD"} of the period ends the analyst cites.

    A feature with no computable value has NaT, serialised as an empty
    string so the JSON record stays small and the key is always present.
    """
    ends = (opinion.meta or {}).get("period_ends") or {}
    out = {}
    for name, values in ends.items():
        end = values[t, column]
        out[name] = (
            str(np.datetime64(end, "D")) if not np.isnat(np.datetime64(end)) else ""
        )
    return out
