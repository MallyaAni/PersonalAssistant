name: search/place
used by: backend/services/search_planner.py -> SearchPlanner.place_judgement() (foreign_places() reads the same answer)
runs on: the reply model (MAIN_LLM_MODEL), once per search turn, on the question and the composed query
pinned by: functional/test_search_compose_behaviour.py::test_the_place_judgement_names_a_previous_answers_town, functional/test_place_bound_judgement_behaviour.py
placeholders: none
2026-09-04: added. A follow-up "try again" after an answer full of Colonial
Heights listings searched "Colonial Heights ... Courthouse Virginia" for a
person whose own place is Courthouse - the previous answer's town was copied
into the query and the retry came back from the wrong one. Whether a name in
a query is a different location is a question about the world, so it is a
model judgement; the caller strips what this names and holds the person's own
place in code.
2026-09-05: `place_bound` added. Whether a question depends on where the
person is used to be a word list in conversation_service.py ("events",
"near me", "brunch", "weather"...), which missed every phrasing its author
had not imagined and is the pattern-decides-meaning rule this repository
forbids. The same call now answers it, with the question in front of it;
the code holds (place, dates, foreign names) follow the verdict.

Names which place names in a search query are a location other than where the
person is, so the caller can drop them and keep the query on the person's own
place.

What breaks when this is wrong:
  - Naming the person's own place: the query loses its anchor and searches
    anywhere.
  - Missing a foreign place: the query carries two towns and the results come
    from the wrong one.

===== PROMPT BELOW — everything under this line is sent to the model =====

A person is about to send a search query. You are given where the person is,
the question they asked, and the query written for it.

First, `place_bound`: whether the answer to their question depends on where
they are. It does when they are asking what is on, what to do, where to go,
where to eat or drink, what is open, the weather, the traffic, how far or how
long to somewhere - anything whose answer changes with the asker's location,
whether or not they said "near me". It does not when the answer is the same
from anywhere: a price, a fact, the news, a decision a body made, how
something works, a person or product. A time word alone - this week, tonight
- does not make a question about here.

Then `places`: the place names in the query that are a location somewhere
other than where the person is - a city, town, district, county or region
that is not theirs. A name that is part of where they are, or that names the
same place, is not listed. A word that is not a place is not listed. When
where they are is not known, list nothing.

Answer `place_bound`, then `places`.
