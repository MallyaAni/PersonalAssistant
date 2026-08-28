name: search/compose
used by: backend/services/search_planner.py -> SearchPlanner.compose()
runs on: the reply model (MAIN_LLM_MODEL), once per turn that searches
pinned by: functional/test_search_compose_behaviour.py, functional/test_followup_keeps_the_subject_behaviour.py
placeholders: {today} {cutoff}

Writes the FIRST web search query of a turn. The router decides *whether* to
search; this decides *what to ask for*.

What breaks when this is wrong:
  - Queries that describe the constraint instead of the options. This exact
    fault shipped: asked what to host on one DGX Spark it searched
    "DGX Spark VLM inference memory bandwidth" twice, retrieved eight hardware
    reviews naming no models, and then recommended models from memory.
  - A year taken from training rather than from {today}, which returns what is
    already out of date.
  - 2026-08-25: "what's going on Weds-Sunday?" in a conversation about Canggu
    venues searched without the place and returned mini PC reviews.

Tuning notes:
  - Keep this short. Every failure here was tempting to answer with another
    sentence, and a prompt that lists cases stops reasoning and starts
    matching them. The rules that earn their place are the ones true of any
    question, not of the one that just went wrong.
  - The word limit is enforced in code as well (16 words); a longer reply is
    discarded as prose rather than sent to the search engine.
  - Keep "Reply with the query alone" last. Instructions at the end are the
    ones this model follows most reliably.

===== PROMPT BELOW — everything under this line is sent to the model =====

Write one web search query that would find what this person is asking for.
Use the words a source that answers them would use, not the words they used:
names, model numbers, versions, units, and the year when the answer changes
over time.
When the request names its subject only as "it", "they", "the villa", "at the
end", the subject is the one the conversation shown is about - the show, the
product, the place, the person - copied into the query exactly as named there.
Never substitute a different one that seems similar, and never one from your
own memory: a conversation about "Surviving Paradise" asked "does only one
person win at the end?" searches Surviving Paradise's winner, not another
show's.
A request with several requirements needs the one that decides the answer, not
all of them at once.
When the request is a choice, search for what the options are before searching
for the limit they have to satisfy: which things exist changes, and a limit
someone states does not.
Today is {today} and your own knowledge ends around {cutoff}. What changed in
between is what you cannot know and what this search is for, so ask for now
rather than for the last state you remember.
When the request is travel - flights, trains, a trip - the origin is where the
person is unless they say otherwise, and a place with no airport (Amalfi) is
searched by the airport people use for it (Naples). Both ends go in the query
with the dates; two foreign places in the message are the trip, not the flight.
When the request is about what is on, happening, open, or scheduled somewhere,
the query carries the place - from the request or the conversation - and the
calendar dates the relative days mean, plus the kind of thing: events, lineup,
schedule. A query for events with no place finds events anywhere, which is
nowhere.
At most 12 words. Reply with the query alone, no quotes, no explanation, and
never a sentence describing what to search for.
