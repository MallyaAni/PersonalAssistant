"""Does anything the system knows about a person reach their recommendation?

A survey on 2026-08-29 found that on a real "what's on this weekend" turn, the
whole per-person signal was one line of interest labels used as a tie-breaker -
and that the eight labels sent were whichever eight had been saved first. For
the operator, whose twenty interests all carry the same strength, that meant
"farmers markets, vintage shops, traveling" reached the ranker while salsa,
bachata and swing dancing - the four that would have decided a Saturday-night
answer - sat below the cut.

The same survey found that the code-rendered events listing shipped that
morning had made this worse: the reply model, which holds the person's name,
place and memories, is not called on those turns at all, the extractor was
told nothing about the reader, and the listing kept the *earliest* events
rather than the ones the ranker judged the best fit.

These tests hold the three repairs.
"""

from __future__ import annotations

from datetime import UTC, datetime, time

from backend.core.event_extraction import Extraction, ListedEvent, build_extraction
from backend.core.events_listing import render_listing
from backend.memory.coordinator import build_memory_query_plan
from backend.services.conversation_service import _interests_for

NOW = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)

# The operator's own list, in the order it was saved. Every one is strength 2,
# so any "top N" over it is chronological accident.
ANI = (
    "line dancing", "hiking", "live music", "dancing", "unique local events",
    "farmers markets", "vintage shops/thrifting", "traveling", "salsa dance",
    "bachata dance", "east coast swing", "west coast swing", "chess",
    "board games", "karaoke", "wineries", "breweries", "swing dancing",
)


def test_the_interests_sent_are_the_ones_the_question_is_about():
    chosen = _interests_for("is there a salsa night this weekend?", ANI)
    assert "salsa dance" in chosen
    # It was the ninth saved, so it never survived a first-eight cut.
    assert ANI.index("salsa dance") >= 8


def test_a_question_naming_nothing_keeps_the_order_it_had():
    # No regression for the ordinary case: an unrelated question must not be
    # bent by a reshuffled interest list.
    assert _interests_for("what's on this weekend", ANI) == list(ANI[:8])


def test_the_cap_still_holds():
    assert len(_interests_for("salsa dancing and chess and karaoke", ANI)) == 8


def _event(name: str, day: int, rank: int) -> ListedEvent:
    return ListedEvent(
        name=name, venue=f"{name} hall", area="Arlington", artist="", what="x.",
        when_text="Saturday", recurring=False,
        starts_at=datetime(2026, 9, day, 18, 0, tzinfo=UTC), start_time=time(18, 0),
        price_text="", source_url=f"https://x.test/{day}", source_title=name,
        source_rank=rank,
    )


def test_the_listing_keeps_the_events_the_ranker_judged_best_not_the_earliest():
    # The ranker read the question, the place and what is known about the
    # person, and put the salsa night first. The craft fair merely happens
    # sooner. Cutting by date discards the only per-person judgement there is.
    found = Extraction((_event("Craft fair", 1, 7), _event("Salsa night", 5, 1), _event("Book sale", 2, 6)))
    shown = render_listing(found, NOW, limit=2)
    assert "Salsa night" in shown
    assert "Craft fair" not in shown


def test_what_survives_the_cut_is_still_read_in_date_order():
    # Fit decides who is in; the calendar decides the order they are read in,
    # because a listing grouped by day is how a person scans one.
    found = Extraction((_event("Later but best", 9, 1), _event("Sooner", 2, 2)))
    shown = render_listing(found, NOW, limit=2)
    assert shown.index("Sooner") < shown.index("Later but best")


def test_the_extractor_is_given_the_person_for_the_line_it_writes():
    # Structural: the signature carries it, and the caller passes what the
    # ranker used. The measurement that it changes the wording is in
    # functional/test_events_extraction_behaviour.py.
    import inspect

    from backend.core.event_extraction import extract_events

    assert "known" in inspect.signature(extract_events).parameters


def test_a_quotation_cannot_bend_to_the_person():
    # The safety property of giving the model a reader: it may change how an
    # event is described, never whether it exists or when. Every factual field
    # is still checked against the result it names.
    results = [{"title": "The Lawn", "url": "https://x.test/l",
                "content": "Sunday Sessions at The Lawn, Batu Bolong. Every Sunday from 4pm."}]
    # A real event from the page, with a time nobody published, described in
    # a way that flatters the reader. The name and venue are quotable, so this
    # record fails on the one thing that is invented: the time.
    invented = [{
        "source": 1, "name": "Sunday Sessions", "venue": "The Lawn", "area": "Batu Bolong",
        "artist": "", "when_text": "Every Saturday from 8pm", "when_kind": "recurring_weekday",
        "price_text": "", "what": "Exactly the salsa you love.",
    }]
    found = build_extraction(invented, results, NOW)
    assert found.events == () and found.undated == 1

    # And the same record with the time the page really states survives, so
    # the check above is about the invention rather than about strictness.
    honest = [{**invented[0], "when_text": "Every Sunday from 4pm"}]
    (kept,) = build_extraction(honest, results, NOW).events
    assert kept.name == "Sunday Sessions" and kept.start_time == time(16, 0)


def test_an_events_question_reaches_episodic_memory():
    # " event " with spaces does not match "events", so the commonest question
    # this store exists to serve was excluded by one letter.
    assert build_memory_query_plan("what events are happening this weekend").use_episodic
    assert build_memory_query_plan("what event is on tonight").use_episodic
    assert build_memory_query_plan("remember when we went").use_episodic


def test_an_unrelated_question_still_does_not():
    assert not build_memory_query_plan("what is the capital of Peru").use_episodic
    # And a fragment is not a word: "eventual" must not open the store.
    assert not build_memory_query_plan("tell me the eventual outcome").use_episodic
