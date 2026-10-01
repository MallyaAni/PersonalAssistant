"""An external stance table is read point in time and graded beside the five.

What has to hold: a row applies to the first session on or after its date
and to no earlier one; a (session, name) with no row is neutral; a name the
panel lacks is ignored; in `sixth` mode the table is another analyst's vote
under the unchanged rule, in `replace:<analyst>` mode it stands in that
analyst's place; and a table of zeros in `sixth` mode reproduces the desk's
own grade, votes, conviction and scores bit for bit.
"""

import hashlib
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import desk, grading, regime, stance_table
from backend.agents.trading.desk.grading import ANALYST_WEIGHTS, grade_from_stances
from backend.agents.trading.desk.opinions import Opinion
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE

NAMES = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
T = 120


# A desk report graded by the desk's own rule from four random analysts and
# an ungated rotation with no view, over T weekday sessions from 2023-01-02.
def desk_report(seed: int = 0, sessions: int = T, names=NAMES) -> desk.DeskReport:
    rng = np.random.default_rng(seed)
    n = len(names)
    days = []
    d = date(2023, 1, 2)
    while len(days) < sessions:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    dates = np.array(days, dtype="datetime64[D]")
    walk = rng.normal(0.0004, 0.02, size=(sessions, n + 1)).cumsum(axis=0)
    close = 100.0 * np.exp(walk)
    panel = Panel(
        dates=dates,
        tickers=tuple(names) + ("SPY",),
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: (AI_COMPUTE,) for t in names},
        benchmark="SPY",
    )

    def opinion(name):
        scores = rng.normal(size=(sessions, n + 1))
        scores[:, n] = np.nan
        return Opinion(name, scores)

    analysts = ("fundamental", "technical", "sentiment", "value")
    opinions = {k: opinion(k) for k in analysts}
    state = regime.RegimeState(
        0.0, 0.0, 0.5, 0.0, 0.0, 0.0, "ai", 0.1, 0.0, 1.0, 1.0, (), 0.0, False
    )
    view = regime.RegimeView(
        [state] * sessions, Opinion("rotation", np.full((sessions, n + 1), np.nan))
    )
    return desk.assemble(panel, {t: "ai" for t in names}, opinions, view, ())


# A table from rows of (date, ticker, stance[, conviction]).
def table(rows, path="t.csv", **extra_columns) -> stance_table.StanceTable:
    columns = {
        "session": [r[0] for r in rows],
        "ticker": [r[1] for r in rows],
        "stance": [r[2] for r in rows],
    }
    if any(len(r) > 3 for r in rows):
        columns["conviction"] = [r[3] if len(r) > 3 else "" for r in rows]
    columns.update(extra_columns)
    return stance_table.from_columns(columns, path, "deadbeef")


# The one-name rule's letter for a cell of a Graded.
def _letter(graded: grading.Graded, t: int, j: int) -> str:
    stances = {k: int(v[t, j]) for k, v in graded.stances.items()}
    return grade_from_stances(stances, ANALYST_WEIGHTS)[0]


# The mode string: sixth, replace:<one of the five>, nothing else.
def test_parse_mode():
    assert stance_table.parse_mode("sixth") == ("sixth", None)
    assert stance_table.parse_mode("replace:sentiment") == ("replace", "sentiment")
    assert stance_table.parse_mode("replace:rotation") == ("replace", "rotation")
    for bad in ("", "seventh", "replace", "replace:", "replace:tone", "sixth:x"):
        with pytest.raises(ValueError, match="unknown stance mode"):
            stance_table.parse_mode(bad)


# The columns: a date column and a name column under their usual names, a
# stance in {-1, 0, 1}, a conviction in [-1, 1] or a rank in [0, 1] turned
# into one; anything else is refused, and the grade name is the file stem.
def test_from_columns_validates_and_names():
    rows = [("2023-01-03", "AAA", 1), ("2023-01-04", "bbb", "-1")]
    t = table(rows, path="x/A2.parquet")
    assert t.name == "table:A2"
    assert len(t) == 2
    assert t.tickers == ("AAA", "BBB")
    assert list(t.stances) == [1, -1]
    assert np.isnan(t.convictions).all()
    assert t.columns == ("session", "ticker", "stance")
    aliased = stance_table.from_columns(
        {"date": ["2023-01-03"], "name": ["AAA"], "stance": [0], "rank": [1.0]}
    )
    assert aliased.convictions[0] == pytest.approx(1.0)
    with_conviction = table([("2023-01-03", "AAA", 1, 0.25)])
    assert with_conviction.convictions[0] == 0.25
    with pytest.raises(ValueError, match="needs columns"):
        stance_table.from_columns({"session": [], "stance": []})
    with pytest.raises(ValueError, match="a stance is -1, 0 or 1"):
        table([("2023-01-03", "AAA", 2)])
    with pytest.raises(ValueError, match="conviction"):
        table([("2023-01-03", "AAA", 1, 1.5)])
    with pytest.raises(ValueError, match="rank"):
        stance_table.from_columns(
            {"session": ["2023-01-03"], "ticker": ["AAA"], "stance": [0], "rank": [2.0]}
        )
    with pytest.raises(ValueError, match="date"):
        table([("not a date", "AAA", 1)])
    empty = stance_table.from_columns({"session": [], "ticker": [], "stance": []})
    assert len(empty) == 0


# The date rule: a row lands on the first session on or after its date and
# on that session only; a row dated after a session cannot touch it; a row
# dated on a weekend lands on the Monday; a row past the panel's end, before
# its start, for a name the panel lacks, or for the benchmark is dropped and
# counted; the later of two rows on one cell wins; everything else is
# neutral.
def test_align_is_point_in_time_and_neutral_where_silent():
    report = desk_report(sessions=10)
    panel = report.panel
    dates = [str(d) for d in panel.dates]
    assert dates[0] == "2023-01-02"
    assert dates[4] == "2023-01-06"
    assert dates[5] == "2023-01-09"
    t = table(
        [
            (dates[3], "AAA", 1),
            ("2023-01-07", "BBB", -1),  # Saturday -> Monday the 9th
            ("2023-01-08", "BBB", 1),  # Sunday -> the same Monday, later, wins
            (dates[2], "CCC", -1),
            (dates[2], "CCC", 1, 0.5),  # the same cell, file order: last wins
            ("2030-01-01", "AAA", 1),  # after the panel
            ("2022-12-30", "AAA", 1),  # before the panel
            (dates[1], "ZZZ", 1),  # not a book name
            (dates[1], "SPY", 1),  # the benchmark
        ]
    )
    aligned = stance_table.align(t, panel)
    stance, conviction = aligned.stance, aligned.conviction
    assert stance.shape == (10, 7)
    aaa, bbb, ccc = 0, 1, 2
    # AAA: dated on session 3 -> session 3 only, nothing before or after.
    assert stance[3, aaa] == 1
    assert conviction[3, aaa] == 1.0
    assert not stance[:3, aaa].any()
    assert not stance[4:, aaa].any()
    # BBB: the weekend rows land on the Monday; the Sunday row wins.
    assert stance[5, bbb] == 1
    assert not stance[:5, bbb].any()
    assert not stance[6:, bbb].any()
    # CCC: two rows on one date, the later in the file wins with its conviction.
    assert stance[2, ccc] == 1
    assert conviction[2, ccc] == 0.5
    # Everything else is neutral with no conviction.
    assert (stance != 0).sum() == 3
    assert np.isfinite(conviction).sum() == 3
    record = aligned.record
    assert record["rows"] == 9
    assert record["rows_used"] == 5
    assert record["rows_after_panel"] == 1
    assert record["rows_before_panel"] == 1
    assert record["rows_unknown_name"] == 1
    assert record["rows_benchmark"] == 1
    assert record["rows_mapped_forward"] == 2
    assert record["rows_overridden"] == 2
    assert record["cells_bullish"] == 3
    assert record["cells_bearish"] == 0
    assert record["first_session"] == dates[2]
    assert record["last_session"] == dates[5]
    assert record["sha256"] == "deadbeef"
    assert record["name"] == "table:t"
    # The point-in-time property, stated as the test the plan asks for: a
    # row dated after session t does not affect t, for every t.
    for t_ in range(10):
        later = table([(d, "DDD", 1) for d in dates[t_ + 1 :]])
        assert not stance_table.align(later, panel).stance[: t_ + 1, 3].any()
    # An empty table is all neutral.
    none = stance_table.align(table([]), panel)
    assert not none.stance.any()
    assert none.record["rows_used"] == 0
    assert none.record["first_session"] is None


# In `sixth` mode the table is another analyst's vote under the unchanged
# rule: every cell's grade is what the one-name rule gives the five stances
# plus the table's, the conviction enters the ordering score, the five
# stances are untouched, and the alternate report is re-graded too.
def test_regrade_sixth_is_another_analysts_vote():
    report = desk_report()
    panel = report.panel
    rng = np.random.default_rng(1)
    rows = []
    for t in range(0, T, 3):
        for name in NAMES:
            s = int(rng.integers(-1, 2))
            if s:
                rows.append((str(panel.dates[t]), name, s))
    aligned = stance_table.align(table(rows, path="A1.csv"), panel)
    with_alternate = replace(report, alternate=report)
    out = stance_table.regrade(with_alternate, [aligned], "sixth")
    assert set(out.graded.stances) == set(report.graded.stances) | {"table:A1"}
    for name in report.graded.stances:
        assert np.array_equal(out.graded.stances[name], report.graded.stances[name])
    assert np.array_equal(out.graded.stances["table:A1"], aligned.stance)
    assert np.array_equal(out.alternate.graded.grades, out.graded.grades)
    moved = out.graded.grades != report.graded.grades
    assert moved.any()
    for t in range(T):
        for j in range(len(NAMES)):
            stances = {k: int(v[t, j]) for k, v in report.graded.stances.items()}
            stances["table:A1"] = int(aligned.stance[t, j])
            letter, votes = grade_from_stances(stances, ANALYST_WEIGHTS)
            assert out.graded.letter(t, j) == letter
            assert out.graded.votes[t, j] == pytest.approx(votes)
    # The table's conviction (its stance, with no conviction column) is in
    # the summed score at a full weight, nowhere else.
    expected = report.graded.conviction + np.nan_to_num(aligned.conviction)
    np.testing.assert_allclose(out.graded.conviction, expected)
    np.testing.assert_allclose(out.scores, expected, equal_nan=True)
    # The book was re-sized from the new grades and scores.
    assert isinstance(out.book, list)
    # Two tables are two votes; the same table twice is refused by name.
    second = stance_table.align(table(rows, path="A4.csv"), panel)
    both = stance_table.regrade(report, [aligned, second], "sixth")
    assert {"table:A1", "table:A4"} <= set(both.graded.stances)
    np.testing.assert_allclose(
        both.graded.votes, report.graded.votes + 2 * aligned.stance
    )
    with pytest.raises(ValueError, match="both named"):
        stance_table.regrade(report, [aligned, aligned], "sixth")
    with pytest.raises(ValueError, match="not aligned"):
        stance_table.regrade(desk_report(sessions=10), [aligned], "sixth")


# In `replace:sentiment` mode the table stands where the release stood:
# the grade is the one-name rule on the five with the table as sentiment,
# the other four are untouched, a bearish table row vetoes as the analyst
# would, and the mode takes exactly one table.
def test_regrade_replace_substitutes_the_analyst():
    report = desk_report(seed=2)
    panel = report.panel
    draws = np.random.default_rng(3).integers(-1, 2, len(NAMES))
    rows = [
        (str(panel.dates[t]), name, int(s))
        for t in range(T)
        for name, s in zip(NAMES, draws, strict=True)
        if s
    ]
    aligned = stance_table.align(table(rows, path="A2.csv"), panel)
    out = stance_table.regrade(report, [aligned], "replace:sentiment")
    assert set(out.graded.stances) == set(report.graded.stances)
    assert np.array_equal(out.graded.stances["sentiment"], aligned.stance)
    for name in ("fundamental", "technical", "rotation", "value"):
        assert np.array_equal(out.graded.stances[name], report.graded.stances[name])
    for t in range(T):
        for j in range(len(NAMES)):
            assert out.graded.letter(t, j) == _letter(out.graded, t, j)
    # The replaced analyst's conviction is the table's in the score.
    own = np.nan_to_num(report.opinions["sentiment"].conviction())
    expected = report.graded.conviction - own + np.nan_to_num(aligned.conviction)
    np.testing.assert_allclose(out.graded.conviction, expected, atol=1e-12)
    # Replacing the value analyst, a bearish row caps the grade at B.
    valued = stance_table.regrade(report, [aligned], "replace:value")
    bear = aligned.stance == -1
    assert (valued.graded.grades[bear] <= grading.ORDINAL["B"]).all()
    # Replacing rotation keeps its half weight.
    rotated = stance_table.regrade(report, [aligned], "replace:rotation")
    np.testing.assert_allclose(
        rotated.graded.votes, report.graded.votes + 0.5 * aligned.stance
    )
    with pytest.raises(ValueError, match="exactly one"):
        stance_table.regrade(report, [aligned, aligned], "replace:sentiment")
    with pytest.raises(ValueError, match="unknown stance mode"):
        stance_table.regrade(report, [aligned], "replace:tone")


# The null: the same rows with every stance and conviction zeroed, in
# `sixth` mode, reproduce the grade, the votes, the conviction and the
# scores bit for bit, with the sixth stance recorded as all zeros.
def test_zeroed_table_reproduces_the_desk_bit_for_bit():
    report = desk_report(seed=4)
    panel = report.panel
    rows = [
        (str(panel.dates[t]), name, 1 if t % 2 else -1)
        for t in range(T)
        for name in NAMES
    ]
    aligned = stance_table.align(table(rows, path="A4.csv"), panel)
    live = stance_table.regrade(report, [aligned], "sixth")
    assert (live.graded.grades != report.graded.grades).any()
    null = stance_table.zeroed(aligned)
    assert null.record["null"] is True
    assert null.record["rows_used"] == aligned.record["rows_used"]
    out = stance_table.regrade(report, [null], "sixth")
    assert np.array_equal(out.graded.grades, report.graded.grades)
    assert np.array_equal(out.graded.votes, report.graded.votes)
    conviction = report.graded.conviction
    assert np.array_equal(out.graded.conviction, conviction, equal_nan=True)
    assert np.array_equal(out.scores, report.scores, equal_nan=True)
    assert not out.graded.stances["table:A4"].any()
    assert len(out.book) == len(report.book)


# The grade record counts the eligible name-sessions at each grade before
# and after, per window, and how many cells moved which way.
def test_grade_record_counts_moves_per_window():
    report = desk_report(seed=5)
    panel = report.panel
    rows = [(str(panel.dates[t]), "AAA", 1) for t in range(T)]
    aligned = stance_table.align(table(rows), panel)
    out = stance_table.regrade(report, [aligned], "sixth")
    mask = np.ones(report.graded.grades.shape, dtype=bool)
    mask[:, -1] = False
    windows = {"all": (None, None), "none": (date(2030, 1, 1), None)}
    record = stance_table.grade_record(report, out, mask, windows)
    everything = record["all"]
    cells = T * len(NAMES)
    assert everything["eligible_name_sessions"] == cells
    assert sum(everything["before"].values()) == cells
    assert sum(everything["after"].values()) == cells
    assert everything["moved"] == everything["moved_up"] + everything["moved_down"]
    assert everything["moved_down"] == 0
    assert everything["moved_up"] > 0
    moved = (out.graded.grades != report.graded.grades)[:, :-1]
    assert everything["moved"] == int(moved.sum())
    assert record["none"]["eligible_name_sessions"] == 0
    assert record["none"]["moved"] == 0


# A CSV on disk loads with its sha256 and its stem as the grade name; a
# parquet file loads the same way when pyarrow is present.
def test_load_reads_csv_and_parquet_with_sha256(tmp_path):
    path = tmp_path / "A1-1_change.csv"
    path.write_text(
        "session,ticker,stance\n2023-01-03,AAA,1\n2023-01-04,BBB,-1\n", encoding="utf-8"
    )
    loaded = stance_table.load(path)
    assert loaded.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert loaded.name == "table:A1-1_change"
    assert loaded.path == str(path)
    assert loaded.tickers == ("AAA", "BBB")
    assert list(loaded.stances) == [1, -1]
    header_only = tmp_path / "empty.csv"
    header_only.write_text("session,ticker,stance\n", encoding="utf-8")
    assert len(stance_table.load(header_only)) == 0
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    parquet = tmp_path / "A2.parquet"
    pq.write_table(
        pa.table({"session": ["2023-01-03"], "ticker": ["CCC"], "stance": [1]}), parquet
    )
    back = stance_table.load(parquet)
    assert back.name == "table:A2"
    assert back.tickers == ("CCC",)
    assert back.sha256 == hashlib.sha256(parquet.read_bytes()).hexdigest()
