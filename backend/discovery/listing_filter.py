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

# A tracking redirect. An affiliate link is an advertisement whatever it is
# titled — "Join now and get 50% off a Club membership" reached a delivered
# digest as though it were a happening. The destination is the only reliable
# tell, because the title is written to sound like an offer worth taking.
_AFFILIATE_HOST = re.compile(
    r"^https?://([^/]*\.)?("
    r"click\.linksynergy\.com|linksynergy\.com|anrdoezrs\.net|dpbolvw\.net"
    r"|jdoqocy\.com|kqzyfj\.com|tkqlhce\.com|shareasale\.com|awin1\.com"
    r"|prf\.hn|go\.skimresources\.com|rstyle\.me|avantlink\.com"
    r"|partnerize\.com|impact\.com|sjv\.io|pxf\.io"
    r")/",
    re.IGNORECASE,
)

# A person's or venue's profile page. It may announce happenings, but it is not
# one, and its title is whatever the account is called plus a date — which is
# exactly the shape a real listing has, so the URL is the only reliable tell.
# An Instagram profile reached a live digest as though it were a concert.
_SOCIAL_PROFILE = re.compile(
    r"^https?://(www\.)?(instagram\.com|facebook\.com|x\.com|twitter\.com"
    r"|tiktok\.com|threads\.net|linkedin\.com)/",
    re.IGNORECASE,
)

# Faceted search, category browsing, and location landing pages.
_DIRECTORY_PATH = re.compile(
    r"(/find/|/near/|/browse/|/search|/category/|/categories/|/things-to-do"
    r"|/directory|/listings?/|/events/p/|/b/[a-z]{2}--"
    # A standing programme rather than a date. Arlington County's own site put
    # a concert series at /Government/Programs/Arts/Programs/Lubber-Run, which
    # is a description of a thing the county runs every summer.
    r"|/government/|/programs?/|/department|/venues?/|/venue-info"
    # A roster page, which is the same object as a calendar.
    r"|/lineup|/line-up|/schedule/?$|/calendar/?$)",
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
    r"|\b(complete\s+)?guide\s+to\b|\bultimate\s+guide\b"
    # All three of these reached a delivered digest, so they are shapes taken
    # from real output rather than guessed at.
    #
    # "Arlington, Virginia Concert Tickets 2026 - 2027 | JamBase": an
    # aggregator selling entry to whatever is on.
    r"|\b(concert|event|show|game)\s+tickets\b"
    # "Arlington Concerts in August 2026 - American Arenas": a month-scoped
    # plural is a listing for that month, however specific the month sounds.
    r"|\b(concerts?|events?|shows?|gigs?)\s+in\s+(january|february|march|april"
    r"|may|june|july|august|september|october|november|december)\b"
    # "... 2026 - 2027 | Find A Race": one happening does not span two years.
    r"|\b20\d{2}\s*[-–]\s*20\d{2}\b"
    # "The Renegade VA - Lineup" led a delivered digest. A lineup is the roster
    # of who is playing across many nights — the venue's calendar under another
    # name — and its summary said so: "events ... from Tuesday through Saturday".
    r"|\blineup\b|\bline-?up\b"
    # "Upcoming Events", "This Week in ...": a heading, not a happening.
    r"|^\s*upcoming\b|^\s*this\s+(week|weekend|month)\b)",
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
    # Checked before the specific-event path, because a social URL can contain
    # anything and its titles look exactly like real listings.
    if url and _SOCIAL_PROFILE.search(url):
        return True
    if url and _AFFILIATE_HOST.search(url):
        return True
    if url and _SPECIFIC_EVENT_PATH.search(url):
        return False
    if url and _DIRECTORY_PATH.search(url):
        return True
    cleaned = " ".join(title.split())
    if _DIRECTORY_TITLE.search(cleaned):
        return True
    # A title is often several segments — "Free Concerts | Upcoming Events near
    # Arlington, VA | Live Music Project" — and the giveaway sits in the middle
    # one. Anchoring the place-scoped rule at the start of the whole string
    # missed exactly that, so each segment is judged on its own.
    return any(
        _PLACE_SCOPED_PLURAL.search(segment.strip())
        for segment in re.split(r"[|–—]|\s-\s", cleaned)
        if segment.strip()
    )
