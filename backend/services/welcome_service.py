"""The first message a newly approved person receives.

Approving someone is the moment they become reachable, and until now it was
also the moment they were left to guess. They got an account and a bridge
grant and no indication that anything was listening, what it could do, or that
they could simply write to it in ordinary words.

**The message is generated, not stored.** It is written by the reply model from
the same capability list the router offers as tools, so it describes what the
system can do today rather than what it could do when someone last edited a
paragraph. A tool that stops being offered stops being mentioned; one that is
added starts being mentioned with no edit anywhere. The alternative - a fixed
welcome - is accurate exactly once and then quietly starts lying, and it lies
to the person least able to notice, since this arrives before they have any
history to judge it against.

Two failure rules shape everything below.

**It must never send twice.** A duplicate introduction to someone who has been
using the assistant for a month is a clear signal that nobody is minding the
system. The account carries `welcomed_at`, set only after the bridge reports
delivery, and it is the single thing consulted before sending.

**It must never cost someone their approval.** Generation calls a model and
delivery calls a Mac, and both can be down. An approval that rolled back
because an introduction failed would be a far worse outcome than an approval
with no introduction, so every failure here is caught, reported to the
operator, and left recoverable.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Bounded so a model that ignores the length rule cannot produce a wall of text,
# and so the result stays inside the channel's own 4,000-character ceiling with
# room to spare. Roughly 200 words at four characters a token.
MAX_WELCOME_TOKENS = 400

# Deterministic. This is the same message for everyone approved on the same
# build, and there is no upside to it varying: a warmer sample is a chance to
# invent a capability, which is the one failure that matters here.
WELCOME_TEMPERATURE = 0.0


class WelcomeNotSent(RuntimeError):
    """Delivery did not happen, with a reason the operator can act on."""


# Build the message for one person, from what the system can currently do.
#
# The agent roster and capability list are rendered by the same helpers the
# reply prompt uses, deliberately: a second renderer here would drift, and the
# failure would be an introduction describing a system that no longer exists.
async def build_welcome(
    db: AsyncSession,
    *,
    user_id: str,
    display_name: str,
    llm: Any,
    capabilities: list[dict[str, str]],
) -> str:
    from backend.agents.graph import (
        _render_agent_context,
        _render_capability_context,
    )
    from backend.agents.registry import AgentRegistry
    from backend.core.prompts import render

    agents = await AgentRegistry(db).describe_all(user_id)

    prompt = render(
        "welcome/system",
        display_name=display_name,
        agents=_render_agent_context([agent.to_dict() for agent in agents]),
        capabilities=_render_capability_context(capabilities),
    )

    answer = llm.chat(
        [
            {"role": "system", "content": prompt},
            # The model is given the task as a turn rather than only as a system
            # instruction: asked purely in the system slot, it tends to answer
            # *about* the message ("Here is a welcome you could send") instead
            # of writing it.
            {
                "role": "user",
                "content": (
                    f"Write the welcome message for {display_name} now. "
                    "Return only the message."
                ),
            },
        ],
        MAX_WELCOME_TOKENS,
        None,
        WELCOME_TEMPERATURE,
    )
    text = _text_of(answer).strip()
    if not text:
        raise WelcomeNotSent("the model returned nothing")
    return _unwrap(text)


# What the turn router can actually do, asked of the selector that offers it.
#
# The selector is request-scoped and built from five dependencies, so it is
# handed in rather than constructed here. Failing soft: a welcome naming fewer
# capabilities is a smaller loss than no welcome at all.
def describe_capabilities(selector: Any) -> list[dict[str, str]]:
    try:
        return list(selector.describe_capabilities())
    except Exception:
        logger.warning("welcome_capabilities_unavailable", exc_info=True)
        return []


# Send the welcome, once, and record that it went.
#
# Returns a short word for the operator's response rather than raising: the
# caller has already approved the account, and the outcome of this is
# information, not a verdict on that decision.
async def send_welcome_if_new(
    db: AsyncSession,
    *,
    user_id: str,
    display_name: str,
    selector: Any,
) -> str:
    from backend.models.auth import UserAccount

    account = await db.get(UserAccount, user_id)
    if account is None:
        return "no_account"
    # The single guard against a second introduction. Checked before any work,
    # so a retry after a partial failure is cheap and safe.
    if account.welcomed_at is not None:
        return "already_welcomed"

    try:
        from backend.core.dependencies import get_llm_client

        message = await build_welcome(
            db,
            user_id=user_id,
            display_name=display_name,
            llm=get_llm_client(),
            capabilities=describe_capabilities(selector),
        )
    except Exception:
        logger.warning(
            "welcome_not_generated for %s; they were approved but not introduced",
            user_id,
            exc_info=True,
        )
        return "not_generated"

    try:
        delivered = await _deliver(db, user_id=user_id, message=message)
    except Exception:
        logger.warning("welcome_not_delivered for %s", user_id, exc_info=True)
        return "not_delivered"

    if not delivered:
        return "not_delivered"

    # Only after the bridge confirmed. Marking on generation would burn the one
    # chance to introduce someone whose Mac happened to be asleep.
    account.welcomed_at = datetime.now(UTC)
    return "sent"


# Put it on the wire, through the ordinary channel so the allowlist and audit
# that govern every other outbound message govern this one too.
async def _deliver(db: AsyncSession, *, user_id: str, message: str) -> bool:
    from backend.core.dependencies import get_discovery_channels
    from backend.discovery.subscribers import SubscriberRepository

    subscribers = await SubscriberRepository(db).list_subscribers(
        user_id, deliverable_only=True
    )
    target = next((s for s in subscribers if s.channel == "imessage"), None)
    if target is None:
        # Approved through a path that enrolled no number - an older request
        # with no phone on it. Nothing is wrong; there is simply nowhere to send.
        return False

    channel = get_discovery_channels()["imessage"]
    result = await channel.send(target.address, message)
    if not result.delivered:
        logger.warning(
            "welcome_refused for %s: %s", user_id, result.error_code or "unknown"
        )
    return bool(result.delivered)


# The text out of whatever shape the client returned.
def _text_of(answer: object) -> str:
    if isinstance(answer, str):
        return answer
    if isinstance(answer, dict):
        return str(answer.get("content") or "")
    return str(getattr(answer, "content", "") or "")


# Strip a wrapping pair of quotes, which a model adds when it reads "return
# only the message" as "return the message as a quoted string".
def _unwrap(text: str) -> str:
    for quote in ('"', "'", "“"):
        if text.startswith(quote) and text[-1] in '"\'”':
            return text[1:-1].strip()
    return text
