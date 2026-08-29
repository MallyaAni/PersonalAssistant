"""What the model writes when it is asked for links, and what the fence does about it.

The turn this replays went to a real phone on 2026-08-29: "Refresh recs",
eight live results about Canggu, and an answer carrying
`https://maps.app.goo.gl/xyz`, `/abc`, `/def`, `/ghi`, `/jkl` and
`https://youtu.be/xyz` - shortened links with placeholder ids. The events
format was never applied to that turn (the ranker did not flag the results
as events), so no prompt rule was even in play. That is the case here:
whatever the model writes, nothing unvouched may survive, and what the
sources really said must not be stripped along with it.
"""

from __future__ import annotations

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.core.links import URL_IN_TEXT, allowed_urls, canonical, fence_text

pytestmark = pytest.mark.asyncio

# Canggu-shaped results: real hosts, snippets that name venues and nights but
# publish no ticket links - which is exactly when a model starts inventing.
RESULTS = [
    {
        "title": "The Lawn Canggu - Sunday Sessions",
        "url": "https://www.thelawncanggu.com/whats-on",
        "content": "Sunday Sessions at The Lawn Canggu, Batu Bolong. Deep house from 4pm, free entry before 6pm.",
        "provider": "brave",
    },
    {
        "title": "La Brisa Bali - upcoming events",
        "url": "https://labrisabali.com/events",
        "content": "La Brisa, Echo Beach, Canggu. Sunset sessions with resident DJs, Thursdays and Saturdays.",
        "provider": "brave",
    },
    {
        "title": "Finns Beach Club Canggu",
        "url": "https://finnsbeachclub.com/whats-on",
        "content": "Finns Beach Club, Berawa, Canggu. Pool parties daily, entry IDR 250k including a sunbed.",
        "provider": "brave",
    },
]
ALLOWED = allowed_urls(RESULTS)
EVIDENCE = " ".join(f"{item['title']} {item['content']}" for item in RESULTS)


def _context() -> dict:
    return {"channel": "imessage", "search": RESULTS, "query": "Refresh recs"}


def _reply(llm) -> str:
    context = _context()
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": "Refresh recs"})
    return str(llm.chat(messages, 700, None, 0.0)["content"]).strip()


async def test_nothing_the_sources_did_not_carry_survives_the_fence(llm):
    raw = _reply(llm)
    fenced, dropped = fence_text(raw, ALLOWED, EVIDENCE)

    # The measurement first: what the model reached for on its own. Printed
    # rather than asserted - the model is the ceiling, the fence is the gate.
    print(f"\nraw links: {URL_IN_TEXT.findall(raw)}\ndropped: {dropped}\n--- fenced ---\n{fenced}")

    # The gate: every address left standing is one the application can vouch
    # for. This is the arsalon failure, made structurally impossible.
    for url in URL_IN_TEXT.findall(fenced):
        cleaned = url.rstrip(".,;:!?)]}\"'")
        vouched = canonical(cleaned) in ALLOWED or "google.com" in cleaned or "youtube.com/results" in cleaned
        assert vouched, (cleaned, fenced)
    for invented in ("maps.app.goo.gl", "youtu.be/", "goo.gl/"):
        assert invented not in fenced, fenced


async def test_the_fence_does_not_strip_what_the_sources_really_said(llm):
    # The other way a fence fails: quietly gutting a good answer. Any source
    # link the model quoted correctly must still be there afterwards.
    raw = _reply(llm)
    fenced, _dropped = fence_text(raw, ALLOWED, EVIDENCE)
    quoted = [
        item["url"] for item in RESULTS if canonical(item["url"]) in {canonical(u) for u in URL_IN_TEXT.findall(raw)}
    ]
    for url in quoted:
        assert url.rstrip("/") in fenced or url in fenced, (url, fenced)
    # And the answer is still an answer, not a husk.
    assert len(fenced.split()) >= 25, fenced


async def test_a_reply_with_no_search_behind_it_keeps_no_address(llm):
    # The ranker-missed case in its purest form: no evidence at all.
    context = {"channel": "imessage", "query": "where can I read about Canggu nightlife?"}
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": "where can I read about Canggu nightlife?"})
    raw = str(llm.chat(messages, 400, None, 0.0)["content"]).strip()
    fenced, dropped = fence_text(raw, frozenset(), "")
    print(f"\nraw links with no evidence: {URL_IN_TEXT.findall(raw)} | dropped: {dropped}")
    assert not URL_IN_TEXT.findall(fenced), fenced
    assert fenced.strip(), "the answer itself must survive"
