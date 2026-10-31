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
import logging
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol

logger = logging.getLogger(__name__)

from backend.agents.scout.aiming import AimPlanner
from backend.agents.scout.describing import EventDescriber, Readable
from backend.agents.scout.reranking import MemoryReranker
from backend.agents.scout.seeing import PictureCaptioner
from backend.config.settings import settings
from backend.core.interfaces import (
    RerankProvider,
    SearchProvider,
    TextWriter,
    VisionProvider,
)
from backend.discovery.decision_log import build_decision
from backend.discovery.digest import MAX_EVENTS_IN_MESSAGE
from backend.discovery.errors import DiscoveryError
from backend.discovery.events import DiscoveredEvent, EventSource, FeedError
from backend.discovery.familiarity import FamiliarItemRepository, FamiliarityFilter
from backend.discovery.feedback_loop import (
    MAX_REPEAT_SENDS,
    REPEAT_RECENCY_DAYS,
    adjusted_strengths,
    last_send_dates,
    reacted_finds,
    send_counts,
    reaction_statements,
)
from backend.discovery.fetching import (
    DEFAULT_RUN_REQUEST_BUDGET,
    RequestBudget,
    fetch_feed,
)
from backend.discovery.notable import NotableSelector
from backend.discovery.novelty import (
    EMBEDDING_DIMENSIONS,
    NoveltyFilter,
    ScoredCandidate,
    SeenItemRepository,
)
from backend.discovery.personal_context import PersonalContext, PersonalContextReader
from backend.discovery.precision import PrecisionRanker
from backend.discovery.relevance import (
    MAX_SELECTED,
    MAX_UNDATED,
    RankedCandidate,
    RelevanceRanker,
    candidate_text,
    cap_by_lead_time,
    cosine_similarity,
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


# The interest a candidate matches best by cosine, whatever it was attributed
# as. A find is shown because it matches an interest, so this is the handle the
# spread uses to keep a digest from being eight of the same one.
def _best_interest_label(
    embedding: list[float] | None,
    interest_vectors: dict[str, list[float]],
) -> str | None:
    best_label: str | None = None
    best_similarity = -1.0
    for label, vector in interest_vectors.items():
        similarity = cosine_similarity(embedding or [], vector)
        if similarity > best_similarity:
            best_label, best_similarity = label, similarity
    return best_label


# The interest a candidate is grouped under for the spread: its confident
# attribution when it has one, the cosine-nearest interest otherwise.
#
# `precision.order` re-decides which interest a find matches and names it only
# when the margin holds (the "near-tie is not a match" rule), so that
# attribution is the handle to spread by. Raw cosine was the old handle, and
# cosine clusters near-ties: a jazz soirée and a wine festival can both sit
# a hair from Line Dancing, so every find grouped under one label and a digest
# that should have had variety came back as eight of the same thing. A find
# with no confident attribution is grouped by nearest cosine so the fallback
# still has something to hold on to.
def _spread_interest_of(
    item: RankedCandidate, interest_vectors: dict[str, list[float]]
) -> str | None:
    if item.matched_interest:
        return item.matched_interest
    return _best_interest_label(item.candidate.embedding, interest_vectors)


# Spread a ranked shortlist across the user's interests before the digest is
# cut, quality first. The input is already ranked by the caller and has passed
# eligibility, so this only reorders — the top find of each distinct interest
# comes first, in the rank order the caller chose, then everything else in that
# same order fills the rest. A digest of eight must not be eight of the same
# thing, but it must never reach below the ranker's floor to make room for an
# interest with no quality find either: what is not in the shortlist is not
# added, and what is added is only reordered.
def _spread_by_interest(
    shortlist: tuple[RankedCandidate, ...],
    interest_vectors: dict[str, list[float]],
    limit: int,
    undated_limit: int,
    now: datetime | None = None,
) -> tuple[RankedCandidate, ...]:
    if not shortlist:
        return shortlist
    moment = now or datetime.now(UTC)
    # The top find of each distinct interest, in the rank order the caller
    # chose (so the overall best still leads), then everything else behind it
    # in that same order.
    first_by_interest: dict[str, RankedCandidate] = {}
    for item in shortlist:
        label = _spread_interest_of(item, interest_vectors)
        if label is not None and label not in first_by_interest:
            first_by_interest[label] = item
    leading = set(id(item) for item in first_by_interest.values())
    spread = list(first_by_interest.values())
    spread.extend(item for item in shortlist if id(item) not in leading)
    return cap_by_lead_time(tuple(spread), moment, limit, undated_limit)


# Only what a sweep needs from the embedding provider, so the runner can be
# tested without one and swapped without touching this module. The provider is
# synchronous, so calls are moved off the event loop rather than awaited.
class EmbeddingClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


# How a configured feed becomes something that can be read.
class AdapterFactory(Protocol):
    def __call__(
        self,
        source: "FeedSource",
        budget: RequestBudget,
        timezone: str | None = None,
    ) -> EventSource: ...


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
    # What the ranker considered and why, chosen and rejected alike. Recorded so
    # the reactions collected on the message can later be joined to the decision
    # that produced it; a thumb with no record of what it beat teaches nothing.
    decision: dict[str, Any] | None = None

    # The persisted form. Deliberately not the model's output: a digest is
    # assembled from typed records so a feed cannot inject text that later
    # reads as instructions.
    def to_digest_json(self) -> str:
        return json.dumps(
            {
                # Version 2 stores the same fields for both sections. A resumed
                # run rebuilds its message from this record alone, and the
                # notable section previously lost its score, its matched
                # interest and its end date — enough to render a different
                # message than the one the sweep produced.
                "version": 2,
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
                        # Kept so a resumed run and a later preview can still
                        # say what picture the find published.
                        "media_url": item.event.media_url,
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
                        "ends_at": (
                            item.event.ends_at.isoformat()
                            if item.event.ends_at
                            else None
                        ),
                        "place": item.event.place,
                        "url": item.event.url,
                        "summary": item.event.summary,
                        "media_url": item.event.media_url,
                        # The score here is unlikeness, not interest. Kept in
                        # its own field on the candidate so a reader cannot
                        # mistake it for a match score.
                        "score": round(item.score, 4),
                        "matched_interest": None,
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
                media_url=item.get("media_url"),
            )
        )
    return tuple(events)


# Rebuild both sections of a persisted digest, so a run that crashed after
# saving but before delivering resumes with the message it already decided on.
#
# This is what makes the save-before-deliver rule real. Re-sweeping would be
# worse than wasteful: the first sweep recorded its finds as seen and announced,
# so novelty would return an empty digest, and the resumed run would overwrite
# the saved one with nothing.
def candidates_from_digest(
    digest_json: str,
) -> tuple[tuple[RankedCandidate, ...], tuple[RankedCandidate, ...]]:
    try:
        payload = json.loads(digest_json)
    except (TypeError, ValueError) as exc:
        raise DiscoveryError("Stored digest is not readable JSON.") from exc
    if not isinstance(payload, dict):
        raise DiscoveryError("Stored digest is not an object.")
    return (
        _ranked_items(payload.get("selected")),
        _ranked_items(payload.get("notable")),
    )


# One digest section as typed candidates. The embedding is not stored — it was
# only needed to rank — so a rebuilt candidate carries none, which is correct
# for rendering and delivery.
def _ranked_items(items: object) -> tuple[RankedCandidate, ...]:
    if not isinstance(items, list):
        return ()
    rebuilt: list[RankedCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            score = float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        matched = item.get("matched_interest")
        rebuilt.append(
            RankedCandidate(
                candidate=ScoredCandidate(
                    event=DiscoveredEvent(
                        source_id=str(item.get("source_id", "")),
                        external_id=str(item.get("external_id", "")),
                        title=str(item.get("title", "")),
                        starts_at=_parse_moment(item.get("starts_at")),
                        ends_at=_parse_moment(item.get("ends_at")),
                        place=item.get("place"),
                        url=item.get("url"),
                        summary=item.get("summary"),
                        media_url=item.get("media_url"),
                    ),
                    embedding=None,
                ),
                score=score,
                matched_interest=str(matched) if matched else None,
            )
        )
    return tuple(rebuilt)


# What the describer's transcribed dates mean for a find: whether it is
# already over, and whether an undated event just became dated.
#
# The same arithmetic-over-model rule _make_readable already applies to
# deadlines, extended to event dates. The describer only transcribes what the
# page states; whether that date has passed is decided here, in code, because
# an audit found every selected web find undated - a county fair was sent
# five days after it ended, and no clock we held could rule it out.
#
# A find with a stated start stops being undated: it can hold a calendar
# entry, show a date in the digest, and compete as dated in later caps
# instead of riding the undated allowance. Midnight UTC exactly is the
# pipeline's one convention for "a date with no stated time" - search
# extraction and ICS date values already produce it, and _format_when
# renders it as a bare date. This first used noon to keep the day ahead of
# western clocks, which broke that convention: two real digests announced
# an all-day happening "at 8:00am", a clock nobody published.
def apply_described_dates(
    event_starts_at: datetime | None,
    described: Readable,
    today: date,
) -> tuple[bool, datetime | None]:
    last_day = described.ends_on or described.starts_on
    if last_day is not None and last_day < today:
        return False, event_starts_at
    starts_at = event_starts_at
    if starts_at is None and described.starts_on is not None:
        starts_at = datetime.combine(described.starts_on, time(0, 0), tzinfo=UTC)
    return True, starts_at


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
        # The two model roles this sweep needs are not interchangeable.
        # Describing a find is prose and wants the best model available;
        # aiming and reranking answer into schemas this application owns and
        # need an engine that enforces them. Passing one client for both is
        # how a main-model promotion silently breaks half a sweep. Defaults
        # to `writer`, so a caller that has only one still works.
        structured_writer: TextWriter | None = None,
        search_budget: SearchBudget | None = None,
        is_operator: bool = False,
        search_limit: int | None = None,
        cross_encoder: RerankProvider | None = None,
        # The model that sees. Optional so a sweep with no vision runtime -
        # and every test that does not exercise pictures - behaves exactly as
        # it did before pictures were read.
        vision: VisionProvider | None = None,
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
        structured = structured_writer or writer
        # Only the selected finds are described, so the model runs a handful of
        # times per sweep rather than once per candidate. The best prose model
        # writes first - this text reaches a person's phone, and a 4B's
        # descriptions read small - with its answer held to the schema by
        # validation in the describer; the grammar engine is the fallback for
        # an answer that does not survive it, and the judge of the focused
        # location question.
        self.describer = EventDescriber(writer, structured)
        # Reads a selected find's poster before it is described. Constructed
        # even without a provider so the call site has one shape; caption()
        # returns nothing when there is nothing to see with.
        self.pictures = PictureCaptioner(vision)
        # What memory knows about the person this sweep is for. Reading it is
        # the whole reason a query can be about someone rather than about a
        # topic; without it both stages below fall back to bare labels.
        # Descriptions of the person's images are left out: they are records
        # of what a picture shows, not facts about who they are, and in a
        # bounded context they crowd out the durable preferences a sweep is
        # supposed to rank by. The same exclusion the group taste projection
        # makes.
        from backend.memory.purposes import VISUAL_ANALYSIS_PURPOSE

        self.personal = PersonalContextReader(
            seen.session, exclude_purposes=(VISUAL_ANALYSIS_PURPOSE,)
        )
        # The sweep's judgement calls go to the strongest model first, with
        # the grammar engine answering whenever its JSON does not survive the
        # wrapper's check. A sweep runs in the background, so the strong
        # model's latency costs nothing anyone is waiting on - and aiming a
        # query at a person is exactly the judgement a small model does
        # smallest.
        judgement = writer
        # Turns each interest into a search subject and a ranking vector aimed
        # at that person. One model call per sweep.
        self.aiming = AimPlanner(judgement)
        # Orders the qualified shortlist against the same facts. One more call,
        # and it can only reorder what deterministic ranking already admitted.
        self.reranker = MemoryReranker(judgement)
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
        # A scheduled run records what it saw but leaves the commit to its
        # caller, so the seen rows and the saved digest land in one transaction.
        # Committing here and saving the digest afterwards leaves a window where
        # a crash records finds as announced that no digest ever contains, and
        # the next attempt sees them as already shown.
        commit_seen: bool = True,
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
        events, failed = await self._collect(
            user_id,
            configured,
            budget,
            primary.timezone if primary else None,
        )

        # Read once and used twice: the same approved facts aim the queries and
        # order the result. Deliberately the same context, so a sweep cannot
        # search for one person and rank for another.
        context = await self._personal_context(user_id, moment)
        # What they reacted to is a fact about them like any approved
        # statement, and the model stages weigh it as one: a thumbs-down on
        # the winery evening is judgement no strength arithmetic reaches.
        reacted = await reacted_finds(self.seen.session, user_id)
        if reacted:
            context = PersonalContext(
                statements=context.statements + reaction_statements(reacted)
            )
        aim = await self._aim(profile, context, primary)

        events = events + await self._search_events(user_id, profile, budget, aim, moment)

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
            # Stored strengths, shaded by the net thumbs each interest has
            # earned. Recomputed from history every sweep rather than written
            # back, so the stored value stays the person's own setting.
            interest_strengths=adjusted_strengths(
                {interest.label: interest.strength for interest in profile.interests},
                reacted,
            ),
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
        # Memory orders the whole shortlist — a wider cut than the digest, so a
        # model that reorders a bad day cannot silently drop an entire interest
        # from it. Then the digest is spread across interests and cut: the top
        # find of each interest leads in the memory order (quality first), the
        # rest fills behind it, and nothing below the ranker's floor is added.
        interest_vectors = ranker.interest_vectors
        ordered = await self._order(
            shortlist,
            context,
            moment,
            limit * SHORTLIST_FACTOR,
            undated_limit=MAX_UNDATED * SHORTLIST_FACTOR,
        )
        selected = _spread_by_interest(
            ordered, interest_vectors, limit, MAX_UNDATED, now=moment
        )
        # A thin novel side does not mean a silent day: fill what is left with
        # the best still-upcoming finds this account was already offered.
        selected = await self._repeat_fill(
            user_id, selected, ranker, limit, moment
        )

        # A sweep may rank wider than a message may carry, but only what the
        # message carries may be described and recorded as announced. Capping
        # here, before description and before the seen rows are written, is what
        # keeps "announced" true: previously eleven finds could be described and
        # marked announced while the delivery path sent five, so the other six
        # were suppressed from every later sweep without ever being seen.
        message_limit = min(limit, MAX_EVENTS_IN_MESSAGE)
        selected = selected[:message_limit]

        # Chosen before anything is recorded as seen. Afterwards these
        # candidates would be in the history they are measured against, and
        # every one of them would look perfectly familiar.
        notable: tuple[RankedCandidate, ...] = ()
        # The notable few share the digest's total bound with the matched
        # finds, so they only get the room the matched side left. A full digest
        # has none, and that is right: the section is an extra, not a second
        # digest.
        notable_room = max(0, message_limit - len(selected))
        if self.notable is not None and notable_room > 0:
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
                for item in picked[:notable_room]
            )

        # Both sections get readable titles and descriptions; an unusual find is
        # no easier to judge from a scraped page title than a matching one.
        place = None
        if primary is not None:
            place = primary.label
            if primary.region:
                place = f"{primary.label}, {primary.region}"
        # The same approved context that aimed the queries and ordered the
        # shortlist. Deliberately the same, for the reason stated where it is
        # read: a sweep must not search for one person and screen for another.
        facts = context.render()
        selected = await self._make_readable(selected, budget, moment, place, facts)
        notable = await self._make_readable(notable, budget, moment, place, facts)

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
            if commit_seen:
                await self.seen.session.commit()

        return SweepResult(
            selected=selected,
            candidate_count=len(events),
            novel_count=len(novel),
            requests_spent=budget.spent,
            failed_sources=failed,
            hidden_count=hidden_count,
            notable=notable,
            # Built from the shortlist rather than from what was sent, because
            # the rejected candidates are the half that a reaction alone can
            # never supply. Both sections count as sent: an unusual find is in
            # front of the person exactly as a matched one is.
            decision=build_decision(
                shortlist=shortlist,
                selected=(*selected, *notable),
                interests=tuple(aim.vector_texts()),
                locality=primary.label if primary else None,
                decided_at=moment,
            ),
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
        place: str | None = None,
        facts: str = "",
    ) -> tuple[RankedCandidate, ...]:
        today = (now or datetime.now(UTC)).date()
        readable: list[RankedCandidate] = []
        for item in selected:
            event = item.event
            source = event.summary or await self._page_text(event.url, budget)
            # The poster is read before the page is described, so a listing
            # whose text omits the date or venue still gives the describer
            # something that states them. It shares the sweep's request budget
            # and is skipped whenever that budget is spent.
            caption = await self.pictures.caption(event.media_url, budget)
            if caption is not None:
                source = f"{caption}\n\n{source}" if source else caption
            described = await self.describer.describe(
                event.title, source, today, place, event.url, facts
            )
            # The page is a directory of many happenings, not one. A find
            # described off a listing names an event its link cannot honor -
            # a delivered "Paint & Sip" linked a city-wide search instead.
            if described.lists_many:
                continue
            # The page says this happens somewhere else. Snippet-level region
            # checks miss whatever the snippet omits; the page is where the
            # real location lives, and this is the only stage that reads it.
            if described.located_elsewhere:
                continue
            # The page states who it is for and an approved fact rules this
            # person out. Ranking cannot reach this: an embedding of an
            # interest sits just as close to an event that excludes the person
            # holding it, and the reranker was measured refusing to act on the
            # question at all. Set only when the judge could quote the page's
            # own words, so a restriction it inferred cannot drop anything.
            if described.audience_rules_out:
                continue
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
            keep, starts_at = apply_described_dates(event.starts_at, described, today)
            if not keep:
                continue
            # A stated end is what keeps a multi-day find alive on its second
            # day. The page's end date is inclusive, so it becomes the exclusive
            # instant the rest of the pipeline compares against: a festival
            # ending on the 5th is over at midnight on the 6th.
            ends_at = event.ends_at
            if (
                ends_at is None
                and described.ends_on is not None
                and (
                    described.starts_on is None
                    or described.ends_on >= described.starts_on
                )
            ):
                ends_at = datetime.combine(
                    described.ends_on + timedelta(days=1),
                    time.min,
                    tzinfo=UTC,
                )
            readable.append(
                RankedCandidate(
                    candidate=ScoredCandidate(
                        event=replace(
                            event,
                            title=described.title,
                            summary=described.description,
                            starts_at=starts_at,
                            ends_at=ends_at,
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
        timezone: str | None = None,
    ) -> tuple[tuple[DiscoveredEvent, ...], tuple[str, ...]]:
        collected: list[DiscoveredEvent] = []
        failed: list[str] = []
        for source in configured:
            if budget.remaining <= 0:
                failed.append(source.id)
                continue
            # An ICS time with no TZID is a wall-clock time in the venue's own
            # zone. Defaulting it to UTC shifted every such listing by the
            # offset — a 7pm class in Arlington arrived as 3pm.
            adapter = self.adapter_factory(source, budget, timezone)
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

    # Order the shortlist against approved memory. Returns the full order, not
    # a cut, so the caller can spread it across interests and then cap: a model
    # that reordered a shortlist and also decided what fits would let a bad day
    # silently drop whole interests from the digest. With the model path off or
    # unavailable this is the plain deterministic order.
    async def _order(
        self,
        shortlist: tuple[RankedCandidate, ...],
        context: PersonalContext,
        now: datetime,
        limit: int,
        undated_limit: int = MAX_UNDATED,
    ) -> tuple[RankedCandidate, ...]:
        if not settings.DISCOVERY_MEMORY_RERANK_ENABLED:
            return shortlist
        try:
            return await self.reranker.order(
                shortlist, context, now=now, limit=limit, undated_limit=undated_limit
            )
        except Exception:
            return shortlist

    # Fill a thin digest with the best still-upcoming finds already suggested,
    # so a day with nothing new does not go silent. Novelty still decides what
    # is new; this only fills what novelty left empty, re-scoring announced
    # items against the same interests so only the still-relevant ones return,
    # and spreading the result so a repeated cluster does not dominate.
    #
    # A find already sent `MAX_REPEAT_SENDS` times is not offered again. Without
    # that bound this is not a fallback but the digest itself: novelty suppresses
    # everything already seen, so on an account with any history the novel side
    # is empty most days and the fill supplies every line. What the person then
    # receives is the same handful of events for as long as they remain
    # upcoming, which reads as an assistant that has stopped looking.
    async def _repeat_fill(
        self,
        user_id: str,
        selected: tuple[RankedCandidate, ...],
        ranker: RelevanceRanker,
        limit: int,
        now: datetime | None = None,
    ) -> tuple[RankedCandidate, ...]:
        # The fill is only needed while the digest has room. A message carries
        # `MAX_EVENTS_IN_MESSAGE` finds in total, so filling past that spends
        # queries on finds the cap will drop.
        if len(selected) >= min(limit, MAX_EVENTS_IN_MESSAGE):
            return selected
        moment = now or datetime.now(UTC)
        try:
            repeats = await self.seen.announced_candidates(user_id, now=moment)
        except Exception:
            return selected
        if not repeats:
            return selected
        chosen = {item.candidate.digest for item in selected}
        # Read once per sweep rather than per candidate: one grouped query on an
        # indexed column, against a table that only this fill needs to consult.
        try:
            already_sent = await send_counts(self.seen.session, user_id)
        except Exception:
            # The cap is a quality bound, not a safety one. Losing it must not
            # cost the person their digest, so an unreadable table falls back to
            # the unbounded behaviour rather than to an empty fill.
            already_sent = {}
        # Recency is read the same way and fails the same way: a find sent
        # within the recency window is not re-offered even if it has not hit its
        # cap, so the same event does not come back on consecutive quiet days.
        try:
            last_sent = await last_send_dates(self.seen.session, user_id)
        except Exception:
            last_sent = {}
        window = moment - timedelta(days=REPEAT_RECENCY_DAYS)
        candidates = tuple(
            c
            for c in repeats
            if c.digest not in chosen
            and already_sent.get(c.digest, 0) < MAX_REPEAT_SENDS
            and not (
                last_sent.get(c.digest) is not None
                and last_sent.get(c.digest) >= window
            )
        )
        if not candidates:
            return selected
        ranked = ranker.rank(
            candidates, now=moment, limit=limit, undated_limit=MAX_UNDATED
        )
        combined = tuple(selected) + ranked
        return _spread_by_interest(
            combined, ranker.interest_vectors, limit, MAX_UNDATED, now=moment
        )

    # Search for what no feed publishes. Failure here is silent by design: a
    # sweep with working feeds must not fail because a search provider is down.
    async def _search_events(
        self,
        user_id: str,
        profile: DiscoveryProfile,
        budget: RequestBudget,
        aim: SweepAim,
        now: datetime | None = None,
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
                # The shared pool meters Tavily's free credits. When those are
                # gone the pool reads spent even though a later rung — Google,
                # prepaid and metered by its own quota — can still serve. So a
                # spent pool alone must not stop a sweep; only the account's own
                # daily or monthly window is a hard stop.
                daily = await self.search_budget.remaining_today(
                    user_id, self.is_operator
                )
                monthly = await self.search_budget.remaining(
                    user_id, self.is_operator, override=self.search_limit
                )
                if daily <= 0 or monthly <= 0:
                    return ()
                granted = wanted

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
            now=now,
        )
        try:
            return await source.fetch()
        except Exception as exc:
            # A search infrastructure failure must not look like "the internet
            # had nothing" - an empty digest is indistinguishable from an
            # outage, which is how three days of silent zero-find sweeps went
            # unremarked. Log it, and remember it so the run can name the cause.
            logger.warning(
                "discovery_search_source_failed user=%s error=%s",
                user_id,
                exc,
                exc_info=True,
            )
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
        # A provider that changes model or truncates its output can return a
        # vector of the wrong width. Such a vector cannot be stored, and mixing
        # widths makes every cosine comparison silently compare only the prefix
        # it happens to share. Degrade that candidate to identity-only novelty
        # rather than ranking it against a vector it does not fit.
        return [
            vector
            if vector is not None and len(vector) == EMBEDDING_DIMENSIONS
            else None
            for vector in vectors
        ]


def _adapter_for(
    source: FeedSource,
    budget: RequestBudget,
    timezone: str | None = None,
) -> EventSource:
    if source.kind == "ics":
        # The venue's zone, not this machine's and not UTC. A floating time in
        # a calendar feed means the wall clock where the calendar is kept.
        return IcsEventSource(
            source.id,
            source.url,
            default_timezone=timezone or "UTC",
            budget=budget,
        )
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
