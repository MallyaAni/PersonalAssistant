"""The namespace test accounts live in, and the guarantee that people do not.

On 2026-08-29 the operator found ten accounts they did not recognise sitting
beside their own - the journey sweep's, one per run, left behind whenever a
run died before its cleanup. The fix has two halves: one id per harness role
instead of one per run, and one place that decides what a harness id is. These
tests hold the second half, because everything destructive downstream trusts
it.
"""

import pytest

from backend.core.harness_identity import (
    HARNESS_PREFIX,
    LEGACY_PREFIXES,
    harness_id,
    is_harness_id,
)


def test_a_role_gets_the_same_id_every_run():
    # The whole point: two runs of the same harness are the same account, so a
    # run that dies before cleanup leaks that one account and never a new one.
    assert harness_id("journeys") == harness_id("journeys")
    assert harness_id("journeys") != harness_id("search")


def test_an_isolated_run_gets_its_own_set():
    # The edge case one fixed id cannot serve: two sweeps at once, each of
    # which purges its own accounts before starting.
    assert harness_id("journeys", "b") != harness_id("journeys")
    assert harness_id("journeys", "b") != harness_id("journeys", "c")
    assert is_harness_id(harness_id("journeys", "b"))


def test_every_id_it_makes_is_one_it_recognises():
    for role in ("journeys", "search", "images", "some new harness"):
        assert is_harness_id(harness_id(role)), role
        assert harness_id(role).startswith(HARNESS_PREFIX)


def test_the_ids_that_predate_the_namespace_are_still_recognised():
    # The ten that were already in the database when this was written.
    for prefix in LEGACY_PREFIXES:
        assert is_harness_id(f"{prefix}3549563b")


@pytest.mark.parametrize(
    "user_id",
    ["ani.mallya", "jenos1", "group:c1ed635532e6", "", "harness", "sweeper", "sweepstakes_bob"],
)
def test_no_real_account_shape_is_mistaken_for_a_harness(user_id):
    # A false positive here is a deleted person, so the check is deliberately
    # a prefix and not a substring: "sweepstakes_bob" is somebody.
    assert not is_harness_id(user_id)


def test_a_role_with_awkward_characters_still_makes_a_usable_id():
    # The id goes into URLs (/memory/{user}) and into a username column with a
    # bounded syntax, so it may not carry whatever a caller typed.
    made = harness_id("Journeys / Group Member!")
    assert made == "harness_journeys_group_member"
    assert is_harness_id(made)
