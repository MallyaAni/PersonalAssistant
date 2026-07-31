from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.auth import authorize_path_user
from backend.core.dependencies import DependencyDiscoveryProfileService
from backend.discovery.errors import DiscoveryProfileLimitError
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
