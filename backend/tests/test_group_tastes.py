"""The taste allowlist: a name and interests reach the room, nothing else."""

from types import SimpleNamespace

import pytest

from backend.memory.tastes import Taste, TasteProjection


class _Memory:
    def __init__(self, profiles):
        self.profiles = profiles

    async def get_user_profile(self, user_id):
        if user_id == "u-broken":
            raise RuntimeError("db down")
        return self.profiles.get(user_id)


class _Scout:
    def __init__(self, interests):
        self.interests = interests

    async def get_profile(self, user_id):
        if user_id == "u-broken":
            raise RuntimeError("db down")
        return SimpleNamespace(
            interests=[SimpleNamespace(label=label, strength=3) for label in self.interests.get(user_id, [])],
            localities=[SimpleNamespace(label="Arlington")],
        )


@pytest.mark.asyncio
async def test_only_name_and_interests_are_projected_in_roster_order():
    memory = _Memory(
        {
            "u-ani": SimpleNamespace(name="Ani", preferences={"address": "1 Main St"}),
            "u-jen": SimpleNamespace(name="Jen", preferences={}),
        }
    )
    scout = _Scout({"u-ani": ["hiking", "thai food"], "u-jen": []})
    tastes = await TasteProjection(memory, scout).for_members(("u-jen", "u-ani"))
    assert tastes == (
        Taste("u-jen", "Jen", ()),
        Taste("u-ani", "Ani", ("hiking", "thai food")),
    )
    assert set(tastes[1].as_dict()) == {"user_id", "name", "interests"}


@pytest.mark.asyncio
async def test_an_unreadable_member_stays_on_the_roster_by_placeholder():
    tastes = await TasteProjection(_Memory({}), _Scout({})).for_members(("u-broken", "u-nobody"))
    assert tastes == (Taste("u-broken", "Member 1", ()), Taste("u-nobody", "Member 2", ()))


@pytest.mark.asyncio
async def test_without_scout_there_are_no_interests():
    memory = _Memory({"u-ani": SimpleNamespace(name="Ani")})
    assert await TasteProjection(memory, None).for_members(("u-ani",)) == (Taste("u-ani", "Ani", ()),)
