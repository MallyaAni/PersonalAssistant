"""Prompts kept as editable files still have to be correct.

Moving wording out of Python makes it tunable by someone who does not want to
open a service module. It also removes the compiler: a typo in a placeholder,
an emptied file, or a rename that misses a call site are all now runtime
faults, and each would reach a model as a broken instruction. These are the
checks that used to be free.
"""

import pytest

from backend.core.prompts import (
    PROMPT_ROOT,
    SEPARATOR,
    PromptError,
    load,
    render,
)

# README.md documents the folder rather than instructing a model, so it is not
# a prompt and must not be checked as one.
ALL_PROMPTS = sorted(
    path.relative_to(PROMPT_ROOT).with_suffix("").as_posix()
    for path in PROMPT_ROOT.rglob("*.md")
    if path.name != "README.md"
)


def test_there_are_prompts_to_check():
    assert ALL_PROMPTS, f"no prompts found under {PROMPT_ROOT}"


@pytest.mark.parametrize("name", ALL_PROMPTS)
def test_every_prompt_has_a_body_after_its_header(name: str):
    body = load(name)

    assert body
    # The header is for the person editing the file and must never be sent.
    assert "used by:" not in body
    assert "placeholders:" not in body


# A header naming where the prompt is used is the whole point of the folder:
# without it the file is wording with no home, and nobody tuning it knows what
# they are about to change.
@pytest.mark.parametrize("name", ALL_PROMPTS)
def test_every_prompt_says_where_it_is_used(name: str):
    raw = (PROMPT_ROOT / f"{name}.md").read_text(encoding="utf-8")
    header = raw.split("\n---\n", 1)[0]

    assert "used by:" in header, name
    assert "backend/" in header, name


def test_a_missing_prompt_fails_loudly_rather_than_returning_nothing():
    with pytest.raises(PromptError, match="missing"):
        load("search/does_not_exist")


# The failure this replaces: a template whose placeholder the caller forgot,
# reaching the model as a literal "{today}".
def test_an_unfilled_placeholder_is_refused():
    with pytest.raises(PromptError, match="needs"):
        render("search/compose", today="2026-08-19")


def test_a_fully_supplied_prompt_renders():
    text = render("search/compose", today="2026-08-19", cutoff="2026-04")

    assert "2026-08-19" in text
    assert "{" not in text.replace("{}", "")


# A `---` rule separated notes from prompt first, and it was too quiet to see:
# both halves are prose, so there was no telling at a glance which half a
# sentence belonged to. The separator is now unmissable, and required.
@pytest.mark.parametrize("name", ALL_PROMPTS)
def test_every_prompt_carries_the_separator(name: str):
    raw = (PROMPT_ROOT / f"{name}.md").read_text(encoding="utf-8")

    assert SEPARATOR in raw, name
    assert raw.count(SEPARATOR) == 1, f"{name} has more than one separator"


# Guessing where the notes end is how they get sent to a model, so a file
# without a separator is refused rather than interpreted.
def test_a_prompt_without_a_separator_is_refused(tmp_path, monkeypatch):
    from backend.core import prompts as loader

    (tmp_path / "stray.md").write_text("just some text", encoding="utf-8")
    monkeypatch.setattr(loader, "PROMPT_ROOT", tmp_path)
    loader.load.cache_clear()

    with pytest.raises(PromptError, match="no '===== PROMPT BELOW"):
        loader.load("stray")

    loader.load.cache_clear()
