"""The desk: run every analyst on the book, grade, size, and re-measure.

`run` builds the book's panel, asks each analyst for its opinion, lets the
regime analyst gate the rotation, grades every name, and sizes today's
book. `calibrate` measures what each grade earned in the history, beta-
adjusted, so a grade that stops paying is seen rather than assumed.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np

from backend.agents.trading.desk import (
    fundamental,
    grading,
    regime,
    risk,
    sentiment,
    technical,
)
from backend.agents.trading.desk.grading import GRADES, ORDINAL, Graded
from backend.agents.trading.desk.opinions import Opinion
from backend.agents.trading.desk.regime import RegimeView
from backend.agents.trading.desk.risk import Sized
from backend.market import baselines
from backend.market.harness import HarnessReport, evaluate_scores
from backend.market.model import load_edgar_features, load_tone_features
from backend.market.panel import Panel, build_panel
from backend.market.store import MarketStore
from backend.market.universe import (
    MARKET_BENCHMARK,
    book_sides,
    build_universe,
    theme_map,
)


@dataclass(frozen=True)
class DeskReport:
    """Everything the desk produced for one as-of date."""

    panel: Panel
    sides: dict[str, str]
    opinions: dict[str, Opinion]
    regime: RegimeView
    graded: Graded
    scores: np.ndarray  # (T, N) the graded score with the blended tie-break
    book: list[Sized]

    # The last session's grade and evidence for one name.
    def brief(self, ticker: str) -> dict[str, object]:
        """Return the desk's view of `ticker` today."""
        t = len(self.panel.dates) - 1
        column = self.panel.index(ticker)
        return {
            "ticker": ticker,
            "side": self.sides.get(ticker, "?"),
            "grade": self.graded.letter(t, column),
            "votes": float(self.graded.votes[t, column]),
            "stances": {
                name: int(s[t, column]) for name, s in self.graded.stances.items()
            },
            "evidence": {
                name: opinion.cite(t, column) for name, opinion in self.opinions.items()
            },
        }


# Build the book's panel: the AI-and-software names plus the benchmark.
def book_panel(store: MarketStore, asof: date | None = None) -> tuple[Panel, dict]:
    """Return (panel, sides) for the book universe."""
    universe = build_universe()
    sides = book_sides(universe)
    themes = {t: g for t, g in theme_map(universe).items() if t in sides}
    tickers = tuple(sorted(sides))
    panel = build_panel(store, tickers, MARKET_BENCHMARK, themes, asof=asof)
    return panel, sides


# The blended tie-break inside a grade: the average rank of the analysts'
# scores, so two A names are ordered by how strong their evidence is.
def blended(opinions: dict[str, Opinion]) -> np.ndarray:
    """Return (T, N) average percentile rank across the analysts."""
    return baselines.rank_blend(*[o.scores for o in opinions.values()])


# Run the whole desk as of a date.
def run(store: MarketStore, asof: date | None = None) -> DeskReport:
    """Return the DeskReport for the book as of `asof` (latest if None)."""
    panel, sides = book_panel(store, asof)
    extra = load_edgar_features(store, panel, asof)
    tone = load_tone_features(store, panel, asof)
    view = regime.opine(panel, sides)
    opinions = {
        fundamental.NAME: fundamental.opine(extra),
        technical.NAME: technical.opine(panel, view.ai_trend),
        sentiment.NAME: sentiment.opine(tone),
    }
    graded = grading.grade(
        opinions[fundamental.NAME],
        opinions[technical.NAME],
        opinions[sentiment.NAME],
        view.rotation,
    )
    scores = graded.as_scores(blended(opinions))
    last = len(panel.dates) - 1
    book = risk.size(scores[last], graded.grades[last], panel, view.today())
    return DeskReport(panel, sides, opinions, view, graded, scores, book)


@dataclass(frozen=True)
class GradeStat:
    """What one grade earned: mean forward beta-adjusted return per period."""

    grade: str
    horizon: int
    periods: int
    names_per_period: float
    mean_bp: float
    tstat: float


# Mean beta-adjusted forward return of the names in each grade, sampled
# every `horizon` sessions so the periods do not overlap.
def calibrate(
    report: DeskReport, horizon: int
) -> tuple[list[GradeStat], HarnessReport]:
    """Return per-grade statistics and the harness row for the graded score."""
    panel = report.panel
    forward = panel.forward_residual(horizon)
    excluded = panel.index(panel.benchmark)
    stats: list[GradeStat] = []
    for letter in GRADES:
        ordinal = ORDINAL[letter]
        means: list[float] = []
        counts: list[int] = []
        for t in range(0, len(panel.dates) - horizon, horizon):
            mask = (report.graded.grades[t] == ordinal) & np.isfinite(forward[t])
            mask[excluded] = False
            if mask.sum() == 0:
                continue
            means.append(float(forward[t, mask].mean()))
            counts.append(int(mask.sum()))
        if not means:
            stats.append(GradeStat(letter, horizon, 0, 0.0, float("nan"), float("nan")))
            continue
        arr = np.array(means)
        tstat = arr.mean() / arr.std() * np.sqrt(len(arr)) if arr.std() > 0 else 0.0
        stats.append(
            GradeStat(
                letter,
                horizon,
                len(arr),
                float(np.mean(counts)),
                float(arr.mean() * 1e4),
                float(tstat),
            )
        )
    harness = evaluate_scores(report.scores, panel, horizon, cost_bps=10, min_names=15)
    return stats, harness
