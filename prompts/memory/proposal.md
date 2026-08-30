name: memory/proposal
used by: backend/memory/proposal_agent.py via backend/agents/memory/prompts.py
runs on: the routing model (schema-enforcing engine)
pinned by: functional/test_memory_capture_discipline.py, functional/test_scout_schedule_referent_behaviour.py

What from one utterance is worth remembering. Known ceiling is the model,
not this wording: Raleigh extracts 4/4 and the identical sentence naming
Durham extracts 0/4, deterministic at temperature 0. Do not fix that here
with examples; that is the overfitting this project forbids.

The 2026-08-24 over-capture - a debate point about how the system works,
stored as a user fact - is pinned by functional/test_memory_capture_discipline.py.
Its fix is the work-at-hand principle below, never a list of phrasings.

The 2026-08-26 mis-capture: "send another don tito reminder at 7" - a
one-off reminder - was captured as the sweep's schedule (daily, hour 7)
and applied, so Scout, which ran daily at 5 PM, announced a "daily 7 AM
check" the user had never asked for. The same evening the schedule field
was removed from this agent altogether: Scout's cadence has one writer,
the routed scout_schedule tool, and a stated time fills nothing here. The
agent is still handed the assistant's previous reply so that "this"
resolves to what was actually just discussed - never as a source of
facts. Pinned by functional/test_scout_schedule_referent_behaviour.py.

The 2026-08-30 mood-and-mood-of-sentence pair, found while measuring the
preference label. "don't bother storing the whole conversation, just
summarize it" was captured, and labelled a standing preference - the
2026-08-24 over-capture again, wearing an imperative instead of an
argument. Measured the same minute: "don't suggest anything over $50" and
"keep it under $50" captured nothing, while "my budget is about $50 for a
night out" captured 1/1. The rule below already said "should work"; what
it lacked was that the mood of a sentence says nothing about its subject.
An instruction is read for what it constrains - the user's own life, or
this system's machinery - never for being phrased as a request. Pinned by
functional/test_preference_labelling_behaviour.py.

What that change bought, and what the wording of it cost. Measured
2026-08-30, four runs per case. The rule had to hold three things at once,
and the first two attempts each broke one of them. At 99 words it drove
the machinery direction to 0/4 and pushed ordinary capture off a cliff -
"my dentist is Dr Lee on Wilson Boulevard" fell to 1/4, the crowding-out
the comment beside this call already warned about. Cut to 37 words,
capture returned to 4/4 and the machinery leak came back at 1/4. What
holds both is 47 words that name the subject rather than argue the point:
ordinary capture 4/4 on all three probes, machinery 0/4 on all three, and
constraints capturing 7-9 of 10 per run.

Recall on any single constraint is not stable and never was - the same
sentence captures in one run and not the next - so the test asserts recall
only as a rate across the set, with a threshold of six against a measured
minimum of seven. What is stable is the label: across roughly eighty
captures in these runs, not one constraint came back as a plain fact, so
that is asserted with no tolerance.

===== PROMPT BELOW — everything under this line is sent to the model =====

Semantically interpret only the current user message. Return typed memory candidates only for facts the user states about themself or explicitly asks to preserve. Do not depend on particular trigger words. Never infer a fact, convert a question into memory, or capture something about another person as the user's own preference. Extract every compatible profile fact in one response. preferred_name is only the name the user says they use. interests are standing pursuits the user enjoys for their own sake - likes, hobbies, and activities they would seek out beyond the current conversation - with comma-separated items kept distinct unless they mean the same broader interest. A plain statement of enjoying or regularly doing a pursuit is an interest, however it is worded. "I love X", "I am into X", "I'm a big fan of X", "I do a lot of X", "X is my thing", "I have gotten into X lately" and "X is a hobby of mine" all state the same interest and must all produce it. There is no phrasing that counts and no phrasing that does not; what matters is whether the user is stating a pursuit as theirs, current, and enjoyed for its own sake. Wanting to use something for a task, aspiring to get better results or abilities from it, or describing what they set up, configured, or are working on states the work at hand, not an interest - however enthusiastic the wording. When a sentence does state an interest, the pursuit itself is the only interest in it: tools, equipment, models, and infrastructure named around it are how the pursuit is done, not further interests. When one sentence names several interests, return each of them. Keep a multi-word interest as one label — "swing dancing" and "machine learning" are each one interest, not two, and splitting a phrase produces labels that mean nothing on their own. locality is where the user says they live. A pet, family relationship, ownership fact, name, or other personal detail is not an interest unless the user also says they enjoy it. response_style is only an explicit preference for concise or detailed replies. entity, procedure, knowledge, and semantic_fact hold stable information the user states about themself likely to matter in a future conversation, and a semantic fact may be offered when the user clearly states one even without a particular save command; what another person likes, does, or is remains that person's fact and fills nothing. A statement about how this assistant, its memory, or any system under discussion works or should work - described, expected, argued for, or corrected - is about the work at hand, not about the user, and fills nothing. An instruction is read for what it constrains, not for being addressed to the assistant: constraining the user's own life states their standing choice and fills what a declarative would, while constraining this assistant's own remembering, storing or summarising is the work at hand and fills nothing. A time, day, or cadence the user wants something to happen at - a reminder, an alarm, a text, or when Scout's own sweep runs - is carried out by the application's tools, states nothing about the user, and fills nothing here, however it is phrased. When the message names its subject only as "this", "it", or "that", the assistant's previous reply, when supplied, says what that is; the previous reply exists only to resolve such a reference and is never itself a source of facts. weekday 0 is Monday and 6 is Sunday, morning is hour 9, and minute is minutes past the hour. episodic_event may capture a concrete first-person past experience, never a hypothetical or question. Prefer a specific typed field over semantic_fact and do not duplicate one fact across fields. Leave every unsupported field null or empty.
