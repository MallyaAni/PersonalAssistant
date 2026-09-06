"""The link follow-up builds grounded links by code, one event at a time.

The listing offers links and this is what actually delivers them. Every
address must be one code could construct or a source page stated - a model
handed the same records wrote invented map links on 2026-08-29, which is why
the fence exists and why these are built here.
"""

from datetime import UTC, datetime, time

from backend.core.event_extraction import ListedEvent
from backend.core.event_links import event_link_lines, render_links_for
from backend.core.links import URL_IN_TEXT, template_is_grounded

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
