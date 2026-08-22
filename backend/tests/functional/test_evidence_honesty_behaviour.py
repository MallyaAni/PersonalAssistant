"""A moving fact is stated only when a result states it, and links reach a phone.

A real exchange about a hard-to-find cable: the results confirmed one store
sold out, and the reply declared two other stores "in stock, 18-minute
pickup available" - then retracted it a turn later as "my own memory, not
what I can verify". A confident guess about availability sends someone
driving to a store that does not have the thing. These replay that shape
with the real prompt and the real evidence rendering: a follow-up asking
about stores the results never mention must not get invented stock, and
over iMessage - where there is no sources panel - a request for links
must carry a URL from the evidence.
"""

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages

pytestmark = pytest.mark.asyncio

# One result, one store, sold out. Nothing about any other location.
_EVIDENCE = {
    "search": [
        {
            "title": "Stacking DAC Cable QSFP/CX7 - Micro Center",
            "url": "https://www.example-retailer.com/product/968610",
            "content": (
                "Stacking DAC Cable QSFP/CX7, SKU 968610, $179.99. SOLD OUT at "
                "Columbus Store. Get a back-in-stock alert."
            ),
        }
    ]
}

_HISTORY = [
    {
        "role": "user",
        "content": "where can i drive to pick up the stacking cable today?",
    },
    {
        "role": "assistant",
        "content": (
            "The only store listing I found is Micro Center, and its Columbus "
            "store shows sold out. Want me to check the other locations?"
        ),
    },
]


def _messages(context: dict, query: str) -> list[dict]:
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(_HISTORY)
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": query})
    return messages


async def test_stock_is_never_asserted_for_a_store_the_results_never_mention(llm):
    from backend.tests.functional.semantic import states

    result = llm.chat(
        _messages(dict(_EVIDENCE), "sure, check rockville"), 400, None, 0.0
    )
    text = str(result["content"])

    assert text.strip()
    # Rockville appears nowhere in the evidence. Judged semantically rather
    # than by phrase: the first regex gate passed a reply that invented a
    # "sold out" for Rockville - the same lie as an invented "in stock".
    assert not states(
        text,
        "The reply claims to have checked Rockville or states whether "
        "Rockville has the cable in stock or sold out.",
    ), text
    assert states(
        text,
        "The reply says it could not confirm or has no information about "
        "Rockville specifically.",
    ), text


async def test_a_request_for_links_over_imessage_carries_a_url(llm):
    context = {**_EVIDENCE, "channel": "imessage"}
    result = llm.chat(_messages(context, "you got links?"), 400, None, 0.0)
    text = str(result["content"])

    assert "example-retailer.com" in text, text
