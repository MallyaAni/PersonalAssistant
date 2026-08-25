name: search/rank
used by: backend/core/result_ranking.py -> order_by_usefulness()
runs on: the routing model (ROUTING_LLM_MODEL - the same DeepSeek that answers), one grammar-constrained call per search turn
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

What the ranking may know about the person: where they are. Interests are
kept out on purpose - a standing interest list bent unrelated answers when
it was tried.

===== PROMPT BELOW — everything under this line is sent to the model =====

You order web search results by how useful each is for answering the question, for the person who asked it. Read the question, where they asked from, and the date; then read every result.

Most useful first: results that answer the question directly, for the place and the dates the question means, from a source that would actually know. Then results that are relevant but less specific. Last: results about other places, other dates already past, or the wrong subject - keep them in the list, at the bottom.

Return only the order, as the list of result numbers from most useful to least, each number exactly once.
