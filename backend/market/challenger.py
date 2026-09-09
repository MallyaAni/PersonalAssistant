"""The challenger: the desk with one input changed, run beside the rule, never traded.

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

The first challenger is the one `market_expectations` found: the
valuation analyst blended with the gap between the learner's expected
revenue growth and the growth the price implies. The learner is
trained on every report filed before the current year and asked on
today's features, which is the walk-forward rule the study used.
"""

from dataclasses import replace

import numpy as np

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import grading, risk

NAME = "expectations-gap"


# The gap on the book's panel for every session, from the study's
# pipeline on the universe.
def expectations_gap(store, book) -> np.ndarray:
    """Return (T, N) expected growth less price-implied growth on the book."""
    from backend.cli import market_expectations as mx

    panel, sector = mx._universe_panel(store, False)
    udates = [d.astype("datetime64[D]").astype(object) for d in panel.dates]
    records, quarters, reactions = mx._records(store, panel, udates)
    fund, fidx, tone, tidx, _beta, mom, ratios = mx._features(store, panel, records)
    feats, implied = mx._block(panel, sector, fund, fidx, tone, tidx, mom, ratios)
    x, y, meta = mx._dataset(panel, udates, quarters, reactions, feats)
    if len(y) < 500:
        return np.full(book.adj_close.shape, np.nan)
    meta_year = np.array([m[2] for m in meta])
    years = sorted(set(meta_year)) + [udates[-1].year]
    expected = mx._carried(udates, x, y, meta_year, sorted(set(years)), feats, 3)
    with np.errstate(all="ignore"):
        gap = expected - implied
    return mx._onto_book(gap, panel, book, udates)


# The rule's report with its valuation analyst blended with `gap`: the
# same grading and sizing, one input changed.
def report_with_gap(report, gap: np.ndarray):
    """Return the challenger's DeskReport from the rule's and the gap."""
    from backend.market import baselines

    opinions = dict(report.opinions)
    value = opinions["value"]
    blended = baselines.rank_blend(value.scores, gap)
    evidence = dict(value.evidence)
    evidence["expectations_gap"] = gap
    opinions["value"] = replace(value, scores=blended, evidence=evidence)
    graded = grading.grade(
        opinions["fundamental"],
        opinions["technical"],
        opinions["sentiment"],
        report.regime.rotation,
        opinions["value"],
        grading.ANALYST_WEIGHTS,
    )
    scores = graded.as_scores(trading_desk.blended(opinions))
    last = len(report.panel.dates) - 1
    book = risk.size(
        scores[last], graded.grades[last], report.panel, report.regime.today()
    )
    return replace(report, opinions=opinions, graded=graded, scores=scores, book=book)


# The challenger's block for the nightly record: its book and grades,
# in the same shape as the rule's, so the scorecard prices both alike.
def record_block(challenger) -> dict:
    """Return the JSON-ready challenger block."""
    panel = challenger.panel
    last = len(panel.dates) - 1
    return {
        "name": NAME,
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
