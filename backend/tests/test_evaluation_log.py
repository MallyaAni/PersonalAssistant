"""Measurements are kept, so a score can be compared with the last one.

Every number this project has measured has lived in a code comment, which
means "did routing get worse this week?" has always been answered by running
it again and remembering. These tests hold the store to the two things that
makes it worth having: a run survives being written and read back, and two
runs can be compared by category.
"""
from pathlib import Path

from backend.core import evaluation_log


def test_a_run_is_written_and_reads_back_the_same(tmp_path: Path):
    written = evaluation_log.record(
        "tool-selection",
        87,
        96,
        reps=3,
        floor=0.85,
        scores={"no-tool": (19, 25), "search": (20, 20)},
        notes="catalogue off",
        root=tmp_path,
    )
    assert written is not None and written.exists()

    runs = evaluation_log.history("tool-selection", root=tmp_path)
    assert len(runs) == 1
    run = runs[0]
    assert (run.right, run.total, run.reps) == (87, 96, 3)
    assert run.notes == "catalogue off"
    assert {score.name: (score.right, score.total) for score in run.scores} == {
        "no-tool": (19, 25),
        "search": (20, 20),
    }
    # The floor is what makes a score a verdict rather than a number.
    assert run.rate > 0.85 and run.passed is True


def test_a_run_below_its_floor_says_so_and_one_without_a_floor_does_not_judge(tmp_path: Path):
    evaluation_log.record("routing", 4, 10, floor=0.9, root=tmp_path)
    evaluation_log.record("routing", 4, 10, root=tmp_path)
    below, unjudged = evaluation_log.history("routing", root=tmp_path)
    assert below.passed is False
    assert unjudged.passed is None


def test_history_is_oldest_first_and_empty_where_nothing_was_measured(tmp_path: Path):
    # Written inside the same second on the same commit: the run-per-category
    # case, which a name resolving only to the second would collapse to one.
    for right in (1, 2, 3):
        evaluation_log.record("sweep", right, 3, root=tmp_path)
    assert len(list((tmp_path / "sweep").glob("*.json"))) == 3
    assert [run.right for run in evaluation_log.history("sweep", root=tmp_path)] == [1, 2, 3]
    assert evaluation_log.history("never-run", root=tmp_path) == []


def test_comparing_two_runs_names_the_categories_that_moved(tmp_path: Path):
    evaluation_log.record(
        "tool-selection", 40, 50, scores={"no-tool": (19, 25), "search": (21, 25)}, root=tmp_path
    )
    evaluation_log.record(
        "tool-selection", 40, 50, scores={"no-tool": (24, 25), "search": (16, 25)}, root=tmp_path
    )
    older, newer = evaluation_log.history("tool-selection", root=tmp_path)
    moved = evaluation_log.compare(older, newer)
    # The aggregate held at 40/50 both times; underneath it two categories
    # swapped. That is the case a single number cannot show you.
    assert older.rate == newer.rate
    assert [category for category, _, _ in moved] == ["no-tool", "search"]
    assert moved[0][1] < moved[0][2] and moved[1][1] > moved[1][2]


def test_an_unreadable_file_is_skipped_rather_than_losing_the_rest(tmp_path: Path):
    evaluation_log.record("routing", 9, 9, root=tmp_path)
    (tmp_path / "routing" / "20260903T000000-bad.json").write_text("{ not json")
    runs = evaluation_log.history("routing", root=tmp_path)
    assert [run.right for run in runs] == [9]


def test_a_store_that_cannot_be_written_does_not_fail_the_measurement(tmp_path: Path):
    blocked = tmp_path / "wall"
    blocked.write_text("this is a file, so it cannot hold a folder")
    assert evaluation_log.record("routing", 9, 9, root=blocked) is None


def test_the_environment_can_say_which_commit_a_run_was_taken_on(tmp_path, monkeypatch):
    # Measurements run inside the container, where the repository arrives
    # without its history and git can say nothing. A run nobody can trace to
    # a commit is a run that cannot be compared with the one before it.
    monkeypatch.setenv("ANIOS_EVALUATION_COMMIT", "deadbee")
    evaluation_log.record("routing", 9, 9, root=tmp_path)
    assert evaluation_log.history("routing", root=tmp_path)[0].commit == "deadbee"
