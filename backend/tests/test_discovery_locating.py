"""Location resolution: precision is discarded before it can travel."""

import os

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.locating import (
    COARSE_DECIMALS,
    DisabledPlaceResolver,
    LocationLookupError,
    PlaceResolver,
    ResolvedPlace,
    coarsen,
    resolve_place,
)


class _RecordingResolver(PlaceResolver):
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.received: list[tuple[float, float]] = []

    def is_enabled(self) -> bool:
        return self.enabled

    async def resolve(self, latitude: float, longitude: float) -> ResolvedPlace:
        self.received.append((latitude, longitude))
        return ResolvedPlace(label="New Haven", region="Connecticut")


def test_coarsening_rounds_rather_than_truncates():
    # Truncation would bias every coordinate toward the equator and prime
    # meridian; rounding keeps the blunted point near the real one.
    assert coarsen(41.30827431) == 41.31
    assert coarsen(-72.92788219) == -72.93
    assert COARSE_DECIMALS == 2


def test_a_non_finite_coordinate_is_refused():
    with pytest.raises(LocationLookupError):
        coarsen(float("nan"))


@pytest.mark.asyncio
async def test_the_resolver_never_sees_the_precise_fix():
    """The property this module exists for."""
    resolver = _RecordingResolver()

    await resolve_place(resolver, 41.30827431, -72.92788219)

    # A street-level fix went in; a kilometre-level one went out.
    assert resolver.received == [(41.31, -72.93)]


@pytest.mark.asyncio
async def test_a_resolved_place_carries_no_coordinates():
    place = await resolve_place(_RecordingResolver(), 41.3, -72.9)

    assert place.label == "New Haven"
    assert not hasattr(place, "latitude")
    assert not hasattr(place, "longitude")


@pytest.mark.asyncio
async def test_lookup_is_disabled_by_default():
    # An unconfigured deployment must not reach a third party.
    with pytest.raises(LocationLookupError, match="not enabled"):
        await resolve_place(DisabledPlaceResolver(), 41.3, -72.9)


@pytest.mark.asyncio
async def test_an_out_of_range_coordinate_never_reaches_the_provider():
    resolver = _RecordingResolver()

    with pytest.raises(LocationLookupError, match="out of range"):
        await resolve_place(resolver, 91.0, 0.0)

    assert resolver.received == []
