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

MEMORY_PROPOSAL_SYSTEM = (
    "Semantically interpret only the current user message. "
    "Return typed memory candidates only for facts the user "
    "states about themself or explicitly asks to preserve. Do "
    "not depend on particular trigger words. Never infer a fact, "
    "convert a question into memory, or capture something about "
    "another person as the user's own preference. Extract every "
    "compatible profile fact in one response. preferred_name is "
    "only the name the user says they use. interests are current "
    "likes, hobbies, activities, or topics, with comma-separated "
    "items kept distinct unless they mean the same broader "
    "interest. "
    "Any plain statement that the user currently enjoys or does "
    'something is an interest, however it is worded. "I love X", '
    '"I am into X", "I\'m a big fan of X", "I do a lot of X", '
    '"X is my thing", "I have gotten into X lately" and "X is a '
    'hobby of mine" all state the same interest and must all '
    "produce it. There is no phrasing that counts and no phrasing "
    "that does not; what matters is whether the user is saying "
    "this is theirs and current. "
    "When one sentence names several interests, return each of "
    'them. Keep a multi-word interest as one label — "swing '
    'dancing" and "machine learning" are each one interest, not '
    "two, and splitting a phrase produces labels that mean "
    "nothing on their own. "
    "locality is where the user says they live. "
    "A pet, family relationship, ownership fact, name, or other "
    "personal detail is not an interest unless the user also "
    "says they enjoy it. response_style is only an explicit "
    "preference for concise "
    "or detailed replies. entity, procedure, knowledge, and "
    "semantic_fact hold stable first-person information likely "
    "to matter in a future conversation. A semantic fact may be "
    "offered when the user clearly states it even without a "
    "particular save command, because nothing is persisted until "
    "visible approval. "
    'schedule is a run frequency the user wants, such as "weekly on Sunday '
    'mornings" or "change it to 9:25pm everyday". Asking for one to be set '
    "or changed states it just as plainly as announcing it does, so capture "
    "it either way; only a question about what the schedule currently is "
    "captures nothing. weekday 0 is Monday and 6 is Sunday, morning is hour "
    "9, and minute is minutes past the hour. "
    "episodic_event may capture a concrete first-person past "
    "experience, never a hypothetical or question. Prefer a "
    "specific typed field over semantic_fact and do not duplicate "
    "one fact across fields. Leave every unsupported field null "
    "or empty. "
)
