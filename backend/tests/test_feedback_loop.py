"""The thumbs finally steer something.

Reactions were collected and recorded for weeks while every sweep ranked as
though nobody had said anything. These pin the read side's arithmetic and
its restraint: net thumbs shade a stored strength inside the 1-3 band the
ranker was built around, stored values are never the input of their own
output, an interest nobody reacted about is untouched, and a reaction that
cannot be joined to an interest shades nothing rather than something.
"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.feedback_loop import (
    ReactedFind,
    adjusted_strengths,
    reaction_statements,
)


def _liked(title: str, interest: str | None) -> ReactedFind:
    return ReactedFind(title=title, reaction="liked", interest=interest)


def _disliked(title: str, interest: str | None) -> ReactedFind:
    return ReactedFind(title=title, reaction="disliked", interest=interest)


def test_a_thumbs_up_raises_and_a_thumbs_down_lowers():
    base = {"live music": 2, "hiking": 2}

    shaded = adjusted_strengths(
        base, (_liked("a concert", "live music"), _disliked("a hike", "hiking"))
    )

    assert shaded == {"live music": 3, "hiking": 1}
    assert base == {"live music": 2, "hiking": 2}, "the input must not be written"


def test_shading_is_clamped_to_the_band_the_ranker_understands():
    base = {"dogs": 3, "opera": 1}

    shaded = adjusted_strengths(
        base,
        (
            _liked("a", "dogs"),
            _liked("b", "dogs"),
            _disliked("c", "opera"),
            _disliked("d", "opera"),
        ),
    )

    assert shaded == {"dogs": 3, "opera": 1}


def test_opposing_thumbs_cancel_rather_than_ratchet():
    shaded = adjusted_strengths(
        {"theater": 2}, (_liked("a", "theater"), _disliked("b", "theater"))
    )

    assert shaded == {"theater": 2}


def test_an_unjoinable_reaction_shades_nothing():
    base = {"hiking": 2}

    shaded = adjusted_strengths(
        base, (_liked("a notable find", None), _disliked("gone interest", "sailing"))
    )

    assert shaded == {"hiking": 2}


def test_no_reactions_change_nothing_at_all():
    assert adjusted_strengths({"hiking": 2}, ()) == {"hiking": 2}


def test_statements_carry_the_thumb_and_the_title():
    statements = reaction_statements(
        (_disliked("Seven Wonders at Tarara Winery", "live music"),)
    )

    assert statements == (
        'They gave a thumbs-down to "Seven Wonders at Tarara Winery" '
        "from an earlier digest.",
    )


def test_statements_are_bounded_to_the_newest():
    reacted = tuple(_liked(f"find {i}", "hiking") for i in range(20))

    assert len(reaction_statements(reacted, limit=6)) == 6
