"""Complete a stored home locality with the city it actually sits in.

A locality is stored as a label and a region, and the region often names only
the state or country - "Courthouse, Virginia" - so a search holds the
neighbourhood against a whole state and a listing in some other town in that
state is judged near the person. The local model knows world geography, costs
no egress, and is asked one narrow question with one right answer.

What makes that safe is that the answer is bounded rather than trusted: the
schema forces a single short region string, the caller keeps the person's own
region on any failure, and only a non-empty result within the same length
bounds as the stored region replaces it. A wrong city would be worse than the
bare state, so an uncertain answer must keep what was written.
"""

import asyncio
import json

from pydantic import BaseModel, ConfigDict, Field

from backend.core.interfaces import TextWriter
from backend.core.prompts import load

MAX_CITY_CHARS = 120


class _Region(BaseModel):
    """The grammar-constrained answer: the region to store, city first."""

    model_config = ConfigDict(extra="forbid")

    region: str = Field(default="", max_length=MAX_CITY_CHARS)


_SYSTEM = load("locality/city")


class LocalityCityResolver:
    """Name the region that carries the city a locality label sits in, or nothing."""

    # The writer is the shared inference contract, so None simply means no
    # resolution rather than an error.
    def __init__(self, writer: TextWriter | None, max_tokens: int = 32) -> None:
        self.writer = writer
        self.max_tokens = max_tokens

    # Resolve one locality, returning None when it cannot be resolved safely.
    async def resolve(self, label: str, region: str) -> str | None:
        query = f"{label}, {region}".strip()[:MAX_CITY_CHARS]
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
                _Region.model_json_schema(),
                # Greedy: the same locality must resolve the same way every
                # time, or a locality saved twice would sit in two regions.
                0.0,
            )
            answer = _Region.model_validate(json.loads(result["content"])).region
        except Exception:
            return None
        candidate = answer.strip()
        if not candidate or len(candidate) > MAX_CITY_CHARS or "\n" in candidate:
            return None
        # The label is stored separately and joined to whatever region this
        # returns, so a region that echoes the label duplicates the place -
        # the model does this readily for a label it knows is a city
        # ("Arlington, Virginia" for the label "Arlington"). Refuse it here so
        # no caller has to remember the rule.
        if any(
            part.strip().casefold() == label.casefold()
            for part in candidate.split(",")
        ):
            return None
        return candidate
