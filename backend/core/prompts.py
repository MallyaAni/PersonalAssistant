"""Load the prompts that live as editable text rather than as Python.

A prompt is the part of this system most worth changing and the part least
worth recompiling to change. Keeping them in `prompts/` means the wording can
be tuned, diffed and reverted on its own, by someone who does not want to open
a service module to do it - and a bad edit shows up as a prompt change in the
history rather than as a line buried in a refactor.

The file is the only copy. There is no in-code default to fall back on,
because a fallback is how a deployment ends up quietly running wording nobody
is looking at: a missing or empty file fails at startup, where it is obvious.

Placeholders are `{name}` and are filled by the caller with `render()`. A
prompt that names a placeholder the caller does not supply is an error too,
rather than reaching a model as a literal brace.
"""

from functools import lru_cache
from pathlib import Path
from string import Formatter

# The repository's prompts directory, resolved from this file so it works the
# same in the container (where the tree is copied to /app) and on a host.
PROMPT_ROOT = Path(__file__).resolve().parents[2] / "prompts"


class PromptError(RuntimeError):
    """A prompt is missing, empty, or asked for something it was not given."""


# Read one prompt by its path under `prompts/`, without the extension.
#
# Cached because prompts do not change while the process runs; editing one
# means a restart, the same as any other deployment change.
@lru_cache(maxsize=128)
def load(name: str) -> str:
    path = PROMPT_ROOT / f"{name}.md"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"prompt {name!r} is missing at {path}") from exc
    body = _strip_notes(name, raw).strip()
    if not body:
        raise PromptError(f"prompt {name!r} is empty at {path}")
    return body


# Fill a prompt's placeholders, refusing to leave one unfilled.
def render(name: str, **values: object) -> str:
    text = load(name)
    expected = {
        field
        for _literal, field, _spec, _conv in Formatter().parse(text)
        if field
    }
    missing = expected - set(values)
    if missing:
        raise PromptError(
            f"prompt {name!r} needs {sorted(missing)}, which the caller did "
            f"not supply"
        )
    return text.format(**values)


# The line that separates the notes from the prompt. Matched by its opening
# run so the trailing words can be reworded without touching every file.
SEPARATOR = "===== PROMPT BELOW"


# Everything above the separator is editorial: what this prompt is for, where
# it is used, and what breaks when it is wrong. It is for the person editing
# the file and must never reach a model.
#
# A `---` rule was the separator first and it was far too quiet: notes are
# prose and the prompt is prose, so with a faint line between them there was no
# telling at a glance which half a sentence belonged to. A file with no
# separator is rejected rather than guessed at, because guessing is how the
# notes end up being sent to a model.
def _strip_notes(name: str, raw: str) -> str:
    for line in raw.splitlines():
        if line.startswith(SEPARATOR):
            return raw.split(line, 1)[1]
    raise PromptError(
        f"prompt {name!r} has no {SEPARATOR!r} line, so there is no way to "
        f"tell its notes from the text meant for the model"
    )
