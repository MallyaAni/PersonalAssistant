"""Turn a coarse coordinate into a place name, and keep it coarse.

The browser's geolocation API returns a precise fix — often to a few metres,
which for a request made at home is the user's address. A home latitude and
longitude is the most sensitive value this application could hold, which is why
the profile stores a place *label* and no coordinates at all.

So this exists to throw precision away before it can travel. A coordinate is
rounded to `COARSE_DECIMALS` before any lookup, the result is a town name, and
nothing numeric is persisted or returned. Typing the town instead makes no
request at all.

`PlaceResolver` is a provider contract for the same reason `EventSource`,
`SearchProvider`, and `ImageProvider` are: this is an outbound boundary, and the
application should depend on the capability rather than on one vendor's HTTP
API. It also makes the default fail-closed — an unconfigured deployment resolves
nothing rather than silently reaching a third party.
"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

# Two decimals is about 1.1 km at the equator and less further north — enough to
# name a town, not enough to name a building.
COARSE_DECIMALS = 2


class LocationLookupError(RuntimeError):
    """Raised when a coordinate could not be resolved to a place."""


@dataclass(frozen=True, slots=True)
class ResolvedPlace:
    """A named place. Deliberately carries no coordinates."""

    label: str
    region: str | None
    # Country is kept separate from region because a town name alone is
    # ambiguous across countries — there is an Arlington in several — and a
    # state name alone does not resolve it either.
    country: str | None = None
    country_code: str | None = None

    # How the place reads to a person: "Arlington, Virginia (US)".
    @property
    def display(self) -> str:
        parts = [self.label]
        if self.region:
            parts.append(self.region)
        rendered = ", ".join(parts)
        if self.country_code:
            rendered += f" ({self.country_code})"
        return rendered

    # What the profile stores as its disambiguator, compact enough for a label.
    @property
    def stored_region(self) -> str | None:
        parts = [part for part in (self.region, self.country_code) if part]
        return ", ".join(parts) or None


class PlaceResolver(ABC):
    """Replaceable reverse-geocoding backend."""

    # Report whether this deployment can resolve at all; callers must not assume.
    @abstractmethod
    def is_enabled(self) -> bool: ...

    # Name the town containing an already-coarsened coordinate.
    @abstractmethod
    async def resolve(self, latitude: float, longitude: float) -> ResolvedPlace: ...


class DisabledPlaceResolver(PlaceResolver):
    """Resolves nothing. The default, so location lookup is opt-in."""

    def is_enabled(self) -> bool:
        return False

    async def resolve(self, latitude: float, longitude: float) -> ResolvedPlace:
        raise LocationLookupError("Location lookup is not enabled.")


class NominatimPlaceResolver(PlaceResolver):
    """OpenStreetMap's public reverse geocoder.

    Free and keyless, and it asks callers to identify themselves rather than to
    authenticate. Requesting city-level zoom means less detail comes back, not
    just less detail used.
    """

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.client = client

    def is_enabled(self) -> bool:
        return bool(self.base_url)

    async def resolve(self, latitude: float, longitude: float) -> ResolvedPlace:
        params = {
            "lat": f"{latitude}",
            "lon": f"{longitude}",
            "format": "jsonv2",
            # Roughly city level.
            "zoom": "10",
            "addressdetails": "1",
        }
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        try:
            if self.client is not None:
                response = await self.client.get(
                    self.base_url, params=params, headers=headers
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as owned:
                    response = await owned.get(
                        self.base_url, params=params, headers=headers
                    )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            # The provider's error text is not propagated: it echoes the query,
            # and the query is a location.
            raise LocationLookupError("Could not resolve that location.") from exc

        place = _place_from(payload)
        if place is None:
            raise LocationLookupError("No place matched that location.")
        return place


# Round toward fewer digits. Truncation would bias every coordinate toward the
# equator and prime meridian; rounding keeps the blunted point near the real one.
def coarsen(value: float, decimals: int = COARSE_DECIMALS) -> float:
    if not math.isfinite(value):
        raise LocationLookupError("Coordinate is not a finite number.")
    return round(value, decimals)


# The one entry point callers use. Coarsening happens here rather than in an
# adapter, so no future resolver can be written that forgets to do it.
async def resolve_place(
    resolver: PlaceResolver,
    latitude: float,
    longitude: float,
) -> ResolvedPlace:
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        raise LocationLookupError("Coordinate is out of range.")
    if not resolver.is_enabled():
        raise LocationLookupError("Location lookup is not enabled.")
    return await resolver.resolve(coarsen(latitude), coarsen(longitude))


# The response is third-party data. Only two known fields are read, both are
# bounded, and everything else — including the precise coordinates the service
# echoes back — is discarded rather than carried forward.
def _place_from(payload: object) -> ResolvedPlace | None:
    if not isinstance(payload, dict):
        return None
    address = payload.get("address")
    if not isinstance(address, dict):
        return None

    label = _first_string(
        address, ("city", "town", "village", "municipality", "suburb", "county")
    )
    if label is None:
        return None
    # Country is read separately rather than as a fallback for region. Falling
    # back would return "United States" as the region for a town with no state,
    # and then drop the country entirely for one that has both.
    region = _first_string(address, ("state", "province", "region"))
    country = _first_string(address, ("country",))
    code = _first_string(address, ("country_code",))
    return ResolvedPlace(
        label=label,
        region=region,
        country=country,
        country_code=code.upper() if code else None,
    )


def _first_string(address: dict[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:80]
    return None
