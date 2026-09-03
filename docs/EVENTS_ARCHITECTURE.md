# Events: from a search result to something you can act on

How "what's on this weekend" is answered, why every part of the answer is
traceable to a page, and what is built versus what is not.

The short version: the reply model no longer writes an events listing. It is
asked to quote; code checks the quotations, decides every date and time, builds
every link, and renders the lines. The decision and its reasoning are
[ADR 0017](adr/0017-a-reply-may-only-say-what-something-else-stated.md).

## Why it works this way

On 2026-08-29 a recommendation reached a real phone with five invented map
links, an invented video link, and a venue's opening hours - "Sundays, 4 PM -
10 PM" - printed where an event's start time goes. Nothing had gone wrong in
the wording. The chat path handed the model raw result fields and asked it, in
prose, to construct links and state times, and no code compared any of it back
to the pages. Scout's digest path had never produced that failure because it is
built the other way round: no URL field reaches its model, its output is
stripped of URL-shaped text, and links are attached afterwards from records.

## The path, step by step

1. **The search runs** and returns results (`backend/services/conversation_service.py`,
   `_load_search_context`). Untrusted third-party text, bounded at the boundary.
2. **The ranker reads them** (`backend/core/result_ranking.py`): one constrained
   call at temperature zero that orders the results and says whether they are
   events. Its `events` flag is what selects everything below.
3. **The events are typed** (`backend/core/event_extraction.py`): one more
   constrained call, which returns records rather than prose. Each record names
   the result it came from and quotes the phrase stating the day and the phrase
   stating the price, word for word.
4. **Code checks every quotation** against the result the record names
   (`backend/core/grounding.py`). A phrase that is not on that page is dropped -
   the record with it, if the phrase was the date. The model also says what kind
   of phrase it copied; `opening_hours` is a listed kind and is discarded, which
   is the 29 August failure refused by name rather than discouraged.
5. **Code decides the calendar.** An explicit date is parsed by the repository's
   one date parser (`backend/core/dates.py`); a weekday resolves to its next
   occurrence. A clock time is taken from the quoted phrase, or from a start
   word - "doors 6pm", "from 4pm" - within a short window of it, so a closing
   time three words away is never borrowed.
6. **Code renders the listing** (`backend/core/events_listing.py`), building the
   map and video links itself from the venue and the act. On a turn the ranker
   flagged, that listing is streamed as the reply and the model is never asked
   to write one.
7. **The link fence stands in front of everything** (`backend/core/links.py`),
   on this path and every other, including the turns the ranker did not flag -
   which is the exact turn that failed. The iMessage worker applies it again at
   the send boundary.

## What the first American question showed (2026-09-03)

The path above was built on Canggu listings. The operator's first real
question from Arlington - "the most fun events happening in the area this
week?" - returned one event, in New York, a week on Sunday. The search had
returned the right pages; the losses were in this path, and each is now a
rule in code with a test:

1. **A date without a year is a date.** American calendars write "Saturday,
   September 5", "Sep 5", "9/5"; `stated_date` resolves such a date to the
   next such day given today (`backend/core/dates.py`). Before, ten of
   twelve extracted records were dropped as undated.
2. **The extractor reads the whole result** (2,500 characters, the search's
   own bound) rather than a 700-character head that held two of ARLnow's
   dozen events. Measured on the same results: 1 kept at 700, 5 at 2,500
   with the old parser (`backend/cli/measure_events_extraction.py`).
3. **The listing is held to the window the words named**
   (`backend/core/event_window.py`: today, tomorrow, this weekend, this
   week, next week, next weekend, in the person's calendar). Events on
   other days are counted, not listed; with nothing inside, the nearest
   few after it are shown under a line that says so.
4. **An event too far away is not a listing.** The model that writes each
   event's line is told where the person is and marks `near`; the listing
   drops the rest and says how many ("3 too far from you to be worth the
   trip"). A listing led with a paddle in Colonial Heights, two hours from
   Arlington, because nothing in this path knew what "near" meant.
5. **The query asks for what they like.** `compose` is handed the person's
   interests and the prompt spends them on a request about things to do and
   on nothing else.
6. **A later search round keeps the place** the first query carried
   (`conversation_service._keep_the_place`), so "another angle" cannot
   find what is on anywhere.

## What the reader is told about what is missing

The count of dropped events is part of the listing, not a footnote: "Not
listed: 3 more that never said when; 1 where the only time given was the
venue's opening hours." An answer that quietly shows two of six reads as "that
is everything there is", which is the same lie by omission that the invented
links were by commission.

## Status

| Piece | State | Where |
| --- | --- | --- |
| Link fence in the reply stream | Deployed 2026-08-29 (68ddd8e) | `backend/core/links.py` |
| Second fence at the iMessage send boundary | Deployed 2026-08-29 (68ddd8e) | `backend/workers/imessage_chat.py` |
| Shared "did the evidence say this" rule | Deployed 2026-08-29 (9db5e747) | `backend/core/grounding.py` |
| One date parser, in core | Deployed 2026-08-29 (9db5e747) | `backend/core/dates.py` |
| Typed event extraction | Deployed 2026-08-29 (cabfdecd) | `backend/core/event_extraction.py` |
| Code-rendered listing | Deployed 2026-08-29 (cabfdecd) | `backend/core/events_listing.py` |
| The listing is the reply on a flagged events turn | Deployed 2026-08-29 (cabfdecd) | `backend/services/conversation_service.py` |
| One-tap Google Calendar link per event | Deployed 2026-08-29 | `backend/core/events_listing.py` |
| Year-less dates resolve to the next such day | Deployed 2026-09-03 (eb1f83fa) | `backend/core/dates.py`, `test_dates.py` |
| Extractor reads the whole result (2,500 chars) | Deployed 2026-09-03 (eb1f83fa); with the parser fix, 9 events kept from the same results (1 before), 2/2 runs | `backend/core/event_extraction.py`, `backend/cli/measure_events_extraction.py` |
| Listing held to the asked calendar window | Deployed 2026-09-03 (eb1f83fa) | `backend/core/event_window.py`, `backend/core/events_listing.py` |
| A later search round keeps the place | Deployed 2026-09-03 (eb1f83fa) | `backend/services/conversation_service.py`, `test_search_keeps_the_place.py` |
| Off-subject results are never typed into a listing | Deployed 2026-09-03 (ca16b0ab) | `conversation_service`, `test_events_listing_wiring.py` |
| A drifted second round: the first round ranked alone and used when on subject | Deployed 2026-09-03 (ca16b0ab) | `conversation_service._research`, `test_events_listing_wiring.py` |
| A search about here is held to the saved place, every round (time words alone do not count, since the thirtieth) | Deployed 2026-09-03 (e4f68ba8, corrected 6dd2d7f5); live: a Fed question searched without a place, an events question with "Raleigh NC" | `conversation_service._hold_to_place`, `test_search_keeps_the_place.py` |
| An event too far to go to is counted, not listed | Built 2026-09-03, not deployed | `core/event_extraction.py` (`near`), `core/events_listing.py`, `prompts/search/event_lines.md` |
| The search query carries what the person likes, for a things-to-do request only | Built 2026-09-03, not deployed | `services/search_planner.py`, `prompts/search/compose.md`, `functional/test_search_compose_behaviour.py` |
| "Remind me about the second one" | Works with no new machinery — measured | `functional/test_act_on_a_listed_event_behaviour.py` |
| `.ics` attached into the iMessage thread | **Not built** | needs `TurnResult` to carry a non-image file; would reuse `backend/discovery/calendar.py` |
| Booking through a bounded browser tool | **Not built** | as an MCP server behind the existing boundary — see [ADR 0018](adr/0018-an-outside-agent-enters-as-a-tool-or-not-at-all.md) |

## What is deliberately not done

- **Bare handles.** "@oldmansbali" is not a URL and no pattern tells an invented
  handle from a real one. The fix is to stop asking a model for handles, which
  the typed extraction does; the fence does not try.
- **Judging meaning.** The grounding check asks whether the words are on the
  page, not whether they mean what the model thought. A time quoted out of an
  opening-hours sentence still passes the phrase check - which is why the model
  is separately asked to classify the phrase, and why that classification is
  acted on in code.
- **Inferring a date.** "This weekend", "next Saturday" and "summer" resolve to
  nothing, because resolving them needs a reference point the snippet does not
  carry. An event nobody dated is dropped and counted, never guessed at.

## Tests

- `backend/tests/test_reply_link_fence.py` - the fence, including the arsalon
  reply itself, chunk-boundary invariance, and the opposite failure (stripping a
  real link).
- `backend/tests/test_grounding.py` - the shared rule, apostrophes and hyphens.
- `backend/tests/test_event_extraction.py` - every check code applies to what
  the model returns, including opening hours, an unsourced record, and a door
  time beside the date versus a closing time beside the date.
- `backend/tests/test_events_listing.py` - the rendered lines, and that what was
  dropped is said out loud.
- `backend/tests/test_events_listing_wiring.py` - that the listing really is the
  reply and the model is never asked to write it.
- `backend/tests/functional/test_no_invented_links_behaviour.py` and
  `functional/test_events_extraction_behaviour.py` - the real model, on the
  Canggu results.
