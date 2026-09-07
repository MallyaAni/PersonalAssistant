"""The sweep's cleanup runs whether or not the run had a group.

Deploy #31 (2026-08-29): the deploy's single-journey retry selects one journey,
which is usually not a group one, so `self.group_id` is empty. `remove` had
imported `purge_owned_rows` inside the group branch and used it again after,
so that run raised UnboundLocalError and logged "harness_journeys left behind".
The account was removed on the next attempt, so the only casualty was a
misleading line in a deploy log - which is exactly the kind of defect that
teaches an operator to ignore their logs.
"""

from __future__ import annotations

import ast
import inspect

from backend.cli.sweep_journeys import Sweep, sweep_identities


def test_every_name_remove_uses_is_bound_on_every_path():
    # Read the function rather than run it: `remove` talks to a database and a
    # live API, and the bug was a binding, which the source can settle.
    tree = ast.parse(inspect.getsource(Sweep.remove).lstrip())
    function = tree.body[0]
    # Imports that sit inside a conditional are the shape that caused this.
    conditional_imports: list[str] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.ImportFrom):
                conditional_imports.extend(alias.name for alias in inner.names)
    used_outside: set[str] = set()
    conditional_bodies = [
        inner
        for node in ast.walk(function)
        if isinstance(node, ast.If)
        for inner in ast.walk(node)
    ]
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and node.id in conditional_imports:
            if node not in conditional_bodies:
                used_outside.add(node.id)
    assert not used_outside, (
        f"{sorted(used_outside)} is imported inside a branch of remove() and used "
        "outside it; a run with no group would raise UnboundLocalError"
    )


def test_the_identities_are_stable_and_recognisable():
    user, member, chat = sweep_identities()
    assert user == "harness_journeys" and member == "harness_journeys_member"
    assert chat == "imessage;+;chatharness_journeys"
    assert sweep_identities() == (user, member, chat)


def test_an_isolated_run_names_a_different_set():
    assert sweep_identities("b")[0] != sweep_identities()[0]
    assert sweep_identities("b")[1] != sweep_identities()[1]
    assert sweep_identities("b")[2] != sweep_identities()[2]


# Every journey runs against the same harness user, so a reminder one journey
# arms is still there when a later one counts rows.
#
# "delete the paused ones" asserts that no reminder remains at its own hours.
# It used to arm 9am and 10am - the same hours "schedule a reminder" and "move
# it to 10am" leave enabled behind - so the assertion counted their rows and
# failed. Only in a full sweep: run alone with --only there is no earlier
# journey, so it passed on every retry and was logged as flaky for three
# deploys running. Nothing about it was timing.
#
# This pins the invariant rather than the fix: any journey that asserts an
# hour is empty must own that hour.
def test_a_journey_that_asserts_an_hour_is_empty_owns_that_hour():
    import re

    from backend.cli.sweep_journeys import JOURNEYS

    def hours_armed(journey) -> set[int]:
        said = " ".join((*journey.before, journey.query)).lower()
        found = set()
        for value, meridiem in re.findall(r"\b(\d{1,2})\s*(am|pm)\b", said):
            hour = int(value) % 12
            found.add(hour + 12 if meridiem == "pm" else hour)
        return found

    def hours_claimed_empty(journey) -> set[int]:
        found = set()
        for clause in journey.sql_holds or ():
            if "count(*) = 0" not in clause:
                continue
            for group in re.findall(r"hour in \(([\d,\s]+)\)", clause):
                found.update(int(part) for part in group.split(","))
            for one in re.findall(r"hour = (\d+)", clause):
                found.add(int(one))
        return found

    for journey in JOURNEYS:
        claimed = hours_claimed_empty(journey)
        if not claimed:
            continue
        for other in JOURNEYS:
            if other.name == journey.name:
                continue
            clash = claimed & hours_armed(other)
            assert not clash, (
                f"{journey.name!r} asserts nothing remains at {sorted(claimed)}, "
                f"but {other.name!r} arms {sorted(clash)} on the same user"
            )
