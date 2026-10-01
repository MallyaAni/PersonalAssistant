"""The text-surprise arms on synthetic records and texts.

What has to hold: the surprise is each ranked field minus the previous
release's, NaN without a predecessor, and the ranked fields are the ones
the analyst ranks, to the bit; the gate zeroes a small change and keeps
NaN; a release is visible from the first session on or after its
reaction date and carried to the next; the level legs through this
module's own alignment reproduce the sentiment analyst's ranks bit for
bit (the null test); the reaction label is the harness's own one-day
residual read before the reaction session; the refits expand, purge
twenty sessions, and no text dated at or after a refit's boundary can
reach its vocabulary; C is chosen on the first training set only.
No store, no model server, no network.
"""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import sentiment
from backend.market import language
from backend.market import text_surprise as ts
from backend.market.baselines import percentile_rank, rank_blend
from backend.market.harness import evaluate_scores
from backend.market.panel import panel_from_histories
from backend.market.yahoo import DailyBar, TickerHistory

NAMES = 40
SESSIONS = 1500
FIRST = date(2016, 1, 4)
QUARTER = 63


# A history from a daily return series, one bar per calendar day.
def _history(ticker: str, returns: np.ndarray) -> TickerHistory:
    prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    bars = tuple(
        DailyBar(FIRST + timedelta(days=i), p, p * 1.01, p * 0.99, p, p, 1_000_000)
        for i, p in enumerate(prices)
    )
    return TickerHistory(
        ticker, bars, (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


# A book whose returns drift with the *change* in each name's tone against
# its previous release, with a smaller drift on the level, so a change
# arm carries a large IC and the level a smaller one. Returns (panel,
# sides, tone per (release k, name)).
def _book(seed: int = 3, change_drift: float = 0.004, level_drift: float = 0.0015):
    rng = np.random.default_rng(seed)
    releases = SESSIONS // QUARTER + 1
    tone = rng.choice([-1.0, 0.0, 1.0], size=(releases, NAMES))
    change = np.vstack([np.zeros((1, NAMES)), np.diff(tone, axis=0)])
    drift = (
        change_drift * np.repeat(change, QUARTER, axis=0)[:SESSIONS]
        + level_drift * np.repeat(tone, QUARTER, axis=0)[:SESSIONS]
    )
    returns = drift + rng.normal(0.0, 0.01, size=(SESSIONS, NAMES))
    histories = {
        f"N{i:03d}": _history(f"N{i:03d}", returns[:, i]) for i in range(NAMES)
    }
    histories["SPY"] = _history("SPY", returns.mean(axis=1))
    panel = panel_from_histories(histories, "SPY", {})
    sides = {f"N{i:03d}": "ai" for i in range(NAMES)}
    return panel, sides, tone


# One tone record; graded values so ties are rare.
def _record(
    accession: str,
    when: date,
    guidance: float,
    demand: float = 0.0,
    pricing: float = 0.0,
) -> language.ToneRecord:
    return language.ToneRecord(
        accession=accession,
        reaction_date=when,
        guidance=guidance,
        demand=demand,
        pricing=pricing,
        capex=0.0,
        supply_constrained=0.0,
        summary="",
        model="test",
        prompt_version="release_tone/3",
        truncated=False,
    )


# Tone records per name from a (releases, names) matrix, one a quarter,
# with demand and pricing drawn so the four legs are not one leg repeated.
def _records(tone: np.ndarray, seed: int = 7) -> dict[str, tuple]:
    rng = np.random.default_rng(seed)
    out = {}
    for j in range(tone.shape[1]):
        ticker = f"N{j:03d}"
        out[ticker] = tuple(
            _record(
                f"{ticker}-{k}",
                FIRST + timedelta(days=k * QUARTER),
                tone[k, j] + 0.1 * rng.integers(-2, 3),
                demand=tone[k, j] * 0.5 + 0.1 * rng.integers(-2, 3),
                pricing=0.1 * rng.integers(-3, 4),
            )
            for k in range(tone.shape[0])
        )
    return out


# --- A1-1 --------------------------------------------------------------------


# The fields this module differences are the ones the analyst ranks.
def test_fields_are_the_analysts_ranked_fields():
    assert ts.FIELDS == sentiment.SCORED


# The ranked fields of a release are what the analyst's block carries: a
# plain field is the record's value, the guidance change is the difference
# against the previous release and zero on the first, all in float32.
def test_release_fields_follow_the_analysts_block():
    records = [
        _record("a", date(2020, 1, 2), 0.7, demand=0.2, pricing=-0.1),
        _record("b", date(2020, 4, 2), 0.3, demand=0.4, pricing=0.0),
        _record("c", date(2020, 7, 2), 0.9, demand=0.1, pricing=0.5),
    ]
    fields = ts.release_fields(records[::-1])  # order must not matter
    assert fields.dtype == np.float32
    assert fields.shape == (3, 4)
    guidance = fields[:, ts.FIELDS.index("tone_guidance")]
    change = fields[:, ts.FIELDS.index("tone_guidance_change")]
    assert guidance.tolist() == pytest.approx([0.7, 0.3, 0.9])
    assert change[0] == 0.0
    assert change[1] == np.float32(0.3 - 0.7)
    assert change[2] == np.float32(0.9 - 0.3)
    assert fields[:, ts.FIELDS.index("tone_pricing")].tolist() == pytest.approx(
        [-0.1, 0.0, 0.5]
    )


# The surprise is each field minus the previous release's field, NaN on
# the first; for the change field that is a second difference.
def test_tone_surprise_arithmetic_and_first_release_nan():
    records = [
        _record("a", date(2020, 1, 2), 0.7, demand=0.2),
        _record("b", date(2020, 4, 2), 0.3, demand=0.4),
        _record("c", date(2020, 7, 2), 0.9, demand=0.1),
    ]
    rows = ts.tone_surprise(records)
    assert [r.accession for r in rows] == ["a", "b", "c"]
    assert all(np.isnan(v) for v in rows[0].change)
    fields = ts.release_fields(records).astype(np.float64)
    for k in (1, 2):
        assert np.asarray(rows[k].change) == pytest.approx(fields[k] - fields[k - 1])
        assert np.asarray(rows[k].level) == pytest.approx(fields[k])
    g = ts.FIELDS.index("tone_guidance")
    gc = ts.FIELDS.index("tone_guidance_change")
    assert rows[1].change[g] == pytest.approx(np.float32(0.3) - np.float32(0.7))
    # second difference: (0.9-0.3) - (0.3-0.7)
    assert rows[2].change[gc] == pytest.approx(
        float(np.float32(0.9 - 0.3)) - float(np.float32(0.3 - 0.7))
    )
    assert rows[1].change[gc] == pytest.approx(float(np.float32(0.3 - 0.7)) - 0.0)


# A single release has a level and no change.
def test_tone_surprise_single_release():
    rows = ts.tone_surprise([_record("a", date(2020, 1, 2), 0.5)])
    assert len(rows) == 1
    assert rows[0].level[ts.FIELDS.index("tone_guidance")] == 0.5
    assert all(np.isnan(v) for v in rows[0].change)


# The gate keeps a change of at least 0.5 in size, zeroes a smaller one,
# and leaves NaN alone.
def test_gated_change():
    change = np.array([[0.5, -0.5, 0.49, -0.2, 0.0, np.nan, 1.7]])
    gated = ts.gated_change(change)
    assert gated[0, :5].tolist() == [0.5, -0.5, 0.0, 0.0, 0.0]
    assert np.isnan(gated[0, 5])
    assert gated[0, 6] == 1.7
    assert ts.gated_change(change, gate=0.2)[0, 3] == -0.2


# A release is visible from the first session on or after its reaction
# date, carried until the next release, NaN before the first, and a
# release after the last session is ignored.
def test_carry_forward_alignment():
    panel, _sides, _tone = _book()
    sessions = [date.fromisoformat(str(d)) for d in panel.dates]
    rows = {
        "N001": [
            (sessions[10], (1.0, 2.0)),
            (sessions[50] + timedelta(days=0), (3.0, 4.0)),
            (sessions[-1] + timedelta(days=5), (9.0, 9.0)),
        ]
    }
    out = ts.carry_forward(panel, rows, 2)
    n = panel.index("N001")
    assert out.shape == (len(panel.dates), len(panel.tickers), 2)
    assert np.isnan(out[:10, n, :]).all()
    assert (out[10:50, n, 0] == 1.0).all()
    assert (out[10:50, n, 1] == 2.0).all()
    assert (out[50:, n, 0] == 3.0).all()
    assert np.isnan(out[:, panel.index("N002"), :]).all()
    assert out.dtype == np.float64
    assert ts.carry_forward(panel, rows, 2, dtype=np.float32).dtype == np.float32


# A release dated off the calendar lands on the next session.
def test_carry_forward_off_calendar_date_lands_on_next_session():
    bars = {
        "X": _history("X", np.zeros(5)),
        "SPY": _history("SPY", np.zeros(5)),
    }
    panel = panel_from_histories(bars, "SPY", {})
    # Drop every other session so dates are not consecutive.
    keep = np.array([0, 2, 4, 5])
    from dataclasses import replace

    panel = replace(
        panel,
        dates=panel.dates[keep],
        open=panel.open[keep],
        high=panel.high[keep],
        low=panel.low[keep],
        close=panel.close[keep],
        adj_close=panel.adj_close[keep],
        volume=panel.volume[keep],
    )
    out = ts.carry_forward(panel, {"X": [(FIRST + timedelta(days=1), (1.0,))]}, 1)
    x = panel.index("X")
    assert np.isnan(out[0, x, 0])
    assert out[1, x, 0] == 1.0
    assert out[2, x, 0] == 1.0


# The null test: the level legs carried forward through this module's own
# alignment and averaged the analyst's way reproduce `sentiment.opine`'s
# ranks and the harness's per-period ICs bit for bit.
def test_level_scores_reproduce_the_sentiment_analyst_bit_for_bit():
    panel, _sides, tone = _book()
    records = _records(tone)
    block = language.tone_features(panel, records)
    expected = sentiment.opine(block).ranks()
    rows = {t: ts.tone_surprise(rs) for t, rs in records.items()}
    level, change = ts.aligned_surprise(panel, rows)
    ours = percentile_rank(ts.level_scores(level))
    assert np.array_equal(ours, expected, equal_nan=True)
    for horizon in (20, 60):
        a = evaluate_scores(expected, panel, horizon, min_names=15)
        b = evaluate_scores(ours, panel, horizon, min_names=15)
        assert [p.rank_ic for p in a.periods] == [p.rank_ic for p in b.periods]
        assert [str(p.date) for p in a.periods] == [str(p.date) for p in b.periods]


# A name whose records are missing has NaN in every variant and the level.
def test_aligned_surprise_missing_name_is_nan():
    panel, _sides, tone = _book()
    records = _records(tone)
    del records["N003"]
    level, change = ts.aligned_surprise(
        panel, {t: ts.tone_surprise(rs) for t, rs in records.items()}
    )
    n = panel.index("N003")
    assert np.isnan(level[:, n, :]).all()
    assert np.isnan(change[:, n, :]).all()
    for scores in ts.variant_scores(level, change).values():
        assert np.isnan(scores[:, n]).all()


# The variants: the change arm has no view until a name's second release;
# change plus level is the equal-weight mean of the two blends; the gated
# arm differs from the change arm only through small changes.
def test_variant_scores():
    panel, _sides, tone = _book()
    records = _records(tone)
    rows = {t: ts.tone_surprise(rs) for t, rs in records.items()}
    level, change = ts.aligned_surprise(panel, rows)
    scores = ts.variant_scores(level, change)
    assert set(scores) == set(ts.VARIANTS)
    first = ts.session_on_or_after(panel.dates, FIRST + timedelta(days=QUARTER))
    names = [n for n in range(len(panel.tickers)) if panel.tickers[n] != "SPY"]
    assert np.isnan(scores[ts.VARIANT_CHANGE][:first]).all()
    assert np.isfinite(scores[ts.VARIANT_CHANGE][first:][:, names]).all()
    # the level is there before the second release, the change is not
    assert np.isfinite(level[:first][:, names]).all()
    change_blend = rank_blend(*[change[:, :, j] for j in range(4)])
    level_blend = rank_blend(*[level[:, :, j].astype(float) for j in range(4)])
    both = 0.5 * (change_blend + level_blend)
    assert np.allclose(scores[ts.VARIANT_CHANGE_PLUS_LEVEL], both, equal_nan=True)
    gated = ts.variant_scores(level, change, gate=0.0)[ts.VARIANT_CHANGE_GATED]
    assert np.allclose(gated, scores[ts.VARIANT_CHANGE], equal_nan=True)
    assert not np.allclose(
        scores[ts.VARIANT_CHANGE_GATED], scores[ts.VARIANT_CHANGE], equal_nan=True
    )


# On a book that drifts with the change, the change arm carries a large
# IC at twenty sessions and beats the level.
def test_change_arm_carries_the_change_drift():
    panel, _sides, tone = _book()
    records = _records(tone)
    rows = {t: ts.tone_surprise(rs) for t, rs in records.items()}
    level, change = ts.aligned_surprise(panel, rows)
    scores = ts.variant_scores(level, change)
    cells = np.isfinite(scores[ts.VARIANT_CHANGE])
    change_arm = evaluate_scores(scores[ts.VARIANT_CHANGE], panel, 20, min_names=15)
    level_arm = evaluate_scores(
        np.where(cells, ts.level_scores(level), np.nan), panel, 20, min_names=15
    )
    assert change_arm.mean_ic > 0.1
    assert change_arm.ic_tstat > 3
    assert change_arm.mean_ic > level_arm.mean_ic


# --- A1-3 --------------------------------------------------------------------


# One text row.
def _row(ticker: str, when: date, text: str, k: int = 0) -> ts.TextRow:
    return ts.TextRow(ticker, f"{ticker}-{k}", when, text)


# The reaction label is the harness's one-day residual read on the session
# before the reaction session: own close-to-close less beta times the
# benchmark's, with beta as known then.
def test_reaction_labels_are_the_harness_residual_before_the_reaction_session():
    panel, _sides, _tone = _book()
    when = date.fromisoformat(str(panel.dates[300]))
    rows = [_row("N005", when, "x"), _row("N006", when - timedelta(days=0), "y")]
    sessions, labels = ts.reaction_labels(panel, rows)
    assert sessions.tolist() == [300, 300]
    residual = panel.forward_residual(1)
    assert labels[0] == residual[299, panel.index("N005")]
    assert labels[1] == residual[299, panel.index("N006")]
    own = np.log(panel.adj_close[300] / panel.adj_close[299])
    beta = panel.rolling_beta(120)[299]
    market = own[panel.index("SPY")]
    n = panel.index("N005")
    assert labels[0] == pytest.approx(own[n] - beta[n] * market)


# A reaction before the panel's second session, past its end, or for a
# name not in the panel has no label; a date off the calendar lands on
# the next session.
def test_reaction_labels_edges():
    panel, _sides, _tone = _book()
    last = date.fromisoformat(str(panel.dates[-1]))
    rows = [
        _row("N005", FIRST, "first session"),
        _row("N005", FIRST - timedelta(days=30), "before the panel"),
        _row("N005", last + timedelta(days=1), "after the panel"),
        _row("ZZZZ", FIRST + timedelta(days=100), "not a name"),
    ]
    sessions, labels = ts.reaction_labels(panel, rows)
    assert sessions.tolist() == [0, 0, -1, -1]
    assert np.isnan(labels).all()


# The schedule: one refit per calendar year from 2018 at the year's first
# session, the purge boundary twenty sessions before it, the year's last
# session before the next refit; a panel ending before 2018 has none.
def test_fit_schedule():
    panel, _sides, _tone = _book()
    schedule = ts.fit_schedule(panel.dates)
    years = [r.year for r in schedule]
    assert years[0] == 2018
    assert years == list(range(2018, 2018 + len(years)))
    for refit in schedule:
        assert str(panel.dates[refit.fit_session]) >= f"{refit.year}-01-01"
        assert str(panel.dates[refit.fit_session - 1]) < f"{refit.year}-01-01"
        assert refit.train_until == refit.fit_session - ts.PURGE
    assert schedule[-1].end == len(panel.dates)
    for a, b in zip(schedule, schedule[1:], strict=False):
        assert a.end == b.fit_session
    assert ts.fit_schedule(panel.dates[:300]) == ()


# Numbers become one token, so figures and years are not vocabulary.
def test_normalise_replaces_numbers():
    out = ts.normalise("Revenue of $4.73 billion, up 57% from 2024.")
    assert "4.73" not in out
    assert "2024" not in out
    assert "57" not in out
    assert out.count("num") == 3


# The AUC by the rank formula: perfect separation, inverse, and chance.
def test_auc():
    y = np.array([0, 0, 1, 1])
    assert ts.auc(np.array([0.1, 0.2, 0.8, 0.9]), y) == 1.0
    assert ts.auc(np.array([0.9, 0.8, 0.2, 0.1]), y) == 0.0
    assert ts.auc(np.array([0.5, 0.5, 0.5, 0.5]), y) == 0.5
    assert np.isnan(ts.auc(np.array([0.1, 0.2]), np.array([1, 1])))


# Texts whose words carry the label: the model separates them, scores
# higher for the positive words, and keeps only terms in enough documents.
def test_fit_text_model_separates_planted_words():
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(1)
    filler = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
    texts, y = [], []
    for i in range(200):
        words = list(rng.choice(filler, size=12))
        positive = i % 2 == 0
        words.append("strong growth" if positive else "weak decline")
        texts.append(" ".join(words))
        y.append(1 if positive else 0)
    model = ts.fit_text_model(texts, np.array(y), c=1.0, min_df=20)
    scores = model.log_odds(texts)
    assert ts.auc(scores, np.array(y)) > 0.95
    assert (
        model.log_odds(["strong growth ahead"])[0] > model.log_odds(["weak decline"])[0]
    )
    assert "strong growth" in model.vocabulary  # a bigram
    assert "zeta" in model.vocabulary
    assert model.log_odds([]).shape == (0,)
    with pytest.raises(ValueError, match="both reaction signs"):
        ts.fit_text_model(texts, np.ones(len(texts)), c=1.0)
    with pytest.raises(ValueError, match="differ in length"):
        ts.fit_text_model(texts[:3], np.array(y), c=1.0)


# C is chosen by in-sample AUC on what it is given, from the grid, with
# both AUCs recorded; a tie goes to the smaller C.
def test_select_c_records_both_aucs():
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(2)
    texts = [
        " ".join(rng.choice(["a", "b", "c", "d", "up", "down"], size=10))
        for _ in range(120)
    ]
    y = np.array([1 if "up" in t.split() else 0 for t in texts])
    if len(np.unique(y)) < 2:
        y[0] = 1 - y[0]
    chosen, record = ts.select_c(texts, y, grid=(0.1, 1.0))
    assert chosen in (0.1, 1.0)
    assert set(record["auc_in_sample"]) == {"0.1", "1.0"}
    assert record["rows"] == 120
    best = max(record["auc_in_sample"].values())
    assert record["auc_in_sample"][str(chosen)] == best


# Texts for the synthetic book whose words follow the sign of each row's
# one-day reaction, with filler; the words are planted after the label is
# known, which is what a word-surprise model is supposed to find.
def _texts(panel, seed: int = 4, releases: int | None = None):
    rng = np.random.default_rng(seed)
    filler = [f"w{i}" for i in range(30)]
    rows = []
    count = releases or (SESSIONS // QUARTER + 1)
    for j in range(NAMES):
        for k in range(count):
            when = FIRST + timedelta(days=k * QUARTER)
            rows.append(_row(f"N{j:03d}", when, "", k))
    sessions, labels = ts.reaction_labels(panel, rows)
    out = []
    for row, label in zip(rows, labels, strict=True):
        words = list(rng.choice(filler, size=20))
        if np.isfinite(label):
            words.append("beat raise" if label > 0 else "miss cut")
        out.append(
            ts.TextRow(row.ticker, row.accession, row.reaction_date, " ".join(words))
        )
    return out


# A recording fit: what each refit was trained on, by text, and a model
# that scores by the planted words.
class _Recorder:
    # Start with no fits recorded.
    def __init__(self):
        self.calls = []

    # Record the training rows and hand back the planted model.
    def __call__(self, texts, y, c):
        self.calls.append((list(texts), np.asarray(y).copy(), c))
        return _PlantedModel()


class _PlantedModel:
    vocabulary = frozenset()

    # Positive for "beat", negative for "miss", zero otherwise.
    def log_odds(self, texts):
        return np.array(
            [1.0 if "beat" in t else (-1.0 if "miss" in t else 0.0) for t in texts]
        )


# The walk-forward: every refit's training rows have a reaction session at
# or before the purge boundary, the windows expand, every scored row falls
# in its refit's year, nothing before 2018 is scored, and rows with no
# label or a zero one never enter a fit.
def test_word_surprise_expanding_windows_and_purge():
    panel, _sides, _tone = _book()
    rows = _texts(panel)
    recorder = _Recorder()
    result = ts.word_surprise(panel, rows, c=1.0, fit=recorder)
    schedule = ts.fit_schedule(panel.dates)
    fitted = [r for r in schedule if r.fit_session < len(panel.dates)]
    assert len(result.refits) == len(schedule)
    # the last year has no release inside the panel, so it is recorded unfitted
    assert [r["fitted"] for r in result.refits] == [True, True, False]
    assert result.refits[-1]["test_rows"] == 0
    schedule = fitted[: len(recorder.calls)]
    assert len(recorder.calls) == 2
    session_of = {r.text: s for r, s in zip(result.rows, result.sessions, strict=True)}
    label_of = {r.text: s for r, s in zip(result.rows, result.labels, strict=True)}
    previous: set[str] = set()
    for refit, (texts, y, c) in zip(schedule, recorder.calls, strict=True):
        assert c == 1.0
        sessions = np.array([session_of[t] for t in texts])
        assert sessions.max() <= refit.fit_session - ts.PURGE
        assert sessions.min() >= 0
        assert set(texts) >= previous  # expanding
        previous = set(texts)
        labels = np.array([label_of[t] for t in texts])
        assert np.isfinite(labels).all()
        assert (labels != 0).all()
        assert np.array_equal(y, (labels > 0).astype(int))
    for session, score, year in zip(
        result.sessions, result.scores, result.fit_years, strict=True
    ):
        if np.isfinite(score):
            refit = next(r for r in schedule if r.year == year)
            assert refit.fit_session <= session < refit.end
        else:
            assert year == -1
            assert session < schedule[0].fit_session or session < 0
    first_2018 = schedule[0].fit_session
    assert np.isnan(result.scores[result.sessions < first_2018]).all()
    assert np.isfinite(result.scores[result.sessions >= first_2018]).all()
    assert result.selection["given"] is True
    assert result.c == 1.0


# Through the recorder the planted model scores the sign of the reaction,
# so the carried-forward score ranks the names by their last reaction.
def test_word_scores_carry_forward_and_reset():
    panel, _sides, _tone = _book()
    rows = _texts(panel)
    result = ts.word_surprise(panel, rows, c=1.0, fit=_Recorder())
    scores = ts.word_scores(panel, result)
    first_2018 = ts.fit_schedule(panel.dates)[0].fit_session
    assert np.isnan(scores[:first_2018]).all()
    row_index = {(r.ticker, r.reaction_date): i for i, r in enumerate(result.rows)}
    for (ticker, _when), i in row_index.items():
        t = result.sessions[i]
        if t >= first_2018:
            assert scores[t, panel.index(ticker)] == result.scores[i]
    # An unscored later release ends the carry: a NaN row resets the name.
    extra = _row("N000", date.fromisoformat(str(panel.dates[-10])), "zz", "x")
    by_ticker = {
        "N000": [
            (r.reaction_date, (s,))
            for r, s in zip(result.rows, result.scores, strict=True)
            if r.ticker == "N000"
        ]
    }
    by_ticker["N000"].append((extra.reaction_date, (float("nan"),)))
    reset = ts.carry_forward(panel, by_ticker, 1)[:, :, 0]
    n = panel.index("N000")
    assert np.isnan(reset[-10:, n]).all()
    assert np.isfinite(reset[-11, n])


# No row after the reaction session enters a fit, with the real model: a
# word planted only in texts dated inside the purge or in the fit's own
# year is absent from that fit's vocabulary, and present once the next
# year's fit can see it.
def test_no_row_after_the_boundary_reaches_a_fit():
    pytest.importorskip("sklearn")
    panel, _sides, _tone = _book()
    rows = _texts(panel)
    schedule = ts.fit_schedule(panel.dates)
    refit_2018, refit_2019 = schedule[0], schedule[1]
    sessions, _labels = ts.reaction_labels(panel, rows)
    planted = []
    for row, session in zip(rows, sessions, strict=True):
        text = row.text
        if refit_2018.train_until < session < refit_2018.end:
            # inside the 2018 purge or 2018 itself: invisible to the 2018 fit
            text = text + " zzpurge zzpurge"
        planted.append(ts.TextRow(row.ticker, row.accession, row.reaction_date, text))
    models = []

    # The real fit, keeping every model so its vocabulary can be read.
    def fit(texts, y, c):
        model = ts.fit_text_model(texts, y, c, min_df=1)
        models.append(model)
        return model

    result = ts.word_surprise(panel, planted, c=1.0, fit=fit)
    assert [r["year"] for r in result.refits if r["fitted"]][:2] == [2018, 2019]
    assert "zzpurge" not in models[0].vocabulary
    assert "zzpurge" in models[1].vocabulary
    assert refit_2019.train_until > refit_2018.fit_session  # 2019 sees 2018's rows
    assert np.isfinite(result.scores[result.sessions >= refit_2018.fit_session]).all()


# With the real model on the planted texts, the out-of-sample AUC of the
# word surprise is high, and C is chosen on the first training set alone.
def test_word_surprise_out_of_sample_with_the_real_model():
    pytest.importorskip("sklearn")
    panel, _sides, _tone = _book()
    rows = _texts(panel)
    result = ts.word_surprise(panel, rows)
    scored = (
        np.isfinite(result.scores) & np.isfinite(result.labels) & (result.labels != 0)
    )
    assert scored.sum() > 200
    assert ts.auc(result.scores[scored], (result.labels[scored] > 0).astype(int)) > 0.9
    assert result.c in ts.C_GRID
    assert result.selection["year"] == 2018
    assert set(result.selection["auc_in_sample"]) == {"0.1", "1.0"}
    assert result.selection["rows"] == result.refits[0]["train_rows"]
    assert all(r["vocabulary"] > 0 for r in result.refits if r["fitted"])


# A refit with too few labelled rows is skipped and recorded, and its
# year stays unscored.
def test_word_surprise_skips_a_thin_refit():
    panel, _sides, _tone = _book()
    rows = _texts(panel)
    result = ts.word_surprise(panel, rows, c=1.0, fit=_Recorder(), min_train=10_000)
    assert not any(r["fitted"] for r in result.refits)
    assert np.isnan(result.scores).all()
    assert (result.fit_years == -1).all()


# The mean per-session rank correlation: identical scores read 1, reversed
# -1, and a session with too few shared cells is left out.
def test_mean_cross_sectional_correlation():
    rng = np.random.default_rng(0)
    a = rng.normal(size=(5, 30))
    cells = np.ones_like(a, dtype=bool)
    same = ts.mean_cross_sectional_correlation(a, a.copy(), cells, 15)
    assert same["mean"] == pytest.approx(1.0)
    assert same["sessions"] == 5
    assert same["pooled"] == pytest.approx(1.0)
    reverse = ts.mean_cross_sectional_correlation(a, -a, cells, 15)
    assert reverse["mean"] == pytest.approx(-1.0)
    cells[0, :20] = False
    fewer = ts.mean_cross_sectional_correlation(a, a, cells, 15)
    assert fewer["sessions"] == 4
    b = a.copy()
    b[:, 0] = np.nan
    assert ts.mean_cross_sectional_correlation(a, b, cells, 15)["sessions"] == 4
