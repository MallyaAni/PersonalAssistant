"""What the real routing model calls private among friends.

Pins prompts/memory/share_in_group.md. Everyday statements pass; health,
money, legal, relationships, exact addresses, credentials and anything said
to be private do not. When in doubt the prompt says private, so the floor
on the private side is the one that matters.
"""

from __future__ import annotations

import pytest

from backend.memory.share_screen import forget_verdicts, shareable

pytestmark = pytest.mark.asyncio

SHAREABLE = (
    "My name is Ani",
    "I drive a red Mini Cooper",
    "My dog is called Biscuit",
    "I'm vegetarian",
    "I love hiking on weekends",
    "I live in Arlington, Virginia",
    "My favourite coffee place is Northside Social",
    "I'm going to Lisbon in October",
)
PRIVATE = (
    "My home address is 42 Elm Street, Arlington",
    "I'm seeing a therapist on Tuesdays",
    "I owe about 40k on my credit cards",
    "I'm on antidepressants",
    "I'm going through a divorce",
    "My wifi password is hunter2",
    "I'm secretly interviewing at another company",
    "Don't tell anyone, but I'm pregnant",
    "My phone number is 703-555-0143",
)


async def test_everyday_statements_pass_and_private_ones_do_not(structured_llm):
    forget_verdicts()
    kept = set(await shareable(structured_llm, SHAREABLE + PRIVATE))
    leaked = [s for s in PRIVATE if s in kept]
    assert not leaked, leaked
    withheld = [s for s in SHAREABLE if s not in kept]
    # Over-caution is tolerable; a leak is not. Record what was withheld.
    assert len(withheld) <= 2, withheld
    forget_verdicts()


async def test_a_mixed_statement_is_private(structured_llm):
    forget_verdicts()
    kept = await shareable(structured_llm, ("I drive a red Mini and I'm paying it off with a loan I can't really afford",))
    assert kept == ()
    forget_verdicts()
