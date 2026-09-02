"""The classifier's utterance for a shared document: the sharer's words lead,
the document is marked as the document's voice, and it is bounded."""
from backend.services.document_facts import EXCERPT_CHARS, document_utterance, facts_utterance


def test_the_sharers_words_lead_and_the_document_is_marked():
    text = document_utterance("Itinerary.pdf", "we are going to do this trip", "## Day 1\n\nDinner in hotel")
    assert text.startswith("we are going to do this trip")
    assert '(shared a document "Itinerary.pdf", which says:)' in text
    assert "Dinner in hotel" in text


def test_page_markers_are_stripped_and_long_documents_are_bounded():
    body = "one <!-- page --> two\n\n\n\n" + ("x" * (EXCERPT_CHARS + 500))
    text = document_utterance("big.pdf", "", body)
    assert "<!--" not in text
    assert text.endswith("...")
    assert len(text) < EXCERPT_CHARS + 200


def test_no_caption_still_reads_as_a_share():
    assert document_utterance("lease.pdf", "   ", "Rent is due on the 1st").startswith("here's a document")


def test_the_facts_utterance_is_the_headline_or_the_declarative_caption():
    headline = "We are going on the Amalfi Choral Tour, October 11 to 15, staying at the Grand Hotel of Salerno."
    assert facts_utterance("we are going to do this trip. what do you think?", headline) == headline
    assert facts_utterance("we are going to do this trip. what do you think?", "") == "we are going to do this trip."
    assert facts_utterance("what is this?", "") == "I'm sharing this document."
