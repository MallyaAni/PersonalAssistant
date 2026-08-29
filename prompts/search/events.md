name: search/events
used by: backend/core/event_extraction.py -> extract_events()
runs on: the routing model (ROUTING_LLM_MODEL - the same DeepSeek that answers), one schema-constrained call per events turn
pinned by: test_events_extraction_behaviour.py
placeholders: none

Turns search results into typed event records, so that code - not a model -
writes the listing. The rules applied to what comes back - every quotation
checked against the result it names - are unit-tested beside the extractor.

The failure this exists for reached a real phone on 2026-08-29: a listing
where "Time: Sundays, 4 PM - 10 PM" was a venue's opening hours presented as
an event's start, and every map and video link was invented. The links are
now fenced (backend/core/links.py). The times needed the same treatment, and
the only way to check a time is to know where it was read.

So this call asks for quotations, not conclusions. Every factual field must
be a phrase copied out of the result it is attributed to; the caller checks
that the phrase is really there and discards the record if it is not. The
model contributes exactly one thing in its own words - the line saying what
the event is - and that line is not allowed to contain an address.

Dates and clock times are parsed from the quoted phrase by code afterwards.
Asking a model to write "2026-08-31T16:00" is asking it to invent precision;
asking it to copy "every Sunday from 4pm" is asking it to read.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are reading web search results and pulling out the events in them.

Return one record per event. An event is a specific happening at a place -
a night, a session, a market, a gig, a class. A venue that merely exists is
not an event. A directory page listing many venues is not an event.

For each record:

- source: the number in brackets of the result you read it from. Every other
  field in the record must come from that result and no other.
- name: what the thing is called, copied from the result. Not invented.
- venue: the place it happens at, as the result names it.
- area: the neighbourhood, suburb or district, as the result names it. Empty
  if the result does not say.
- artist: the named act or DJ, as the result names it. Empty if none is named.
- when_text: the exact phrase from the result that says when it happens.
  Copy it word for word - "every Sunday from 4pm", "Saturday 6 September,
  doors 8pm". Do not tidy it, do not convert it, do not combine two phrases.
  If the result never says when, leave it empty.
- when_kind: what that phrase actually is.
    one_off_date - a specific date this year or next.
    recurring_weekday - it happens on a named weekday, weekly or regularly.
    opening_hours - the phrase is the venue's opening or serving hours, not
      an event's start. "Open daily 11am-late", "kitchen until 10pm",
      "Sundays 4 PM - 10 PM" under a venue's name are all this.
    not_stated - the result does not say when.
- price_text: the exact phrase stating price or entry, copied word for word -
  "IDR 250k entry", "free before 6pm". Empty if the result does not say.
- what: one short line, in your own words, saying what it is - the style, the
  vibe, who it is for. No links, no addresses, no times, no prices. Under
  twenty words.

Rules that are not negotiable:

- Never write a URL, a handle, or a domain name in any field.
- Never write a date or a clock time of your own. Only copy when_text.
- If you cannot find the phrase in the result, leave the field empty. An
  empty field is correct; a plausible one is a lie the reader cannot see.
- Prefer fewer, well-sourced records over covering every result.
