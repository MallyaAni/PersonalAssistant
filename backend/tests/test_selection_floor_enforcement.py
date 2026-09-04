"""A floor that is never checked is a comment.

Every per-tool floor in PER_TOOL_ACCURACY_FLOORS carries a dated measurement
in its comment, and report() compared the aggregate and nothing else. So the
mechanism built to stop one capability collapsing behind a good average had
never once run, which is how a matrix whose no-tool cases scored 55/75 - six
of them wrong on every pass - printed PASS.
"""
from backend.cli.evaluate_tool_selection import Observation, report
from backend.services.tool_selection_cases import (
    PER_TOOL_ACCURACY_FLOORS,
    TOOL_NAMES,
)

NO_TOOL = "none"
SEARCH = "search_web"


def _observations(rows: list[tuple[str, str, int]]) -> list[Observation]:
    made = []
    for expected, chosen, count in rows:
        for index in range(count):
            # arguments_held is None: these cases state no expectation of what
            # the model writes, so the argument floor must not judge them.
            made.append(
                Observation(expected, chosen, "measured", f"case {expected} {index}", None, "")
            )
    return made


def test_one_tool_below_its_floor_fails_the_run(capsys):
    # Everything else perfect, so the aggregate is far above 0.70 and only
    # the per-tool floor can catch it. This is the shape of the real run.
    floor = PER_TOOL_ACCURACY_FLOORS[NO_TOOL]
    below = int(100 * floor) - 5
    passed = report(
        _observations(
            [(NO_TOOL, NO_TOOL, below), (NO_TOOL, SEARCH, 100 - below), (SEARCH, SEARCH, 400)]
        ),
        reps=1,
    )
    assert passed is False
    printed = capsys.readouterr().out
    assert "BREACH" in printed and "floors breached" in printed


def test_a_run_over_every_floor_passes(capsys):
    passed = report(
        _observations([(NO_TOOL, NO_TOOL, 100), (SEARCH, SEARCH, 100)]), reps=1
    )
    assert passed is True
    assert "BREACH" not in capsys.readouterr().out


def test_a_healthy_aggregate_no_longer_hides_a_collapsed_tool(capsys):
    # 400 right out of 500 is 0.80, comfortably over the 0.70 aggregate, while
    # no-tool is at zero. Before enforcement this printed PASS.
    observations = _observations([(NO_TOOL, SEARCH, 100), (SEARCH, SEARCH, 400)])
    correct = sum(1 for seen in observations if seen.expected == seen.chosen)
    assert correct / len(observations) == 0.8
    assert report(observations, reps=1) is False


def test_every_floor_is_a_tool_the_matrix_can_report(capsys):
    # A floor keyed on a name the report never iterates is a floor that cannot
    # fire, which is the same failure one layer along.
    assert set(PER_TOOL_ACCURACY_FLOORS) <= set(TOOL_NAMES)


def test_arguments_that_dropped_the_turns_own_words_fail_the_run(capsys):
    # The gap this closes: the right cell, the wrong thing written into it.
    # Every tool choice here is correct, so only the argument floor can fail.
    held = Observation(SEARCH, SEARCH, "live_data", "what's on this weekend?", True, "Arlington VA events")
    dropped = Observation(SEARCH, SEARCH, "live_data", "what's on this weekend?", False, "events this week")
    assert report([held] * 9 + [dropped], reps=1) is False
    printed = capsys.readouterr().out
    assert "arguments: 9/10" in printed and "BREACH" in printed
    # The failure names what was written, since that is the thing to fix.
    assert "events this week" in printed


def test_cases_stating_no_expectation_are_not_scored_as_passing(capsys):
    report(_observations([(SEARCH, SEARCH, 10)]), reps=1)
    assert "no case states what its arguments must carry" in capsys.readouterr().out
