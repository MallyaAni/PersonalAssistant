name: search/rank
used by: backend/core/result_ranking.py -> order_by_usefulness()
runs on: the routing model (ROUTING_LLM_MODEL - the same DeepSeek that answers), one grammar-constrained call per search turn
pinned by: functional/test_search_rerank_behaviour.py, functional/test_followup_keeps_the_subject_behaviour.py, functional/test_constraint_ranking_behaviour.py
placeholders: none

Orders the web results a search gathered before they reach the reply prompt.
They arrive in the providers' order - Brave's index order, which carries no
score, or Tavily's own - and neither reads the question.

2026-08-25: the deployed 0.6B cross-encoder was tried first. Asked to order
four results for "what events are happening in Arlington Virginia this
weekend? (asked from Arlington, Virginia)", it put a festival at Snowshoe,
West Virginia second, above an Arlington concert, with scores of 0.1-0.25
across the board. The main model reads the question, the place and the
dates the way a person does, so it does the ordering; the cost is one short
constrained call, and every failure keeps the providers' order.

What the ranking may know about the person: where they are, and what the
turn already retrieved about them - interests, facts - as a tie-breaker
only. The reply keeps interests out of ordinary answers on purpose (a
standing interest list bent unrelated answers when it was tried); ordering
results that already answer the question is the one place they cannot do
that harm, because the ranker can reorder but never add.

===== PROMPT BELOW — everything under this line is sent to the model =====

You order web search results by how useful each is for answering the question, for the person who asked it. Read the question, where they asked from, and the date; then read every result.

Most useful first: results that answer the question directly, for the place and the dates the question means, from a source that would actually know. Then results that are relevant but less specific. Last: results about other places, other dates already past, or the wrong subject - keep them in the list, at the bottom.

When something is known about the person, use it only to choose between results that answer the question equally well - a salsa night above a farmers market for someone who dances salsa, when both are on the asked dates in the asked place. It never lifts a result that answers the question worse, and it never brings in a subject the question did not ask about.

When hard constraints are given, a result that violates one is not an answer for this person, however well it fits the question: an oyster bar for someone allergic to shellfish, a walk-up venue for someone who needs step-free access, a place over their firm budget. List the numbers of such results under violates - only results the text shown actually violates, never a guess from a name - and still place them in the order (at the bottom). With no constraints given, violates is empty.

Return the order, as the list of result numbers from most useful to least, each number exactly once - whether these results are events: things happening at a place and time (concerts, nights out, markets, festivals, meetups, shows), as opposed to products, articles, facts, or places to visit any day - and whether they are travel fares: flight, train or trip prices from airlines or aggregator pages - and whether they are on the subject: about the show, product, place, person or thing the question names (the part after "searched as" says exactly what was searched), true when at least the most useful results are about that thing, false when they describe a different one of the same kind - another show, another product - however well they answer the question's shape.
