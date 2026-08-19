---
name: search/another_angle
used by: backend/services/search_planner.py -> SearchPlanner.another_angle()
runs on: the reply model (MAIN_LLM_MODEL), on rounds below SEARCH_MIN_ROUNDS
placeholders: {today} {cutoff}

Asks for the NEXT search, unconditionally. This runs instead of judging whether
the results are sufficient.

Why it exists: shown results that named two options and gave a size for
neither, the model answered "these are enough" 8 times out of 8. Four wordings
of that yes/no moved the rate between 0/8 and 3/5 with no trend. Asking for a
query instead has no cheap answer - the reply is a query or it is nothing - and
on the same input it proposed a useful one 6 times out of 6.

Tuning notes:
  - Raise SEARCH_MIN_ROUNDS to make more rounds unconditional; each round
    costs one search and one model call.
  - The word limit is enforced in code (16 words). Longer replies are treated
    as no proposal, and the round is recovered by asking search/refine instead.
---

Here is a question and the search results gathered so far.
Give one more search query, on a different angle from the ones already tried,
that would make the answer more specific.
Prefer the figures an answer has to cite and the results do not yet contain:
sizes, requirements, prices, versions, dates.
First check what is missing. If the results so far describe the constraint -
the hardware, the budget, the limit - but name no current options to apply it
to, the missing half is the options: search for what exists now, by category
and year. If the options are named but their sizes or requirements are not,
search for those figures by name and unit. Naming options from your own memory
instead of searching for them is the failure this exists to prevent.
Search the category, not their hardware: a query naming the box returns reviews
of the box.
Today is {today} and your own knowledge ends around {cutoff}: search that gap
rather than the last state you remember.
At most 12 words. Reply with the query alone, never a sentence describing what
to search for.
