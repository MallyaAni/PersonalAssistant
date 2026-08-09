"""What Scout is allowed to know about the person it is searching for.

Until now a sweep was handed a `DiscoveryProfile` — interest labels and a city —
and nothing else. Every approved fact in personal memory reached nothing, so a
query was about a two-word topic in a place rather than about anyone, and the
results were the results a stranger would get. That is upstream of ranking: a
better sort cannot rescue candidates that were never chosen with this person in
mind.

This module is the only door between personal memory and the discovery loop, and
it is deliberately narrow:

- **approved only.** A fact is read when the user approved it and it has not
  expired. A pending or superseded one is not what they agreed to be known by;
- **projections are skipped.** Interests and the locality already reach a sweep
  as typed rows, so re-reading their facts would say the same thing twice;
- **identifiers never leave.** A preferred name adds nothing to a search for a
  happening and everything to identifying who searched, so it is dropped here
  rather than trusted to a prompt not to use it;
- **screened at the door.** Every statement passes the same
  `OutboundPrivacyPolicy` that guards chat search, so a secret cannot reach even
  the local model, and a sensitive topic loses its personal framing first;
- **bounded.** A fixed number of statements of fixed length, so a long memory
  cannot grow a prompt without limit.

Nothing here reasons. It reads, filters, bounds, and hands over plain sentences.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.egress import OutboundPrivacyPolicy
from backend.discovery.events import clean_text
from backend.discovery.projection import LOCALITY_KEY, is_interest_key
from backend.models.memory import MemoryFact, SemanticMemory

# Enough to describe a person, few enough that the model reads all of them and
# that one prompt stays small. A sweep runs unattended on a local model, so the
# cost of an unbounded context is paid every week, forever.
MAX_STATEMENTS = 12
MAX_STATEMENT_CHARS = 200

# How many recent free-text memories may accompany the structured facts. Facts
# are durable and keyed; semantic memories are whatever the user last asked to
# be remembered, so they are the tail rather than the body of the context.
MAX_SEMANTIC_MEMORIES = 8

# Facts that describe how to talk to the user rather than who they are. Neither
# helps choose an event, and a name actively harms: it identifies the searcher
# in text that leaves the machine.
_EXCLUDED_FACT_KEYS = frozenset({"preferred_name", "response_style"})

# How much fact history one read scans. Bounded for the same reason the setup
# service bounds it: a user with a long memory must not turn a read into an
# unbounded one.
MAX_FACTS_READ = 60


# The current version of every approved, unexpired fact for one user.
#
# `DISTINCT ON (fact_key)` with a matching order asks PostgreSQL for one row per
# key — the newest approved version — instead of reading a whole fact history
# and discarding the superseded rows afterwards.
#
# Shared rather than written twice. Scout reads this in two places for two
# different reasons: to propose interests during setup, and to aim a sweep. Two
# copies of "approved, current, and not expired" is how a superseded fact
# eventually reaches one of them and not the other.
async def current_approved_facts(
    session: AsyncSession,
    user_id: str,
    now: datetime | None = None,
    limit: int = MAX_FACTS_READ,
) -> tuple[MemoryFact, ...]:
    moment = now or datetime.now(UTC)
    stmt = (
        select(MemoryFact)
        .where(
            MemoryFact.user_id == user_id,
            MemoryFact.approval_state == "approved",
            or_(MemoryFact.expires_at.is_(None), MemoryFact.expires_at > moment),
        )
        .order_by(MemoryFact.fact_key, MemoryFact.version.desc())
        .distinct(MemoryFact.fact_key)
        .limit(limit)
    )
    return tuple((await session.execute(stmt)).scalars().all())


@dataclass(frozen=True, slots=True)
class PersonalContext:
    """Bounded, approved, screened statements about one person."""

    statements: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.statements

    # Render for a prompt as numbered plain lines. Numbered rather than bulleted
    # so a later instruction can refer to "the facts above" and a model reading
    # its own output can tell one statement from the next.
    def render(self) -> str:
        return "\n".join(
            f"{index}. {statement}"
            for index, statement in enumerate(self.statements, start=1)
        )


class PersonalContextReader:
    """Read one user's approved memory into a bounded personal context."""

    # The session is the caller's, so this reads inside whatever transaction the
    # sweep already holds rather than opening a second one.
    def __init__(
        self,
        session: AsyncSession,
        privacy: OutboundPrivacyPolicy | None = None,
        max_statements: int = MAX_STATEMENTS,
    ) -> None:
        self.session = session
        # Screening is not optional. These statements shape text that reaches a
        # third-party search provider, so they pass the same gate a typed query
        # passes, at the point they are read rather than at the point they are
        # used.
        self.privacy = privacy or OutboundPrivacyPolicy()
        self.max_statements = max_statements

    # Read everything approved, in the order a reader would want it: durable
    # keyed facts first, then whatever was most recently remembered.
    async def read(self, user_id: str, now: datetime | None = None) -> PersonalContext:
        moment = now or datetime.now(UTC)
        statements: list[str] = []
        seen: set[str] = set()
        for raw in await self._facts(user_id, moment):
            self._admit(raw, statements, seen)
            if len(statements) >= self.max_statements:
                return PersonalContext(tuple(statements))
        for raw in await self._semantic(user_id, moment):
            self._admit(raw, statements, seen)
            if len(statements) >= self.max_statements:
                break
        return PersonalContext(tuple(statements))

    # Screen, bound, and deduplicate one candidate statement in place. A blocked
    # statement is dropped silently and never logged: the whole point of the
    # block is that its text must not be repeated anywhere.
    def _admit(self, raw: str, statements: list[str], seen: set[str]) -> None:
        # The same bounding every other untrusted string in this subsystem gets.
        # It also strips control characters, which a hand-rolled whitespace
        # collapse does not — and these strings are about to enter a prompt.
        text = clean_text(raw, MAX_STATEMENT_CHARS)
        if not text:
            return
        screened = self.privacy.sanitize(text)
        if not screened.allowed or not screened.query:
            return
        identity = screened.query.casefold()
        if identity in seen:
            return
        seen.add(identity)
        statements.append(screened.query)

    # The approved, unexpired, non-projection facts, newest version of each key.
    async def _facts(self, user_id: str, moment: datetime) -> list[str]:
        rows = await current_approved_facts(self.session, user_id, moment)
        statements: list[str] = []
        for row in rows:
            key = row.fact_key
            if key in _EXCLUDED_FACT_KEYS or key == LOCALITY_KEY:
                continue
            if is_interest_key(key):
                continue
            statements.append(_as_sentence(key, row.value))
        return statements

    # The free-text memories the user asked to be remembered, most recent first.
    async def _semantic(self, user_id: str, moment: datetime) -> list[str]:
        rows = (
            (
                await self.session.execute(
                    select(SemanticMemory)
                    .where(
                        SemanticMemory.user_id == user_id,
                        or_(
                            SemanticMemory.expires_at.is_(None),
                            SemanticMemory.expires_at > moment,
                        ),
                    )
                    .order_by(SemanticMemory.created_at.desc(), SemanticMemory.id)
                    .limit(MAX_SEMANTIC_MEMORIES)
                )
            )
            .scalars()
            .all()
        )
        return [row.content for row in rows if row.content]


# Say a keyed fact the way a person would. The key carries the meaning for a
# bare value — "dog_name" and "Biscuit" are only a fact together — while a value
# that already repeats its key reads as a sentence on its own.
def _as_sentence(fact_key: str, value: str) -> str:
    label = fact_key.replace("_", " ").strip()
    text = (value or "").strip()
    if not label or not text:
        return text
    if label.casefold() in text.casefold():
        return text
    return f"{label}: {text}"
