"""Editing a Word file in place keeps everything but its body: styles,
footer, page setup, and the parts a real file carries (a header with a logo)
are byte-identical; the new body is written in the original's own style ids
and numbering."""
import io
import zipfile

import pytest

from backend.services.document_editor import EditError, edit_docx, is_docx
from backend.services.document_writer import render_docx

ORIGINAL_BODY = "# Choral Tour 2026\n\n## Day 1\n- Arrive Salerno\n- Dinner at the hotel\n\nA plain paragraph."
REVISED = "# Choral Tour 2026 (revised)\n\n## Day 1 - Arrival\n- Arrive Salerno, 6pm orientation\n- 7:30pm dinner\n\n## Day 2 - Pompeii only\nAfternoon free for **Amalfi** town."


def _parts(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _word_original() -> bytes:
    # The writer's own file stands in for someone's Word file: it has a
    # styles part with Title/Heading/ListBullet ids, a footer, and a section.
    return render_docx("Choral Tour 2026", ORIGINAL_BODY)


def test_everything_but_the_body_is_kept_byte_for_byte():
    original = _word_original()
    edited = edit_docx(original, "Choral Tour 2026 (revised)", REVISED)
    before, after = _parts(original), _parts(edited)
    assert set(before) == set(after)
    for name in before:
        if name != "word/document.xml":
            assert before[name] == after[name], f"{name} changed"


def test_the_new_body_uses_the_originals_own_styles_and_keeps_its_section():
    original = _word_original()
    edited = _parts(edit_docx(original, "Choral Tour 2026 (revised)", REVISED))["word/document.xml"].decode("utf-8")
    assert 'w:pStyle w:val="Title"' in edited and "Choral Tour 2026 (revised)" in edited
    assert 'w:pStyle w:val="Heading2"' in edited and "Day 2 - Pompeii only" in edited
    assert 'w:pStyle w:val="ListBullet"' in edited and "7:30pm dinner" in edited
    assert "<w:b/>" in edited and "Amalfi" in edited
    assert "<w:sectPr" in edited and "<w:footerReference" in edited
    # The old body is gone.
    assert "A plain paragraph." not in edited and "Dinner at the hotel" not in edited


def test_a_file_without_heading_styles_still_gets_a_readable_body():
    # A bare Word file: a document part and nothing else, as the upload tests build.
    from backend.tests.functional.fixtures.make_docx import make_docx

    original = make_docx(["Old line one", "Old line two"])
    edited = _parts(edit_docx(original, "New title", "## Section\n- a point\n\nBody text."))["word/document.xml"].decode("utf-8")
    assert "New title" in edited and "Section" in edited and "• a point" in edited and "Body text." in edited
    assert "Old line one" not in edited


def test_a_non_word_file_is_refused_and_recognised():
    assert is_docx(_word_original())
    assert not is_docx(b"%PDF-1.4 not a word file")
    with pytest.raises(EditError):
        edit_docx(b"%PDF-1.4 not a word file", "t", "body")
