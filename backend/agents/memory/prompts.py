"""What memory capture asks the model for, in its own words.

This runs on every ordinary chat turn and decides what is offered for saving.
The judgement is almost entirely about what *not* to capture: a question is not
a fact, another person's preference is not the user's, a pet is not an interest
unless they say they enjoy it, and nothing is inferred. Those lines were drawn
from real failures — a regex extractor once read "hi my name is Jen and i like
acting" as the name "Jen and i like acting".

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
    "interest. locality is where the user says they live. "
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
    "episodic_event may capture a concrete first-person past "
    "experience, never a hypothetical or question. Prefer a "
    "specific typed field over semantic_fact and do not duplicate "
    "one fact across fields. Leave every unsupported field null "
    "or empty. "
)
