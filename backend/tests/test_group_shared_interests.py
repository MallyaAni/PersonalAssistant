"""A group's Scout starts from what its members share, and follows the membership."""

from types import SimpleNamespace

import pytest

from backend.groups.shared_interests import SHARED_PROVENANCE, refresh_shared_interests


def _interest(label, strength=2, provenance="user_explicit", ident="i"):
    return SimpleNamespace(id=ident, label=label, strength=strength, provenance=provenance)


def _locality(label):
    return SimpleNamespace(label=label, region="Virginia", radius_km=25, timezone="America/New_York", is_primary=True)


class _Repo:
    def __init__(self, profiles):
        self.profiles = profiles
        self.upserts = []
        self.deleted = []
        self.localities = []

    async def get_profile(self, user_id):
        p = self.profiles.get(user_id) or {"interests": [], "primary_locality": None}
        return SimpleNamespace(interests=tuple(p["interests"]), primary_locality=p.get("primary_locality"))

    async def upsert_interest(self, user_id, label, strength, provenance):
        self.upserts.append((user_id, label, strength, provenance))

    async def delete_interest(self, user_id, interest_id):
        self.deleted.append((user_id, interest_id))

    async def upsert_locality(self, **kw):
        self.localities.append(kw)


class _Session:
    async def commit(self):
        pass


@pytest.fixture
def repo(monkeypatch):
    holder = {}

    def factory(session):
        return holder["repo"]

    import backend.discovery.repository as module

    monkeypatch.setattr(module, "DiscoveryProfileRepository", factory)
    return holder


@pytest.mark.asyncio
async def test_interests_two_members_share_reach_the_group_with_their_provenance(repo):
    repo["repo"] = _Repo({
        "u-ani": {"interests": [_interest("Thai food", 3), _interest("hiking", 2)], "primary_locality": _locality("Arlington")},
        "u-jen": {"interests": [_interest("thai food", 2), _interest("horses", 3)], "primary_locality": _locality("Alexandria")},
        "group:x": {"interests": [], "primary_locality": None},
    })
    shared = await refresh_shared_interests(_Session(), "group:x", ("u-ani", "u-jen"))
    assert shared == ("Thai food",)
    assert repo["repo"].upserts == [("group:x", "Thai food", 3, SHARED_PROVENANCE)]
    # Two cities: no home is guessed for the room.
    assert repo["repo"].localities == []


@pytest.mark.asyncio
async def test_an_interest_no_longer_shared_is_removed_and_the_rooms_own_stay(repo):
    repo["repo"] = _Repo({
        "u-ani": {"interests": [_interest("hiking")], "primary_locality": _locality("Arlington")},
        "u-jen": {"interests": [_interest("horses")], "primary_locality": _locality("Arlington")},
        "group:x": {"interests": [
            _interest("thai food", provenance=SHARED_PROVENANCE, ident="old-shared"),
            _interest("climbing", provenance="user_explicit", ident="rooms-own"),
        ], "primary_locality": None},
    })
    shared = await refresh_shared_interests(_Session(), "group:x", ("u-ani", "u-jen"))
    assert shared == ()
    assert repo["repo"].deleted == [("group:x", "old-shared")]
    assert repo["repo"].upserts == []
    # One city for everyone: the room gets it as its home.
    assert [loc["label"] for loc in repo["repo"].localities] == ["Arlington"]
    assert repo["repo"].localities[0]["is_primary"] is True


@pytest.mark.asyncio
async def test_a_member_whose_profile_cannot_be_read_does_not_break_the_others(repo):
    class _Flaky(_Repo):
        async def get_profile(self, user_id):
            if user_id == "u-broken":
                raise RuntimeError("db")
            return await super().get_profile(user_id)

    repo["repo"] = _Flaky({
        "u-ani": {"interests": [_interest("hiking")], "primary_locality": None},
        "u-jen": {"interests": [_interest("Hiking")], "primary_locality": None},
        "group:x": {"interests": [], "primary_locality": None},
    })
    assert await refresh_shared_interests(_Session(), "group:x", ("u-ani", "u-broken", "u-jen")) == ("hiking",)
