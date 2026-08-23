"""Two defects the step loop shipped with, pinned so they cannot come back.

Both were found by re-reading the loop against the code around it rather than
by anything failing, which is why they get assertions rather than a comment.

1. `_local_now` is `async def`. The loop called it without `await`, so the
   second and later routing decisions were handed a **coroutine object** where
   a date string belongs. `select` renders it straight into the prompt, so the
   model would have read `Current date and time: <coroutine object ...>` and
   lost the one fact it cannot infer - what "tomorrow" means. It never fired in
   production only because `TURN_MAX_STEPS` ships at 1 and the loop body is
   unreachable; it would have fired on the first turn after the flag was
   raised. The sibling call at :494 was correct, which is what makes this the
   kind of mistake a reader skims past.

2. `ConversationService.__init__` handed `llm` to the graph builder and never
   kept it, while two call sites - the task picker and the skill picker - read
   `self.llm` when no action selector is wired. That path raises
   AttributeError instead of degrading.
"""

import inspect

import pytest

from backend.services import conversation_service as module
from backend.services.conversation_service import ConversationService


class _Llm:
    """Stands in for an LLMClient; only identity is asserted on."""


# The constructor must keep the client, not only hand it to the graph.
def test_the_service_keeps_the_llm_it_was_given(monkeypatch) -> None:
    monkeypatch.setattr(module, "build_assistant_graph", lambda llm: object())
    service = ConversationService.__new__(ConversationService)
    llm = _Llm()

    # Run only the two lines under test; the full constructor wires a dozen
    # collaborators that have nothing to do with this.
    service.llm = llm
    service.assistant_graph = module.build_assistant_graph(llm)

    assert service.llm is llm

    # And the real constructor must do the same. Read the source of __init__
    # rather than building one, because building one needs every collaborator.
    source = inspect.getsource(ConversationService.__init__)
    assert "self.llm = llm" in source, (
        "__init__ no longer keeps the llm; _manage_tasks and the skill picker "
        "read self.llm and would raise AttributeError"
    )


# Every call to the async clock must be awaited, or a coroutine reaches a prompt.
def test_the_clock_is_never_passed_unawaited() -> None:
    # Scan the whole module rather than a list of methods: a list is the thing
    # that goes stale when a third call site appears.
    source = inspect.getsource(module)
    checked = 0
    for line in source.splitlines():
        if "self._local_now(" not in line or line.strip().startswith("#"):
            continue
        if "async def" in line:
            continue
        checked += 1
        assert "await self._local_now(" in line, (
            f"_local_now is async; this passes the coroutine itself: {line.strip()}"
        )
    assert checked >= 2, f"expected several call sites, scanned {checked}"


# _local_now really is a coroutine function - the assertion above is only
# meaningful while that holds, and a future rewrite to a sync helper should
# fail here loudly rather than leave the checks above quietly vacuous.
def test_local_now_is_still_async() -> None:
    assert inspect.iscoroutinefunction(ConversationService._local_now)
