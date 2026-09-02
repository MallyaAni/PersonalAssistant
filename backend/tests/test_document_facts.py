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


# The digest step reads three things: the headline, the statements split by
# whether they outlive the document's dates, and the last date it is about.
class _Llm:
    def __init__(self, payload):
        self.payload = payload

    def chat(self, messages, max_tokens, schema, temperature):
        import json

        return {"content": json.dumps(self.payload)}


def test_the_digest_reads_dated_statements_and_the_last_date():
    from datetime import date

    from backend.services.document_facts import digest_document

    digest = digest_document(
        _Llm({
            "headline": "We are going on the Amalfi Choral Tour, October 11 to 15.",
            "statements": [
                {"text": "We stay at the Grand Hotel of Salerno.", "dated": False},
                {"text": "The Pompeii excursion leaves at 8:30 on October 12.", "dated": True},
            ],
            "about_until": "2026-10-15",
        }),
        "Itinerary.pdf",
        "# Day 1 ...",
        "we are going to do this trip",
    )
    assert digest.headline.startswith("We are going")
    assert digest.statements == ["We stay at the Grand Hotel of Salerno."]
    assert digest.dated == ["The Pompeii excursion leaves at 8:30 on October 12."]
    assert digest.about_until == date(2026, 10, 15)


def test_an_undated_document_has_no_last_date_and_a_bad_date_is_none():
    from backend.services.document_facts import digest_document

    recipe = digest_document(_Llm({"headline": "", "statements": [], "about_until": ""}), "Sourdough.pdf", "# Sourdough", "")
    assert recipe.about_until is None and recipe.headline == ""
    odd = digest_document(_Llm({"headline": "x", "statements": ["plain string tolerated"], "about_until": "October 15th"}), "t", "b", "")
    assert odd.about_until is None and odd.statements == ["plain string tolerated"] and odd.dated == []
