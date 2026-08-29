"""Whether a fragment of a reply was actually stated by what this turn saw.

The link fence answers this question for addresses (`backend/core/links.py`).
It turns out to be the same question for every other fact a listing carries -
a start time, a price, a venue name - and on 2026-08-29 the times were wrong
for exactly the reason the links were: nothing compared them to the evidence.
A venue's opening hours ("Sundays, 4 PM - 10 PM") reached a phone as an
event's start time, and the model had no way to know the difference because
it was never asked to point at where it read it.

So the rule these helpers exist for: a claim survives only if the words that
make it appear in the source it names. Not "is plausible", not "was in the
context somewhere" - present, in that result, in those words. Punctuation and
case are normalised away, because a source writes "Old Man's" and a search
box spells it "Old Mans", and a check that called those different would strip
the true claims along with the invented ones.

What this deliberately cannot do: judge meaning. "4 PM" quoted out of an
opening-hours sentence still passes here. That is a schema problem, solved by
asking the model to quote the whole phrase it read the time from and letting
a person see it - not by a cleverer matcher.
"""

from __future__ import annotations

import re

# Words only: case folded, punctuation dropped, whitespace collapsed. Both
# sides of every comparison go through this, so the two can never disagree
# about what counts as a word.
#
# An apostrophe is deleted and every other mark becomes a space, and the
# difference matters in both directions. An apostrophe joins a word - a search
# box spells "Old Man's" as "Old Mans", and replacing it with a space would
# give "old man s", which matches nothing. A hyphen or a slash separates two -
# "beach-bar" is the same as "beach bar", and deleting the hyphen would give
# "beachbar", which also matches nothing.
_APOSTROPHE = re.compile(r"['’ʼ`]")
_NOT_WORD = re.compile(r"[^\w\s]+")


def bare_words(text: str) -> str:
    lowered = _APOSTROPHE.sub("", (text or "").casefold())
    return " ".join(_NOT_WORD.sub(" ", lowered).split())


# Whether `fragment` appears in `source` as a phrase - the words in order,
# with punctuation and case ignored. Used for a quotation: the model is asked
# for the exact phrase it read a time or a price from, and this is what checks
# that the phrase is really there.
def states(fragment: str, source: str) -> bool:
    needle = bare_words(fragment)
    if not needle:
        return False
    return f" {needle} " in f" {bare_words(source)} "


# Whether every substantial word of `fragment` appears somewhere in `source`,
# in any order. Looser than `states` on purpose: a venue name reaches us as
# "The Lawn Canggu" when the page says "The Lawn, Batu Bolong, Canggu", and
# requiring the phrase would reject a name the source plainly carries. Short
# words are ignored so "of"/"at"/"the" never decide it.
def mentions(fragment: str, source: str, min_word: int = 3) -> bool:
    haystack = bare_words(source)
    words = [word for word in bare_words(fragment).split() if len(word) >= min_word]
    if not words:
        return False
    return all(word in haystack for word in words)
