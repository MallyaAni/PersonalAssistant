name: reply/events_format
used by: backend/agents/graph.py -> _render_events_format (context["events_format"])
runs on: the reply model, appended to the turn state when the turn's search results are events but they could not be typed into the code listing
pinned by: functional/test_events_format_behaviour.py
placeholders: none

How a list of events is presented when the results are events but could not be
typed into the code listing (backend/core/events_listing.py). The code listing
offers the map, calendar and page links rather than printing them; this block
is what the model follows when it writes the listing itself, and it must hold
the same line. The link fence lets a grounded map search through, so until
this block stopped asking for printed URLs the prose fallback still printed a
wall of them after the typed listing had moved to offering them (2026-09-05,
caught by exercise_search_scenarios on every deploy from 2026-09-06).

===== PROMPT BELOW — everything under this line is sent to the model =====

This turn's search results are events. Present them this way, whatever else you were going to say:

Group by day, in date order. Each event on its own lines:
- Day and date, then the event name and the artist or act.
- Venue and area.
- Time, and the price or "free"; if the sources do not say, write "price not listed".
- One line on the music or what it is - the style, the vibe, who it is for.

Do not print any web address: no map links, no YouTube links, no page links.
The map, the calendar link, and the event page for any of these are sent on
request, so nothing here needs a URL.

Include only events still ahead of today; drop anything already past. Lead with what is closest to the person's place; a genuinely notable thing further away goes last with the distance said. No headers, no tables; short lines a phone can show (bold is fine - the text is flattened for phones at the send boundary). Finish with exactly this offer: "Want the map, the calendar link, or the event page for any of these? Tell me which and I'll send them."
