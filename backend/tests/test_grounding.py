"""Whether the evidence actually said it - the check two modules now share.

The link fence asks this about addresses; the event extractor asks it about
times, prices and venue names. One pair of rules, so a map link and the line
it sits under can never disagree about whether a page named the place.
"""

import pytest

from backend.core.grounding import bare_words, mentions, states


def test_punctuation_and_case_never_decide_it():
    # A page writes "Old Man's"; a search box spells it "Old Mans". A check
    # that called those different would strip the true claims with the false.
    assert bare_words("  The  LAWN, Canggu! ") == "the lawn canggu"
    assert bare_words("Old Man's Beach-Bar") == "old mans beach bar"
    assert mentions("Old Man's Beach Bar", "old mans beach bar in canggu")
    assert states("Old Man's", "at Old Mans Beach Bar")
    assert states("beach bar", "the beach-bar is open")


def test_states_wants_the_words_in_order_and_mentions_does_not():
    source = "Sunday Sessions at The Lawn, Batu Bolong, every Sunday from 4pm."
    assert states("every Sunday from 4pm", source)
    assert not states("Sunday from 6pm", source)
    # The venue as a listing names it, against the page's own phrasing.
    assert mentions("The Lawn Batu Bolong", source)
    assert not mentions("Sky Garden Seminyak", source)


def test_a_phrase_must_be_whole_not_merely_overlapping():
    # The failure this exists for: "Sundays, 4 PM" lifted out of opening
    # hours. It passes - it IS in the page - which is why the extractor also
    # asks the model what kind of phrase it is. What must not pass is a time
    # the page never wrote at all.
    hours = "Open Sundays 4 pm to 10 pm"
    assert states("Sundays 4 pm", hours)
    assert not states("Sundays 9 pm", hours)


@pytest.mark.parametrize("empty", ["", "   ", None, "!!!"])
def test_nothing_is_never_grounded(empty):
    assert not states(empty, "anything at all")
    assert not mentions(empty, "anything at all")


def test_every_word_of_three_letters_or_more_must_be_present():
    # Pinned rather than assumed, because it is the strict direction and it
    # decides real cases: "The Lawn at Canggu" does NOT ground against a page
    # that only says "lawn canggu", since "the" is three letters and is
    # required like any other word. Loosening this would loosen the link
    # fence, which shares the rule - so it stays strict until something
    # measured says otherwise.
    assert mentions("The Lawn at Canggu", "the lawn in canggu tonight")
    assert not mentions("The Lawn at Canggu", "lawn canggu sessions")
    assert not mentions("Sky Garden Seminyak", "the lawn at canggu")
    # Words under three letters are ignored on the subject side, so "at" and
    # "of" never decide it either way.
    assert mentions("Lawn at Canggu", "lawn canggu sessions")
    # An apostrophe joins; a hyphen separates. Both must survive the trip.
    assert mentions("Old Man's Beach-Bar", "old mans beach bar in canggu")


def test_an_empty_source_grounds_nothing():
    assert not states("anything", "")
    assert not mentions("anything", "")
