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
from backend.agents.trading.desk.grading import (
    GRADES,
    ORDINAL,
    SIZE_MULTIPLIER,
    A,
    Graded,
)
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


@dataclass(frozen=True)
class HistoryRow:
    """One name on one session: what the desk said and what came next."""

    date: np.datetime64
    grade: str
    votes: float
    stances: dict[str, int]
    exposure: float
    confidence: float
    # Log return over the next `horizon` sessions, raw and beta-adjusted;
    # NaN while the future is not fully known.
    forward: float
    forward_residual: float
    # True on the first session the market could react to an earnings
    # release (the grade that day already includes the release's tone).
    earnings: bool = False


# The desk's day-by-day view of one name from `since`, with what followed.
def history(
    report: DeskReport, ticker: str, horizon: int, since: date | None = None
) -> list[HistoryRow]:
    """Return one HistoryRow per session for `ticker`."""
    panel = report.panel
    column = panel.index(ticker)
    raw = panel.forward_log_returns(horizon)[:, column]
    residual = panel.forward_residual(horizon)[:, column]
    start = np.datetime64(since) if since else panel.dates[0]
    since_earnings = None
    fundamental = report.opinions.get("fundamental")
    if fundamental is not None:
        since_earnings = fundamental.evidence.get("sessions_since_earnings")
    rows: list[HistoryRow] = []
    for t, day in enumerate(panel.dates):
        if day < start or not np.isfinite(panel.adj_close[t, column]):
            continue
        state = report.regime.states[t]
        reaction = since_earnings is not None and since_earnings[t, column] == 0
        rows.append(
            HistoryRow(
                date=day,
                grade=report.graded.letter(t, column),
                votes=float(report.graded.votes[t, column]),
                stances={
                    k: int(v[t, column]) for k, v in report.graded.stances.items()
                },
                exposure=state.exposure,
                confidence=state.selection_confidence,
                forward=float(raw[t]),
                forward_residual=float(residual[t]),
                earnings=bool(reaction),
            )
        )
    return rows


@dataclass(frozen=True)
class NameBacktest:
    """Holding one name only while the desk grades it at or above a grade."""

    ticker: str
    min_grade: str
    sessions: int
    sessions_in: int
    switches: int
    # Log returns over the span: the rule, buy-and-hold, and the benchmark.
    rule_return: float
    hold_return: float
    benchmark_return: float
    # Mean daily log return of the name on days in and days out, annualised.
    in_annualised: float
    out_annualised: float


# Hold the name from the close after a qualifying grade until the close
# after the grade drops, paying `cost_bps` on each switch; grade multiplier
# and regime exposure scale the position as they do in the book.
def name_backtest(
    report: DeskReport,
    ticker: str,
    min_grade: str = A,
    since: date | None = None,
    cost_bps: float = 10.0,
) -> NameBacktest:
    """Return the NameBacktest for `ticker` from `since`."""
    panel = report.panel
    column = panel.index(ticker)
    bench = panel.index(panel.benchmark)
    returns = panel.log_returns()
    start = np.datetime64(since) if since else panel.dates[0]
    first = int(np.searchsorted(panel.dates, start))
    rule = 0.0
    hold = 0.0
    market = 0.0
    held = 0.0
    switches = 0
    sessions = 0
    days_in: list[float] = []
    days_out: list[float] = []
    for t in range(first, len(panel.dates) - 1):
        own = returns[t + 1, column]
        if not np.isfinite(own):
            continue
        letter = report.graded.letter(t, column)
        state = report.regime.states[t]
        size = 0.0
        if ORDINAL[letter] >= ORDINAL[min_grade]:
            size = SIZE_MULTIPLIER[letter] * state.exposure
        if abs(size - held) > 1e-9:
            switches += 1
            rule -= abs(size - held) * cost_bps / 1e4
            held = size
        # The position set at close t earns session t+1.
        rule += held * own
        hold += own
        spy = returns[t + 1, bench]
        market += spy if np.isfinite(spy) else 0.0
        sessions += 1
        (days_in if held > 0 else days_out).append(own)
    ann = 252.0
    return NameBacktest(
        ticker=ticker,
        min_grade=min_grade,
        sessions=sessions,
        sessions_in=len(days_in),
        switches=switches,
        rule_return=rule,
        hold_return=hold,
        benchmark_return=market,
        in_annualised=float(np.mean(days_in) * ann) if days_in else float("nan"),
        out_annualised=float(np.mean(days_out) * ann) if days_out else float("nan"),
    )
