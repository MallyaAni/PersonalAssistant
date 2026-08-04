"""Tell a happening apart from a page that lists happenings.

Search returns both, and an embedding cannot separate them: "Events in Arlington,
Virginia | Meetup" is an excellent semantic match for someone interested in local
events, and it is not something you can go to. Neither is "Best Hiking Trails
Near Arlington". A digest full of directory pages is a digest nobody reads.

The distinction is structural rather than semantic, so it is decided here by
signals rather than by a model:

- **the URL usually says.** A specific happening lives at `/event/<slug>` or
  `/events/<id>`; a directory lives at `/find/`, `/near/`, `/browse/`, or a
  faceted search path. This is the strongest signal and the hardest to fake;
- **the title usually says too.** "Best…", "Top 10…", "Things to do in…", and
  "…near me" are how a page about a category names itself. A real happening has
  a name.

A positive URL signal wins, because a page at `/events/307791319` is a specific
event however generically it is titled. Everything else is judged on the title.
"""

import re

# A specific happening. Checked first: a page at one of these paths is an event
# even when its title reads like a category.
_SPECIFIC_EVENT_PATH = re.compile(
    r"(/event/[^/]+|/events/\d+|/e/[^/]+|/tickets/[^/]+)",
    re.IGNORECASE,
)

# Faceted search, category browsing, and location landing pages.
_DIRECTORY_PATH = re.compile(
    r"(/find/|/near/|/browse/|/search|/category/|/categories/|/things-to-do"
    r"|/directory|/listings?/|/events/p/|/b/[a-z]{2}--)",
    re.IGNORECASE,
)

# How a page about a category titles itself. The guide patterns were added after
# "The Complete Guide To Hiking In Northern Virginia" reached a live digest: a
# guide to a category is a directory under another name.
_DIRECTORY_TITLE = re.compile(
    r"(^\s*(the\s+)?(\d+\s+)?best\b|^\s*top\s+\d+|\bthings\s+to\s+do\b"
    r"|\bnear\s+me\b|\bevent\s+calendar\b|\ball\s+events\b"
    r"|\bevents?\s+(and|&|\+)\s+tickets\b|\bwhat'?s\s+on\b"
    # "Arlington, VA Events, Calendar & Tickets" — the ticketing sites separate
    # the words, so requiring "events & tickets" adjacent missed them.
    r"|\bcalendar\s*(and|&|\+)\s*tickets\b"
    r"|\b(complete\s+)?guide\s+to\b|\bultimate\s+guide\b)",
    re.IGNORECASE,
)

# "Events in Arlington, Virginia" — a place-scoped plural with no specific name.
#
# The second branch is the same page without the preposition, which is how a
# query that names no interest returns them: "Events Arlington, Virginia".
# Plural, and only at the start: "Event Horizon Film Festival" is a happening,
# and a rule keyed on the singular would throw it away.
_PLACE_SCOPED_PLURAL = re.compile(
    r"^\s*[\w\s&'-]*\bevents?\b\s+(in|near|around)\s+|^\s*events\b",
    re.IGNORECASE,
)


# Whether this result is a page listing happenings rather than one happening.
def looks_like_a_directory(title: str, url: str | None) -> bool:
    if url and _SPECIFIC_EVENT_PATH.search(url):
        return False
    if url and _DIRECTORY_PATH.search(url):
        return True
    cleaned = " ".join(title.split())
    if _DIRECTORY_TITLE.search(cleaned):
        return True
    return bool(_PLACE_SCOPED_PLURAL.search(cleaned))
