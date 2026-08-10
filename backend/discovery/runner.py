"""The body of one scheduled discovery sweep.

Stage 3 supplied the durable machinery — leases, exactly-once slots, write-once
delivery. This is the work that machinery carries: read the user's feeds within
a fixed request budget, drop what they have already been shown, rank what
remains against their approved interests, and persist a digest.

The order is deliberate. Novelty is decided before ranking so a repeat cannot
consume a slot in the digest, and the digest is persisted before anything tries
to deliver it, so a crash between the two leaves work to resume rather than work
to redo.

What the user has approved being known by is read once, before any query is
spent, and used at both ends of the sweep: `aiming.py` turns it into the subject
of each search and the vector each candidate is scored against, and
`reranking.py` orders the qualified shortlist against the same facts. Reading it
once is what stops a sweep searching for one person and ranking for another.
Every part of that degrades to the bare interest labels, so a sweep with no
model, no memory, or an unreachable runtime does exactly what it did before.

Nothing here reaches outward. A sweep writes a digest; delivering it is a
separate, permissioned stage.
"""

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from backend.agents.scout.aiming import AimPlanner
from backend.agents.scout.describing import EventDescriber
from backend.agents.scout.reranking import MemoryReranker
from backend.config.settings import settings
from backend.core.interfaces import RerankProvider, SearchProvider, TextWriter
from backend.discovery.errors import DiscoveryError
from backend.discovery.events import DiscoveredEvent, EventSource, FeedError
from backend.discovery.familiarity import FamiliarItemRepository, FamiliarityFilter
from backend.discovery.fetching import (
    DEFAULT_RUN_REQUEST_BUDGET,
    RequestBudget,
    fetch_feed,
)
from backend.discovery.notable import NotableSelector
from backend.discovery.novelty import NoveltyFilter, ScoredCandidate, SeenItemRepository
from backend.discovery.personal_context import PersonalContext, PersonalContextReader
from backend.discovery.precision import PrecisionRanker
from backend.discovery.relevance import (
    MAX_SELECTED,
    MAX_UNDATED,
    RankedCandidate,
    RelevanceRanker,
    candidate_text,
    cap_by_lead_time,
)
from backend.discovery.search_budget import SearchBudget
from backend.discovery.sources.ics import IcsEventSource
from backend.discovery.sources.links import LinkPageEventSource
from backend.discovery.sources.rss import RssEventSource
from backend.discovery.sources.web import WebEventSource
from backend.discovery.sources_repository import DiscoverySourceRepository, FeedSource
from backend.discovery.summarize import text_from_html
from backend.discovery.types import DiscoveryProfile, Locality, SweepAim
from backend.discovery.url_dates import deadline_has_passed

# How much wider than the digest the shortlist is ranked before the model orders
# it. Two gives the re-ranker a real choice — sixteen finds for an eight-item
# digest — while a sweep that found fewer than that behaves exactly as it did
# before, because there is nothing extra to drop.
SHORTLIST_FACTOR = 2


# Only what a sweep needs from the embedding provider, so the runner can be
# tested without one and swapped without touching this module. The provider is
# synchronous, so calls are moved off the event loop rather than awaited.
class EmbeddingClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


# How a configured feed becomes something that can be read.
class AdapterFactory(Protocol):
    def __call__(self, source: "FeedSource", budget: RequestBudget) -> EventSource: ...


@dataclass(frozen=True, slots=True)
class SweepResult:
    """What one sweep produced, before anything delivers it."""

    selected: tuple[RankedCandidate, ...]
    candidate_count: int
    novel_count: int
    requests_spent: int
    failed_sources: tuple[str, ...]
    # How many novel finds were dropped as already known. Reported because a
    # wrong dismissal is otherwise undiscoverable: the panel lists what was
    # dismissed, never what those dismissals removed from this sweep.
    hidden_count: int = 0
    # Finds surfaced for being unlike anything this account has been shown,
    # rather than for matching an interest. Kept as their own field so they can
    # never quietly pad the matched list.
    notable: tuple[RankedCandidate, ...] = ()

    # The persisted form. Deliberately not the model's output: a digest is
    # assembled from typed records so a feed cannot inject text that later
    # reads as instructions.
    def to_digest_json(self) -> str:
        return json.dumps(
            {
                "version": 1,
                "selected": [
                    {
                        "source_id": item.event.source_id,
                        "external_id": item.event.external_id,
                        "title": item.event.title,
                        "starts_at": (
                            item.event.starts_at.isoformat()
                            if item.event.starts_at
                            else None
                        ),
                        "ends_at": (
                            item.event.ends_at.isoformat()
                            if item.event.ends_at
                            else None
                        ),
                        "place": item.event.place,
                        "url": item.event.url,
                        "summary": item.event.summary,
                        "score": round(item.score, 4),
                        "matched_interest": item.matched_interest,
                    }
                    for item in self.selected
                ],
                "candidate_count": self.candidate_count,
                "novel_count": self.novel_count,
                "hidden_count": self.hidden_count,
                "notable": [
                    {
                        "source_id": item.event.source_id,
                        "external_id": item.event.external_id,
                        "title": item.event.title,
                        "starts_at": (
                            item.event.starts_at.isoformat()
                            if item.event.starts_at
                            else None
                        ),
                        "ends_at": None,
                        "place": item.event.place,
                        "url": item.event.url,
                        "summary": item.event.summary,
                    }
                    for item in self.notable
                ],
                "failed_sources": list(self.failed_sources),
            },
            separators=(",", ":"),
        )


# Rebuild the typed events a persisted digest describes, so stage 5 can render a
# calendar without re-fetching anything.
def events_from_digest(digest_json: str) -> tuple[DiscoveredEvent, ...]:
    try:
        payload = json.loads(digest_json)
    except (TypeError, ValueError) as exc:
        raise DiscoveryError("Stored digest is not readable JSON.") from exc
    events: list[DiscoveredEvent] = []
    for item in payload.get("selected", []):
        starts_at = _parse_moment(item.get("starts_at"))
        events.append(
            DiscoveredEvent(
                source_id=str(item.get("source_id", "")),
                external_id=str(item.get("external_id", "")),
                title=str(item.get("title", "")),
                starts_at=starts_at,
                ends_at=_parse_moment(item.get("ends_at")),
                place=item.get("place"),
                url=item.get("url"),
                summary=item.get("summary"),
            )
        )
    return tuple(events)


class DiscoveryRunner:
    """Execute one sweep for one user."""

    def __init__(
        self,
        sources: DiscoverySourceRepository,
        seen: SeenItemRepository,
        embeddings: EmbeddingClient,
        adapter_factory: AdapterFactory | None = None,
        search: SearchProvider | None = None,
        writer: TextWriter | None = None,
        search_budget: SearchBudget | None = None,
        is_operator: bool = False,
        search_limit: int | None = None,
        cross_encoder: RerankProvider | None = None,
    ) -> None:
        self.sources = sources
        self.seen = seen
        self.embeddings = embeddings
        self.novelty = NoveltyFilter(seen)
        # Different question from novelty: not "have I shown you this" but "did
        # you already know it". They diverge for anyone who has lived somewhere
        # a while.
        self.familiarity = FamiliarityFilter(FamiliarItemRepository(seen.session))
        # Surfaces the few finds unlike anything this account has been shown, so
        # the loop can return something the user never thought to ask for. Every
        # other ranking path is anchored to a stated interest and therefore can
        # only ever return more of what it already knew about.
        self.notable = NotableSelector(seen)
        # Optional second enumerator. Feeds are the source of record for
        # anything that must reach a calendar; this covers what publishes no
        # feed at all, which for a niche interest is most of it.
        self.search = search
        # Only the selected finds are described, so the model runs a handful of
        # times per sweep rather than once per candidate.
        self.describer = EventDescriber(writer)
        # What memory knows about the person this sweep is for. Reading it is
        # the whole reason a query can be about someone rather than about a
        # topic; without it both stages below fall back to bare labels.
        self.personal = PersonalContextReader(seen.session)
        # Turns each interest into a search subject and a ranking vector aimed
        # at that person. One model call per sweep.
        self.aiming = AimPlanner(writer)
        # Orders the qualified shortlist against the same facts. One more call,
        # and it can only reorder what deterministic ranking already admitted.
        self.reranker = MemoryReranker(writer)
        # Between the two: a local cross-encoder that reads each interest and
        # candidate as one sequence. Embeddings decide what qualifies, this
        # decides the order among them, the model above applies what memory
        # knows. Absent weights leave the embedding order untouched.
        self.precision = PrecisionRanker(cross_encoder)
        # Search is the one metered component here and its key belongs to the
        # operator, so an account's monthly spend is bounded independently of
        # any single run's request budget.
        self.search_budget = search_budget
        self.is_operator = is_operator
        # An operator-set monthly ceiling for this account, or None for the
        # deployment default.
        self.search_limit = search_limit
        # Injected so a sweep can be exercised end to end without a network,
        # which is what makes the "announce once" guarantee testable at all.
        self.adapter_factory = adapter_factory or _adapter_for

    async def sweep(
        self,
        user_id: str,
        profile: DiscoveryProfile,
        run_id: str | None = None,
        now: datetime | None = None,
        budget_limit: int = DEFAULT_RUN_REQUEST_BUDGET,
        limit: int = MAX_SELECTED,
        persist: bool = True,
    ) -> SweepResult:
        """Run one sweep.

        With `persist` false this is a rehearsal: nothing is recorded as seen and
        novelty is not consulted, so the same configuration can be run
        repeatedly and compared. That matters because the novelty filter is
        working correctly when a second real sweep finds nothing — which is
        exactly what makes a real sweep useless for judging output quality.
        """
        moment = now or datetime.now(UTC)
        budget = RequestBudget(limit=budget_limit)
        # Where the user actually is, which scopes both what is read and what
        # counts as already known.
        primary = profile.active_locality

        # Scoped to where the user currently is. A page of DC events is worth
        # nothing in Denver, and reading it anyway is how a digest fills with
        # things happening several hundred miles away.
        configured = await self.sources.list_sources(
            user_id,
            enabled_only=True,
            locality_label=primary.label if primary else None,
            scoped=True,
        )
        events, failed = await self._collect(user_id, configured, budget)

        # Read once and used twice: the same approved facts aim the queries and
        # order the result. Deliberately the same context, so a sweep cannot
        # search for one person and rank for another.
        context = await self._personal_context(user_id, moment)
        aim = await self._aim(profile, context, primary)

        events = events + await self._search_events(user_id, profile, budget, aim)

        candidates = await self._embed(events)
        # A rehearsal treats everything as new. Applying novelty would show an
        # empty result to anyone who had already run a real sweep, which is the
        # opposite of what a rehearsal is for.
        # A rehearsal never applies novelty, and an operator can switch it off
        # entirely. What is seen is still recorded either way, so turning it
        # back on resumes with the history intact rather than from nothing.
        suppress_seen = persist and settings.DISCOVERY_NOVELTY_ENABLED
        novel = (
            await self.novelty.novel(user_id, candidates, now=moment)
            if suppress_seen
            else candidates
        )

        # Scoped the same way, so travelling to a new place starts from nothing
        # known and everything ordinary there is a find.
        novel, hidden_count = await self.familiarity.filter_known(
            user_id, primary.label if primary else None, novel
        )

        ranker = RelevanceRanker(
            interest_vectors=await self._interest_vectors(profile, aim),
            interest_strengths={
                interest.label: interest.strength for interest in profile.interests
            },
        )
        # Ranked wider than the digest, then ordered against what memory knows.
        # Deterministic scoring still decides what is eligible; the model only
        # decides which of the eligible finds this person hears about first, and
        # the shortlist is what gives that decision anything to work with.
        shortlist = ranker.rank(
            novel,
            now=moment,
            limit=limit * SHORTLIST_FACTOR,
            undated_limit=MAX_UNDATED * SHORTLIST_FACTOR,
        )
        # Then read each pair properly. Embeddings compared the two halves
        # without ever seeing them together, which is why they cluster; this
        # reorders what they admitted and re-decides which interest to name.
        shortlist = await self.precision.order(shortlist, aim)
        selected = await self._order(shortlist, context, moment, limit)

        # Chosen before anything is recorded as seen. Afterwards these
        # candidates would be in the history they are measured against, and
        # every one of them would look perfectly familiar.
        notable: tuple[RankedCandidate, ...] = ()
        if self.notable is not None:
            # The matcher's own scores, so "would this have been selected?" is
            # answered by the thing that selects rather than by a second scorer
            # that could drift from it.
            interest_scores = {
                candidate.digest: ranker.score(candidate)[0] for candidate in novel
            }
            picked = await self.notable.select(
                user_id,
                novel,
                selected,
                now=moment,
                interest_scores=interest_scores,
            )
            notable = tuple(
                RankedCandidate(
                    candidate=item.candidate,
                    score=item.unlikeness,
                    # No interest matched, which is the point of this section.
                    matched_interest=None,
                )
                for item in picked
            )

        # Both sections get readable titles and descriptions; an unusual find is
        # no easier to judge from a scraped page title than a matching one.
        selected = await self._make_readable(selected, budget, moment)
        notable = await self._make_readable(notable, budget, moment)

        # Everything considered is recorded, but only what was selected counts
        # as announced. An item ranked out stays eligible for a later sweep,
        # while an announced one suppresses its own near-duplicates.
        #
        # A selected item is stored in its *described* form. The stored payload
        # is what a later preview, digest, or calendar file is built from, so
        # persisting the raw scraped title here would mean the description work
        # only ever existed in this function's return value.
        # Everything shown counts as announced, including the unusual few, so
        # they do not return next sweep as though they had never been sent.
        described = {
            item.candidate.digest: item.candidate for item in (*selected, *notable)
        }
        if persist:
            for candidate in novel:
                await self.seen.record_seen(
                    user_id,
                    described.get(candidate.digest, candidate),
                    announced=candidate.digest in described,
                    run_id=run_id,
                    now=moment,
                )
            await self.seen.session.commit()

        return SweepResult(
            selected=selected,
            candidate_count=len(events),
            novel_count=len(novel),
            requests_spent=budget.spent,
            failed_sources=failed,
            hidden_count=hidden_count,
            notable=notable,
        )

    # Rewrite each selection's title and summary into something a person can
    # decide on. A scraped page title names the site, not the happening, and a
    # recipient cannot judge "Official Website of Arlington County" — so this
    # runs before the digest is persisted rather than at render time.
    async def _make_readable(
        self,
        selected: tuple[RankedCandidate, ...],
        budget: RequestBudget | None = None,
        now: datetime | None = None,
    ) -> tuple[RankedCandidate, ...]:
        today = (now or datetime.now(UTC)).date()
        readable: list[RankedCandidate] = []
        for item in selected:
            event = item.event
            source = event.summary or await self._page_text(event.url, budget)
            described = await self.describer.describe(event.title, source, today)
            # Read before the model is trusted with it. The describe call does
            # ask — "Today is {today}, set already_happened when a deadline has
            # gone by" — and a real digest still offered a vote that closed on
            # August 3 to someone reading it on August 10. A stated deadline is
            # arithmetic, and arithmetic belongs here rather than in a 4B model.
            if deadline_has_passed(source, today) or deadline_has_passed(
                event.summary, today
            ):
                continue
            if described.already_happened:
                # The page says it is over. Nothing else in the sweep could know
                # that: these are the finds with no published start, so no clock
                # of ours can rule them out, and a digest announcing a deadline
                # that has passed is the clearest possible sign that whatever
                # sent it is not paying attention.
                continue
            readable.append(
                RankedCandidate(
                    candidate=ScoredCandidate(
                        event=replace(
                            event,
                            title=described.title,
                            summary=described.description,
                        ),
                        embedding=item.candidate.embedding,
                    ),
                    score=item.score,
                    matched_interest=item.matched_interest,
                )
            )
        return tuple(readable)

    # The destination's own prose, for a find that arrived without any.
    #
    # Only for what has already been selected, so this reads a handful of pages
    # rather than every candidate, and it spends the sweep's own budget so a
    # digest can never cost more requests than the run was allowed. A failure
    # leaves the find exactly as it was: unreadable is better than absent.
    async def _page_text(
        self, url: str | None, budget: RequestBudget | None
    ) -> str | None:
        if not url or budget is None or budget.remaining <= 0:
            return None
        try:
            return text_from_html(await fetch_feed(url, budget=budget))
        except Exception:
            return None

    # Read every configured feed. One broken source degrades that source rather
    # than failing the sweep, because a user with five feeds should still hear
    # about the four that work.
    async def _collect(
        self,
        user_id: str,
        configured: tuple[FeedSource, ...],
        budget: RequestBudget,
    ) -> tuple[tuple[DiscoveredEvent, ...], tuple[str, ...]]:
        collected: list[DiscoveredEvent] = []
        failed: list[str] = []
        for source in configured:
            if budget.remaining <= 0:
                failed.append(source.id)
                continue
            adapter = self.adapter_factory(source, budget)
            try:
                events = await adapter.fetch()
            except FeedError:
                failed.append(source.id)
                await self.sources.record_fetch(user_id, source.id, "feed_unreadable")
                continue
            await self.sources.record_fetch(user_id, source.id, None)
            collected.extend(events)
        return tuple(collected), tuple(failed)

    # What this account has approved being known by, or nothing. A sweep must
    # never fail because memory could not be read, and with both personalizing
    # stages switched off there is nothing to read it for.
    async def _personal_context(self, user_id: str, now: datetime) -> PersonalContext:
        if not (
            settings.DISCOVERY_PERSONAL_QUERIES_ENABLED
            or settings.DISCOVERY_MEMORY_RERANK_ENABLED
        ):
            return PersonalContext()
        try:
            return await self.personal.read(user_id, now=now)
        except Exception:
            return PersonalContext()

    # Aim every interest at this person, or leave them as bare labels. The
    # fallback is not a degraded mode: it is exactly how every sweep before this
    # searched and ranked.
    async def _aim(
        self,
        profile: DiscoveryProfile,
        context: PersonalContext,
        primary: Locality | None,
    ) -> SweepAim:
        labels = tuple(interest.label for interest in profile.interests)
        if not settings.DISCOVERY_PERSONAL_QUERIES_ENABLED:
            return SweepAim.from_labels(labels)
        place = primary.label if primary else ""
        if primary is not None and primary.region:
            place = f"{place}, {primary.region}"
        try:
            return await self.aiming.plan(labels, context, place)
        except Exception:
            return SweepAim.from_labels(labels)

    # Order the shortlist against approved memory and cut it to the digest's
    # size. With the model path off or unavailable this is the plain truncation
    # `RelevanceRanker.rank` would have done on its own.
    async def _order(
        self,
        shortlist: tuple[RankedCandidate, ...],
        context: PersonalContext,
        now: datetime,
        limit: int,
    ) -> tuple[RankedCandidate, ...]:
        if not settings.DISCOVERY_MEMORY_RERANK_ENABLED:
            return cap_by_lead_time(shortlist, now, limit, MAX_UNDATED)
        try:
            return await self.reranker.order(
                shortlist, context, now=now, limit=limit, undated_limit=MAX_UNDATED
            )
        except Exception:
            return cap_by_lead_time(shortlist, now, limit, MAX_UNDATED)

    # Search for what no feed publishes. Failure here is silent by design: a
    # sweep with working feeds must not fail because a search provider is down.
    async def _search_events(
        self,
        user_id: str,
        profile: DiscoveryProfile,
        budget: RequestBudget,
        aim: SweepAim,
    ) -> tuple[DiscoveredEvent, ...]:
        if self.search is None or not settings.DISCOVERY_WEB_SEARCH_ENABLED:
            return ()
        primary = profile.active_locality
        if primary is None:
            # Without a place, a query would be about nowhere in particular.
            return ()
        # Ask for this sweep's share of the month before spending any of it. A
        # reduced grant still runs — finding less beats finding nothing — and a
        # zero grant skips search while configured feeds still contribute.
        wanted = settings.DISCOVERY_WEB_QUERIES_PER_SWEEP
        granted = wanted
        if self.search_budget is not None:
            granted = await self.search_budget.reserve(
                user_id, self.is_operator, wanted, override=self.search_limit
            )
            if granted <= 0:
                return ()

        source = WebEventSource(
            source_id="web-search",
            search=self.search,
            locality=primary.label,
            region=primary.region,
            # The subject of each query, aimed at this person where memory
            # supported one and the plain interest label everywhere else.
            subjects=aim.subjects(),
            budget=budget,
            max_queries=granted,
        )
        try:
            return await source.fetch()
        except Exception:
            return ()

    # Embed candidates for both novelty and ranking, in one batch rather than
    # one call per event. An embedding failure downgrades the batch to
    # identity-only novelty rather than failing the sweep; those candidates
    # simply never outrank one that embedded.
    async def _embed(
        self, events: tuple[DiscoveredEvent, ...]
    ) -> tuple[ScoredCandidate, ...]:
        if not events:
            return ()
        texts = [
            candidate_text(event.title, event.place, event.summary) for event in events
        ]
        vectors = await self._embed_batch(texts)
        return tuple(
            ScoredCandidate(event=event, embedding=vector)
            for event, vector in zip(events, vectors, strict=True)
        )

    # The vectors a candidate is scored against.
    #
    # Embedding the bare label made the whole user representation a two-word
    # string, which is why scores clustered: a genuine concert scored 0.612
    # against "Concerts" while a lantern festival scored 0.616 against "Line
    # Dancing". Where memory supported an aimed profile, that sentence is
    # embedded instead — but the key stays the user's own label, so a digest
    # still names the interest they stated rather than a phrasing of ours.
    async def _interest_vectors(
        self, profile: DiscoveryProfile, aim: SweepAim
    ) -> dict[str, list[float]]:
        labels = [interest.label for interest in profile.interests]
        if not labels:
            return {}
        aimed = aim.vector_texts()
        vectors = await self._embed_batch([aimed.get(label, label) for label in labels])
        return {
            label: vector
            for label, vector in zip(labels, vectors, strict=True)
            if vector is not None
        }

    # The provider is synchronous, so the call moves off the event loop. A
    # failure yields one None per input, keeping positional alignment with the
    # texts the caller supplied.
    async def _embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        try:
            vectors = await asyncio.to_thread(self.embeddings.embed_texts, texts)
        except Exception:
            return [None] * len(texts)
        if len(vectors) != len(texts):
            return [None] * len(texts)
        return list(vectors)


def _adapter_for(source: FeedSource, budget: RequestBudget) -> EventSource:
    if source.kind == "ics":
        return IcsEventSource(source.id, source.url, budget=budget)
    if source.kind == "links":
        return LinkPageEventSource(source.id, source.url, budget=budget)
    return RssEventSource(source.id, source.url, budget=budget)


def _parse_moment(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
