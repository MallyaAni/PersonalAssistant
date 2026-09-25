"""The fundamental analyst: what the filings say.

Reads the point-in-time EDGAR layer. The score is the blend that measured
positive beta-adjusted (revenue growth, sequential growth, gross margin,
acceleration); the balance-sheet instants (share issuance, asset growth,
book-to-market) measured nothing on this universe and are cited, not scored.

Versioned calculation paths feed this analyst. `opine` reads the frozen EDGAR feature
block (`edgar.edgar_features`), which replaces any missing ratio with a zero
and then treats that fabricated zero as a valid leg whenever revenue is
known: a real correctness defect, kept only for explicit side-by-side
comparison and for the frozen callers. `opine_corrected` reads the corrected
feature adapter (`market/fundamental_features`), built from the stored
as-of filing versions, where a missing ratio stays NaN and a genuine zero
stays a valid zero. Version 2 also requires margins to match retained full
intervals without hiding ambiguity at the latest common end. Growth and the
scoring blend are unchanged; legacy currency and annual-partition limitations
remain. The research default retains that /2 path. The explicitly selected
`opine_current` /3 path additionally withholds features behind the newest
reported revenue period in the supplied data and resets held votes when their
scored inputs become ineligible. It does not supply newer financial definitions
or qualify erased units, historical availability, or investment performance.

`opine_qualified` is a separate research-only USD customer-revenue profile. It
retains full source/unit/interval evidence and does not replace either current
path or the valuation analyst's inputs.
"""

from copy import deepcopy

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
CORRECTED_SOURCE = "fundamentals-features/2"
CURRENT_SOURCE = "fundamentals-features/3"
QUALIFIED_SOURCE = "fundamentals-qualified/1"
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
    score rather than a fabricated one. Its raw stance is neutral, but this
    retained /2 path can persist a previous vote until confirmation. The cited
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


# Validate the named feature/date contract before labelling an opinion period-checked.
def _validate_eligibility(features):
    from backend.market.fundamental_features import FEATURE_NAMES

    eligibility = features.eligibility
    if eligibility is None:
        raise ValueError("current fundamentals require reporting-period eligibility")
    shape = features.values.shape
    if (
        len(shape) != 3
        or len(features.names) != len(FEATURE_NAMES)
        or set(features.names) != set(FEATURE_NAMES)
        or shape[-1] != len(features.names)
        or features.available.shape != shape[:2]
        or features.staleness.shape != shape[:2]
        or features.period_ends.shape != shape
        or eligibility.input_period_ends.shape != shape
        or eligibility.reasons.shape != shape
        or eligibility.target_period_ends.shape != shape[:2]
        or any(
            values.dtype != np.dtype("datetime64[D]")
            for values in (
                features.period_ends,
                eligibility.input_period_ends,
                eligibility.target_period_ends,
            )
        )
    ):
        raise ValueError("fundamental eligibility has invalid names, shapes or dates")
    reasons = eligibility.reasons
    accepted = reasons == "accepted"
    target = eligibility.target_period_ends[..., None]
    original = eligibility.input_period_ends
    if (
        not np.isin(
            reasons,
            (
                "accepted",
                "older_revenue_period",
                "period_mismatch",
                "not_computable",
                "no_revenue_period",
            ),
        ).all()
        or not np.array_equal(accepted, np.isfinite(features.values))
        or np.isinf(features.values).any()
        or np.any(accepted & ((original != target) | (features.period_ends != target)))
        or np.any(~accepted & ~np.isnat(features.period_ends))
        or np.any((reasons == "no_revenue_period") != np.isnat(target))
        or np.any((reasons == "older_revenue_period") & ~(original < target))
        or np.any((reasons == "period_mismatch") & (original == target))
        or np.any((reasons == "not_computable") & ~np.isnat(original))
    ):
        raise ValueError(
            "fundamental eligibility contradicts feature values or periods"
        )
    return eligibility


# Score period-checked inputs and restart confirmation whenever a scored leg is lost.
def opine_current(features) -> Opinion:
    """Return the explicitly versioned period-checked opinion and reset evidence."""
    eligibility = _validate_eligibility(features)
    opinion = opine_corrected(features)
    admitted = np.stack([np.isfinite(features.feature(n)) for n in SCORED], axis=0)
    resets = ~np.isfinite(opinion.scores)
    # A finite remaining score is not permission to retain a vote that relied
    # on a newly rejected leg. Losing cited-only inputs does not reset a vote.
    resets[1:] |= np.any(admitted[:, :-1] & ~admitted[:, 1:], axis=0)
    return Opinion(
        NAME,
        opinion.scores,
        opinion.evidence,
        meta={
            **opinion.meta,
            "source": CURRENT_SOURCE,
            "eligibility": eligibility,
            "eligibility_names": tuple(features.names),
        },
        stance_resets=resets,
    )


# Validate qualified numerical readings against their explicit per-cell source evidence.
def opine_qualified(result) -> Opinion:
    from backend.market.qualified_fundamentals import (
        PROFILE_ID,
        REVENUE_TAG,
        SELECTION_POLICY,
        QualifiedFeatures,
    )

    if not isinstance(result, QualifiedFeatures) or result.profile_id != PROFILE_ID:
        raise ValueError("qualified features require the declared source profile")
    features = result.features
    _validate_eligibility(features)
    rows = result.observations
    if (
        len(rows) != features.values.shape[0]
        or len(result.decision_dates) != len(rows)
        or len(result.tickers) != features.values.shape[1]
        or any(len(row) != len(result.tickers) for row in rows)
    ):
        raise ValueError("qualified evidence must align with every feature cell")
    for t, row in enumerate(rows):
        for column, observation in enumerate(row):
            if (
                observation.get("profile_id") != PROFILE_ID
                or observation.get("ticker") != result.tickers[column]
                or observation.get("decision") != result.decision_dates[t]
                or observation.get("unit") != "USD"
                or observation.get("revenue_tag") != REVENUE_TAG
                or observation.get("period_kind") != "quarter"
                or observation.get("selection_policy") != SELECTION_POLICY
                or observation.get("revenue_period_end")
                != (
                    _period_string(features.eligibility.target_period_ends[t, column])
                    or None
                )
                or observation.get("historical_authenticity_verified") is not False
                or set(observation.get("features", {})) != set(features.names)
            ):
                raise ValueError(
                    "qualified evidence has an invalid profile or feature set"
                )
            for k, name in enumerate(features.names):
                cell = observation["features"][name]
                value = features.values[t, column, k]
                if np.isfinite(value):
                    period = cell.get("period") or {}
                    if (
                        cell.get("status") != "accepted"
                        or type(cell.get("value")) not in (int, float)
                        or cell["value"] != value
                        or period.get("end") != str(features.period_ends[t, column, k])
                        or period.get("unit") != "USD"
                        or not observation.get("source_sha256")
                        or not cell.get("inputs")
                    ):
                        raise ValueError(
                            "qualified evidence contradicts an accepted value"
                        )
                elif cell.get("value") is not None or cell.get("status") == "accepted":
                    raise ValueError("qualified evidence invents an unavailable value")
    opinion = opine_current(features)
    return Opinion(
        NAME,
        opinion.scores,
        opinion.evidence,
        meta={
            **opinion.meta,
            "source": QUALIFIED_SOURCE,
            "qualification": deepcopy(rows),
        },
        stance_resets=opinion.stance_resets,
    )


# Return independently owned source evidence alongside archive and vote provenance.
def cited_qualification(opinion: Opinion, t: int, column: int) -> dict:
    if (
        opinion.meta.get("source") != QUALIFIED_SOURCE
        or "qualification" not in opinion.meta
    ):
        raise ValueError("qualified fundamental source lacks its evidence")
    row = deepcopy(opinion.meta["qualification"][t][column])
    archive = (opinion.meta.get("source_archives") or {}).get(row["ticker"])
    if row.get("source_sha256") is not None and archive is None:
        raise ValueError("qualified source evidence requires its persisted archive")
    if archive is not None and (
        archive.get("source_sha256") != row["source_sha256"]
        or archive.get("cik") != row["cik"]
    ):
        raise ValueError("qualified evidence does not match its source archive")
    return {
        **row,
        "archive": deepcopy(archive),
        "score_available": bool(np.isfinite(opinion.scores[t, column])),
        "vote_reset": bool(opinion.stance_resets[t, column]),
    }


# Convert a fiscal end without inventing a date where the calculation has none.
def _period_string(value) -> str:
    end = np.datetime64(value, "D")
    return "" if np.isnat(end) else str(end)


# Retain accepted and rejected inputs even for a name without a score.
def cited_eligibility(opinion: Opinion, t: int, column: int) -> dict:
    """Return JSON-safe reporting-period decisions, not full financial qualification."""
    eligibility = opinion.meta.get("eligibility")
    names = opinion.meta.get("eligibility_names")
    if (
        opinion.meta.get("source") not in (CURRENT_SOURCE, QUALIFIED_SOURCE)
        or eligibility is None
        or not names
        or opinion.stance_resets is None
    ):
        raise ValueError("current fundamental source lacks eligibility evidence")
    return {
        "revenue_period_end": _period_string(eligibility.target_period_ends[t, column]),
        "score_available": bool(np.isfinite(opinion.scores[t, column])),
        "vote_reset": bool(opinion.stance_resets[t, column]),
        "features": {
            name: {
                "status": str(eligibility.reasons[t, column, names.index(name)]),
                "input_period_end": _period_string(
                    eligibility.input_period_ends[t, column, names.index(name)]
                ),
            }
            for name in CITED_CORRECTED
        },
    }


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
