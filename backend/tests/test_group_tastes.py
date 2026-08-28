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
            # A property on the real DiscoveryProfile; a plain attribute here.
            primary_locality=SimpleNamespace(label="Arlington"),
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
        Taste("u-jen", "Jen", (), "Arlington", ()),
        Taste("u-ani", "Ani", ("hiking", "thai food"), "Arlington", ()),
    )
    assert set(tastes[1].as_dict()) == {"user_id", "name", "interests", "home", "facts"}


@pytest.mark.asyncio
async def test_an_unreadable_member_stays_on_the_roster_by_placeholder(monkeypatch):
    projection = TasteProjection(_Memory({}), _Scout({}))

    async def no_username(user_id):
        return ""

    monkeypatch.setattr(projection, "_username", no_username)
    tastes = await projection.for_members(("u-broken", "u-nobody"))
    # The broken profile yields no home either; the unknown one still has
    # Scout's locality (the fake answers for anyone).
    assert tastes == (Taste("u-broken", "Member 1", (), "", ()), Taste("u-nobody", "Member 2", (), "Arlington", ()))


@pytest.mark.asyncio
async def test_without_a_profile_name_the_username_serves(monkeypatch):
    projection = TasteProjection(_Memory({"u-ani": SimpleNamespace(name="")}), _Scout({}))

    async def username(user_id):
        return {"u-ani": "Ani"}.get(user_id, "")

    monkeypatch.setattr(projection, "_username", username)
    assert await projection.for_members(("u-ani",)) == (Taste("u-ani", "Ani", (), "Arlington", ()),)


def test_usernames_read_as_first_names():
    from backend.memory.tastes import humanize_username

    assert humanize_username("ani.mallya") == "Ani"
    assert humanize_username("jenos1") == "Jenos"
    assert humanize_username("amanda_k") == "Amanda"
    assert humanize_username("  ") == ""
    assert humanize_username("42") == ""


@pytest.mark.asyncio
async def test_a_profile_handed_back_as_a_dict_still_names_the_member():
    memory = _Memory({"u-ani": {"name": "Ani", "preferences": {}}})
    (taste,) = await TasteProjection(memory, None).for_members(("u-ani",))
    assert taste.name == "Ani"


@pytest.mark.asyncio
async def test_without_scout_there_are_no_interests():
    memory = _Memory({"u-ani": SimpleNamespace(name="Ani")})
    assert await TasteProjection(memory, None).for_members(("u-ani",)) == (Taste("u-ani", "Ani", ()),)


@pytest.mark.asyncio
async def test_remembered_statements_reach_the_room_only_through_the_share_screen(monkeypatch):
    from backend.memory import share_screen

    share_screen.forget_verdicts()
    memory = _Memory({"u-jen": SimpleNamespace(name="Jen")})

    class _Judge:
        def chat(self, messages, max_tokens, schema, temperature):
            import json

            return {"content": json.dumps({"private": [2]})}

    projection = TasteProjection(memory, _Scout({}), _Judge())

    async def statements(user_id):
        return ("I drive a red Mini", "I'm seeing a therapist on Tuesdays", "My dog is Biscuit")

    monkeypatch.setattr(projection, "_statements", statements)
    (taste,) = await projection.for_members(("u-jen",))
    assert taste.facts == ("I drive a red Mini", "My dog is Biscuit")
    assert taste.as_dict()["facts"] == ["I drive a red Mini", "My dog is Biscuit"]
    share_screen.forget_verdicts()


@pytest.mark.asyncio
async def test_without_a_judge_no_statement_reaches_the_room(monkeypatch):
    projection = TasteProjection(_Memory({"u-jen": SimpleNamespace(name="Jen")}), _Scout({}))

    async def statements(user_id):
        raise AssertionError("must not even be read without a judge")

    monkeypatch.setattr(projection, "_statements", statements)
    (taste,) = await projection.for_members(("u-jen",))
    assert taste.facts == ()



@pytest.mark.asyncio
async def test_the_personal_context_reader_can_leave_a_purpose_out():
    from types import SimpleNamespace

    from backend.discovery.personal_context import PersonalContextReader

    rows = [
        SimpleNamespace(content="A brown horse wearing a pink hat", purpose="visual_artifact_analysis"),
        SimpleNamespace(content="I drive a red Mini", purpose="personalization"),
    ]

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return rows

    class _Session:
        async def execute(self, statement):
            return _Result()

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    reader = PersonalContextReader(_Session(), exclude_purposes=("visual_artifact_analysis",))
    assert await reader._semantic("u-jen", now) == ["I drive a red Mini"]
    assert await PersonalContextReader(_Session())._semantic("u-jen", now) == [
        "A brown horse wearing a pink hat",
        "I drive a red Mini",
    ]



@pytest.mark.asyncio
async def test_the_messages_nearest_memories_come_first_and_pictures_stay_out(monkeypatch):
    from backend.memory import share_screen

    share_screen.forget_verdicts()

    class _Searching(_Memory):
        async def get_semantic_memory(self, user_id, query, top_k=5, query_embedding=None):
            assert query == "what was my chili recipe?" and query_embedding == [0.1]
            return [
                {"content": "A bowl of chili in a red pot", "purpose": "visual_artifact_analysis"},
                {"content": "My chili recipe: two chipotles, cumin, and dark beer", "purpose": "personalization"},
                {"content": "I drive a red Mini", "purpose": "personalization"},
            ]

    class _Judge:
        def chat(self, messages, max_tokens, schema, temperature):
            import json

            return {"content": json.dumps({"private": []})}

    projection = TasteProjection(_Searching({"u-jen": SimpleNamespace(name="Jen")}), _Scout({}), _Judge())

    async def statements(user_id):
        return ("I drive a red Mini", "My dog is Biscuit")

    monkeypatch.setattr(projection, "_statements", statements)
    (taste,) = await projection.for_members(("u-jen",), query="what was my chili recipe?", query_embedding=[0.1])
    assert taste.facts == (
        "My chili recipe: two chipotles, cumin, and dark beer",
        "I drive a red Mini",
        "My dog is Biscuit",
    )
    share_screen.forget_verdicts()


@pytest.mark.asyncio
async def test_without_a_message_only_recent_statements_are_read(monkeypatch):
    from backend.memory import share_screen

    share_screen.forget_verdicts()

    class _Searching(_Memory):
        async def get_semantic_memory(self, *a, **k):
            raise AssertionError("no query, no search")

    class _Judge:
        def chat(self, messages, max_tokens, schema, temperature):
            import json

            return {"content": json.dumps({"private": []})}

    projection = TasteProjection(_Searching({"u-jen": SimpleNamespace(name="Jen")}), _Scout({}), _Judge())

    async def statements(user_id):
        return ("My dog is Biscuit",)

    monkeypatch.setattr(projection, "_statements", statements)
    (taste,) = await projection.for_members(("u-jen",))
    assert taste.facts == ("My dog is Biscuit",)
    share_screen.forget_verdicts()


@pytest.mark.asyncio
async def test_a_secret_in_a_relevant_memory_never_reaches_the_room(monkeypatch):
    from backend.memory import share_screen

    share_screen.forget_verdicts()

    class _Searching(_Memory):
        async def get_semantic_memory(self, user_id, query, top_k=5, query_embedding=None):
            return [{"content": "my wifi password is hunter2 and the API key is sk-live-abcdefghijklmnopqrstuvwxyz1234", "purpose": "personalization"}]

    judged = []

    class _Judge:
        def chat(self, messages, max_tokens, schema, temperature):
            import json

            judged.append(messages[1]["content"])
            return {"content": json.dumps({"private": []})}

    projection = TasteProjection(_Searching({"u-jen": SimpleNamespace(name="Jen")}), _Scout({}), _Judge())

    async def statements(user_id):
        return ()

    monkeypatch.setattr(projection, "_statements", statements)
    (taste,) = await projection.for_members(("u-jen",), query="what's the wifi?", query_embedding=[0.2])
    # The deterministic screen blocks the secret before any judgement; the
    # judge never even sees it.
    assert taste.facts == ()
    assert judged == []
    share_screen.forget_verdicts()
