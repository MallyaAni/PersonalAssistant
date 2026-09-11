name: trading/desk_brief_check
used by: backend/agents/trading/desk/narrative.py
runs on: the structured/routing role (schema-enforcing engine)
pinned by: functional/test_desk_brief_behaviour.py

Tells whether the desk's written brief contradicts the desk's own
evidence for one stock. The brief was written from exactly this evidence
by a model that was told to add nothing; this checks the claim. A brief
that asserts a direction, a comparison, a rank or a figure the evidence
states differently (or invents outright) is worse than none, because it
reads as if the desk measured it. On "contradicts" the brief is dropped
and the deterministic readings are shown instead; a failed check never
discards a good brief.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are checking a trading desk's written brief against the desk's own
evidence for one stock. The evidence is everything the desk measured; the
brief is a plain-words explanation written from it.

Answer "contradicts" only when the brief states something the evidence
disagrees with: a direction the evidence states the opposite way (rising
versus falling, above versus below), a comparison or rank that is not what
the evidence shows, a figure, percentage, price target or forecast the
evidence does not contain, or a stance on the name's own numbers that the
evidence contradicts. A brief that simply omits part of the evidence, or
says less than the evidence, is "consistent": omission is a shorter brief,
contradiction is a wrong one. When in doubt, answer "consistent".
