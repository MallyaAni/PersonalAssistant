"""Write a discovery profile edit into memory as an approved fact.

The profile service depends on the narrow `FactRecorder` protocol rather than on
memory itself, so editing a place cannot become a path to reading someone's
conversations. This is the only implementation, and it can do exactly one thing.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.projection import ProjectedFact
from backend.memory.repository import MemoryRepository


class MemoryFactRecorder:
    """Record a profile edit as an approved, provenanced memory fact."""

    # Retain the request-scoped session used for atomic memory operations.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Approve one profile edit as a versioned personal-memory fact.
    async def record(self, user_id: str, fact: ProjectedFact) -> None:
        # Approved rather than proposed: the user typed this into their own
        # profile, which is a stronger signal than anything inferred from chat.
        # Provenance says so, so a later reader can tell it apart from an
        # approved inference.
        await MemoryRepository(self.session).approve_fact(
            user_id=user_id,
            fact_type=fact.fact_type,
            fact_key=fact.fact_key,
            value=fact.value,
            purpose=fact.purpose,
            source_conversation_id=None,
            # A profile edit has no conversation trace, but uniqueness is keyed
            # on one. A fresh identifier per edit is what makes a correction a
            # new superseding version rather than a rejected duplicate.
            source_trace_id=str(uuid.uuid4()),
            expires_at=None,
            extra_data={"source": "discovery_profile_edit"},
        )

    # Clear the complete fact history when its profile value is removed.
    async def forget(self, user_id: str, fact_key: str) -> None:
        await MemoryRepository(self.session).clear_fact_key(user_id, fact_key)
