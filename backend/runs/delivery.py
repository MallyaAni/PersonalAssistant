"""Tell the person how their run ended, on the channel the run was asked from.

A run that completes and tells nobody has not finished its job: the report
sits in `agent_runs` until someone opens the Agents tab. This delivers a
short, bounded message when a run reaches a stop the person should hear
about - completed, failed, or waiting for their approval - through the same
notification channels the discovery digest uses, to the address the person
enrolled for that channel. A run asked from the web has no push channel:
the runs API and the card are its delivery, and the event says so.

What is sent is a summary, never the evidence: findings with file names
and quoted lines stay behind the API, where the person is authenticated.
Delivery is recorded as an event on the run - delivered, skipped with why,
or failed with the channel's error - so a missing message is diagnosable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from backend.core.logging_config import get_logger
from backend.discovery.channels import NotificationChannel
from backend.runs.repository import AgentRunRepository

logger = get_logger(__name__)

# The stops a person hears about; a run that merely paused between attempts
# is not one of them.
NOTIFIED_STATUSES = frozenset({"completed", "failed", "waiting_approval"})
MAX_MESSAGE_CHARS = 600

# Finds the address a person enrolled for a channel, or None.
AddressResolver = Callable[[str, str], Awaitable[str | None]]


# The words for one run's stop, bounded, with no evidence in them.
def compose(run: Mapping[str, Any], outcome_status: str, summary: str) -> str:
    kind = str(run.get("kind") or "run").replace("_", " ")
    head = {
        "completed": f"Your {kind} finished.",
        "failed": f"Your {kind} stopped without finishing" + (
            f" ({run.get('error_code')})." if run.get("error_code") else "."
        ),
        "waiting_approval": f"Your {kind} is waiting for your approval before it goes on.",
    }.get(outcome_status, f"Your {kind} is {outcome_status}.")
    body = " ".join(str(summary or "").split())
    text = f"{head} {body}".strip()
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[: MAX_MESSAGE_CHARS - 1].rstrip() + "…"
    return text


class RunDelivery:
    """Send one run's stop to its person, and record what happened."""

    def __init__(
        self,
        channels: Mapping[str, NotificationChannel],
        resolve_address: AddressResolver,
    ) -> None:
        self.channels = channels
        self.resolve_address = resolve_address

    # Deliver if the stop and the channel call for it; always record.
    async def deliver(
        self, repo: AgentRunRepository, run: Mapping[str, Any], outcome_status: str, summary: str
    ) -> str:
        run_id = str(run["id"])
        if outcome_status not in NOTIFIED_STATUSES:
            return "not_a_stop"
        channel_id = str(run.get("channel") or "web")
        if channel_id == "web":
            await repo.record_event(run_id, "delivery_skipped", {"reason": "web: the runs API is the delivery"})
            return "web"
        channel = self.channels.get(channel_id)
        if channel is None:
            await repo.record_event(run_id, "delivery_skipped", {"reason": f"no channel {channel_id}"})
            return "no_channel"
        address = await self.resolve_address(str(run["user_id"]), channel_id)
        if not address:
            await repo.record_event(run_id, "delivery_skipped", {"reason": f"no {channel_id} address enrolled"})
            return "no_address"
        message = compose(run, outcome_status, summary)
        try:
            result = await channel.send(address, message)
        except Exception as exc:  # the channel promised not to raise; hold the line anyway
            logger.warning("run_delivery_raised", extra={"run_id": run_id}, exc_info=True)
            await repo.record_event(run_id, "delivery_failed", {"channel": channel_id, "error": type(exc).__name__})
            return "failed"
        if getattr(result, "delivered", False):
            await repo.record_event(run_id, "delivered", {"channel": channel_id, "chars": len(message)})
            return "delivered"
        error = str(getattr(result, "error_code", "") or "refused")
        await repo.record_event(run_id, "delivery_failed", {"channel": channel_id, "error": error[:120]})
        return "failed"
