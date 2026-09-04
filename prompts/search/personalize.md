name: search/personalize
used by: backend/services/search_planner.py -> SearchPlanner.relevant_interests()
runs on: the reply model (MAIN_LLM_MODEL), once per turn that searches, only when interests are on file
pinned by: functional/test_search_compose_behaviour.py::test_the_search_is_personalised_only_where_that_is_the_answer
placeholders: none
2026-09-04: added. The interests used to be advice inside search/compose, which "decides when to use them"; asked for fun things to do by an account with twenty interests on file, it decided not to and returned four listings two hours away. Whether a request depends on who is asking is now its own judgement, and the caller puts what this names into the query rather than hoping the composer did.

Decides whether a person's own tastes belong in the web search that answers
their request, and which of them.

What breaks when this is wrong:
  - True for a price, a score or a spec, and the query is corrupted: a taste
    for dancing does not change what a PS5 costs.
  - False for a request about what to do, and the person gets whatever is
    most popular near them rather than anything they would go to. That is
    the failure it was written for.
  - Vague interests named over specific ones. "Exploring new things" matches
    every page and finds nothing; "salsa" finds a salsa night.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are deciding whether a person's own tastes belong in the web search that answers their request, and if so, which of them.

Answer `personal` first, then `interests`.

`personal` is true when the answer depends on who is asking - a request for something to do, see, watch, read, eat, play, or attend; somewhere to go; a recommendation, suggestion, or idea; what is on near them. These are questions where two different people are owed different answers, and searching them without knowing the person returns whatever is most popular rather than what they would want.

`personal` is false when the answer is the same for everyone. A price, a score, a specification, a date, an address, an opening time, who holds an office, how something works, what happened in the news, whether a deal went through. A person's taste in dancing does not change what a PS5 costs, and putting it in the query corrupts the search.

A person's interests come in two kinds and they are used in two different places, so sort them.

`terms`: the ones that name something a listing page will actually say - "salsa", "swing dancing", "live music", "breweries", "farmers markets", "board games", "hiking". These go into the search query as written, so name only what you would want searched, most useful first, at most six.

- Prefer the ones that fit the request. An evening out is not served by "hiking"; a Saturday afternoon might be.
- Leave out anything the request already says. If they asked about live music, the query has it.

`preferences`: the ones that say how this person likes to *choose*, not what to look for. "Exploring new things", "trying new places", "unique local events" are real and they matter - someone who likes new things is bored by the same night out twice, and someone who does not wants their usual. They are useless in a query, because every page matches them and none is about them. They are used afterwards, when picking which of the results to put in front of the person and how to describe them.

Put each interest in whichever list it belongs to. An interest can be in neither if the request has nothing to do with it. When `personal` is true and nothing fits, return both lists empty.

Answer `personal`, then `terms`, then `preferences`.
