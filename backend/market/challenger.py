"""Growth-gap augmentation and the live/shadow desk record boundary.

Current availability boundary: an explicit `asof` bounds every underlying
partition read. None means latest, even when a newer extraction ends at an old
bar date. Each year's fit requires 500 labels published before that year and
three publication years. First-report labels retain their filing dates; later
amendments cannot replace them. This is not complete historical causality:
within-vintage feature revisions and historical membership remain separate
validation gaps. Per-session ranking does not remedy those input limitations.
This loader correction does not rerun or repair earlier study outputs.

Historical design and promotion record
--------------------------------------

The rule is frozen. A change that looks better in the history is
development evidence until it has a forward record of its own, so a
candidate runs here as a shadow desk: the same analysts, the same
grading, the same sizing, with one input changed, written into the
nightly record beside the rule's book and never traded. The scorecard
(`backend/cli/market_scorecard.py --records`) reads both books from
the records and prices them forward, so after a season the two tracks
can be compared on real days with identical execution assumptions.

The shadow is frozen at every decision point, not just once: the
expectation it adds is walked forward (each year's learner is trained
on the reports of the years before it), the blend of it with the
valuation analyst ranks each session against its own cross-section
rather than against the whole history, and the record is written once
and never rewritten. A change that looks better can therefore be
believed only once the forward track, pricing the frozen books on real
days, says the same.

The first challenger was the one `market_expectations` found: the
valuation analyst blended with the gap between the learner's expected
revenue growth and the growth the price implies. The learner is
trained on every report filed before the current year and asked on
today's features, which is the walk-forward rule the study used. On
2026-09-10 the operator promoted it into the live rule
(`desk.LIVE_INPUTS`); the plain rule is the shadow from the next
record, so the two tracks keep the same real days and the scorecard
prices each strategy by name across the swap.
"""

import warnings
from dataclasses import replace
from datetime import date

import numpy as np

NAME = "expectations-gap"
PLAIN = "plain-value"


# The strategy a report is, by what it carries beyond the analysts.
def strategy(report) -> str:
    """Return the report's strategy name."""
    inputs = tuple(getattr(report, "inputs", ()) or ())
    return "+".join(inputs) if inputs else PLAIN


# Compute the gap on the book while preserving the caller's extraction cutoff.
def expectations_gap(store, book, asof: date | None = None) -> np.ndarray:
    """Return (T, N) model growth minus the relative-P/S proxy on the book."""
    from backend.cli import market_expectations as mx

    panel, sector = mx._universe_panel(store, False, asof=asof)
    udates = [d.astype("datetime64[D]").astype(object) for d in panel.dates]
    records, quarters, reactions = mx._records(store, panel, udates, asof=asof)
    fund, fidx, tone, tidx, _beta, mom, ratios = mx._features(
        store, panel, records, asof=asof
    )
    feats, implied = mx._block(panel, sector, fund, fidx, tone, tidx, mom, ratios)
    x, y, meta = mx._dataset(panel, udates, quarters, reactions, feats)
    meta_year = np.array([m[2] for m in meta])
    years = sorted({d.year for d in udates})
    expected = mx._carried(
        udates,
        x,
        y,
        meta_year,
        years,
        feats,
        3,
        available_dates=[m[3] for m in meta],
    )
    with np.errstate(all="ignore"):
        gap = expected - implied
    return mx._onto_book(gap, panel, book, udates)


# The analysts with the valuation analyst blended with `gap`: each
# session's rank of the analyst's score averaged with that session's rank
# of the gap, so the blend is frozen to its own cross-section.
def with_gap(opinions: dict, gap: np.ndarray) -> dict:
    """Return the opinions with the value analyst blended with the gap."""
    from backend.market import baselines

    out = dict(opinions)
    value = out["value"]
    # A name the gap does not cover keeps the plain valuation rank: a NaN
    # here erased the value stance, and with it the bearish veto.
    ranked = np.stack(
        [baselines.percentile_rank(value.scores), baselines.percentile_rank(gap)]
    )
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        blended = np.nanmean(ranked, axis=0)
    evidence = dict(value.evidence)
    evidence["expectations_gap"] = gap
    out["value"] = replace(value, scores=blended, evidence=evidence)
    return out


# The challenger's block for the nightly record: its book and grades,
# in the same shape as the rule's, so the scorecard prices both alike.
def record_block(challenger) -> dict:
    """Return the JSON-ready challenger block."""
    panel = challenger.panel
    last = len(panel.dates) - 1
    return {
        "name": strategy(challenger),
        "book": [
            {
                "ticker": s.position.ticker,
                "grade": s.grade,
                "weight": float(s.weight),
            }
            for s in challenger.book
        ],
        "grades": {
            ticker: challenger.graded.letter(last, column)
            for column, ticker in enumerate(panel.tickers)
            if ticker != panel.benchmark
        },
    }
