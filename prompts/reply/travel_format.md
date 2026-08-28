name: reply/travel_format
used by: backend/agents/graph.py -> _render_travel_format (context["travel_format"])
runs on: the reply model, appended to the turn state when the turn's search results are flight or trip fares
pinned by: functional/test_travel_format_behaviour.py
placeholders: none

How a trip answer is built when the evidence is aggregator fare pages. On
2026-08-26 the operator asked for the cheapest nonstop to Rome and back from
the Amalfi coast and was told "ITA nonstop Rome to Amalfi from $86" - a
route that does not exist, a teaser price presented as a quote, and no
reasoning about the trip's shape. The query construction was fixed
separately; this block is what the reply owes a trip regardless: the legs
and their airports, whether a nonstop exists at all, and fares labelled for
what they are. The result ranker says whether the results are fares.

===== PROMPT BELOW — everything under this line is sent to the model =====

This turn's search results are flight or trip fares from aggregator pages. Build the answer this way:

First the shape of the trip, before any price: each leg with its airports (a place with no airport - Amalfi - is served by the one people use, Naples), whether a nonstop exists on that leg at all and from where, and the realistic alternatives when it does not (fly from a nearby hub, or a train to the airport that has the nonstop). Use what you know about routes; this is knowledge, not a live fact.

Then fares. A price on an aggregator page is a teaser for some date, cabin and bag allowance, not a quote for theirs: give it as "indicative, from <source>, as of today" with the dates it applies to when the page says, never as "the price". Give a range when the sources disagree. Never state a fare for a route that does not exist.

Then what to do: the two or three searches or sites that would turn the indicative figure into a bookable one for their exact dates, and the one decision that changes the price most (which airport, which day, nonstop versus one stop).

Short lines a phone can show; no headers or tables. Finish by asking which leg or option they want pinned down.
