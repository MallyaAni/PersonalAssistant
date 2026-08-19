name: search/compose
used by: backend/services/search_planner.py -> SearchPlanner.compose()
runs on: the reply model (MAIN_LLM_MODEL), once per turn that searches
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

Tuning notes:
  - The last line's word limit is enforced in code as well (16 words); a reply
    longer than that is discarded as prose, not sent to the search engine.
  - Keep "Reply with the query alone" last. Instructions at the end are the
    ones this model follows most reliably.

===== PROMPT BELOW — everything under this line is sent to the model =====

Write one web search query that would find what this person is asking for.
Use the words a source that answers them would use, not the words they used:
names, model numbers, versions, units, and the year when the answer changes
over time.
A request with several requirements needs the one that decides the answer, not
all of them at once.
When the request is a choice - what to use, run, host, buy, or pick - search
first for which options exist right now, by category and year. That is the half
your memory is stale about and the half a search can actually replace; the
hardware, budget or limit they named is fixed and can be looked up afterwards.
Do not spend this query on the constraint and then name the options from memory.
Today is {today}, and your own knowledge ends around {cutoff}. Everything
between those two dates is precisely what you cannot know and what this search
is for, so search for now rather than for the last state you remember - a year
taken from your own memory is the one thing guaranteed to return what is
already out of date.
Searching for the options means searching the category, not their hardware: a
query naming the box returns reviews of the box.
At most 12 words. Reply with the query alone, no quotes, no explanation, and
never a sentence describing what to search for.
