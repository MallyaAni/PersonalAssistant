# ADR 0017: A reply may only say what something else stated

- Status: Accepted; the link fence implemented and deployed 2026-08-29 (68ddd8e - unit 2093, all nine group journeys, the search harness green). The typed-event path and the code-rendered listing in 9db5e747 (unit 2161, ten real-model tests). Step 4 (calendar offer) and the browser tool are not built; see the status table in [EVENTS_ARCHITECTURE.md](../EVENTS_ARCHITECTURE.md).
- Date: 2026-08-29

## Context

On 2026-08-29 a recommendation went to a real phone carrying
`https://maps.app.goo.gl/xyz`, `/abc`, `/def`, `/ghi`, `/jkl` and
`https://youtu.be/xyz` - shortened links with placeholder ids, invented whole -
and "Time: Sundays, 4 PM - 10 PM", which was The Lawn's opening hours printed
where an event's start time goes.

Neither was a lapse in the prompt's wording. On the chat path the reply model
is handed four raw fields per search result (title, url, content, provider) and
asked, in prose, to *construct* a Google Maps link for a venue it also inferred,
and to state a time. Nothing in code compared any of it to the pages the fields
came from. The events format was not even applied to that turn: it is rendered
only when a ranker model flags the results as events, and it did not.

Scout's own digest path has never had this failure, and the reason is
structural rather than instructional: its model is given no URL field, its
output is stripped of URL-shaped text, and links are attached afterwards from
typed records. The chat path never got that discipline.

Two more instructions were considered and rejected. "Never invent a link" was
already effectively present and did not hold. "Only use links from the results"
cannot be checked by the thing being asked to follow it - a model has no way to
know whether a link it wrote came from a result or from its own weights.

## Decision

**Nothing leaves a reply that the application cannot vouch for, and the check is
code.**

Three rules, applied in order of how much they cost:

1. **A URL survives only if the turn's evidence carried it, or code built it.**
   `backend/core/links.py` fences the reply as it streams: an address is kept if
   it appeared in this turn's sources, or if it is one of four search-box
   templates (maps, maps in Google's path form, a YouTube search, a Google
   Calendar prefill) whose subject is made of words the evidence contains.
   Everything else is removed and the words around it kept. A search box cannot
   send anyone to an invented destination; a shortened link is a claim about a
   destination, and a model cannot know one. The fence runs where the streamed
   bytes and the stored bytes are the same bytes, so what is shown, saved and
   texted agree, and the iMessage worker applies it a second time at the send
   boundary because that is the last place before a real phone.

2. **An event is a record, not a sentence.** `backend/core/event_extraction.py`
   asks the routing model to *quote*: which result each event came from, the
   exact phrase in it that states the day, the exact phrase that states the
   price. Code checks each quotation against the result it names
   (`backend/core/grounding.py`) and discards what is not there. The model also
   classifies what kind of phrase it copied, and `opening_hours` is one of the
   kinds - so the 29 August failure is named and refused rather than
   discouraged.

3. **Code writes the listing.** `backend/core/events_listing.py` renders the
   lines and builds every link from the venue and the act. On a turn the ranker
   judges to be events, that listing *is* the reply: the model is not asked for
   it and cannot alter it. Dates come from the repository's one date parser
   (`backend/core/dates.py`); a weekday resolves to its next occurrence, which
   is a fact about the calendar; a clock time is read only from a start word
   ("doors 6pm") within a short window of the quoted date, so "open until 11pm"
   is never borrowed.

What was dropped is part of the listing. "Nothing is on this week" and "four
things turned up and none of them said when" are different answers, and a
reader who cannot tell them apart is misled by omission.

## Consequences

- A model that would have invented a link now produces a reply with the words
  and no link. That is the intended trade: a missing link costs a search; a
  wrong one costs a drive.
- The fence can be wrong in the other direction - stripping a real address the
  evidence did not happen to carry. It is pinned against that
  (`backend/tests/test_reply_link_fence.py`), and the failure is visible in the
  log by host, never by URL, because a dropped address is untrusted text.
- The reply streams by line rather than by token on turns that carry an
  address, because whether a line survives cannot be decided until the address
  on it has finished arriving. Risk-free prose is still released mid-line, so
  ordinary answers read as they always did.
- An events turn whose extraction finds nothing falls back to the model writing
  the listing, behind the fence, exactly as before. The new path is an
  improvement on a flagged turn, never a cliff.
- Bare handles ("@oldmansbali") are deliberately out of scope. A handle is not
  a URL and no pattern distinguishes an invented one; the fix is to stop asking
  a model for handles, which the typed extraction does.

## Alternatives considered

- **A stricter prompt.** Rejected: the failing turn had no events prompt applied
  at all, and the rule cannot be checked by its follower.
- **Allowing any URL whose host appears in the evidence.** Rejected: the
  invented links were on `maps.app.goo.gl` and `youtu.be`, hosts a listing
  legitimately mentions, and a host is not a destination.
- **Dropping the whole reply when a link is invented.** Rejected: the words are
  usually right, and a blank answer teaches the reader nothing.
