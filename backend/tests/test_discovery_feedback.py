"""A digest sent as bubbles, and the reactions that come back to them.

The first positive signal in the loop, so the things worth proving are that it
cannot invent one and cannot cost a delivery.
"""

import json
from datetime import UTC, datetime

import pytest

from backend.discovery.channels import DeliveryResult, MessagesAppChannel
from backend.discovery.digest import write_bubbles
from backend.discovery.events import DiscoveredEvent
from backend.discovery.novelty import ScoredCandidate
from backend.discovery.reactions import ReactionCollector
from backend.discovery.relevance import RankedCandidate

NOW = datetime(2026, 11, 10, 8, 30, tzinfo=UTC)


def _candidate(title: str, starts_at: datetime | None, url: str | None = None):
    event = DiscoveredEvent(
        source_id="test",
        external_id=title,
        title=title,
        starts_at=starts_at,
        ends_at=None,
        place="Somewhere",
        url=url,
        summary=f"{title} happens and people go to it.",
    )
    return RankedCandidate(
        candidate=ScoredCandidate(event=event, embedding=None),
        score=1.0,
        matched_interest="Jazz",
    )


SELECTED = (
    _candidate("First find", datetime(2026, 11, 14, 20, 0, tzinfo=UTC), "https://a.test"),
    _candidate("Second find", datetime(2026, 11, 15, 20, 0, tzinfo=UTC)),
)


@pytest.mark.asyncio
async def test_each_find_becomes_its_own_bubble_without_a_model():
    bubbles = await write_bubbles(SELECTED, writer=None, now=NOW)

    # A tapback attaches to a bubble, so per-find feedback needs per-find
    # messages whether or not a model was there to word them.
    assert len(bubbles) == len(SELECTED)
    assert all(bubble.item_digest for bubble in bubbles)
    assert {bubble.label for bubble in bubbles} == {"First find", "Second find"}


@pytest.mark.asyncio
async def test_a_bubble_carries_the_record_s_own_link():
    bubbles = await write_bubbles(SELECTED, writer=None, now=NOW)

    assert "https://a.test" in bubbles[0].text
    # The second find has no link, and a line saying nothing is worse than none.
    assert "http" not in bubbles[1].text


@pytest.mark.asyncio
async def test_the_whole_shortlist_reaches_the_phone():
    busy = SELECTED + (
        _candidate("Third find", datetime(2026, 11, 16, 20, 0, tzinfo=UTC)),
        _candidate("Fourth find", datetime(2026, 11, 17, 20, 0, tzinfo=UTC)),
        _candidate("Fifth find", datetime(2026, 11, 18, 20, 0, tzinfo=UTC)),
    )

    bubbles = await write_bubbles(busy, writer=None, now=NOW)

    # Five, because the phone is where this is read. A find held back to keep
    # the thread quiet is a find nobody sees.
    assert len(bubbles) == 5
    assert all(bubble.item_digest for bubble in bubbles)


@pytest.mark.asyncio
async def test_no_bubble_points_the_reader_somewhere_else():
    busy = SELECTED + tuple(
        _candidate(f"Find {n}", datetime(2026, 11, 16 + n, 20, 0, tzinfo=UTC))
        for n in range(4)
    )

    bubbles = await write_bubbles(busy, writer=None, now=NOW)

    # A digest that ends by referring somewhere else is a digest that did not
    # finish its job. The message is the product, not a notification about one.
    for bubble in bubbles:
        assert "in the app" not in bubble.text
        assert "more find" not in bubble.text


@pytest.mark.asyncio
async def test_nothing_live_produces_no_bubbles():
    past = (_candidate("Over already", datetime(2026, 11, 1, tzinfo=UTC)),)

    assert await write_bubbles(past, writer=None, now=NOW) == ()


class _Invoker:
    """Stand in for the bridge, recording what it was asked."""

    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, tool_name: str, arguments: dict) -> object:
        self.calls.append((tool_name, arguments))
        return self.answer


@pytest.mark.asyncio
async def test_a_guid_answer_is_carried_back_from_the_send():
    invoker = _Invoker("A1B2C3D4-5E6F-7890-ABCD-EF1234567890")

    result = await MessagesAppChannel(invoker, "send_message").send("+1", "hello")

    assert result.delivered
    # Without this the bubble and its future tapback have nothing in common.
    assert result.provider_message_id == "A1B2C3D4-5E6F-7890-ABCD-EF1234567890"


@pytest.mark.asyncio
async def test_an_older_bridge_still_delivers_and_reports_no_identifier():
    invoker = _Invoker("sent")

    result = await MessagesAppChannel(invoker, "send_message").send("+1", "hello")

    # A bridge without Full Disk Access answers exactly as it always did. That
    # costs the feedback for this bubble and must cost nothing else.
    assert result.delivered
    assert result.provider_message_id is None


class _Sent:
    """A feedback repository that records calls instead of rows."""

    def __init__(self, pending: tuple[str, ...]) -> None:
        self.pending = pending
        self.recorded: list[tuple[str, str]] = []

    async def awaiting_reaction(self, limit: int = 200) -> tuple[str, ...]:
        return self.pending

    async def record_reaction(self, guid, reaction, at=None) -> bool:
        # Mirrors the real one: a GUID we never sent is not ours to record.
        if guid not in self.pending:
            return False
        self.recorded.append((guid, reaction))
        return True


@pytest.mark.asyncio
async def test_reactions_are_recorded_against_the_bubbles_they_name():
    sent = _Sent(("GUID-1", "GUID-2"))
    invoker = _Invoker(
        json.dumps(
            {
                "reactions": [
                    {"message_guid": "GUID-1", "reaction": "liked"},
                    {"message_guid": "GUID-2", "reaction": "disliked"},
                ]
            }
        )
    )

    recorded = await ReactionCollector(sent, invoker).collect()

    assert recorded == 2
    assert sent.recorded == [("GUID-1", "liked"), ("GUID-2", "disliked")]
    # Only the identifiers this asked about, which is what keeps the bridge from
    # being a way to read anything else on that Mac.
    assert invoker.calls[0][1] == {"message_guids": ["GUID-1", "GUID-2"]}


@pytest.mark.asyncio
async def test_a_reaction_for_a_bubble_we_never_sent_is_ignored():
    sent = _Sent(("GUID-1",))
    invoker = _Invoker(
        json.dumps(
            {"reactions": [{"message_guid": "SOMEONE-ELSES", "reaction": "liked"}]}
        )
    )

    assert await ReactionCollector(sent, invoker).collect() == 0
    assert sent.recorded == []


@pytest.mark.asyncio
async def test_an_unreadable_answer_records_nothing_and_does_not_raise():
    sent = _Sent(("GUID-1",))

    assert await ReactionCollector(sent, _Invoker("not json at all")).collect() == 0
    assert await ReactionCollector(sent, _Invoker(None)).collect() == 0


@pytest.mark.asyncio
async def test_an_unreachable_bridge_is_not_a_failure():
    sent = _Sent(("GUID-1",))

    class _Broken:
        async def __call__(self, tool_name, arguments):
            raise RuntimeError("the Mac is asleep")

    # A worker tick that cannot collect feedback has still done its real job.
    assert await ReactionCollector(sent, _Broken()).collect() == 0


@pytest.mark.asyncio
async def test_only_thumbs_are_taken_from_the_six_tapbacks():
    sent = _Sent(("GUID-1",))
    invoker = _Invoker(
        json.dumps({"reactions": [{"message_guid": "GUID-1", "reaction": "loved"}]})
    )

    # Loved, laughed, emphasised and questioned are all ambiguous about wanting
    # more of something, and guessing would put noise in the only clean signal.
    assert await ReactionCollector(sent, invoker).collect() == 0


@pytest.mark.asyncio
async def test_each_bubble_records_which_subscriber_received_it():
    import uuid as _uuid

    from backend.discovery.feedback import SentFindRepository

    recorded: list[dict] = []

    class _Session:
        def add(self, row):
            recorded.append(
                {"user_id": row.user_id, "subscriber_id": row.subscriber_id}
            )

        async def flush(self):
            return None

    guest = str(_uuid.uuid4())
    await SentFindRepository(_Session()).record_sent(
        user_id="alice",
        item_digest="d" * 64,
        label="A find",
        locality="Arlington, Virginia",
        message_guid="GUID-1",
        subscriber_id=guest,
    )

    # A digest goes to every subscriber, and subscribers are other people. Which
    # copy a reaction came back from is the whole boundary: without it a guest's
    # thumbs-down is indistinguishable from the owner's, and would train a feed
    # that is not theirs.
    assert recorded[0]["user_id"] == "alice"
    assert str(recorded[0]["subscriber_id"]) == guest


@pytest.mark.asyncio
async def test_a_delivery_result_defaults_to_no_identifier():
    # Every channel that has not thought about feedback reports none, rather
    # than something that would join to the wrong bubble.
    assert DeliveryResult(delivered=True).provider_message_id is None
