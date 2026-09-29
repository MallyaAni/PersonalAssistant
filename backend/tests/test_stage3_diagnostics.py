"""Stage 3's post-hoc A/A+ book diagnostics on hand-made exports.

What has to hold (backend/market/stage3_diagnostics.py):

- The book is the rows graded A or A+ with a finite score and a finite r;
  its statistics exist only with `min_names` such rows, the graded IC only
  with `min_names` usable graded rows, and `usable` narrows both.
- `lowest` / `highest` are 1e4 * (r of the lowest / highest-scored book
  name - the book's mean r); the ICs are `stage3_io.spearman`; `gain` is
  -lowest / (n - 1) / 20 bp per session where the book acts, 0 where a
  scored session's book is too small, NaN on unscored sessions.
- `summarize` splits by window and calendar year, ignores NaN, and its t is
  `candidate_stats.hac_t` at `stage3_io.HAC_LAG`.
- A forecast whose keys are not the export's rows, a T-I forecast or
  export, an unknown feature and a rule without its reference are refused.
- End to end, a forecast that knows r puts a laggard at the bottom of the
  book (a negative lowest spread) and its mirror does the opposite; the
  command prints per minimum book size and writes strict JSON.
"""

from __future__ import annotations

import dataclasses
import io as textio
import json
import math

import numpy as np
import pytest

from backend.cli import market_stage3_diagnostics as cli
from backend.market import candidate_stats
from backend.market import stage3_diagnostics as diag
from backend.market import stage3_io as io


# An S1 export from per-session lists of (ticker, grade, r) and one feature
# column per name in `features` ({name: per-row values}).
def _export(sessions, features=None):
    dates, tickers, grades, r = [], [], [], []
    for day, rows in sessions:
        for ticker, grade, value in rows:
            dates.append(np.datetime64(day, "D"))
            tickers.append(ticker)
            grades.append(grade)
            r.append(value)
    count = len(dates)
    features = features or {"d_zero": np.zeros(count)}
    names = tuple(features)
    x = np.column_stack([np.asarray(features[n], dtype=float) for n in names]).astype(np.float32)
    return io.Stage3Data(
        kind=io.S1,
        dates=np.asarray(dates, dtype="datetime64[D]"),
        tickers=np.asarray(tickers),
        slot=np.zeros(count, dtype=np.int8),
        x=x,
        feature_names=names,
        y=np.asarray(r, dtype=np.float32),
        extra={"r": np.asarray(r, dtype=np.float32), "grade": np.asarray(grades, dtype=np.int8)},
    )


# A T-S1 forecast on the export's keys.
def _forecast(data, yhat, family="seq", kind=io.S1):
    count = len(data)
    return io.Stage3Forecast(
        kind=kind,
        family=family,
        dates=data.dates,
        tickers=data.tickers,
        slot=np.zeros(count, dtype=np.int8),
        yhat=np.asarray(yhat, dtype=np.float32),
        yhat_seeds=np.zeros((count, len(io.SEEDS)), dtype=np.float32),
        yhat_configs=None,
        fold=np.zeros(count, dtype=np.int32),
    )


# The three hand-made sessions: a full book, a book of four, and a book cut
# to four by a missing score.
def _three_sessions():
    return _export(
        [
            ("2023-12-29", [("A", 3, 0.01), ("B", 3, 0.03), ("C", 2, -0.02), ("D", 2, 0.00), ("E", 2, 0.05), ("F", 1, -0.04), ("G", 0, 0.02)]),
            ("2024-01-02", [("A", 3, 0.01), ("B", 2, 0.02), ("C", 2, 0.03), ("D", 2, -0.01), ("E", 1, 0.00), ("F", 1, 0.04)]),
            ("2024-01-03", [("A", 2, 0.01), ("B", 2, 0.02), ("C", 2, 0.03), ("D", 2, -0.01), ("E", 2, 0.00), ("F", 1, 0.04)]),
        ]
    )


SCORES = np.array(
    [0.5, 0.9, -0.3, 0.1, 0.2, -1.0, 0.0,
     0.1, 0.2, 0.3, 0.4, 0.5, 0.6,
     np.nan, 0.2, 0.3, 0.4, 0.5, 0.6]
)


# The book statistics of the first session by hand; the second and third
# sessions have books of four, so only their graded IC exists.
def test_book_series_reads_the_lowest_and_highest_book_names():
    data = _three_sessions()
    series = diag.book_series(data, SCORES, min_names=5)
    assert series.dates.tolist() == [np.datetime64(d, "D") for d in ("2023-12-29", "2024-01-02", "2024-01-03")]
    assert series.book_size.tolist() == [5, 4, 4]
    assert series.graded_size.tolist() == [7, 6, 5]
    r = data.extra["r"].astype(float)
    book = [0, 1, 2, 3, 4]
    centre = r[book].mean()
    assert series.lowest[0] == pytest.approx(1e4 * (r[2] - centre))  # C, score -0.3
    assert series.highest[0] == pytest.approx(1e4 * (r[1] - centre))  # B, score 0.9
    assert series.lowest[0] == pytest.approx(-340.0, abs=1e-3)
    assert series.gain[0] == pytest.approx(340.0 / 4 / io.S1_HORIZON, abs=1e-4)
    assert series.gain[1] == 0.0 and series.gain[2] == 0.0
    assert series.ic_book[0] == pytest.approx(io.spearman(SCORES[book], r[book]))
    assert series.ic_all[0] == pytest.approx(io.spearman(SCORES[:7], r[:7]))
    assert all(math.isnan(v) for v in (series.ic_book[1], series.lowest[1], series.highest[2]))
    assert series.ic_all[1] == pytest.approx(io.spearman(SCORES[7:13], r[7:13]))
    assert series.ic_all[2] == pytest.approx(io.spearman(SCORES[14:19], r[14:19]))
    # A smaller minimum admits the books of four.
    small = diag.book_series(data, SCORES, min_names=4)
    assert small.lowest[1] == pytest.approx(1e4 * (r[7] - r[7:11].mean()))  # A, score 0.1
    assert small.highest[1] == pytest.approx(1e4 * (r[10] - r[7:11].mean()))  # D, score 0.4


# `usable` narrows the book: removing one book row leaves four, so the
# first session's book statistics disappear.
def test_usable_narrows_the_book():
    data = _three_sessions()
    usable = np.ones(len(data), dtype=bool)
    usable[4] = False
    series = diag.book_series(data, SCORES, usable=usable, min_names=5)
    assert series.book_size[0] == 4 and math.isnan(series.lowest[0]) and series.gain[0] == 0.0
    nothing = diag.book_series(data, SCORES, usable=np.zeros(len(data), dtype=bool), min_names=5)
    assert np.isnan(nothing.gain).all() and (nothing.graded_size == 0).all()
    with pytest.raises(ValueError, match="one entry per row"):
        diag.book_series(data, SCORES, usable=usable[:3])


# summarize: per window and year, NaN ignored, the t is candidate_stats.hac_t.
def test_summarize_splits_windows_and_years():
    dates = np.datetime64("2023-12-20", "D") + np.arange(30).astype("timedelta64[D]")
    values = np.linspace(-1.0, 2.0, 30)
    values[3] = np.nan
    out = diag.summarize(dates, values)
    early = dates < np.datetime64("2024-01-01")
    first = values[early & np.isfinite(values)]
    assert out["2016-2023"]["n"] == len(first) == 11
    assert out["2016-2023"]["mean"] == pytest.approx(first.mean())
    assert out["2016-2023"]["t"] == pytest.approx(candidate_stats.hac_t(first, io.HAC_LAG))
    assert out["2016-2023"]["median"] == pytest.approx(np.median(first))
    assert out["2016-2023"]["below_zero"] == pytest.approx((first < 0).mean())
    assert out["2024-2026"]["n"] == 18
    assert set(out["years"]) == {"2023", "2024"}
    assert out["years"]["2024"] == pytest.approx(values[~early].mean())
    empty = diag.summarize(dates[:2], np.array([np.nan, np.nan]))
    assert empty["2016-2023"]["n"] == 0 and math.isnan(empty["2016-2023"]["mean"])


# The book correlation of a score with itself is 1 and with its mirror -1,
# and needs min_names book rows.
def test_book_correlation_reads_inside_the_book():
    data = _three_sessions()
    days, same = diag.book_correlation(data, SCORES, SCORES, min_names=5)
    assert same[0] == pytest.approx(1.0) and math.isnan(same[1])
    _, mirror = diag.book_correlation(data, SCORES, -SCORES, min_names=4)
    assert mirror[0] == pytest.approx(-1.0) and mirror[1] == pytest.approx(-1.0)
    assert len(days) == 3


# Refusals: keys that are not the export's rows, T-I inputs, unsorted rows,
# missing extras, an unknown feature, a rule without its reference, scores
# of the wrong length and a book minimum below two.
def test_refusals():
    data = _three_sessions()
    good = _forecast(data, SCORES)
    moved = dataclasses.replace(good, tickers=good.tickers[::-1])
    with pytest.raises(ValueError, match="keys"):
        diag.check_forecast(data, moved)
    with pytest.raises(ValueError, match="not T-S1"):
        diag.check_forecast(data, _forecast(data, SCORES, kind=io.TI))
    ti = dataclasses.replace(data, kind=io.TI)
    with pytest.raises(ValueError, match="T-S1 export"):
        diag.book_series(ti, SCORES)
    bare = dataclasses.replace(data, extra={"r": data.extra["r"]})
    with pytest.raises(ValueError, match="grade"):
        diag.book_series(bare, SCORES)
    with pytest.raises(ValueError, match="sorted"):
        diag.session_bounds(data.dates[::-1])
    with pytest.raises(ValueError, match="unknown feature"):
        diag.diagnose(data, {"seq": good}, features=("d_nope",), reference="seq")
    with pytest.raises(ValueError, match="reference"):
        diag.diagnose(data, {"seq": good}, features=("d_zero",), reference="lgbm")
    with pytest.raises(ValueError, match="rows"):
        diag.book_series(data, SCORES[:5])
    with pytest.raises(ValueError, match="two names"):
        diag.book_series(data, SCORES, min_names=1)


# A synthetic export over late 2023 and early 2024: eight names, six in the
# book on most dates, r random; a feature equal to r and one of noise.
def _world(sessions=60, seed=3):
    rng = np.random.default_rng(seed)
    names = [chr(ord("A") + i) for i in range(8)]
    rows, feature_r, noise = [], [], []
    first = np.datetime64("2023-11-15", "D")
    for s in range(sessions):
        day = str(first + np.timedelta64(s, "D"))
        values = rng.normal(0.0, 0.05, size=len(names))
        grades = np.where(np.arange(len(names)) < 6, 2 + (np.arange(len(names)) % 2), 1)
        rows.append((day, [(n, int(g), float(v)) for n, g, v in zip(names, grades, values)]))
        feature_r.extend(values.tolist())
        noise.extend(rng.normal(size=len(names)).tolist())
    return _export(rows, {"d_r": np.asarray(feature_r), "d_noise": np.asarray(noise)})


# End to end: a forecast that knows r puts the laggard at the bottom (a
# negative lowest spread, a positive highest one), its mirror the opposite;
# the rule on the r column agrees with the reference; the command prints
# per minimum book size, writes strict JSON and refuses a malformed flag.
def test_diagnose_and_the_command_end_to_end(tmp_path):
    data = _world()
    r = data.extra["r"].astype(float)
    knows = r + np.random.default_rng(9).normal(0.0, 0.005, size=len(r))
    record = diag.diagnose(
        data,
        {"good": _forecast(data, knows, "good"), "bad": _forecast(data, -knows, "bad")},
        features=("d_r", "d_noise"),
        reference="good",
        min_names=5,
    )
    for window in ("2016-2023", "2024-2026"):
        assert record["forecasts"]["good"]["lowest"][window]["mean"] < 0
        assert record["forecasts"]["good"]["highest"][window]["mean"] > 0
        assert record["forecasts"]["bad"]["lowest"][window]["mean"] > 0
        assert record["forecasts"]["good"]["gain"][window]["mean"] > 0
        assert record["forecasts"]["bad"]["gain"][window]["mean"] < 0
        assert record["forecasts"]["good"]["ic_book"][window]["mean"] > 0.9
        assert record["rules"]["d_r"]["drop_lowest"][window]["mean"] < 0
        assert record["rules"]["d_r"]["correlation_with_reference"][window]["mean"] > 0.9
    assert record["forecasts"]["good"]["book_sizes"]["2016-2023"] == {"6": 1.0}
    assert record["rules"]["reference"] == "good"

    data_path = io.save_data(tmp_path / "s1.npz", data)
    good_path = io.save_forecast(tmp_path / "good.npz", _forecast(data, knows, "good"))
    out_path = tmp_path / "diag" / "book.json"
    text = textio.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--data", str(data_path), "--forecast", f"good={good_path}", "--reference", "good",
            "--features", "d_r,d_noise", "--min-names", "3", "5", "--out", str(out_path),
        ]
    )
    assert cli.run(args, out=text) == 0
    printed = text.getvalue()
    assert "book of at least 3 names" in printed and "book of at least 5 names" in printed
    assert "rule d_r" in printed and "frictionless drop" in printed and f"wrote {out_path}" in printed
    written = json.loads(out_path.read_text())
    assert set(written["by_min_names"]) == {"3", "5"}
    assert written["by_min_names"]["5"]["forecasts"]["good"]["lowest"]["2024-2026"]["mean"] < 0
    assert "NaN" not in out_path.read_text()
    bad = cli.build_parser().parse_args(["--data", str(data_path), "--forecast", "good"])
    assert cli.run(bad, out=textio.StringIO()) == 2
