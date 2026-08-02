import asyncio
from dataclasses import asdict
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.config.settings import settings
from backend.core.auth import authorize_path_user
from backend.core.dependencies import (
    DependencyDiscoveryFamiliar,
    DependencyDiscoveryProfileService,
    DependencyDiscoveryRunner,
    DependencyDiscoveryRuns,
    DependencyDiscoverySeenItems,
    DependencyDiscoverySetup,
    DependencyDiscoverySources,
    DependencyDiscoverySubscribers,
    DependencyPlaceResolver,
    EmbeddingDependency,
)
from backend.discovery.calendar import (
    build_calendar,
    build_vevent,
    calendar_filename,
)
from backend.discovery.delivery import describe_recipients
from backend.discovery.digest import render_message
from backend.discovery.errors import DiscoveryProfileLimitError
from backend.discovery.events import MAX_URL_CHARS
from backend.discovery.locating import (
    COARSE_DECIMALS,
    LocationLookupError,
    resolve_place,
)
from backend.discovery.novelty import ScoredCandidate
from backend.discovery.reachability import (
    calendar_base_url,
    is_reachable_from_other_devices,
)
from backend.discovery.relevance import RankedCandidate
from backend.discovery.schedule import Cadence
from backend.discovery.types import (
    MAX_LABEL_CHARS,
    MAX_RADIUS_KM,
    MAX_REGION_CHARS,
    MIN_RADIUS_KM,
)

router = APIRouter(
    prefix="/discovery/{user_id}",
    tags=["discovery"],
    dependencies=[Depends(authorize_path_user)],
)
UserId = Annotated[str, Path(min_length=1, max_length=50)]

# A subscriber's own calendar feed is addressed by an unguessable token and
# nothing else, so it cannot sit behind the owning user's path or authorization.
# This is how every calendar subscription URL works, including Apple's and
# Google's: the secret is the URL. Revoking rotates the token, which is why
# revocation and rotation are the same operation.
feed_router = APIRouter(prefix="/discovery/feed", tags=["discovery"])


class InterestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS)
    strength: int = Field(default=2, ge=1, le=3)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class LocalityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS)
    region: str | None = Field(default=None, max_length=MAX_REGION_CHARS)
    radius_km: int = Field(default=25, ge=MIN_RADIUS_KM, le=MAX_RADIUS_KM)
    timezone: str = Field(default="America/New_York", min_length=1, max_length=64)
    is_primary: bool = False

    @field_validator("label", "timezone")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


# Return the profile a discovery run would read, so the user can see exactly
# what the assistant knows about their interests and where they live.
@router.get("")
async def read_profile(
    user_id: UserId,
    service: DependencyDiscoveryProfileService,
) -> dict[str, object]:
    profile = await service.get_profile(user_id)
    return {
        "user_id": user_id,
        "interests": [asdict(interest) for interest in profile.interests],
        "localities": [asdict(locality) for locality in profile.localities],
    }


@router.put("/interests", status_code=status.HTTP_200_OK)
async def put_interest(
    user_id: UserId,
    body: InterestRequest,
    service: DependencyDiscoveryProfileService,
) -> dict[str, object]:
    try:
        interest = await service.add_interest(user_id, body.label, body.strength)
    except DiscoveryProfileLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return asdict(interest)


@router.delete("/interests/{interest_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interest(
    user_id: UserId,
    interest_id: UUID,
    service: DependencyDiscoveryProfileService,
) -> None:
    if not await service.remove_interest(user_id, interest_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Interest not found."
        )


@router.put("/localities", status_code=status.HTTP_200_OK)
async def put_locality(
    user_id: UserId,
    body: LocalityRequest,
    service: DependencyDiscoveryProfileService,
) -> dict[str, object]:
    try:
        locality = await service.add_locality(
            user_id,
            body.label,
            body.region,
            body.radius_km,
            body.timezone,
            body.is_primary,
        )
    except DiscoveryProfileLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return asdict(locality)


@router.delete("/localities/{locality_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_locality(
    user_id: UserId,
    locality_id: UUID,
    service: DependencyDiscoveryProfileService,
) -> None:
    if not await service.remove_locality(user_id, locality_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Locality not found."
        )


class SourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["ics", "rss"]
    url: str = Field(min_length=8, max_length=MAX_URL_CHARS)
    label: str | None = Field(default=None, max_length=MAX_LABEL_CHARS)
    enabled: bool = True


@router.get("/sources")
async def list_sources(
    user_id: UserId,
    sources: DependencyDiscoverySources,
) -> dict[str, object]:
    configured = await sources.list_sources(user_id)
    return {"user_id": user_id, "sources": [asdict(item) for item in configured]}


@router.put("/sources", status_code=status.HTTP_200_OK)
async def put_source(
    user_id: UserId,
    body: SourceRequest,
    sources: DependencyDiscoverySources,
) -> dict[str, object]:
    try:
        source = await sources.upsert_source(
            user_id, body.kind, body.url, body.label, body.enabled
        )
    except DiscoveryProfileLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return asdict(source)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    user_id: UserId,
    source_id: UUID,
    sources: DependencyDiscoverySources,
) -> None:
    if not await sources.delete_source(user_id, source_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source not found."
        )


# Run one sweep now. The scheduled path is the ordinary one; this exists so a
# user can see what their configuration actually produces without waiting for
# the next slot, and so acceptance can exercise the body directly.
@router.post("/sweep", status_code=status.HTTP_200_OK)
async def run_sweep(
    user_id: UserId,
    profile_service: DependencyDiscoveryProfileService,
    runner: DependencyDiscoveryRunner,
    # A rehearsal runs the whole pipeline and records nothing, so the same
    # configuration can be tried repeatedly while judging output quality. A real
    # sweep marks what it found as seen, which correctly makes the second run
    # empty and therefore useless for comparison.
    commit: bool = True,
) -> dict[str, object]:
    profile = await profile_service.get_profile(user_id)
    result = await runner.sweep(user_id, profile, persist=commit)
    primary = profile.primary_locality
    base = calendar_base_url(settings.DISCOVERY_CALENDAR_BASE_URL)
    return {
        # The message as it would actually be sent, so quality is judged on the
        # thing a person receives rather than on a field listing.
        "message": render_message(
            result.selected,
            f"{base.rstrip('/')}/{user_id}/calendar",
            timezone=primary.timezone if primary else "America/New_York",
        ),
        "committed": commit,
        "user_id": user_id,
        "selected": [
            {
                "title": item.event.title,
                "starts_at": (
                    item.event.starts_at.isoformat() if item.event.starts_at else None
                ),
                "place": item.event.place,
                "url": item.event.url,
                "score": round(item.score, 4),
                "matched_interest": item.matched_interest,
                # Only a dated event can become a calendar file. Offering a
                # link that would fail is worse than offering none.
                "calendar_path": (
                    f"/api/v1/discovery/{user_id}/calendar/{item.candidate.digest}.ics"
                    if item.event.starts_at is not None
                    else None
                ),
            }
            for item in result.selected
        ],
        "candidate_count": result.candidate_count,
        "novel_count": result.novel_count,
        "requests_spent": result.requests_spent,
        "failed_sources": list(result.failed_sources),
    }


# One event as a calendar file. iOS adds a .ics natively from a link, so this is
# the whole "add to calendar" mechanism: no CalDAV, no developer account, and no
# write access to the user's calendar.
@router.get("/calendar/{item_digest}.ics")
async def download_event_calendar(
    user_id: UserId,
    item_digest: str,
    seen: DependencyDiscoverySeenItems,
) -> Response:
    event = await seen.event_for_digest(user_id, item_digest)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found."
        )
    try:
        body = build_vevent(event)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{calendar_filename(event)}"'
            )
        },
    )


class SubscriberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["imessage", "shortcuts_pull"]
    address: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=MAX_LABEL_CHARS)
    # Consent is stated, never inferred. Without it the permission is stored
    # inactive, so the default outcome of a mistake is that nothing is sent.
    consented: bool = False


@router.get("/subscribers")
async def list_subscribers(
    user_id: UserId,
    subscribers: DependencyDiscoverySubscribers,
) -> dict[str, object]:
    people = await subscribers.list_subscribers(user_id)
    return {
        "user_id": user_id,
        "egress_enabled": settings.DISCOVERY_EGRESS_ENABLED,
        "subscribers": [
            {
                "id": person.id,
                "channel": person.channel,
                "label": person.label,
                "active": person.active,
                "deliverable": person.deliverable,
                "delivery_count": person.delivery_count,
                "last_error": person.last_error,
                # The address is deliberately absent from the listing: it is
                # someone else's contact detail, and enumerating recipients
                # should not hand them out.
                "feed_path": f"/api/v1/discovery/feed/{person.token}.ics",
            }
            for person in people
        ],
    }


@router.put("/subscribers", status_code=status.HTTP_200_OK)
async def put_subscriber(
    user_id: UserId,
    body: SubscriberRequest,
    subscribers: DependencyDiscoverySubscribers,
) -> dict[str, object]:
    try:
        person = await subscribers.enroll(
            user_id, body.channel, body.address, body.label, body.consented
        )
    except DiscoveryProfileLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return {
        "id": person.id,
        "channel": person.channel,
        "deliverable": person.deliverable,
        "feed_path": f"/api/v1/discovery/feed/{person.token}.ics",
    }


# Stop delivery now, and invalidate any calendar link already shared. Kept
# separate from deletion so revoking preserves the record of what was sent.
@router.post("/subscribers/{subscriber_id}/revoke", status_code=status.HTTP_200_OK)
async def revoke_subscriber(
    user_id: UserId,
    subscriber_id: UUID,
    subscribers: DependencyDiscoverySubscribers,
) -> dict[str, object]:
    if not await subscribers.revoke(user_id, subscriber_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscriber not found."
        )
    return {"id": str(subscriber_id), "revoked": True}


@router.delete("/subscribers/{subscriber_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscriber(
    user_id: UserId,
    subscriber_id: UUID,
    subscribers: DependencyDiscoverySubscribers,
) -> None:
    if not await subscribers.delete(user_id, subscriber_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscriber not found."
        )


# One subscriber's own subscription feed. A calendar client re-reads this on its
# own schedule and reconciles by UID, so an event that leaves this document
# leaves their calendar. Unauthenticated by necessity and unguessable by design.
@feed_router.get("/{token}.ics")
async def subscriber_feed(
    token: str,
    subscribers: DependencyDiscoverySubscribers,
    seen: DependencyDiscoverySeenItems,
) -> Response:
    resolved = await subscribers.by_token(token)
    if resolved is None:
        # A revoked or unknown token is indistinguishable from the outside.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found."
        )
    owner, _subscriber = resolved
    events = await seen.announced_events(owner)
    if not events:
        # An empty calendar is still a valid calendar; a subscriber whose feed
        # errors would see a broken-subscription warning on their phone.
        body = _EMPTY_CALENDAR
    else:
        body = build_calendar(events, calendar_name="AniOS Discoveries")
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "private, max-age=900"},
    )


_EMPTY_CALENDAR = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//AniOS//Ambient Discovery//EN\r\n"
    "CALSCALE:GREGORIAN\r\n"
    "METHOD:PUBLISH\r\n"
    "X-WR-CALNAME:AniOS Discoveries\r\n"
    "END:VCALENDAR\r\n"
)


# Propose feeds for the user's primary place. Search is used here and only here,
# to find sources rather than events: a sweep never searches, which is what keeps
# the weekly loop inside the free tier and out of the business of inferring dates
# from prose. Every candidate has already been fetched and parsed before it is
# offered.
@router.get("/sources/suggest")
async def suggest_sources(
    user_id: UserId,
    profile_service: DependencyDiscoveryProfileService,
    setup: DependencyDiscoverySetup,
) -> dict[str, object]:
    profile = await profile_service.get_profile(user_id)
    if profile.primary_locality is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Add a place first so suggestions can be local.",
        )
    candidates = await setup.suggest_feeds(profile)
    return {
        "user_id": user_id,
        "locality": profile.primary_locality.label,
        "candidates": [asdict(candidate) for candidate in candidates],
    }


# Propose interests from memory the user already approved. These are candidates,
# never facts: accepting one is a separate call, and that acceptance is what
# records it as user-stated.
@router.get("/interests/suggest")
async def suggest_interests(
    user_id: UserId,
    profile_service: DependencyDiscoveryProfileService,
    setup: DependencyDiscoverySetup,
) -> dict[str, object]:
    profile = await profile_service.get_profile(user_id)
    proposals = await setup.suggest_interests(user_id, profile)
    return {
        "user_id": user_id,
        "proposals": [asdict(proposal) for proposal in proposals],
    }


class ResolveLocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


# Name the town containing a coordinate, without keeping the coordinate.
#
# The browser returns a precise fix, which for a request made at home is the
# user's address. This rounds it to roughly a kilometre before the single
# outbound lookup, returns a place label, and persists nothing numeric. Typing
# the town instead makes no request at all.
@router.post("/locality/resolve", status_code=status.HTTP_200_OK)
async def resolve_locality(
    user_id: UserId,
    body: ResolveLocationRequest,
    resolver: DependencyPlaceResolver,
) -> dict[str, object]:
    try:
        place = await resolve_place(resolver, body.latitude, body.longitude)
    except LocationLookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return {
        "label": place.label,
        "region": place.region,
        "country": place.country,
        "country_code": place.country_code,
        # A town name alone is ambiguous across countries, so the caller is
        # given something it can show a person without guessing.
        "display": place.display,
        "stored_region": place.stored_region,
        # Stated back so the caller can show what was actually sent.
        "sent_precision_decimals": COARSE_DECIMALS,
    }


# Show exactly what a delivery would send, without sending it.
#
# Verifying an outbound feature by triggering it is a bad trade: the send cannot
# be recalled, and a wrong digest reaches real people. This renders the same
# string the channel would receive, from the same code path, and names who would
# have received it — so the whole loop can be checked before egress is ever
# switched on.
@router.get("/digest/preview")
async def preview_digest(
    user_id: UserId,
    profile_service: DependencyDiscoveryProfileService,
    runner: DependencyDiscoveryRunner,
    subscribers: DependencyDiscoverySubscribers,
    seen: DependencyDiscoverySeenItems,
) -> dict[str, object]:
    profile = await profile_service.get_profile(user_id)
    primary = profile.primary_locality
    timezone = primary.timezone if primary else "America/New_York"

    # Preview reads what has already been announced rather than sweeping again,
    # so looking does not consume a metered query or mark anything as seen.
    events = await seen.announced_events(user_id)
    selected = tuple(
        RankedCandidate(ScoredCandidate(event, None), 1.0, None) for event in events
    )

    base = calendar_base_url(settings.DISCOVERY_CALENDAR_BASE_URL)
    message = render_message(
        selected, f"{base.rstrip('/')}/{user_id}/calendar", timezone=timezone
    )
    recipients = await subscribers.list_subscribers(user_id, deliverable_only=True)

    return {
        "user_id": user_id,
        # None means nothing would be sent, which is a valid outcome rather
        # than an error: silence beats a weekly "nothing this week".
        "message": message,
        "would_send": message is not None and bool(recipients),
        "recipients": describe_recipients(recipients),
        "egress_enabled": settings.DISCOVERY_EGRESS_ENABLED,
        "calendar_links_reachable": is_reachable_from_other_devices(base),
        "event_count": len(events),
    }


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cadence: Literal["daily", "weekly"] = "weekly"
    hour: int = Field(default=9, ge=0, le=23)
    # Monday is 0, matching datetime.weekday(). Ignored for a daily cadence.
    weekday: int = Field(default=4, ge=0, le=6)
    timezone: str = Field(default="America/New_York", min_length=1, max_length=64)
    enabled: bool = True


# Without a schedule the worker polls forever and finds nothing due, so the
# whole loop only ever runs when someone presses a button.
@router.get("/schedule")
async def read_schedule(
    user_id: UserId,
    runs: DependencyDiscoveryRuns,
) -> dict[str, object]:
    schedule = await runs.get_schedule(user_id)
    return {"user_id": user_id, "schedule": schedule}


@router.put("/schedule", status_code=status.HTTP_200_OK)
async def put_schedule(
    user_id: UserId,
    body: ScheduleRequest,
    runs: DependencyDiscoveryRuns,
) -> dict[str, object]:
    try:
        cadence = Cadence(
            cadence=body.cadence,
            hour=body.hour,
            weekday=body.weekday,
            timezone=body.timezone,
        )
        saved = await runs.upsert_schedule(user_id, cadence, enabled=body.enabled)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return saved


@router.delete("/schedule", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    user_id: UserId,
    runs: DependencyDiscoveryRuns,
) -> None:
    if not await runs.delete_schedule(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No schedule set."
        )


class KnownRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The title as shown. Carried rather than referenced by id, because a
    # rehearsal persists nothing and dismissing something you just saw in one is
    # the most likely moment to want this.
    label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS * 3)


# Record that the user already knows this, here.
#
# Scoped to their current primary place, which is the point: someone who knows
# every trail in Arlington knows none in Denver, so a global list would make the
# agent progressively useless exactly when travel makes it most valuable.
@router.post("/known", status_code=status.HTTP_200_OK)
async def mark_known(
    user_id: UserId,
    body: KnownRequest,
    profile_service: DependencyDiscoveryProfileService,
    familiar: DependencyDiscoveryFamiliar,
    embeddings: EmbeddingDependency,
) -> dict[str, object]:
    profile = await profile_service.get_profile(user_id)
    primary = profile.primary_locality
    label = body.label.strip()

    # Embedded so dismissing one trail directory suppresses the family rather
    # than that single instance. A failure still records it by identity.
    vector: list[float] | None
    try:
        vector = await asyncio.to_thread(embeddings.embed_query, label)
    except Exception:
        vector = None

    await familiar.remember_known(
        user_id, primary.label if primary else None, label, vector
    )
    return {
        "label": label,
        "locality": primary.label if primary else None,
        "known_here": await familiar.count_known(
            user_id, primary.label if primary else None
        ),
    }


@router.get("/known")
async def list_known(
    user_id: UserId,
    profile_service: DependencyDiscoveryProfileService,
    familiar: DependencyDiscoveryFamiliar,
) -> dict[str, object]:
    profile = await profile_service.get_profile(user_id)
    primary = profile.primary_locality
    return {
        "locality": primary.label if primary else None,
        "known": list(
            await familiar.list_known(user_id, primary.label if primary else None)
        ),
    }


@router.delete("/known/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_known(
    user_id: UserId,
    item_id: str,
    familiar: DependencyDiscoveryFamiliar,
) -> None:
    if not await familiar.forget(user_id, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
