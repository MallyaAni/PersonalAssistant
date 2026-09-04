name: search/place
used by: backend/services/search_planner.py -> SearchPlanner.foreign_places()
runs on: the reply model (MAIN_LLM_MODEL), once per place-bound search turn, on the composed query
pinned by: functional/test_search_compose_behaviour.py::test_the_place_judgement_names_a_previous_answers_town
placeholders: none
2026-09-04: added. A follow-up "try again" after an answer full of Colonial
Heights listings searched "Colonial Heights ... Courthouse Virginia" for a
person whose own place is Courthouse - the previous answer's town was copied
into the query and the retry came back from the wrong one. Whether a name in
a query is a different location is a question about the world, so it is a
model judgement; the caller strips what this names and holds the person's own
place in code.

Names which place names in a search query are a location other than where the
person is, so the caller can drop them and keep the query on the person's own
place.

What breaks when this is wrong:
  - Naming the person's own place: the query loses its anchor and searches
    anywhere.
  - Missing a foreign place: the query carries two towns and the results come
    from the wrong one.

===== PROMPT BELOW — everything under this line is sent to the model =====

A person is about to send a search query. You are given where the person is
and the query. List the place names in the query that are a location somewhere
other than where the person is - a city, town, district, county or region that
is not theirs. A name that is part of where they are, or that names the same
place, is not listed. A word that is not a place is not listed.

Reply with the list alone.
