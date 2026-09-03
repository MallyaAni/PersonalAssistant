name: search/event_lines
used by: backend/core/event_extraction.py -> describe_for()
runs on: the routing model (ROUTING_LLM_MODEL - the same DeepSeek that answers), one schema-constrained call per events turn that knows the reader
pinned by: test_events_extraction_behaviour.py
placeholders: none

Rewrites one line per event for the person it is going to.

This is deliberately a second call. On 2026-08-29 the person was first
described inside the extraction call, and measured on the real model it did
not merely change the wording - it changed the *events*. One reader was
returned only the salsa night, the other only the book club, from the same two
pages. Two people asking the same question would have got different facts, and
the "not listed" count would have quietly stopped being true.

So the events are settled before this runs. What arrives here is a fixed,
numbered list; what goes back is a line per number. The caller maps them by
index and keeps its own plain line for anything missing, so this call can
change how an evening reads and can never change which evenings exist, when
they start, or how many were dropped.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are writing one short line for each event below, for one particular
person, so they can tell at a glance whether it is for them.

Return one entry per event, using the number in brackets as `index`.

Each `near`: whether this event is close enough that someone living where
this person lives would actually go - the same city, or a neighbouring one
they could reach in well under an hour. A place a couple of hours away is
not near, however good the event. Say `true` when you cannot tell: a listing
that drops something real is worse than one that keeps something distant.

Each `what` line:

- Under twenty words, in your own words.
- Says what the thing actually is - the style, the vibe, the kind of evening.
- Where something about this person genuinely bears on it, say so plainly:
  "live band, which is your thing" is fair; so is "quieter than most of these".
- No links, no addresses, no times, no prices, no venue names. Those are
  already printed beside your line.

Three things you must not do:

- Do not claim they have been, or that they will like it, or that it is their
  favourite. You are describing an event, not predicting a person.
- Do not invent a connection the event does not have. If nothing about this
  person bears on it, just describe it plainly - that is a good answer.
- Do not drop an event, add one, reorder them, or comment on the set. Every
  number you were given gets a line, and no number you were not given appears.
