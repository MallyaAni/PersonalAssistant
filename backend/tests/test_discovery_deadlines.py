"""Refusing a find whose own text says the deadline has gone.

The describe call already asks the model to notice this, and a real digest still
offered a vote that closed on August 3 to someone reading it on August 10. Date
arithmetic is not what a 4B model is for.
"""

import os
from datetime import date

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.url_dates import deadline_has_passed

TODAY = date(2026, 8, 10)


@pytest.mark.parametrize(
    "text",
    [
        "Vote for your favourite cat or dog through August 3.",
        "Entries close Aug 5.",
        "Open until Jul 31.",
        "Submission deadline August 1",
    ],
)
def test_a_deadline_already_gone_is_refused(text):
    assert deadline_has_passed(text, TODAY) is True


@pytest.mark.parametrize(
    "text",
    [
        # Still open, including the day itself: a page and this machine can be
        # a timezone apart, and dropping something still open where it happens
        # is the worse mistake.
        "Runs through August 10.",
        # Yesterday still passes: a page and this machine can be a timezone
        # apart, and dropping something still open where it happens is worse.
        "Entries close Aug 9.",
        "Open until Sept 12.",
        # A year makes it explicit, which the dated parser already handles.
        "Through August 3, 2026",
        # A start, not a deadline.
        "A concert on August 3.",
        "",
        None,
    ],
)
def test_anything_else_is_left_alone(text):
    assert deadline_has_passed(text, TODAY) is False
