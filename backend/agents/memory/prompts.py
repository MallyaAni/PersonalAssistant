"""What memory capture asks the model for, in its own words.

This runs on every ordinary chat turn and decides what is offered for saving.
The judgement is almost entirely about what *not* to capture: a question is not
a fact, another person's preference is not the user's, a pet is not an interest
unless they say they enjoy it, and nothing is inferred. Those lines were drawn
from real failures — a regex extractor once read "hi my name is Jen and i like
acting" as the name "Jen and i like acting".

The opposite failure is quieter and was measured here: the prompt said not to
depend on trigger words while doing exactly that, so "I love woodworking"
produced the interest and "I am into woodworking" produced nothing. A missed
interest is never proposed, never approved, and leaves no trace, so the
phrasings are stated as a rule rather than left to the examples. They are held
by `tests/functional/test_interest_capture_behaviour.py`.

Nothing here persists anything. Every candidate is shown on an approval card and
written only if the user says yes, which is what makes it safe to propose from a
plain statement rather than demanding a trigger phrase.

The mechanism — the typed decision models, the grammar, the catalogue of
interests already held — stays in `memory/proposal_agent.py`.
"""

from backend.core.prompts import load

MEMORY_PROPOSAL_SYSTEM = load("memory/proposal")
