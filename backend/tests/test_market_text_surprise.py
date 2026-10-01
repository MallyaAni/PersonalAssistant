"""The text-surprise study runner on a synthetic book.

What has to hold: the tables round-trip through their columns; texts load
from a JSONL file and a directory of partial files; every arm is measured
with the stored tone on shared cells through the tone-validity machinery,
with the paired IC and the rank correlation against it; the null test
passes on the level legs and fails on anything else; the plan's criteria
read a change arm that carries the drift as a candidate and a noise arm
as RECORD, with the role following the correlation; the stance tables
hold the analyst's own stances. No store, no model server, no network;
the parquet round-trip runs only where pyarrow is installed.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from backend.agents.trading.desk import sentiment
from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_text_surprise as cli
from backend.market import language
from backend.market import text_surprise as ts
from backend.tests.test_text_surprise import FIRST, QUARTER, _book, _records, _texts


# The A1-1 table: one row per release, the change NaN on the first, and
# the rows read back equal to the surprise rows they came from.
def test_tone_table_round_trip():
    _panel, _sides, tone = _book()
    records = _records(tone)
    columns = cli.tone_table(records)
    releases = sum(len(r) for r in records.values())
    assert len(columns["ticker"]) == releases
    assert set(columns) == {"ticker", "accession", "reaction_date"} | {
        f"{kind}_{name}" for kind in ("level", "change") for name in ts.FIELDS
    }
    back = cli.tone_rows_from_table(columns)
    for ticker, rows in records.items():
        expected = ts.tone_surprise(rows)
        assert len(back[ticker]) == len(expected)
        for a, b in zip(back[ticker], expected, strict=True):
            assert a.accession == b.accession
            assert a.reaction_date == b.reaction_date
            assert np.allclose(a.level, b.level)
            assert np.allclose(a.change, b.change, equal_nan=True)
    first = [i for i, a in enumerate(columns["accession"]) if a.endswith("-0")]
    assert all(np.isnan(columns[f"change_{ts.FIELDS[0]}"][i]) for i in first)


# The A1-3 table: one row per text with its session, label sign, refit
# year and score; the carry-forward rows read back carry the scores.
def test_word_table_round_trip():
    panel, _sides, _tone = _book()
    rows = _texts(panel)
    result = ts.word_surprise(panel, rows, c=1.0, fit=_planted_fit)
    columns = cli.word_table(panel, result)
    assert len(columns["ticker"]) == len(rows)
    for i, row in enumerate(result.rows):
        assert columns["ticker"][i] == row.ticker
        label = result.labels[i]
        sign = columns["label_sign"][i]
        if np.isfinite(label) and label != 0:
            assert sign == (1 if label > 0 else -1)
        else:
            assert sign == 0
        session = result.sessions[i]
        assert columns["reaction_session"][i] == (
            str(panel.dates[session]) if session >= 0 else ""
        )
    assert set(columns["c"]) == {1.0}
    back = cli.word_rows_from_table(columns)
    scores = ts.carry_forward(panel, back, 1)[:, :, 0]
    assert np.array_equal(scores, ts.word_scores(panel, result), equal_nan=True)


# A fit that scores by the planted words, for tests that need no model.
def _planted_fit(texts, y, c):
    class Model:
        vocabulary = frozenset()

        # Positive for "beat", negative for "miss", zero otherwise.
        def log_odds(self, items):
            return np.array(
                [1.0 if "beat" in t else (-1.0 if "miss" in t else 0.0) for t in items]
            )

    return Model()


# Texts load from one JSONL file (rows carrying their ticker) and from a
# directory of <TICKER>.jsonl partial files, restricted to the names asked.
def test_load_texts_from_jsonl_and_directory(tmp_path):
    rows = [
        {
            "ticker": "AAA",
            "accession": "a1",
            "reaction_date": "2020-01-02",
            "text": "x",
        },
        {
            "ticker": "BBB",
            "accession": "b1",
            "reaction_date": "2020-01-03",
            "text": "y",
        },
        {
            "ticker": "AAA",
            "accession": "a0",
            "reaction_date": "2019-10-02",
            "text": "w",
        },
    ]
    one = tmp_path / "texts.jsonl"
    one.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    loaded = cli.load_texts(one)
    assert [(r.ticker, r.accession) for r in loaded] == [
        ("AAA", "a0"),
        ("AAA", "a1"),
        ("BBB", "b1"),
    ]
    assert loaded[0].reaction_date == date(2019, 10, 2)
    assert [r.ticker for r in cli.load_texts(one, ["BBB"])] == ["BBB"]
    folder = tmp_path / "partials"
    folder.mkdir()
    for ticker in ("AAA", "BBB"):
        with (folder / f"{ticker}.partial.jsonl").open("w") as fh:
            for r in rows:
                if r["ticker"] == ticker:
                    fh.write(json.dumps({k: v for k, v in r.items() if k != "ticker"}))
                    fh.write("\n")
    loaded = cli.load_texts(folder)
    assert [(r.ticker, r.accession) for r in loaded] == [
        ("AAA", "a0"),
        ("AAA", "a1"),
        ("BBB", "b1"),
    ]
    assert [r.ticker for r in cli.load_texts(folder, ["AAA"])] == ["AAA", "AAA"]
    with pytest.raises(SystemExit):
        cli.load_texts(tmp_path / "missing")


# A parquet round-trip of a table, where pyarrow is installed.
def test_write_and_read_table(tmp_path):
    pytest.importorskip("pyarrow")
    columns = {"ticker": ["A", "B"], "score": [0.5, float("nan")], "year": [2018, -1]}
    cli.write_table(tmp_path / "t.parquet", columns)
    back = cli.read_table(tmp_path / "t.parquet")
    assert back["ticker"] == ["A", "B"]
    assert back["score"][0] == 0.5
    assert np.isnan(back["score"][1])
    assert back["year"] == [2018, -1]


# The arms on the synthetic book: A is the analyst's ranks, the null arm
# equals it bit for bit, the variants and the word arm are present.
def _arms(panel, tone, with_word: bool = True):
    records = _records(tone)
    tone_a = language.tone_features(panel, records)
    tone_rows = cli.tone_rows_from_table(cli.tone_table(records))
    word_rows = None
    if with_word:
        result = ts.word_surprise(panel, _texts(panel), c=1.0, fit=_planted_fit)
        word_rows = cli.word_rows_from_table(cli.word_table(panel, result))
    return tone_a, cli.arm_ranks(panel, tone_a, tone_rows, word_rows)


# Every arm is present as percentile ranks; A and the null arm coincide.
def test_arm_ranks():
    panel, _sides, tone = _book()
    tone_a, arms = _arms(panel, tone)
    expected = {cli.ARM_A, cli.ARM_LEVEL, cli.ARM_WORD} | {
        cli.ARM_PREFIX_TONE + v for v in ts.VARIANTS
    }
    assert set(arms) == expected
    assert np.array_equal(
        arms[cli.ARM_A], sentiment.opine(tone_a).ranks(), equal_nan=True
    )
    assert np.array_equal(arms[cli.ARM_A], arms[cli.ARM_LEVEL], equal_nan=True)
    for ranks in arms.values():
        finite = ranks[np.isfinite(ranks)]
        assert finite.min() >= 0.0
        assert finite.max() <= 1.0


# The payload: every group measured per horizon and window on shared
# cells with A, the paired IC and the correlation with A per arm, the
# null test passing, the change arm a candidate on the in-window period
# and the word arm a candidate on both windows as one.
def test_evaluate_arms_payload_and_verdicts(monkeypatch):
    panel, sides, tone = _book()
    _tone_a, arms = _arms(panel, tone)
    monkeypatch.setattr(
        cli,
        "WINDOWS",
        {
            "in_window": (date(2016, 1, 4), date(2019, 6, 30)),
            "post_window": (date(2019, 7, 1), None),
            "all_window": (date(2016, 1, 4), None),
        },
    )
    payload = cli.evaluate_arms(panel, sides, arms)
    assert payload["null_test"]["pass"] is True
    assert len(payload["null_test"]["checks"]) == len(cli.HORIZONS) * 3
    for horizon in cli.HORIZONS:
        windows = payload["horizons"][str(horizon)]
        assert set(windows) == {"in_window", "post_window", "all_window"}
        for window in windows.values():
            assert set(window) == {"a1_1", "a1_3", "all"}
            a1_1 = window["a1_1"]
            assert set(a1_1["arms"]) == {cli.ARM_A} | {
                cli.ARM_PREFIX_TONE + v for v in ts.VARIANTS
            }
            assert set(window["a1_3"]["arms"]) == {cli.ARM_A, cli.ARM_WORD}
            assert len(window["all"]["arms"]) == 5
            for group in window.values():
                periods = {r["periods"] for r in group["arms"].values()}
                assert len(periods) == 1  # shared cells, shared periods
                for arm in group["arms"]:
                    if arm != cli.ARM_A:
                        assert arm in group["paired_vs_A"]
                        assert arm in group["correlation_with_A"]
    change = cli.ARM_PREFIX_TONE + ts.VARIANT_CHANGE
    crit = payload["criteria"]
    assert set(crit) == {cli.ARM_PREFIX_TONE + v for v in ts.VARIANTS} | {cli.ARM_WORD}
    assert crit[change]["window"] == "in_window"
    assert crit[cli.ARM_WORD]["window"] == "all_window"
    assert crit[change]["clears_ic_floor"] is True
    assert crit[change]["not_worse_than_A"] is True
    assert crit[change]["paired_delta_vs_A"] > 0
    assert payload["verdicts"][change].startswith("CANDIDATE")
    assert "pending" in crit[change]["book_gate"]
    # The word arm carries the sign of the one-day reaction, which on this
    # book is noise at twenty sessions: RECORD, with the gate not run.
    assert payload["verdicts"][cli.ARM_WORD] == "RECORD"
    assert crit[cli.ARM_WORD]["book_gate"].startswith("not run")


# A1-1 alone, without a word table, still evaluates and judges its variants.
def test_evaluate_arms_without_the_word_arm(monkeypatch):
    panel, sides, tone = _book()
    _tone_a, arms = _arms(panel, tone, with_word=False)
    monkeypatch.setattr(
        cli,
        "WINDOWS",
        {
            "in_window": (date(2016, 1, 4), date(2019, 6, 30)),
            "post_window": (date(2019, 7, 1), None),
            "all_window": (date(2016, 1, 4), None),
        },
    )
    payload = cli.evaluate_arms(panel, sides, arms)
    assert set(payload["horizons"]["20"]["in_window"]) == {"a1_1"}
    assert cli.ARM_WORD not in payload["criteria"]
    assert len(payload["criteria"]) == 3


# The null test fails when the level arm is not the analyst's: a shifted
# release date or a noise level breaks the bit-for-bit equality.
def test_null_test_fails_on_a_misaligned_level():
    panel, sides, tone = _book()
    _tone_a, arms = _arms(panel, tone, with_word=False)
    in_book = np.array([t in sides for t in panel.tickers])
    assert cli.null_test(arms, panel, in_book)["pass"] is True
    shifted = dict(arms)
    shifted[cli.ARM_LEVEL] = np.vstack(
        [arms[cli.ARM_LEVEL][1:], arms[cli.ARM_LEVEL][-1:]]
    )
    assert cli.null_test(shifted, panel, in_book)["pass"] is False


# The criteria on handcrafted numbers: the floor, the paired guard, the
# role by correlation, and the null test's veto.
def _window(ic, t, delta, paired_t, corr, arm="A1-1 change"):
    return {
        "arms": {cli.ARM_A: {"ic": 0.03, "t": 2.5}, arm: {"ic": ic, "t": t}},
        "paired_vs_A": {arm: {"delta": delta, "t": paired_t, "periods": 90}},
        "correlation_with_A": {arm: {"mean": corr, "sessions": 100, "pooled": corr}},
    }


def test_criteria_and_verdict_rules():
    # The criteria of one arm from handcrafted window numbers.
    def crit(ic, t, delta, paired_t, corr, null_pass=True):
        windows = {
            "in_window": {"a1_1": _window(ic, t, delta, paired_t, corr)},
            "post_window": {"a1_1": _window(0.01, 0.5, -0.01, -0.3, corr)},
            "all_window": {"a1_1": _window(ic, t, delta, paired_t, corr)},
        }
        return cli.criteria(windows, null_pass)["A1-1 change"]

    good = crit(0.025, 2.4, 0.002, 0.3, 0.1)
    assert good["clears_ic_floor"] is True
    assert good["not_worse_than_A"] is True
    assert good["role"] == "sixth analyst"
    assert good["ic_post_window"] == 0.01
    assert cli.verdict(good).startswith("CANDIDATE (sixth analyst)")
    replacement = crit(0.025, 2.4, 0.002, 0.3, 0.6)
    assert replacement["role"] == "replacement candidate"
    assert cli.verdict(replacement).startswith("CANDIDATE (replacement candidate)")
    low_ic = crit(0.019, 2.4, 0.002, 0.3, 0.1)
    assert low_ic["clears_ic_floor"] is False
    assert cli.verdict(low_ic) == "RECORD"
    low_t = crit(0.03, 1.9, 0.002, 0.3, 0.1)
    assert cli.verdict(low_t) == "RECORD"
    worse = crit(0.03, 2.4, -0.01, -1.2, 0.1)
    assert worse["not_worse_than_A"] is False
    assert cli.verdict(worse) == "RECORD"
    worse_but_noisy = crit(0.03, 2.4, -0.01, -0.8, 0.1)
    assert worse_but_noisy["not_worse_than_A"] is True
    nan_ic = crit(float("nan"), float("nan"), float("nan"), float("nan"), float("nan"))
    assert cli.verdict(nan_ic) == "RECORD"
    assert nan_ic["role"] == "replacement candidate"  # unknown correlation is not < 0.3
    vetoed = crit(0.03, 2.4, 0.002, 0.3, 0.1, null_pass=False)
    assert cli.verdict(vetoed).startswith("INVALID")


# The stance table holds the analyst's own stances of the arm: every
# non-zero stance, in {-1, 1}, on a session and a name.
def test_stance_table():
    panel, _sides, tone = _book()
    _tone_a, arms = _arms(panel, tone, with_word=False)
    ranks = arms[cli.ARM_PREFIX_TONE + ts.VARIANT_CHANGE]
    columns = cli.stance_table(panel, ranks)
    stances = Opinion("arm", ranks).stances()
    assert len(columns["session"]) == int((stances != 0).sum())
    assert set(columns["stance"]) == {-1, 1}
    for session, ticker, stance in zip(
        columns["session"], columns["ticker"], columns["stance"], strict=True
    ):
        t = int(
            np.searchsorted(panel.dates.astype("datetime64[D]"), np.datetime64(session))
        )
        assert stances[t, panel.index(ticker)] == stance


# The printed payload names the null test, every group and every verdict.
def test_print_payload(capsys, monkeypatch):
    panel, sides, tone = _book()
    _tone_a, arms = _arms(panel, tone, with_word=False)
    monkeypatch.setattr(
        cli,
        "WINDOWS",
        {
            "in_window": (date(2016, 1, 4), date(2019, 6, 30)),
            "post_window": (date(2019, 7, 1), None),
            "all_window": (date(2016, 1, 4), None),
        },
    )
    payload = cli.evaluate_arms(panel, sides, arms)
    cli.print_payload(payload)
    out = capsys.readouterr().out
    assert "null test" in out
    assert "PASS" in out
    assert "=== horizon 20, in_window, a1_1" in out
    assert "=== verdicts ===" in out
    assert cli.ARM_PREFIX_TONE + ts.VARIANT_CHANGE_GATED in out


# The parser: both subcommands and their arguments.
def test_parser():
    parser = cli.build_parser()
    args = parser.parse_args(["build", "--root", "r", "--out", "o", "--c", "0.1"])
    assert args.command == "build"
    assert args.c == 0.1
    assert args.texts is None
    args = parser.parse_args(["evaluate", "--root", "r", "--tables", "t", "--out", "o"])
    assert args.command == "evaluate"
    assert args.stances is None


# Windows and constants as the plan registered them.
def test_registered_windows_and_floors():
    assert (date(2018, 1, 1), date(2025, 5, 31)) == cli.IN_WINDOW
    assert (date(2025, 6, 1), None) == cli.POST_WINDOW
    assert (date(2018, 1, 1), None) == cli.ALL_WINDOW
    assert cli.HORIZONS == (20, 60)
    assert cli.PRIMARY_HORIZON == 20
    assert cli.IC_FLOOR == 0.02
    assert cli.T_FLOOR == 2.0
    assert cli.PAIRED_T_FLOOR == -1.0
    assert cli.SIXTH_ANALYST_CORRELATION == 0.3
    assert ts.PURGE == 20
    assert ts.C_GRID == (0.1, 1.0)
    assert ts.MIN_DF == 20
    assert ts.FIRST_REFIT_YEAR == 2018
    assert date(2015, 1, 1) == ts.TRAIN_START
    assert ts.GATE == 0.5
    assert FIRST + timedelta(days=QUARTER) > FIRST  # the fixtures are shared


# The two steps end to end on the synthetic book, the store replaced by
# the fixtures and the parquet writer by JSON where pyarrow is absent:
# build writes both tables and the fit record, evaluate reads them back,
# passes the null test, writes the payload and the stance tables.
def test_build_then_evaluate_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("sklearn")
    panel, sides, tone = _book()
    records = _records(tone)
    tone_a = language.tone_features(panel, records)
    monkeypatch.setattr(cli.tv, "_panel_and_tone", lambda root: (panel, sides, tone_a))
    monkeypatch.setattr(cli, "stored_tone_records", lambda store, tickers: records)
    monkeypatch.setattr(cli, "load_texts", lambda path, tickers=None: _texts(panel))
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        # The table as JSON, in place of parquet.
        def write_json(path, columns):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(columns, default=float))

        # The JSON table back as columns.
        def read_json(path):
            return json.loads(path.read_text())

        monkeypatch.setattr(cli, "write_table", write_json)
        monkeypatch.setattr(cli, "read_table", read_json)
    monkeypatch.setattr(
        cli,
        "WINDOWS",
        {
            "in_window": (date(2016, 1, 4), date(2019, 6, 30)),
            "post_window": (date(2019, 7, 1), None),
            "all_window": (date(2016, 1, 4), None),
        },
    )
    tables = tmp_path / "tables"
    summary = cli.run_build(tmp_path / "store", None, tables, None, False)
    assert summary["tone_releases"] == sum(len(r) for r in records.values())
    assert summary["tone_with_predecessor"] == summary["tone_releases"] - len(records)
    assert (tables / cli.TONE_TABLE).exists()
    assert (tables / cli.WORD_TABLE).exists()
    fit = json.loads((tables / cli.WORD_FIT).read_text())
    assert fit["c"] in ts.C_GRID
    assert fit["scored"] > 0
    assert fit["purge"] == 20
    out = tmp_path / "result.json"
    payload = cli.run_evaluate(tmp_path / "store", tables, out, None)
    assert out.exists()
    assert payload["null_test"]["pass"] is True
    assert payload["word_surprise_fit"]["c"] == fit["c"]
    assert set(payload["stance_tables"]) == {cli.ARM_WORD} | {
        cli.ARM_PREFIX_TONE + v for v in ts.VARIANTS
    }
    for path in payload["stance_tables"].values():
        assert Path(path).exists()
    assert payload["scorecard_follow_up"].startswith(
        "python -m backend.cli.market_pit_scorecard"
    )
    written = json.loads(out.read_text())
    assert written["verdicts"] == payload["verdicts"]
