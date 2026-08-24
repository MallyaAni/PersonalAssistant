"""What one conversation turn's vector is made of, decided in one place.

A turn's embedding used to cover only the user's words, so anything said only
by the assistant - a recommendation, a looked-up fact - was invisible to
recall. Both sides are embedded now, bounded so no response can exceed the
embedding server's input window.

The signature names the model *and* the content scheme. Vectors are only
comparable within one space, and there are two ways to silently leave it: the
embedding model changes, or what gets embedded changes. Every row records the
signature it was built with, retrieval matches only the current one, and the
backfill re-embeds whatever does not match - so either kind of change makes
old rows invisible-until-rebuilt rather than quietly wrong, and the rebuild is
one idempotent command instead of a migration someone has to remember.
"""

from backend.config.settings import settings

# Bump when the composed text below changes shape, so existing vectors stop
# matching and the backfill knows to rebuild them.
_SCHEME = "qr1"

# Bounded for the embedding input window, not for storage: the vector is a
# retrieval key, and the head of each side carries its subject.
_MAX_QUERY_CHARS = 2_000
_MAX_RESPONSE_CHARS = 4_000


# The exact signature a freshly embedded turn records, and the only one
# retrieval will match.
def turn_embedding_signature() -> str:
    return f"{settings.EMBEDDING_MODEL}#{_SCHEME}"


# The text a turn's vector is computed from: both voices, bounded.
def turn_embedding_text(query: str, response: str) -> str:
    said = (query or "").strip()[:_MAX_QUERY_CHARS]
    answered = (response or "").strip()[:_MAX_RESPONSE_CHARS]
    if said and answered:
        return f"user: {said}\nassistant: {answered}"
    return said or answered
