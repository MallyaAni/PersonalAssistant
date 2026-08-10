"""Resolve a place name to the timezone it is actually in.

A schedule is stored in a zone, and the zone was hardcoded to America/New_York
wherever a place arrived through a chat approval. An account living in Canggu,
Bali therefore held a locality — and then a schedule — in Virginia time, so a
digest set for 11:15 fired at 23:15 where the person was. Nothing in the product
contradicted it, because one stored zone looks as plausible as another.

Geocoding would answer this, and the only geocoder here is disabled by default.
The local model knows world geography, costs no egress, and is asked one narrow
question with one right answer.

What makes that safe is that the answer is checked rather than trusted:
`zoneinfo.available_timezones()` is the real IANA database shipped with the
runtime, so an invented zone — and this model does invent them — cannot survive.
An unresolvable place keeps the caller's fallback, which is the behaviour every
place had before this existed.

One limit, measured rather than assumed: a bare name whose most famous bearer
dominates the others — "Naples", "Athens", "Odessa" — is answered with that
bearer instead of being refused, where "Perth" or "Toledo" are correctly
refused. Passing `region` removes the ambiguity and is why every caller here
does.
"""

import asyncio
import json
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field

from backend.core.interfaces import TextWriter

MAX_PLACE_CHARS = 120


class _Zone(BaseModel):
    """The grammar-constrained answer."""

    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(default="", max_length=64)


_SYSTEM = """You name the IANA timezone a place is in.

Answer with one identifier from the IANA database, exactly as it is written
there — "Asia/Makassar", "Europe/London", "America/New_York". Region and city,
separated by a slash.

Give the zone the place actually observes, which is not always the one named
after the nearest large city: Bali is Asia/Makassar, not Asia/Jakarta.

When the place comes with a state, region or country, it is settled — answer it.
"Phoenix, Arizona" is America/Phoenix and "Alexandria, Virginia" is
America/New_York.

Return an empty string, and nothing else, when the place is a bare name with
nothing to settle it and that name is a well-known place in more than one
country or more than one zone. "Alexandria" alone is both Egypt and Virginia.
"Arlington", "Springfield", "Cambridge" and "Richmond" alone are each several
places in different zones. Picking the most famous one is not an answer.

Return an empty string too when the place is too broad or vague to sit in one
zone at all.

A wrong zone is worse than no zone, because it silently moves every scheduled
time by hours and nothing looks broken."""


class TimezoneResolver:
    """Name the zone a place is in, or nothing."""

    # The writer is the shared inference contract, so None simply means no
    # resolution rather than an error.
    def __init__(self, writer: TextWriter | None, max_tokens: int = 32) -> None:
        self.writer = writer
        self.max_tokens = max_tokens
        # Read once: the set is a few hundred strings and never changes at
        # runtime.
        self._known = available_timezones()

    # Resolve one place, returning None when it cannot be resolved safely.
    #
    # `region` is whatever the locality holds to disambiguate its label. Passing
    # it matters more than it looks: "Alexandria" alone resolves to Egypt, and
    # "Alexandria, Virginia" resolves to the place the user meant.
    async def resolve(self, place: str, region: str | None = None) -> str | None:
        parts = [part for part in (place, region) if part and part.strip()]
        query = " ".join(", ".join(parts).split())[:MAX_PLACE_CHARS]
        if not query or self.writer is None:
            return None
        try:
            result = await asyncio.to_thread(
                self.writer.chat,
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": query},
                ],
                self.max_tokens,
                _Zone.model_json_schema(),
                # Greedy: the same place must resolve the same way every time,
                # or a locality saved twice would sit in two different zones.
                0.0,
            )
            answer = _Zone.model_validate(json.loads(result["content"])).timezone
        except Exception:
            return None
        candidate = answer.strip()
        # The whole safety of this: an identifier the IANA database does not
        # contain is a hallucination, and there is no partial credit for one.
        return candidate if candidate in self._known else None
