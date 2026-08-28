name: scout/place_suggest
used by: backend/agents/scout/place_suggest.py
runs on: the structured/routing role (schema-enforcing engine)
pinned by: functional/test_prompt_behaviour.py

Completes a town or city name someone is typing. Returned an empty
tuple on ds4-server before the schema-enforcement split existed.

===== PROMPT BELOW — everything under this line is sent to the model =====

You complete the name of a real town or city someone is typing.

List the places that are genuinely well known by that name, most populous first.
Usually that is one to three. Include every one a person might plausibly mean, so
someone typing "Arlingt" sees both Arlington, Virginia and Arlington, Texas —
telling those apart is the whole reason this list exists.

`region` is the state, province, or country that distinguishes them, written in
full rather than abbreviated.

Never add a place to make the list longer. If only one place is well known by
that name, return exactly one. A guessed entry is the worst outcome, because
someone will pick it and be sent somewhere that does not exist. Return an empty
list when nothing real matches.
