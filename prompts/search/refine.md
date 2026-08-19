name: search/refine
used by: backend/services/search_planner.py -> SearchPlanner.refine()
runs on: the reply model (MAIN_LLM_MODEL), on rounds at or above SEARCH_MIN_ROUNDS
placeholders: {today} {cutoff}

Decides whether to keep searching, and if so what for. Unlike search/another_angle
this one may answer ENOUGH and stop the turn's research.

Known weakness: this model reaches for ENOUGH readily, which is why the first
refinement round does not use this prompt at all. Past the minimum the question
is whether to keep going rather than whether to start, so its opinion is worth
having here.

Reply contract:
  - "ENOUGH" (optionally with commentary) stops the research.
  - "NOT ENOUGH" with no query also stops it - there is nothing to run.
  - Anything else is treated as the next query.

===== PROMPT BELOW — everything under this line is sent to the model =====

Here is a question and the search results gathered so far.
Judge them against what answering actually requires, not against whether they
are on topic.
A choice made under a limit - what fits in this much memory, runs on this
hardware, finishes in this long, costs under this much - is only answerable
when the results give you both halves: which options exist, and the figure that
decides between them. Naming the options is not enough. If the options are
named but their sizes, requirements or prices are not, search for that figure
directly, by option name and unit.
The same applies to any question whose answer turns on a specific fact the
results talk around rather than state.
Reply ENOUGH only if you could write the final answer, with its specific names
and numbers, using nothing but the text of these results. If you would have to
supply any figure, version, date or name from your own memory to complete it,
that is not enough - your memory is what is out of date, and it is the reason
this search is running. Feeling able to answer is not the test; being able to
point at where each specific came from is.
Otherwise reply with one better search query and nothing else - the one that
would find the missing half. Use the vocabulary that source would use.
Never repeat a query that has already been tried.
Today is {today} and your own knowledge ends around {cutoff}: search that gap
rather than the last state you remember.

Worked example. Question: 'why not the latest model? I have one 128GB box'.
Results say only 'Vendor released Pro and Flash; both are strong.' That is NOT
enough: it names the options and gives no size for either, so nothing in it
says which one fits 128GB. The right reply is a query for the missing figure,
such as: Vendor Pro Flash parameter count memory requirement GB
Now judge the results below the same way.
