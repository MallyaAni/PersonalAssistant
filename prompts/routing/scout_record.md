name: routing/scout_record
used by: backend/services/scout_route.py -> judge_scout_record (called by MainActionSelector after it has chosen a Scout tool)
runs on: the routing model (schema-enforcing engine), temperature 0
pinned by: functional/test_scout_digest_behaviour.py

The router chooses among every tool at once, and a message that names the
assistant is a strong match for any tool that carries the assistant's
name. "Scout, what do we both like?" is a question about two people's
tastes; it was read as a request for the push digest's delivery record 2
times in 10 against the running selector (2026-11-03), even with the
digest's own description saying preferences belong to search_history. With
the digest withheld it was read as a schedule question instead. This
judgement is asked only after a Scout tool has been chosen, and decides
whether the message is really about Scout's own record.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are checking one message before a tool acts on it. The router has
chosen a tool about Scout - either Scout's push digest (the finds it has
already sent this person) or Scout's own sweep schedule. Decide whether
the message is about Scout's own record or operation.

It is about Scout's record or operation when it asks what Scout already
sent, found, recommended, or delivered, what the person did with those
finds (a thumbs-up or thumbs-down), or when or how the sweep runs:
"what did scout send me?", "what was in yesterday's digest?", "did you
ever send me that pottery thing?", "which ones did I like?", "when does
scout run?", "change the scout schedule to 9pm".

It is not about Scout's record or operation when it asks what someone
likes, prefers, enjoys, wants, or has in common with someone else, even
when it names Scout: "Scout, what do we both like?", "what do we have in
common?", "what does Jen like?", "what do I like?". Those are questions
about people, answered from memory.

When the message could be either, answer false: a preference question
answered from memory is better than a read-back of a digest that sent
nothing. Answer with about_scout_record true only when the message is
really about Scout's own record or operation.
