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
