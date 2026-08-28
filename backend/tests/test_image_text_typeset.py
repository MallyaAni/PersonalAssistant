"""Quoted words are typeset onto the picture; the language instruction leads."""

from __future__ import annotations

import os
from io import BytesIO

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from PIL import Image

from backend.artifacts.image import ComfyUIImageProvider, quoted_words, typeset_onto, without_quoted_words


def test_quoted_phrases_are_found_and_replaced_by_a_blank_space():
    prompt = 'a wooden sign reading "Welcome to Arlington" beside a road, with a banner saying “Fall Fest 2026”'
    assert quoted_words(prompt) == ["Welcome to Arlington", "Fall Fest 2026"]
    stripped = without_quoted_words(prompt)
    assert "Welcome" not in stripped and "Fall Fest" not in stripped
    assert stripped.count("a blank space for lettering") == 2
    assert quoted_words("a brown horse wearing a pink hat") == []


def test_words_are_drawn_onto_the_picture_as_a_readable_band():
    canvas = Image.new("RGB", (640, 400), (30, 120, 200))
    buffer = BytesIO(); canvas.save(buffer, format="PNG")
    out = typeset_onto(buffer.getvalue(), ["Welcome to Arlington"])
    with Image.open(BytesIO(out)) as result:
        assert result.size == (640, 400)
        bottom = result.crop((0, 340, 640, 400)).convert("L")
        top = result.crop((0, 0, 640, 60)).convert("L")
        assert bottom.getextrema()[1] > 240, "no white lettering in the band"
        assert sum(bottom.getdata()) / (640 * 60) < sum(top.getdata()) / (640 * 60), "the band is not darker than the sky"


def test_the_prefix_leads_and_the_quoted_words_leave_the_diffusion_prompt():
    provider = ComfyUIImageProvider.__new__(ComfyUIImageProvider)
    provider.style_suffix = ""
    provider.portrait_suffix = ""
    provider.text_suffix = "any writing in the picture is in clear, correctly spelled English"
    provider.text_prefix = "English lettering only:"
    provider.text_overlay = True
    composed = provider._positive_prompt('a chalkboard menu that says "Soup of the day"')
    assert composed.startswith("English lettering only: a chalkboard menu")
    assert "Soup of the day" not in composed and "a blank space for lettering" in composed
    assert composed.endswith("correctly spelled English")
