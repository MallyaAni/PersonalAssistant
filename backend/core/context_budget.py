"""Deciding what goes into a prompt, and saying what did not.

Until now nothing counted. The prompt was assembled from whatever each source
happened to return, bounded only incidentally: ten history turns, six thousand
characters of memory, ten thousand of search payload, numbers set once and
never measured against the window they share. A heavy turn came to five or
eight thousand tokens against a million-token context, so nothing collided and
the absence of accounting cost nothing visible - which is exactly the condition
under which it stops being true quietly.

Three defects in one day came from the same shape, and they are the design
brief here:

- A budget **raced for** rather than divided. Search results were serialized
  until a byte budget ran out and the rest dropped by a `break`, so twelve
  sources became six and the ones lost were the last in the list rather than
  the least useful.
- A limit **nobody chose**. Replies were capped at 1,024 tokens by a function
  signature default, which on a reasoning model returned an empty string rather
  than a short answer.
- A setting that **looked** like it controlled something and did not.

So: floors before ceilings, priority before greed, and a report of what was
dropped rather than silence.

## What this is not

It is not compaction. Nothing here summarises, rewrites, or asks a model what
to keep. It selects, from material the caller has already ordered, and says
what it left out. Summarising is a later and much more expensive step, and
doing it before the cheap thing is measured would hide whether the cheap thing
was enough.

## Order is the caller's, not ours

Every section arrives sorted by the caller in descending relevance - search
results by score, memories by cosine distance, history by recency, which for a
conversation *is* relevance. Trimming drops from the tail of that order.

That is not the positional dropping this replaces. The defect there was
discarding by *arrival* order when arrival had nothing to do with usefulness.
Dropping the lowest-scored source, or the oldest turn, is a judgement the
caller has already made and this honours.
"""

from dataclasses import dataclass, field

# Characters per token, deliberately lower than anything measured.
#
# Calibrated against real `prompt_tokens` returned by the models actually
# served here: 4.46 for code on DeepSeek, 4.72 for code on Qwen, 6.05 for
# English prose. The densest sample sets the floor, and 4.0 sits under it, so
# this over-estimates token count for every text seen so far.
#
# The direction matters more than the accuracy. Over-estimating wastes a little
# window; under-estimating overruns it, and an overrun is a failed request
# rather than a shorter one. Re-measure with `calibrate_chars_per_token` after
# a model change - it is a property of the tokenizer, not of this code.
_CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    """Estimate a text's token cost, never lower than the true figure."""
    if not text:
        return 0
    return int(len(text) / _CHARS_PER_TOKEN) + 1


def calibrate_chars_per_token(characters: int, prompt_tokens: int) -> float:
    """Report the ratio a real request observed, for re-tuning the constant."""
    if prompt_tokens <= 0:
        raise ValueError("prompt_tokens must be positive to calibrate")
    return round(characters / prompt_tokens, 2)


@dataclass(frozen=True, slots=True)
class Section:
    """One source of prompt material, already ordered by the caller."""

    name: str
    # Descending relevance. Trimming removes from the end.
    items: tuple[str, ...]
    # Lower sorts first. Two sections may share a rank when neither should
    # starve the other.
    priority: int
    # Kept before any section takes more than its floor, so a low-priority
    # source is never erased entirely by a greedy high-priority one. This is
    # the whole reason the search payload fix worked, applied one level up.
    floor_items: int = 0
    # A source that could otherwise swallow the window on a quiet turn.
    ceiling_items: int | None = None


@dataclass(frozen=True, slots=True)
class Allocation:
    """What survived from one section, and what did not."""

    name: str
    kept: tuple[str, ...] = field(default_factory=tuple)
    dropped: int = 0
    tokens: int = 0

    @property
    def complete(self) -> bool:
        return self.dropped == 0


@dataclass(frozen=True, slots=True)
class BudgetReport:
    """What the turn spent, so a thin answer can be traced to a trim."""

    budget_tokens: int
    used_tokens: int
    allocations: tuple[Allocation, ...]

    @property
    def dropped_total(self) -> int:
        return sum(item.dropped for item in self.allocations)

    @property
    def headroom_tokens(self) -> int:
        return max(0, self.budget_tokens - self.used_tokens)

    # A single line for a trace. Silence about a trim is the thing this
    # replaces, so the report is built whether or not anything was dropped.
    def summary(self) -> str:
        parts = [
            f"{item.name}={len(item.kept)}"
            + (f"(-{item.dropped})" if item.dropped else "")
            for item in self.allocations
        ]
        return (
            f"context {self.used_tokens}/{self.budget_tokens} tokens, "
            f"{self.headroom_tokens} spare: " + " ".join(parts)
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "budget_tokens": self.budget_tokens,
            "used_tokens": self.used_tokens,
            "headroom_tokens": self.headroom_tokens,
            "dropped_total": self.dropped_total,
            "sections": {
                item.name: {
                    "kept": len(item.kept),
                    "dropped": item.dropped,
                    "tokens": item.tokens,
                }
                for item in self.allocations
            },
        }


# Text reduced to what would make two items the same thing said twice.
#
# Case and spacing only. This is identity, not meaning: it catches the same
# sentence arriving twice through different routes, and deliberately does not
# try to decide that two differently-worded sentences say the same thing. That
# judgement belongs to a model or an embedding, never to string handling, and
# guessing at it here would drop material a reader needed.
def _same_thing(text: str) -> str:
    return " ".join(text.split()).casefold()


def deduplicate(
    sections: tuple[Section, ...],
    collapse: tuple[tuple[str, str], ...],
) -> tuple[Section, ...]:
    """Drop items from one section that already appear in another.

    `collapse` names ordered pairs - (keep, drop) - so the caller states which
    copy survives rather than it falling out of section order by accident.

    **Most duplication here is not redundancy.** A promoted memory and a
    recalled remark can carry the same words and mean different things: one is
    something this application asserts, the other something the user said and
    may since have stopped meaning. The reply prompt draws that distinction
    explicitly, so collapsing the two would destroy it to save a few tokens.

    The case worth collapsing is narrow and real: a remark recalled from the
    past that is already sitting in the visible history. Recall exists to
    surface what is *not* in the window, so a hit already in it is pure
    repetition - and repetition reads as emphasis to a model, which makes it
    worse than merely wasteful.
    """
    by_name = {section.name: section for section in sections}
    dropped: dict[str, set[str]] = {}

    for keep_name, drop_name in collapse:
        keeper, loser = by_name.get(keep_name), by_name.get(drop_name)
        if keeper is None or loser is None:
            continue
        seen = {_same_thing(item) for item in keeper.items if item.strip()}
        dropped.setdefault(drop_name, set()).update(
            item for item in loser.items if _same_thing(item) in seen
        )

    if not any(dropped.values()):
        return sections

    return tuple(
        section
        if not dropped.get(section.name)
        else Section(
            name=section.name,
            items=tuple(
                item for item in section.items if item not in dropped[section.name]
            ),
            priority=section.priority,
            floor_items=section.floor_items,
            ceiling_items=section.ceiling_items,
        )
        for section in sections
    )


def _ordered(sections: tuple[Section, ...]) -> list[Section]:
    # Stable, so equal priorities keep the caller's declaration order.
    return sorted(sections, key=lambda section: section.priority)


def _wanted(section: Section) -> tuple[str, ...]:
    if section.ceiling_items is None:
        return section.items
    return section.items[: section.ceiling_items]


def plan(
    sections: tuple[Section, ...],
    budget_tokens: int,
    reserved_tokens: int = 0,
) -> BudgetReport:
    """Choose what fits, floors first, then by priority.

    `reserved_tokens` is space the caller has already committed elsewhere - the
    reply the model has yet to write, most obviously. Spending the whole window
    on input and leaving nothing to answer with is a failure this signature
    makes hard to reach by accident.
    """
    if budget_tokens < 0:
        raise ValueError("budget_tokens cannot be negative")

    spendable = max(0, budget_tokens - max(0, reserved_tokens))
    taken: dict[str, list[str]] = {section.name: [] for section in sections}
    used = 0

    # Floors first, so priority decides who is squeezed rather than who exists.
    for section in _ordered(sections):
        for item in _wanted(section)[: section.floor_items]:
            cost = estimate_tokens(item)
            if used + cost > spendable:
                break
            taken[section.name].append(item)
            used += cost

    # Then the remainder, most important section first, until the window ends.
    for section in _ordered(sections):
        already = len(taken[section.name])
        for item in _wanted(section)[already:]:
            cost = estimate_tokens(item)
            if used + cost > spendable:
                # Stop this section rather than skipping to a cheaper item
                # further down it: the caller ordered these by relevance, and
                # keeping a less relevant item because it happened to be
                # shorter would quietly reverse that judgement.
                break
            taken[section.name].append(item)
            used += cost

    allocations = tuple(
        Allocation(
            name=section.name,
            kept=tuple(taken[section.name]),
            dropped=len(section.items) - len(taken[section.name]),
            tokens=sum(estimate_tokens(item) for item in taken[section.name]),
        )
        for section in sections
    )
    return BudgetReport(
        budget_tokens=spendable, used_tokens=used, allocations=allocations
    )
