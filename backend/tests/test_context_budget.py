"""What goes into a prompt, and whether the leaving-out is honest.

Three defects in one day came from the same shape: a budget raced for rather
than divided, a limit nobody chose, and a setting that looked like it
controlled something and did not. This is that shape at the next level up, so
the tests are about the properties rather than the arithmetic.

The property that matters most is that a section is never *silently* emptied.
Dropping is allowed - a window is finite - but it has to be reported, and a
low-priority source must not be erased by a greedy high-priority one before it
has had its floor.
"""

import pytest

from backend.core.context_budget import (
    Section,
    calibrate_chars_per_token,
    estimate_tokens,
    plan,
)


def _items(count: int, size: int = 40, tag: str = "x") -> tuple[str, ...]:
    return tuple(f"{tag}{index}:" + "w" * size for index in range(count))


# Under-estimating overruns the window, which fails a request rather than
# shortening it. Over-estimating only wastes a little space.
def test_the_estimate_never_falls_below_what_real_text_costs():
    for chars_per_token in (4.46, 4.72, 6.05):  # measured on the real models
        text = "w" * 1000
        real = int(len(text) / chars_per_token)
        assert estimate_tokens(text) >= real


def test_empty_text_costs_nothing():
    assert estimate_tokens("") == 0


def test_calibration_reports_the_observed_ratio():
    assert calibrate_chars_per_token(184_500, 41_414) == 4.46
    with pytest.raises(ValueError, match="positive"):
        calibrate_chars_per_token(1000, 0)


# The core promise: a floor is honoured before anything takes seconds.
def test_a_low_priority_section_keeps_its_floor_against_a_greedy_one():
    greedy = Section("evidence", _items(50, tag="e"), priority=0)
    small = Section("memory", _items(4, tag="m"), priority=9, floor_items=2)

    report = plan((greedy, small), budget_tokens=60)

    kept = {item.name: item for item in report.allocations}
    assert len(kept["memory"].kept) >= 2, "the floor was not honoured"
    assert kept["evidence"].kept, "the important section was starved"


def test_priority_decides_who_is_squeezed_once_floors_are_paid():
    first = Section("evidence", _items(20, tag="e"), priority=0)
    second = Section("history", _items(20, tag="h"), priority=5)

    report = plan((first, second), budget_tokens=80)

    kept = {item.name: len(item.kept) for item in report.allocations}
    assert kept["evidence"] > kept["history"]


# Dropping is allowed. Dropping without saying so is the defect.
def test_everything_dropped_is_counted():
    section = Section("evidence", _items(30), priority=0)

    report = plan((section,), budget_tokens=25)

    allocation = report.allocations[0]
    assert allocation.dropped == 30 - len(allocation.kept)
    assert allocation.dropped > 0
    assert report.dropped_total == allocation.dropped
    assert not allocation.complete


def test_nothing_is_dropped_when_everything_fits():
    section = Section("memory", _items(3), priority=0)

    report = plan((section,), budget_tokens=10_000)

    assert report.allocations[0].dropped == 0
    assert report.allocations[0].complete
    assert report.dropped_total == 0


# The caller ordered these by relevance. Keeping a later item because it
# happens to be shorter would quietly reverse that judgement.
def test_a_shorter_later_item_does_not_jump_the_queue():
    section = Section(
        "evidence",
        ("A" + "w" * 400, "B" + "w" * 400, "C"),  # C is tiny and least relevant
        priority=0,
    )

    kept = plan((section,), budget_tokens=105).allocations[0].kept

    assert kept
    assert kept[0].startswith("A")
    assert not any(item == "C" for item in kept), "relevance order was reversed"


def test_a_ceiling_stops_one_source_swallowing_a_quiet_turn():
    section = Section("images", _items(40), priority=0, ceiling_items=3)

    report = plan((section,), budget_tokens=100_000)

    assert len(report.allocations[0].kept) == 3
    assert report.allocations[0].dropped == 37


# Spending the whole window on input leaves nothing to answer with. That is
# the reply-budget defect from the same day, one level up.
def test_room_is_left_for_the_reply():
    section = Section("evidence", _items(100), priority=0)

    report = plan((section,), budget_tokens=1_000, reserved_tokens=900)

    assert report.used_tokens <= 100
    assert report.budget_tokens == 100


def test_a_reservation_larger_than_the_window_keeps_nothing():
    section = Section("evidence", _items(10), priority=0)

    report = plan((section,), budget_tokens=100, reserved_tokens=500)

    assert report.used_tokens == 0
    assert report.allocations[0].dropped == 10


def test_a_negative_budget_is_refused():
    with pytest.raises(ValueError, match="negative"):
        plan((), budget_tokens=-1)


def test_no_sections_is_not_an_error():
    report = plan((), budget_tokens=100)
    assert report.used_tokens == 0
    assert not report.allocations


# Equal priorities must not reorder by accident, or the arrangement changes
# whenever someone edits an unrelated section.
def test_equal_priorities_keep_the_declared_order():
    first = Section("a", _items(2, tag="a"), priority=1)
    second = Section("b", _items(2, tag="b"), priority=1)

    report = plan((first, second), budget_tokens=10_000)

    assert [item.name for item in report.allocations] == ["a", "b"]


# The report exists because silence about a trim is what this replaces.
def test_the_report_says_what_happened_whether_or_not_anything_was_dropped():
    sections = (
        Section("evidence", _items(20), priority=0),
        Section("memory", _items(2), priority=5, floor_items=1),
    )

    report = plan(sections, budget_tokens=60)

    summary = report.summary()
    assert "evidence" in summary
    assert "memory" in summary
    assert "tokens" in summary
    payload = report.as_dict()
    assert payload["budget_tokens"] == 60
    assert set(payload["sections"]) == {"evidence", "memory"}
    assert payload["used_tokens"] <= 60


def test_the_budget_is_never_exceeded():
    sections = tuple(
        Section(f"s{index}", _items(30, size=60, tag=f"s{index}"), priority=index)
        for index in range(5)
    )

    for budget in (0, 1, 17, 250, 4_000):
        report = plan(sections, budget_tokens=budget)
        assert report.used_tokens <= budget, f"overran at budget={budget}"
