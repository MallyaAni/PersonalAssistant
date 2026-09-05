"""What a tool declares about itself governs what may be done with it.

The contract replaced four rules kept in four places: the automation
allowlist for later steps, trust-equals-replay-safe for MCP retries, the
creation lambda, and the repr repeat guard. These pin the policy each field
now carries, and that every built-in row actually declares one.
"""

import pytest

from backend.core.effects import (
    SLOW_STEP_NEEDS_SECONDS,
    UNDECLARED,
    EffectContract,
    contract_for_classification,
    narrow,
)
from backend.tools import (
    action_creates,
    action_key,
    contract_for_action,
    later_step_tools,
)
from backend.tools.actions import (
    ManageCheckInsAction,
    ManageTasksAction,
    ScheduleTaskAction,
    ScoutScheduleAction,
    SearchAction,
)
from backend.tools.registry import _MODULES


# A read that is quick is always a later step; a slow one needs time in hand;
# an expensive one, anything needing approval, and anything that sends or
# spends are the turn's own request or nothing.
@pytest.mark.parametrize(
    ("contract", "remaining", "allowed"),
    [
        (EffectContract("read", "fast"), 1.0, True),
        (EffectContract("read", "slow"), SLOW_STEP_NEEDS_SECONDS, True),
        (EffectContract("read", "slow"), SLOW_STEP_NEEDS_SECONDS - 1, False),
        (EffectContract("write", "fast"), 1.0, True),
        (EffectContract("write", "expensive"), 100.0, False),
        (EffectContract("send", "fast"), 100.0, False),
        (EffectContract("spend", "fast"), 100.0, False),
        (EffectContract("mutate_external", "fast"), 100.0, False),
        (EffectContract("read", "fast", approval="consequential"), 100.0, False),
        (UNDECLARED, 100.0, False),
    ],
)
def test_what_a_later_step_may_start(contract, remaining, allowed):
    assert contract.allows_later_step(remaining) is allowed


# Only a read or a keyed call is ever replayed, whatever is declared.
def test_replay_is_derived_from_the_effect_and_only_made_safer_by_declaration():
    assert EffectContract("read", "fast").retry_policy == "replay_safe"
    assert EffectContract("write", "fast").retry_policy == "never"
    assert EffectContract("write", "fast", retry="replay_safe").retry_policy == "never"
    keyed = EffectContract("write", "fast", idempotency=lambda a: "k", retry="replay_safe")
    assert keyed.retry_policy == "replay_safe"
    assert EffectContract("read", "fast", retry="never").retry_policy == "never"


# A trusted server's call changes something outside this system: never
# replayed and never a later step, unlike a read-only one. Trust only means
# it may be called without asking.
def test_trust_is_not_idempotency():
    assert contract_for_classification("read_only").retry_policy == "replay_safe"
    trusted = contract_for_classification("trusted")
    assert trusted.retry_policy == "never"
    assert trusted.approval == "never"
    assert trusted.allows_later_step(60.0) is False
    assert contract_for_classification("untrusted").approval == "consequential"


# A per-tool declaration can raise the approval its server implies, never lower it.
def test_narrowing_never_lowers_approval():
    base = contract_for_classification("untrusted")
    declared = EffectContract("read", "fast", approval="never")
    assert narrow(base, declared).approval == "consequential"
    raised = EffectContract("read", "fast", approval="always")
    assert narrow(contract_for_classification("read_only"), raised).approval == "always"


def test_a_contract_refuses_a_value_policy_does_not_know():
    with pytest.raises(ValueError, match="unknown effect"):
        EffectContract("delete")
    with pytest.raises(ValueError, match="unknown cost"):
        EffectContract("read", "cheap")
    with pytest.raises(ValueError, match="unknown approval"):
        EffectContract("read", "fast", approval="maybe")


# Every built-in row declares what it does; an undeclared one would be
# silently offered to no later step, which is safe and also invisible.
def test_every_builtin_row_declares_a_contract():
    undeclared = [module.NAME for module in _MODULES if module.TOOL.contract is UNDECLARED]
    assert undeclared == [], undeclared


# The later-step set is read off the rows: bookkeeping and reads are in it,
# the generating tools are not, and a slow search needs budget.
def test_later_step_tools_follow_the_contracts():
    with_time = later_step_tools(45.0)
    assert {"schedule_task", "manage_tasks", "search_history", "search_web"} <= with_time
    assert not (
        {"generate_image", "edit_image", "create_diagram", "create_document",
         "edit_document", "delegate_to_presentation_agent"}
        & with_time
    )
    assert "search_web" not in later_step_tools(5.0)


# The same reminder worded twice is one key; two different reminders are two.
def test_schedule_keys_normalise_words_and_keep_the_time():
    first = ScheduleTaskAction("Call  Mum", "once", 18, 0, 0, "2026-09-05")
    same = ScheduleTaskAction("call mum", "once", 18, 0, 0, "2026-09-05")
    other = ScheduleTaskAction("call mum", "once", 20, 0, 0, "2026-09-05")
    assert action_key(first) == action_key(same)
    assert action_key(first) != action_key(other)
    assert action_key(first).startswith("schedule_task:")


# One sweep schedule per person: a second "set" is the same key whatever its
# arguments, and "show" is not a creation at all.
def test_scout_schedule_is_a_singleton_key():
    weekly = ScoutScheduleAction("weekly", 9, 0, 6, "set")
    daily = ScoutScheduleAction("daily", 21, 25, 0, "set")
    assert action_key(weekly) == action_key(daily)
    assert action_creates(weekly) is True
    assert action_creates(ScoutScheduleAction("daily", 9, 0, 0, "show")) is False


def test_only_arming_a_check_in_creates():
    assert action_creates(ManageCheckInsAction(mode="once", subject="the dentist")) is True
    assert action_creates(ManageCheckInsAction(mode="status")) is False
    assert action_creates(ManageTasksAction("cancel", "the gym one")) is False


def test_a_search_is_a_slow_read_keyed_on_its_query():
    contract = contract_for_action(SearchAction("salsa nights arlington"))
    assert contract.effect == "read"
    assert contract.cost == "slow"
    assert action_key(SearchAction("Salsa  nights arlington")) == action_key(
        SearchAction("salsa nights arlington")
    )
