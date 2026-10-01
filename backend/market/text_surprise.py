"""Text surprise (A1): the release's tone *change* and a learned word-surprise.

Registered in `docs/research/text-surprise-plan-2026-10-01.md` before any
of this was written. The sentiment analyst scores each release's tone
*level*; PEAD.txt (Meursault, Liang, Ross, Zhu 2021) finds that a text
*surprise* drifts. Two arms, both scored on the harness's cells by
`backend.cli.market_text_surprise`:

A1-1, tone surprise (`tone_surprise`)
    For each release, each of the four fields the analyst ranks
    (`FIELDS`, which equals `sentiment.SCORED`) minus the same field on
    the company's previous release, NaN when there is none. The fields
    are taken as the analyst sees them, so `tone_guidance_change` is the
    reader's change against the prior release (0 on a first release, as
    `language.tone_features` writes it) and its surprise is a second
    difference. Three registered variants (`VARIANTS`): the change alone;
    the change and the level at equal weight; the change only where
    |change| >= `GATE`, per field. Each variant is averaged as the analyst
    averages its fields (`baselines.rank_blend`: the mean cross-sectional
    percentile rank of every leg, NaN where any leg is NaN) and carried
    forward until the next release, as the level is.

A1-3, word surprise (`word_surprise`)
    A point-in-time text model: tf-idf unigrams and bigrams (at least
    `MIN_DF` documents) into an L2 logistic regression on the sign of the
    one-day beta-adjusted reaction - the close of the session before the
    release's reaction session to the reaction session's close, less beta
    times the benchmark's move, with the harness's own rolling beta
    (`Panel.forward_residual(1)` read one row before the reaction
    session). Fitted on an expanding window with a `PURGE`-session purge
    and refit at the first session of every calendar year from
    `FIRST_REFIT_YEAR`, so 2015-2017 is the first training set; the score
    is the fitted log-odds of the release, dated by its reaction session.
    Nothing dated at or after a refit's purge boundary enters that fit:
    `fit_schedule` fixes the boundary and `test_text_surprise` plants a
    word to prove it. C is chosen among `C_GRID` on the first training
    set alone, by in-sample AUC, and recorded.

The level legs (`level_scores`) exist for the null test: carried forward
through this module's own alignment and averaged the analyst's way they
must reproduce the stored tone's per-period ICs bit for bit, or nothing
built on them is comparable with the sentiment analyst.

scikit-learn is the repository's research dependency (`requirements.txt`,
the `research` extra) and is imported inside `fit_text_model` as
`day_type.py` and `learned_policy.py` import it, so this module loads
where scikit-learn is absent and only the fit needs it.
"""

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from backend.market import language
from backend.market.baselines import average_rank, rank_blend
from backend.market.panel import Panel

# The four tone fields the sentiment analyst ranks, in its order. Kept
# here rather than imported so the market layer does not import the desk;
# `test_text_surprise` asserts it equals `sentiment.SCORED`.
FIELDS: tuple[str, ...] = (
    "tone_guidance",
    "tone_demand",
    "tone_guidance_change",
    "tone_pricing",
)
VARIANT_CHANGE = "change"
VARIANT_CHANGE_PLUS_LEVEL = "change_plus_level"
VARIANT_CHANGE_GATED = "change_gated"
VARIANTS: tuple[str, ...] = (
    VARIANT_CHANGE,
    VARIANT_CHANGE_PLUS_LEVEL,
    VARIANT_CHANGE_GATED,
)
GATE = 0.5

# A1-3's registered settings.
PURGE = 20
C_GRID: tuple[float, ...] = (0.1, 1.0)
FIRST_REFIT_YEAR = 2018
TRAIN_START = date(2015, 1, 1)
MIN_DF = 20
# A refit with fewer labelled releases than this is skipped (its year is
# left unscored) rather than fitted on nothing.
MIN_TRAIN = 100
MAX_ITER = 2000
_NUMBER = re.compile(r"\d[\d,.]*")
_NUMBER_TOKEN = " num "


# --- A1-1: tone surprise -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class SurpriseRow:
    """One release's ranked fields and their change against the previous release."""

    accession: str
    reaction_date: date
    # The four ranked fields as the analyst sees them, `FIELDS` order.
    level: tuple[float, ...]
    # Field minus the same field on the previous release; NaN without one.
    change: tuple[float, ...]


# The value of a ranked field on one release, given the previous release:
# a `tone_X` field is the record's X, a `tone_X_change` field is X minus the
# previous release's X, 0 on a first release - exactly as
# `language.tone_features` writes them into the analyst's block.
def _field_value(
    name: str, record: language.ToneRecord, previous: language.ToneRecord | None
) -> float:
    """Return the analyst's value of `name` on `record`."""
    if name.endswith("_change"):
        base = name[len("tone_") : -len("_change")]
        if previous is None:
            return 0.0
        return float(getattr(record, base)) - float(getattr(previous, base))
    return float(getattr(record, name[len("tone_") :]))


# The four ranked fields of every release of one name, oldest first, as
# float32 - the dtype of the analyst's feature block, so a value here is
# the value the analyst ranks, to the bit.
def release_fields(records: Sequence[language.ToneRecord]) -> np.ndarray:
    """Return (releases, len(FIELDS)) float32 of the ranked fields, oldest first."""
    rows = sorted(records, key=lambda r: r.reaction_date)
    out = np.zeros((len(rows), len(FIELDS)), dtype=np.float32)
    previous: language.ToneRecord | None = None
    for k, record in enumerate(rows):
        for j, name in enumerate(FIELDS):
            out[k, j] = _field_value(name, record, previous)
        previous = record
    return out


# Each release's ranked fields and their change against the previous
# release of the same name, NaN on the first.
def tone_surprise(records: Sequence[language.ToneRecord]) -> tuple[SurpriseRow, ...]:
    """Return one SurpriseRow per release of one name, oldest first."""
    rows = sorted(records, key=lambda r: r.reaction_date)
    fields = release_fields(rows).astype(np.float64)
    out: list[SurpriseRow] = []
    for k, record in enumerate(rows):
        change = fields[k] - fields[k - 1] if k > 0 else np.full(len(FIELDS), np.nan)
        out.append(
            SurpriseRow(
                accession=record.accession,
                reaction_date=record.reaction_date,
                level=tuple(float(v) for v in fields[k]),
                change=tuple(float(v) for v in change),
            )
        )
    return tuple(out)


# The gated change: the change where it is at least `gate` in size, else
# zero; NaN stays NaN so a first release still has no view.
def gated_change(change: np.ndarray, gate: float = GATE) -> np.ndarray:
    """Return `change` with every |value| < gate set to 0, NaN kept."""
    change = np.asarray(change, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        keep = np.abs(change) >= gate
    return np.where(np.isnan(change), np.nan, np.where(keep, change, 0.0))


# Per-release values carried forward over the panel until the next
# release of the same name, the alignment `language.tone_features` uses:
# a release is visible from the first session on or after its reaction
# date. Rows are {ticker: [(reaction_date, values), ...]}; `width` values
# per row. NaN where a name has no release yet.
def carry_forward(
    panel: Panel,
    rows: Mapping[str, Sequence[tuple[date, Sequence[float]]]],
    width: int,
    dtype: Any = np.float64,
) -> np.ndarray:
    """Return (T, N, width) values carried forward from each release's session."""
    size = len(panel.dates)
    out = np.full((size, len(panel.tickers), width), np.nan, dtype=dtype)
    calendar = panel.dates.astype("datetime64[D]")
    for column, ticker in enumerate(panel.tickers):
        items = sorted(rows.get(ticker, ()), key=lambda r: r[0])
        if not items:
            continue
        positions = np.searchsorted(
            calendar,
            np.asarray([d for d, _ in items], dtype="datetime64[D]"),
            side="left",
        )
        for index, (_when, values) in enumerate(items):
            start = int(positions[index])
            if start >= size:
                break
            end = int(positions[index + 1]) if index + 1 < len(items) else size
            end = min(max(end, start), size)
            out[start:end, column, :] = np.asarray(values, dtype=dtype)
    return out


# The level and change blocks of every name, aligned to the panel: level
# in float32 like the analyst's block, change in float64.
def aligned_surprise(
    panel: Panel, rows: Mapping[str, Sequence[SurpriseRow]]
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((T, N, F) level float32, (T, N, F) change float64), NaN where none."""
    level = carry_forward(
        panel,
        {t: [(r.reaction_date, r.level) for r in rs] for t, rs in rows.items()},
        len(FIELDS),
        dtype=np.float32,
    )
    change = carry_forward(
        panel,
        {t: [(r.reaction_date, r.change) for r in rs] for t, rs in rows.items()},
        len(FIELDS),
    )
    return level, change


# The level legs averaged as the analyst averages them: float32 values
# cast to float, NaN where there is no release, the mean percentile rank.
def level_scores(level: np.ndarray) -> np.ndarray:
    """Return the (T, N) level-only score, the null arm."""
    legs = [level[:, :, j].astype(float) for j in range(level.shape[2])]
    return rank_blend(*legs)


# Every registered variant's (T, N) score from the aligned blocks.
def variant_scores(
    level: np.ndarray, change: np.ndarray, gate: float = GATE
) -> dict[str, np.ndarray]:
    """Return {variant: (T, N) score} for the three registered variants."""
    width = change.shape[2]
    change_legs = [change[:, :, j] for j in range(width)]
    level_legs = [level[:, :, j].astype(float) for j in range(width)]
    gated = gated_change(change, gate)
    gated_legs = [gated[:, :, j] for j in range(width)]
    return {
        VARIANT_CHANGE: rank_blend(*change_legs),
        VARIANT_CHANGE_PLUS_LEVEL: rank_blend(*change_legs, *level_legs),
        VARIANT_CHANGE_GATED: rank_blend(*gated_legs),
    }


# --- A1-3: word surprise -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextRow:
    """One release's text, dated by when the market could first react."""

    ticker: str
    accession: str
    reaction_date: date
    text: str


@dataclass(frozen=True, slots=True)
class Refit:
    """One walk-forward refit: the year it scores and its session bounds."""

    year: int
    # The first session of the year: the refit's date; rows with a reaction
    # session at or after it, and before `end`, are scored by this fit.
    fit_session: int
    end: int
    # The last reaction session a training row may carry: fit - PURGE.
    train_until: int


@dataclass(frozen=True, slots=True)
class WordSurprise:
    """The point-in-time word-surprise scores of every text row."""

    rows: tuple[TextRow, ...]
    # Per row: the reaction session's index into the panel (-1 if none),
    # the one-day beta-adjusted reaction (NaN if unknown), the fitted
    # log-odds (NaN if not scored) and the refit year that scored it (-1).
    sessions: np.ndarray
    labels: np.ndarray
    scores: np.ndarray
    fit_years: np.ndarray
    c: float
    # What the C choice and each refit saw, for the record.
    selection: dict[str, Any]
    refits: tuple[dict[str, Any], ...]


# The index of the first session on or after a calendar date, len(dates)
# when there is none.
def session_on_or_after(dates: np.ndarray, when: date) -> int:
    """Return the first session index whose date is >= `when`."""
    calendar = np.asarray(dates).astype("datetime64[D]")
    return int(np.searchsorted(calendar, np.datetime64(when), side="left"))


# Each row's reaction session and one-day beta-adjusted reaction: the
# residual the harness computes at horizon 1, read on the session before
# the reaction session, so it spans that session's close to the reaction
# session's close with beta as known before the release. NaN when the
# name is not in the panel, the reaction session is the panel's first or
# past its last, or either close is missing.
def reaction_labels(
    panel: Panel, rows: Sequence[TextRow]
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((n,) reaction session index or -1, (n,) one-day residual or NaN)."""
    residual = panel.forward_residual(1)
    size = len(panel.dates)
    sessions = np.full(len(rows), -1, dtype=np.int64)
    labels = np.full(len(rows), np.nan)
    columns = {t: i for i, t in enumerate(panel.tickers)}
    for i, row in enumerate(rows):
        column = columns.get(row.ticker)
        t = session_on_or_after(panel.dates, row.reaction_date)
        if column is None or t >= size:
            continue
        sessions[i] = t
        if t >= 1:
            labels[i] = residual[t - 1, column]
    return sessions, labels


# The walk-forward refits: one per calendar year from `first_year` to the
# panel's last, each fitted at the year's first session on rows whose
# reaction session is at least `purge` sessions earlier.
def fit_schedule(
    dates: np.ndarray, first_year: int = FIRST_REFIT_YEAR, purge: int = PURGE
) -> tuple[Refit, ...]:
    """Return the refits in order, empty when the panel ends before `first_year`."""
    size = len(dates)
    last_year = int(str(np.asarray(dates).astype("datetime64[Y]")[-1]))
    out: list[Refit] = []
    for year in range(first_year, last_year + 1):
        fit = session_on_or_after(dates, date(year, 1, 1))
        end = session_on_or_after(dates, date(year + 1, 1, 1))
        if fit >= size:
            break
        out.append(Refit(year, fit, min(end, size), fit - purge))
    return tuple(out)


# Numbers replaced by one token, so the vocabulary is words rather than
# the figures (and years) a release happens to quote.
def normalise(text: str) -> str:
    """Return `text` with every number replaced by a placeholder token."""
    return _NUMBER.sub(_NUMBER_TOKEN, text)


class TextModel:
    """A fitted tf-idf + L2 logistic regression; scores texts as log-odds."""

    # Keep the fitted vectorizer and classifier together.
    def __init__(self, vectorizer: Any, classifier: Any) -> None:
        self.vectorizer = vectorizer
        self.classifier = classifier

    # The fitted vocabulary, for tests of what a fit could see.
    @property
    def vocabulary(self) -> frozenset[str]:
        """Return the terms the vectorizer kept."""
        return frozenset(self.vectorizer.vocabulary_)

    # The fitted log-odds of the positive reaction for each text.
    def log_odds(self, texts: Sequence[str]) -> np.ndarray:
        """Return (n,) decision values; higher means a positive reaction."""
        if not len(texts):
            return np.zeros(0)
        x = self.vectorizer.transform([normalise(t) for t in texts])
        return np.asarray(self.classifier.decision_function(x), dtype=np.float64)


# Fit the registered text model on labelled texts: tf-idf unigrams and
# bigrams kept when they appear in at least `min_df` of these texts, into
# an L2 logistic regression at strength C. The vocabulary and the idf
# are fitted on the training texts only, so a later text can add nothing.
def fit_text_model(
    texts: Sequence[str], y: np.ndarray, c: float, min_df: int = MIN_DF
) -> TextModel:
    """Return the TextModel fitted on `texts` against binary `y`."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    y = np.asarray(y, dtype=np.int64)
    if len(texts) != len(y):
        raise ValueError("texts and labels differ in length")
    if len(np.unique(y)) < 2:
        raise ValueError("both reaction signs are needed to fit")
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2), min_df=min(min_df, len(texts)), dtype=np.float64
    )
    x = vectorizer.fit_transform([normalise(t) for t in texts])
    # The default penalty is L2 in every scikit-learn release the repository
    # pins (`penalty="l2"` is deprecated from 1.8, with the same default).
    classifier = LogisticRegression(C=c, solver="lbfgs", max_iter=MAX_ITER)
    classifier.fit(x, y)
    return TextModel(vectorizer, classifier)


# Area under the ROC curve from scores and binary labels, by the rank
# formula; NaN when one class is absent.
def auc(scores: np.ndarray, y: np.ndarray) -> float:
    """Return the AUC of `scores` against binary `y`."""
    scores = np.asarray(scores, dtype=np.float64)
    y = np.asarray(y, dtype=np.int64)
    positives = int((y == 1).sum())
    negatives = int(len(y) - positives)
    if positives == 0 or negatives == 0:
        return float("nan")
    ranks = average_rank(scores) + 1.0
    return float(
        (ranks[y == 1].sum() - positives * (positives + 1) / 2.0)
        / (positives * negatives)
    )


# The C with the best in-sample AUC on the first training set, as the
# plan registered; both AUCs are returned for the record. Ties go to the
# smaller C.
def select_c(
    texts: Sequence[str], y: np.ndarray, grid: Sequence[float] = C_GRID
) -> tuple[float, dict[str, Any]]:
    """Return (chosen C, {"auc_in_sample": {C: auc}, "rows": n})."""
    aucs: dict[str, float] = {}
    best: tuple[float, float] | None = None
    for c in grid:
        model = fit_text_model(texts, y, c)
        value = auc(model.log_odds(texts), y)
        aucs[str(c)] = value
        if best is None or (np.isfinite(value) and value > best[1]):
            best = (c, value)
    assert best is not None
    return best[0], {"auc_in_sample": aucs, "rows": int(len(y)), "grid": list(grid)}


# A1-3: the point-in-time word-surprise of every text row. Each refit is
# fitted on every usable row whose reaction session is at or before its
# purge boundary and scores the rows whose reaction session falls in its
# year. C is chosen on the first refit's training set unless given.
def word_surprise(
    panel: Panel,
    rows: Sequence[TextRow],
    c: float | None = None,
    first_year: int = FIRST_REFIT_YEAR,
    purge: int = PURGE,
    train_start: date = TRAIN_START,
    min_train: int = MIN_TRAIN,
    fit: Any = fit_text_model,
) -> WordSurprise:
    """Return the WordSurprise of `rows` on `panel`, fitted walk-forward."""
    rows = tuple(sorted(rows, key=lambda r: (r.reaction_date, r.ticker, r.accession)))
    sessions, labels = reaction_labels(panel, rows)
    with np.errstate(invalid="ignore"):
        usable = (
            (sessions >= 0)
            & np.isfinite(labels)
            & (labels != 0.0)
            & np.array([r.reaction_date >= train_start for r in rows], dtype=bool)
        )
    y_all = np.where(labels > 0, 1, 0)
    texts = [r.text for r in rows]
    schedule = fit_schedule(panel.dates, first_year, purge)
    scores = np.full(len(rows), np.nan)
    fit_years = np.full(len(rows), -1, dtype=np.int64)
    selection: dict[str, Any] = {"chosen": c, "given": c is not None}
    refits: list[dict[str, Any]] = []
    for refit in schedule:
        train = usable & (sessions <= refit.train_until)
        test = (sessions >= refit.fit_session) & (sessions < refit.end)
        record: dict[str, Any] = {
            "year": refit.year,
            "fit_session": str(panel.dates[refit.fit_session]),
            "train_rows": int(train.sum()),
            "test_rows": int(test.sum()),
            "fitted": False,
        }
        if train.sum() < min_train or not test.any():
            refits.append(record)
            continue
        train_texts = [texts[i] for i in np.flatnonzero(train)]
        y_train = y_all[train]
        if len(np.unique(y_train)) < 2:
            refits.append(record)
            continue
        if c is None:
            c, chosen = select_c(train_texts, y_train)
            selection.update(chosen)
            selection["chosen"] = c
            selection["year"] = refit.year
        model = fit(train_texts, y_train, c)
        test_index = np.flatnonzero(test)
        scores[test_index] = model.log_odds([texts[i] for i in test_index])
        fit_years[test_index] = refit.year
        record.update(
            fitted=True,
            vocabulary=int(len(model.vocabulary))
            if hasattr(model, "vocabulary")
            else -1,
            positives=int(y_train.sum()),
        )
        refits.append(record)
    return WordSurprise(
        rows=rows,
        sessions=sessions,
        labels=labels,
        scores=scores,
        fit_years=fit_years,
        c=float(c) if c is not None else float("nan"),
        selection=selection,
        refits=tuple(refits),
    )


# The (T, N) word-surprise score: each row's log-odds from its reaction
# session until the name's next release, NaN before any scored release.
# An unscored release (a NaN score) still ends the previous one's carry,
# so a stale score never outlives the release that replaced it.
def word_scores(panel: Panel, result: WordSurprise) -> np.ndarray:
    """Return the (T, N) carried-forward word-surprise scores."""
    by_ticker: dict[str, list[tuple[date, Sequence[float]]]] = {}
    for row, score in zip(result.rows, result.scores, strict=True):
        by_ticker.setdefault(row.ticker, []).append((row.reaction_date, (score,)))
    return carry_forward(panel, by_ticker, 1)[:, :, 0]


# The mean per-session Spearman correlation of two (T, N) scores over the
# cells both define, on sessions with at least `min_names` such cells:
# how far a candidate ranks the names as the tone level does.
def mean_cross_sectional_correlation(
    a: np.ndarray, b: np.ndarray, cells: np.ndarray, min_names: int
) -> dict[str, float]:
    """Return {"mean": mean per-session Spearman, "sessions": count, "pooled": ...}."""
    both = cells & np.isfinite(a) & np.isfinite(b)
    values: list[float] = []
    pooled_a: list[np.ndarray] = []
    pooled_b: list[np.ndarray] = []
    for t in range(a.shape[0]):
        columns = np.flatnonzero(both[t])
        if len(columns) < min_names:
            continue
        rho = _spearman(a[t, columns], b[t, columns])
        if np.isfinite(rho):
            values.append(rho)
        pooled_a.append(average_rank(a[t, columns]) / (len(columns) - 1))
        pooled_b.append(average_rank(b[t, columns]) / (len(columns) - 1))
    pooled = float("nan")
    if pooled_a:
        pooled = _spearman(np.concatenate(pooled_a), np.concatenate(pooled_b))
    return {
        "mean": float(np.mean(values)) if values else float("nan"),
        "sessions": int(len(values)),
        "pooled": pooled,
    }


# Spearman correlation of two 1-D arrays, ties averaged, NaN when constant.
def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return float("nan")
    ra, rb = average_rank(a), average_rank(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denominator = math.sqrt(float((ra * ra).sum()) * float((rb * rb).sum()))
    if denominator == 0:
        return float("nan")
    return float((ra * rb).sum() / denominator)


__all__ = [
    "C_GRID",
    "FIELDS",
    "FIRST_REFIT_YEAR",
    "GATE",
    "MIN_DF",
    "PURGE",
    "VARIANTS",
    "Refit",
    "SurpriseRow",
    "TextModel",
    "TextRow",
    "WordSurprise",
    "aligned_surprise",
    "auc",
    "carry_forward",
    "fit_schedule",
    "fit_text_model",
    "gated_change",
    "level_scores",
    "mean_cross_sectional_correlation",
    "normalise",
    "reaction_labels",
    "release_fields",
    "select_c",
    "session_on_or_after",
    "tone_surprise",
    "variant_scores",
    "word_scores",
    "word_surprise",
]
