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
discards a good brief. The engine is not strictly deterministic at
temperature 0, so the narrator asks this three times and drops only on a
majority "contradicts"; the facts below include the regime lines and book
status so a brief that faithfully reports them is not read as invented.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are checking a trading desk's written brief against the desk's own
facts for one stock. The facts are the desk's measured stances and the
key measurements behind them, read from the evidence in code; the brief
is a plain-words explanation written from those same facts.

Answer "contradicts" only when the brief states something the facts
disagree with: a direction the facts state the opposite way (rising
versus falling, above versus below), a stance the facts assign the other
way, a comparison or rank that is not what the facts show, or a figure,
percentage, price target or forecast the facts do not contain. A brief
that simply omits part of the facts, or says less than the facts, is
"consistent": omission is a shorter brief, contradiction is a wrong one.
When in doubt, answer "consistent".

The facts themselves can hold a name that looks conflicted: a price above
its short-term average while the analyst's stance is bearish, revenue up
while the stock falls, a positive tone with a neutral stance. When the
facts carry both sides, a brief that faithfully reports both is
consistent, not contradictory — whether or not it joins them with a word
like "but". A clause about the price's position next to a clause about the
stance is two facts from the same evidence, not a contradiction.

The stance each analyst holds is given in the facts. A clause in the brief
after "the <analyst> analyst is <stance>" describes the supporting detail;
it can mention a price's position, a trend, or a tone, and it never
changes the stance the label already states. When the brief labels an
analyst with the same stance the facts assign, that analyst is consistent
even if a supporting clause sounds like the opposite direction. A figure
the brief cites that appears among the measurements in the facts is
consistent, not invented. Only a claim the facts state the opposite way
is a contradiction.
