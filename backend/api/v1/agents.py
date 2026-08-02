"""The workspace's view of which specialized agents exist and what they are doing."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from backend.core.auth import authorize_path_user
from backend.core.dependencies import DependencyAgentRegistry

router = APIRouter(
    prefix="/agents/{user_id}",
    tags=["agents"],
    dependencies=[Depends(authorize_path_user)],
)
UserId = Annotated[str, Path(min_length=1, max_length=50)]


# Every field is read from the tables each agent writes, so this cannot report a
# state the agent is not actually in.
@router.get("")
async def list_agents(
    user_id: UserId,
    registry: DependencyAgentRegistry,
) -> dict[str, object]:
    agents = await registry.describe_all(user_id)
    return {
        "user_id": user_id,
        "agents": [agent.to_dict() for agent in agents],
    }
