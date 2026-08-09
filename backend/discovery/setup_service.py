"""Turn an unconfigured discovery agent into a configured one.

Setup is the only place in this subsystem that uses search, and it uses it to
find *sources* rather than events — see `feed_finder` for why that distinction
carries the free-tier and correctness properties the weekly loop depends on.

Nothing here writes to the profile. Both halves return proposals; accepting one
is a separate, explicit call, which is what records `user_explicit` provenance
rather than inferring it.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.interfaces import SearchProvider
from backend.discovery.feed_finder import FeedCandidate, FeedFinder
from backend.discovery.interest_finder import (
    MAX_PROPOSALS,
    InterestProposal,
    propose_interests,
)
from backend.discovery.link_graph import MAX_RUNS_READ, LinkGraphExpander
from backend.discovery.personal_context import current_approved_facts
from backend.discovery.runs import DiscoveryRunRepository
from backend.discovery.sources_repository import DiscoverySourceRepository
from backend.discovery.types import DiscoveryProfile

# Only approved facts are read, and only their current version: the shared
# reader in `personal_context` owns that rule for the whole subsystem. The
# memory subsystem distinguishes what the user confirmed from what was
# inferred, and proposing interests from inferences would build a profile out
# of things they never said.

# How much memory one proposal pass reads. Bounded because this runs while the
# user waits.
MAX_FACTS_SCANNED = 60


class DiscoverySetupService:
    """Propose feeds and interests for a user who has configured neither."""

    def __init__(self, session: AsyncSession, search: SearchProvider) -> None:
        self.session = session
        self.finder = FeedFinder(search)

    async def suggest_feeds(
        self, profile: DiscoveryProfile
    ) -> tuple[FeedCandidate, ...]:
        primary = profile.active_locality
        if primary is None:
            # Without a place, a query would either be useless or would have to
            # guess where the user lives. Neither is acceptable.
            return ()
        return await self.finder.suggest(
            primary.label,
            tuple(interest.label for interest in profile.interests),
        )

    # Propose sources from where this user's own past finds pointed.
    #
    # Separate from `suggest_feeds` because it needs no search and no locality:
    # it reads history the user already has. That makes it the only proposal
    # path that keeps working once the metered allowance is spent, and the only
    # one that improves as the agent runs rather than only at setup.
    async def suggest_from_link_graph(self, user_id: str) -> tuple[FeedCandidate, ...]:
        runs = await DiscoveryRunRepository(self.session).recent_runs(
            user_id, limit=MAX_RUNS_READ
        )
        known = await DiscoverySourceRepository(self.session).list_sources(user_id)
        return await LinkGraphExpander().propose(
            tuple(str(run.get("digest_json") or "") or None for run in runs),
            tuple(source.url for source in known),
        )

    async def suggest_interests(
        self, user_id: str, profile: DiscoveryProfile, limit: int = MAX_PROPOSALS
    ) -> tuple[InterestProposal, ...]:
        records = await self._approved_facts(user_id)
        return propose_interests(records, profile, limit=limit)

    # Read the current approved version of each fact. Corrections create a new
    # version rather than mutating the old one, so taking the highest version
    # per key is what keeps a superseded value from being proposed as current.
    # Expired facts are excluded for the same reason: retention already decided
    # they should no longer be acted on.
    async def _approved_facts(self, user_id: str) -> tuple[dict[str, object], ...]:
        rows = await current_approved_facts(
            self.session, user_id, limit=MAX_FACTS_SCANNED
        )
        return tuple(
            {
                "value": row.value,
                "content": row.value,
                "source": f"memory:{row.fact_type}",
                # Carried so the finder can tell what a fact *is*. Without it
                # every approved fact looked alike, and a home locality and a
                # preferred name were offered as things to be interested in.
                "fact_key": row.fact_key,
            }
            for row in rows
        )
