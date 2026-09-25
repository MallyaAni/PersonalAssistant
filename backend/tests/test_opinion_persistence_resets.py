"""Explicit input-validity resets discard held stances without changing defaults."""

import numpy as np
import pytest

from backend.agents.trading.desk.opinions import (
    Opinion,
    persist,
    stances_from_ranks,
)


# Pin the predecessor's calculation independently for default-output comparisons.
def _legacy_persist(raw, sessions):
    if sessions <= 1 or raw.shape[0] == 0:
        return raw
    held = raw.copy()
    run = np.ones(raw.shape[1], dtype=int)
    for t in range(1, raw.shape[0]):
        run = np.where(raw[t] == raw[t - 1], run + 1, 1)
        held[t] = np.where(run >= sessions, raw[t], held[t - 1])
    return held


# A missing-input reset must erase the old vote throughout fresh confirmation.
def test_missing_input_reset_clears_held_vote_and_recovery():
    raw = np.array([[1], [1], [0], [1], [1], [1]])
    resets = np.array([[False], [False], [True], [False], [False], [False]])
    assert persist(raw, 3)[:, 0].tolist() == [1, 1, 1, 1, 1, 1]
    assert persist(raw, 3, resets=resets)[:, 0].tolist() == [1, 1, 0, 0, 0, 1]


# Every missing row starts over, so a gap cannot preserve or rebuild a held vote.
def test_repeated_missing_resets_need_three_fresh_scored_rows():
    raw = np.array([[-1], [-1], [0], [0], [-1], [-1], [-1]])
    resets = np.array([[False], [False], [True], [True], [False], [False], [False]])
    assert persist(raw, 3, resets=resets)[:, 0].tolist() == [
        -1,
        -1,
        0,
        0,
        0,
        0,
        -1,
    ]


# A still-scored reset counts that day's raw stance as confirmation number one.
@pytest.mark.parametrize("sessions", [2, 3, 4])
def test_scored_reset_counts_current_session_as_first_confirmation(sessions):
    raw = np.ones((sessions + 3, 1), dtype=int)
    resets = np.zeros_like(raw, dtype=bool)
    resets[2] = True
    expected = [1, 1] + [0] * (sessions - 1) + [1, 1]
    assert persist(raw, sessions, resets=resets)[:, 0].tolist() == expected


# Resetting partway through a pending change discards its earlier confirmations.
def test_reset_clears_an_in_progress_confirmation_run():
    raw = np.array([[1], [-1], [-1], [-1], [-1], [-1]])
    resets = np.zeros_like(raw, dtype=bool)
    resets[2] = True
    assert persist(raw, 3, resets=resets)[:, 0].tolist() == [1, 1, 0, 0, -1, -1]


# Resetting one ticker leaves all other tickers' persistence byte-identical.
def test_reset_is_isolated_per_ticker():
    raw = np.array([[1, -1, 1], [1, 0, -1], [1, 0, -1], [1, 0, -1], [1, 1, 0]])
    resets = np.zeros_like(raw, dtype=bool)
    resets[2, 0] = True
    held = persist(raw, 3, resets=resets)
    assert held[:, 0].tolist() == [1, 1, 0, 0, 1]
    assert held[:, 1:].tobytes() == _legacy_persist(raw, 3)[:, 1:].tobytes()


# Only an explicit initial reset removes the predecessor's immediate first vote.
def test_first_row_reset_requires_confirmation_only_for_reset_tickers():
    raw = np.array([[1, -1]] * 4)
    resets = np.zeros_like(raw, dtype=bool)
    resets[0, 0] = True
    held = persist(raw, 3, resets=resets)
    assert held[:, 0].tolist() == [0, 0, 1, 1]
    assert held[:, 1].tolist() == [-1, -1, -1, -1]


# Ordinary rank changes still hold the last confirmed stance after recovery.
def test_ordinary_rank_changes_keep_persistence_after_reset():
    raw = np.array([[1], [1], [1], [-1], [1], [0], [0], [0]])
    resets = np.zeros_like(raw, dtype=bool)
    resets[0] = True
    assert persist(raw, 3, resets=resets)[:, 0].tolist() == [0, 0, 1, 1, 1, 1, 1, 0]


# Repeated resets never accumulate confirmations even if every raw vote agrees.
def test_repeated_nonzero_resets_remain_neutral():
    raw = np.ones((7, 2), dtype=int)
    raw[:, 1] = -1
    np.testing.assert_array_equal(
        persist(raw, 3, resets=np.ones_like(raw, dtype=bool)),
        np.zeros_like(raw),
    )


# With at most one required confirmation, a valid reset preserves immediate raw output.
@pytest.mark.parametrize("sessions", [-3, 0, 1])
def test_immediate_confirmation_returns_raw_even_on_reset(sessions):
    raw = np.array([[1, -1], [0, 1]])
    assert persist(raw, sessions, resets=np.ones_like(raw, dtype=bool)) is raw


# Explicitly shaped empty panels remain supported without creating votes.
@pytest.mark.parametrize("shape", [(0, 0), (0, 3), (4, 0)])
def test_valid_empty_panels(shape):
    raw = np.zeros(shape, dtype=np.int8)
    actual = persist(raw, 3, resets=np.zeros(shape, dtype=bool))
    assert actual.shape == shape
    assert actual.dtype == raw.dtype
    assert actual.size == 0


# Reject masks whose types, dimensions or values require coercion before any fast path.
@pytest.mark.parametrize("sessions", [0, 1, 3])
@pytest.mark.parametrize(
    "resets",
    [
        True,
        [[False, False], [False, False]],
        np.array(True),
        np.zeros((2, 2), dtype=int),
        np.zeros((2, 2), dtype=float),
        np.full((2, 2), False, dtype=object),
        np.zeros((4,), dtype=bool),
        np.zeros((2, 1), dtype=bool),
        np.zeros((1, 2, 2), dtype=bool),
        np.zeros((0, 2), dtype=bool),
        np.ma.array(np.zeros((2, 2), dtype=bool), mask=True),
    ],
)
def test_malformed_reset_masks_are_rejected(sessions, resets):
    with pytest.raises(ValueError, match="resets"):
        persist(np.ones((2, 2), dtype=int), sessions, resets=resets)


# Empty input cannot hide a malformed mask merely because the loop has no rows.
def test_empty_panel_still_validates_reset_mask():
    with pytest.raises(ValueError, match="resets"):
        persist(np.empty((0, 2), dtype=int), 3, resets=np.zeros((0, 2), dtype=int))


# Default and all-false masks preserve exact predecessor values and dtypes.
@pytest.mark.parametrize("sessions", [-1, 0, 1, 2, 3, 5])
@pytest.mark.parametrize("shape", [(0, 0), (0, 4), (1, 4), (20, 0), (32, 7)])
@pytest.mark.parametrize("dtype", [np.int8, np.int64])
def test_default_persistence_is_byte_identical_to_predecessor(sessions, shape, dtype):
    raw = np.random.default_rng(184).integers(-1, 2, size=shape, dtype=dtype)
    expected = _legacy_persist(raw, sessions)
    for actual in (
        persist(raw, sessions),
        persist(raw, sessions, resets=None),
        persist(raw, sessions, resets=np.zeros(shape, dtype=bool)),
    ):
        assert actual.shape == expected.shape
        assert actual.dtype == expected.dtype
        assert actual.tobytes() == expected.tobytes()
        if sessions <= 1 or shape[0] == 0:
            assert actual is raw


# Opinion forwards missing-score resets into the state machine, not an output-only mask.
def test_opinion_resets_propagate_through_ranking_and_recovery():
    scores = np.array([[3.0, 2.0, 1.0]] * 6)
    scores[2, 0] = np.nan
    resets = ~np.isfinite(scores)
    opinion = Opinion("test", scores, stance_resets=resets)
    assert opinion.stances()[:, 0].tolist() == [1, 1, 0, 0, 0, 1]
    assert Opinion("legacy", scores).stances()[:, 0].tolist() == [1] * 6


# Appending the optional field preserves existing positional evidence and metadata.
def test_opinion_default_preserves_legacy_positional_arguments():
    scores = np.array([[3.0, 2.0, 1.0], [1.0, 2.0, 3.0]])
    evidence = {"feature": scores.copy()}
    meta = {"source": "legacy"}
    opinion = Opinion("legacy", scores, evidence, meta)
    assert opinion.evidence is evidence
    assert opinion.meta is meta
    assert opinion.stance_resets is None
    expected = _legacy_persist(stances_from_ranks(opinion.ranks(), 0.3), 3)
    assert opinion.stances().tobytes() == expected.tobytes()


# Opinion cannot bypass reset validation by selecting immediate confirmation.
def test_opinion_rejects_malformed_reset_mask():
    opinion = Opinion("test", np.ones((3, 2)), stance_resets=np.ones((3, 2)))
    with pytest.raises(ValueError, match="resets"):
        opinion.stances(persistence=1)


# Read-only raw votes and reset masks remain untouched throughout the calculation.
def test_persistence_does_not_mutate_either_input():
    raw = np.array([[1], [-1], [-1], [-1]])
    resets = np.array([[False], [True], [False], [False]])
    raw_before, reset_before = raw.tobytes(), resets.tobytes()
    raw.flags.writeable = False
    resets.flags.writeable = False
    assert persist(raw, 3, resets=resets)[:, 0].tolist() == [1, 0, 0, -1]
    assert raw.tobytes() == raw_before
    assert resets.tobytes() == reset_before


# A future reset cannot alter any already-calculated stance in the prefix.
def test_future_reset_does_not_change_prior_stances():
    raw = np.array([[1], [0], [0], [0], [1], [1], [1]])
    resets = np.zeros_like(raw, dtype=bool)
    resets[5] = True
    full = persist(raw, 3, resets=resets)
    for stop in range(1, len(raw) + 1):
        np.testing.assert_array_equal(
            full[:stop], persist(raw[:stop], 3, resets=resets[:stop])
        )
