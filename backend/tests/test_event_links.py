"""The link follow-up builds grounded links by code, one event at a time.

The listing offers links and this is what actually delivers them. Every
address must be one code could construct or a source page stated - a model
handed the same records wrote invented map links on 2026-08-29, which is why
the fence exists and why these are built here.
"""

from datetime import UTC, datetime, time

import pytest

import backend.tasks.picker as picker_module
from backend.core.event_extraction import ListedEvent
from backend.core.event_links import event_link_lines, render_links_for
from backend.core.links import URL_IN_TEXT, template_is_grounded
from backend.services import conversation_service as cs
from backend.services import last_listing_store as listing_store
from backend.tools.actions import SendEventLinksAction

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
EVIDENCE = (
    "Sunday Sessions at The Lawn, Batu Bolong, every Sunday from 4pm with DJ Dea. "
    "Sunset session at Potato Head on Saturday 5 September 2026."
)

BASE = "https://deep-matter.com/api/v1/discovery"


def _event(**overrides):
    base = dict(
        name="Sunday Sessions", venue="The Lawn", area="Batu Bolong", artist="DJ Dea",
        what="Deep house on the grass.", when_text="every Sunday from 4pm",
        recurring=True,
        starts_at=datetime(2026, 8, 30, 16, 0, tzinfo=UTC), start_time=time(16, 0),
        price_text="free before 6pm", source_url="https://www.thelawncanggu.com/whats-on",
        source_title="The Lawn",
    )
    base.update(overrides)
    return ListedEvent(**base)


def test_every_link_is_grounded_or_from_a_source_page():
    message = render_links_for((_event(),), calendar_base_url=BASE)
    sources = {"https://www.thelawncanggu.com/whats-on"}
    for url in URL_IN_TEXT.findall(message):
        cleaned = url.rstrip(".,;:!?)]}\"'")
        assert cleaned in sources or template_is_grounded(cleaned, EVIDENCE), cleaned


def test_each_event_keeps_its_links_with_its_line():
    # Two events in one follow-up must not run together into an unreadable
    # block: each keeps its own headline and its own link row.
    second = _event(name="Sunset Session", venue="Potato Head", area="Seminyak",
                    artist="", source_url="https://potatohead.co/events",
                    starts_at=datetime(2026, 9, 5, 18, 0, tzinfo=UTC),
                    when_text="Saturday 5 September 2026", recurring=False)
    message = render_links_for((_event(), second), calendar_base_url=BASE)
    first = message.index("Sunday Sessions")
    second_i = message.index("Sunset Session")
    # Each event leads, and the first event's row is fully before the second's.
    assert first < second_i
    lawn = "Map](https://maps.google.com/?q=The+Lawn+Batu+Bolong"
    assert lawn in message[first:second_i]
    head = "Map](https://maps.google.com/?q=Potato+Head+Seminyak"
    assert head in message[second_i:]


def test_the_link_row_covers_the_map_calendar_and_page():
    links = "\n".join(event_link_lines(_event(), calendar_base_url=BASE))
    assert "[Map](" in links
    assert "[Calendar](" in links
    assert "[Add to iMessage calendar](" in links
    # A named act keeps the "Hear it" search; a source page keeps its Details.
    assert "[Hear it](" in links
    assert "[Details](https://www.thelawncanggu.com/whats-on)" in links


def test_an_event_with_no_artist_and_no_source_gets_only_what_it_can():
    links = "\n".join(
        event_link_lines(
            _event(artist="", source_url="", area="", starts_at=None, start_time=None)
        )
    )
    assert "[Map](" in links
    assert "[Calendar](" in links
    assert "[Hear it](" not in links
    assert "[Details](" not in links


def _service() -> cs.ConversationService:
    """A service with only what the link lookup touches."""
    service = cs.ConversationService.__new__(cs.ConversationService)
    service.main_action_selector = None
    service.llm = None
    return service


def _listing(rendered: str, name: str) -> dict:
    return {
        "rendered": rendered,
        "calendar_base_url": BASE,
        "saved_at": "2026-09-04T11:00:00+00:00",
        "events": [_event(name=name)],
    }


@pytest.mark.asyncio
async def test_a_direct_message_sends_links_from_the_room_that_showed_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, object] = {}

    async def load_own(user_id: str) -> dict:
        return _listing("own listing", "Own Event")

    async def load_member(user_id: str, group_user_ids) -> dict:
        asked["call"] = (user_id, list(group_user_ids))
        return _listing("room listing", "Sunday Sessions")

    async def member_groups(self, user_id: str) -> list[str]:
        return ["group:chess"]

    async def pick(llm, which, items, describe, hint=""):
        return [0]

    monkeypatch.setattr(listing_store, "load_last_listing", load_own)
    monkeypatch.setattr(listing_store, "load_last_listing_for_member", load_member)
    monkeypatch.setattr(cs.ConversationService, "_member_group_ids", member_groups)
    monkeypatch.setattr(picker_module, "pick_many", pick)

    result = await _service()._apply_event_links(
        "ani", SendEventLinksAction(which="the salsa night")
    )

    # The member's own listing is not what they meant: the room showed the
    # newest one, and that is where the links come from.
    assert asked["call"] == ("ani", ["group:chess"])
    assert result["kind"] == "links"
    assert "Sunday Sessions" in result["message"]


@pytest.mark.asyncio
async def test_a_room_turn_never_reads_the_speakers_personal_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read: list[str] = []

    async def load_own(user_id: str) -> dict:
        read.append(user_id)
        return _listing("room listing", "Sunday Sessions")

    async def load_member(*args, **kwargs) -> dict:
        raise AssertionError("a room turn must not read a member's listings")

    async def member_groups(self, user_id: str) -> list[str]:
        raise AssertionError("a room turn has no member listings to look up")

    async def pick(llm, which, items, describe, hint=""):
        return [0]

    monkeypatch.setattr(listing_store, "load_last_listing", load_own)
    monkeypatch.setattr(listing_store, "load_last_listing_for_member", load_member)
    monkeypatch.setattr(cs.ConversationService, "_member_group_ids", member_groups)
    monkeypatch.setattr(picker_module, "pick_many", pick)

    token = cs._turn_speaker.set("ani")
    try:
        result = await _service()._apply_event_links(
            "group:chess", SendEventLinksAction(which="the salsa night")
        )
    finally:
        cs._turn_speaker.reset(token)

    # The room reads the room's own listing; the speaker's private one stays
    # private even though they are the one asking.
    assert read == ["group:chess"]
    assert result["kind"] == "links"
    assert "Sunday Sessions" in result["message"]
