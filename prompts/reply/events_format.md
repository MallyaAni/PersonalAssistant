name: reply/events_format
used by: backend/agents/graph.py -> _render_events_format (context["events_format"])
runs on: the reply model, appended to the turn state when the turn's search results are events
placeholders: none

How a list of events is presented, whatever route produced it. Arsalon
asked for this shape on 2026-08-25 and the operator made it the default for
everyone: it was first shipped as the "What's on" skill pack, but a skill
only applies when the router invokes it, and the operator's very next
events answer arrived through a plain web search without the format.
Now the result ranker, which reads every result anyway, says whether the
results are events, and this block is rendered when they are. The pack
keeps the same shape for the turns it is invoked on; this file is the
canonical wording.

===== PROMPT BELOW — everything under this line is sent to the model =====

This turn's search results are events. Present them this way, whatever else you were going to say:

Group by day, in date order. Each event on its own lines:
- Day and date, then the event name and the artist or act.
- Venue and area.
- Map: a Google Maps link for the venue, written as https://maps.google.com/?q=<venue name>+<area>.
- Time, and the price or "free"; if the sources do not say, write "price not listed".
- One line on the music or what it is - the style, the vibe, who it is for.
- Hear it: a YouTube search link for the artist, written as https://www.youtube.com/results?search_query=<artist name>, when there is a named artist.
- Details: the Instagram or event page link only when a source gives one; never invent a handle or a URL.

Include only events still ahead of today; drop anything already past. Lead with what is closest to the person's place; a genuinely notable thing further away goes last with the distance said. No headers, no tables, no markdown bold; short lines a phone can show. Finish by asking whether they want any of these kept, reminded about, or searched further.
