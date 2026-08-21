"""Complete a place name while it is being typed, using the local model.

A town name alone is ambiguous to a search engine exactly as it is to a person:
`sources/web.py` records that querying "hiking near Arlington" returns Texas and
Washington alongside Virginia. So the profile stores a town *and* a region, and
the form has to help someone supply both — which it could not, because whoever
typed it had to already know that "Arlington, Virginia" was wanted rather than
"Arlington" or "Arlington, VA".

The obvious fix is a geocoding autocomplete, and it is the wrong one here: the
only geocoder this deployment can reach is disabled by default, and
OpenStreetMap's usage policy rules out a request per keystroke. A bundled list
of regions was tried and is worse than it looks — it is a fixed list, it is
mostly one country, and it cannot help with the *town* half, which is the
ambiguous one.

The local model has neither problem. It knows world geography, it costs no
egress, and it answers the actual question: given some letters, which real
places might this be, and what tells them apart.

What measurement changed, all against the live 4B, greedily:

- **it pads.** Asked for "up to six", it returned exactly six every time,
  inventing "Tuscaloosa, Alaska", "Tuscaloosa, California" and "Silver Spring,
  Illinois" to fill the list. A suggestion someone can pick is worse than no
  suggestion, because picking it sends the sweep somewhere that does not exist;
- **it over-corrects.** Told to stop as soon as it was unsure, it collapsed to
  exactly one answer for everything — including "Arlingt", where offering both
  Virginia and Texas is the entire point;
- the wording below is the one that did neither: Arlington returns two,
  Springfield and Portland return five real ones, Tuscaloosa returns one,
  and nonsense returns none. About 500 ms per call, identical across runs.

Suggestions are exactly that. The fields stay free text, so anywhere in the
world can still be typed, and nothing here decides anything on its own.
"""

import asyncio
import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from backend.core.interfaces import TextWriter
from backend.core.prompts import load
from backend.discovery.types import MAX_LABEL_CHARS, MAX_REGION_CHARS, normalize_label

# Below this there is nothing to go on and every name in the world matches.
MIN_QUERY_CHARS = 2

# Longer than any real town name, and a bound on what reaches a prompt.
MAX_QUERY_CHARS = 60

# How many suggestions may be offered. The model is asked not to reach this;
# the cap only stops a runaway list.
MAX_SUGGESTIONS = 5


class _Place(BaseModel):
    """One completion the model offers."""

    model_config = ConfigDict(extra="forbid")

    town: str = Field(max_length=MAX_LABEL_CHARS)
    region: str = Field(max_length=MAX_REGION_CHARS)


class _Places(BaseModel):
    """The grammar-constrained completion list."""

    model_config = ConfigDict(extra="forbid")

    places: list[_Place] = Field(default_factory=list, max_length=MAX_SUGGESTIONS)


@dataclass(frozen=True, slots=True)
class PlaceSuggestion:
    """A town and the region that tells it apart from its namesakes."""

    town: str
    region: str


_SYSTEM = load("scout/place_suggest")


class PlaceSuggester:
    """Offer completions for a partly typed place name."""

    # The writer is the same narrow inference contract the rest of discovery
    # uses, so None simply means no suggestions rather than an error.
    def __init__(self, writer: TextWriter | None, max_tokens: int = 220) -> None:
        self.writer = writer
        self.max_tokens = max_tokens

    # Report whether suggesting can work at all, so a caller can skip the call.
    def is_enabled(self) -> bool:
        return self.writer is not None

    # Suggest places for what has been typed so far.
    #
    # Empty is a normal answer, not a failure: too few characters, no model, an
    # unparseable reply, or nothing real matching all land here, and the form
    # stays exactly as usable as it is without this.
    async def suggest(self, typed: str) -> tuple[PlaceSuggestion, ...]:
        query = " ".join((typed or "").split())[:MAX_QUERY_CHARS]
        if len(query) < MIN_QUERY_CHARS or self.writer is None:
            return ()
        try:
            result = await asyncio.to_thread(
                self.writer.chat,
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": f"They typed: {query}"},
                ],
                self.max_tokens,
                _Places.model_json_schema(),
                # Greedy, so the same prefix suggests the same places every
                # time. A list that reshuffles between keystrokes is unusable.
                0.0,
            )
            parsed = _Places.model_validate(json.loads(result["content"]))
        except Exception:
            return ()

        suggestions: list[PlaceSuggestion] = []
        seen: set[tuple[str, str]] = set()
        for place in parsed.places:
            town = " ".join(place.town.split())
            region = " ".join(place.region.split())
            if not town or not region:
                continue
            # Identity is the pair, never the town alone.
            #
            # Deduplicating on the town looks tidier and is catastrophic here:
            # it collapses "Arlington, Texas" and "Arlington, Virginia" into one
            # entry, which is precisely the distinction this list exists to
            # draw. The cost of the pair is that one place offered at two
            # granularities — the live model returned "Bengaluru, Karnataka"
            # beside "Bengaluru, India" — survives as two rows. Telling those
            # apart needs to know Karnataka is in India, and a redundant row is
            # a far cheaper mistake than a deleted one.
            identity = (normalize_label(town), normalize_label(region))
            if identity in seen:
                continue
            seen.add(identity)
            suggestions.append(PlaceSuggestion(town=town, region=region))
        return tuple(suggestions[:MAX_SUGGESTIONS])
