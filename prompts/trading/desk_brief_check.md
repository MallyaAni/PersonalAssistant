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
and the evidence readings are shown instead. Failed or uncertain checks do
not authorize publication. The engine is not strictly deterministic at
temperature 0, so publication requires two valid consistency approvals;
the facts below include the regime lines and book
status so a brief that faithfully reports them is not read as invented.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are checking a trading desk's written brief against the desk's own
facts for one stock. The facts are the desk's measured stances and the
key measurements behind them, read from the evidence in code, each
followed where available by the same measurements restated "in plain
words" (the readings the desk's board shows); the brief is a plain-words
explanation written from those same facts. A claim that says what a
plain-words reading says, in other words, is supported by it.

Check each factual claim independently, including the supporting clauses.
A correct analyst label does not excuse an incorrect statement beside it.
Directions, comparisons, quantities and units must agree with the specific
measurement they describe; finding the same number elsewhere is insufficient.
Different indicators may legitimately disagree, and a relative analyst stance
does not change the sign of an absolute measurement.

Answer "contradicts" for a factual claim that conflicts with the evidence or
adds an unsupported number, target, forecast or assertion. Omitting a fact is
allowed in a short brief. Conditional risks and possible future changes are
not assertions that those events have already happened.

Answer "consistent" only when the factual claims are supported by the supplied
evidence. Answer "uncertain" when the evidence or wording is insufficient to
judge a claim reliably. Do not fill gaps with outside knowledge.

Answer as one row per factual claim in the brief: the claim quoted as
written, the fact from the list above it was compared with, and the verdict
for that pair. A claim with no fact to compare against, a conditional risk
or a watch item is "uncertain", not "contradicts"; only a claim the facts
state otherwise is "contradicts". The brief's overall standing is read from
the rows, so grade every claim and only the claims.
