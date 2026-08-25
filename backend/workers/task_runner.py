"""Fire scheduled tasks: claim a due run, converse as the person, deliver.

A task is the person's own instruction run later as an ordinary chat turn
under their identity, on the task's own conversation so its history is the
task's and not their live thread's. Delivery follows the channel the task
was made from: an iMessage task lands in the subscriber's thread through
the same bubble path a reply takes; a web task keeps its output on the run
for the UI to show.
"""

import asyncio
import uuid

import httpx
from sqlalchemy import select

from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.core.logging_config import get_logger
from backend.database.session import AsyncSessionLocal
from backend.tasks.repository import ScheduledTaskRepository
from backend.tasks.quiet import is_nothing_to_report
from backend.workers.imessage_chat import (
    _CHAT_TIMEOUT_SECONDS,
    IMessageChatWorker,
    TurnImage,
    TurnResult,
    _loads,
)

logger = get_logger(__name__)


class TaskRunner:
    """Produce due runs and work the oldest claimable one."""

    def __init__(
        self,
        invoke_tool,
        base_url: str | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.worker_id = worker_id or f"tasks-{uuid.uuid4().hex[:8]}"
        self.chat = IMessageChatWorker(invoke_tool, base_url=base_url)

    # Every task whose slot has arrived becomes a queued run.
    async def enqueue_due(self) -> int:
        async with AsyncSessionLocal() as db:
            created = await ScheduledTaskRepository(db).enqueue_due_runs()
        return len(created)

    # One run, or False when nothing is claimable. The lease is renewed
    # while the turn runs, so a slow generation is never mistaken for a dead
    # worker and handed to a second one that would deliver it twice.
    async def run_once(self) -> bool:
        async with AsyncSessionLocal() as db:
            run = await ScheduledTaskRepository(db).claim_next(
                self.worker_id, settings.SCHEDULED_TASK_LEASE_SECONDS
            )
        if run is None:
            return False
        task = run.get("task")
        if not task:
            await self._finish(run["id"], "failed", error_code="task_missing")
            return True
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._renew(run["id"], stop))
        try:
            turn = await self._turn(task)
        finally:
            stop.set()
            await asyncio.gather(heartbeat, return_exceptions=True)
        if turn is None:
            await self._finish(run["id"], "failed", task, error_code="turn_failed")
            return True
        await self._deliver(run["id"], task, turn)
        return True

    # Hold the claim while the turn runs.
    async def _renew(self, run_id: str, stop: asyncio.Event) -> None:
        interval = max(30.0, settings.SCHEDULED_TASK_LEASE_SECONDS / 3)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            async with AsyncSessionLocal() as db:
                await ScheduledTaskRepository(db).renew_lease(
                    run_id, self.worker_id, settings.SCHEDULED_TASK_LEASE_SECONDS
                )

    # The finished turn to where the task was made from.
    async def _deliver(self, run_id: str, task: dict, turn: TurnResult) -> None:
        # A check that found nothing worth saying stays silent. The reply
        # model is told (reply/scheduled_task) to answer with exactly this
        # token when the instruction says to speak only under a condition
        # that does not hold - "message me if search credits are low" fires
        # every morning, and a daily "still fine" is the noise that gets an
        # alert muted.
        if is_nothing_to_report(turn.reply):
            await self._finish(run_id, "quiet", task, turn.reply)
            return
        if task["channel"] != "imessage":
            await self._finish(run_id, "completed", task, turn.reply)
            return
        address = await self._address_for(task["user_id"])
        if address is None:
            await self._finish(
                run_id, "undeliverable", task, turn.reply, "no_subscriber"
            )
            return
        try:
            await self.chat._deliver(address, turn)
        except Exception as exc:
            logger.warning(
                "scheduled_task_delivery_failed: %s: %s",
                type(exc).__name__,
                str(exc)[:200],
            )
            await self._finish(run_id, "failed", task, turn.reply, "delivery_failed")
            return
        await self._finish(run_id, "delivered", task, turn.reply)

    # Close a run, or put it back on the queue when it still has attempts.
    # A run that has finally given up is told to the person rather than
    # dying in the table: a one-time reminder that never arrives is worse
    # than one that arrives saying it could not be done.
    async def _finish(
        self,
        run_id: str,
        status: str,
        task: dict | None = None,
        output: str | None = None,
        error_code: str | None = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            outcome = await ScheduledTaskRepository(db).finish(
                run_id, status, output, error_code, worker_id=self.worker_id
            )
        logger.info(
            "scheduled_task_run_finished",
            extra={"run": run_id, "status": outcome, "error": error_code},
        )
        if outcome == "failed" and task is not None:
            await self._apologize(task)

    # One short line on the task's own channel when a firing is given up on.
    async def _apologize(self, task: dict) -> None:
        if task.get("channel") != "imessage":
            return
        address = await self._address_for(str(task["user_id"]))
        if address is None:
            return
        instruction = str(task.get("instruction") or "your scheduled task")
        try:
            await self.chat.invoke_tool(
                settings.DISCOVERY_IMESSAGE_TOOL,
                {
                    "to": address,
                    "body": (
                        "Heads up - I couldn't run your scheduled task "
                        f'("{instruction[:80]}") just now. It stays on your '
                        "schedule; tell me if you want it changed."
                    ),
                },
            )
        except Exception:
            logger.warning("scheduled_task_apology_failed", extra={"task": task["id"]})

    # The instruction as a chat turn on the task's own conversation. Marked
    # so the reply model knows it is a firing, not a person typing.
    async def _turn(self, task: dict) -> TurnResult | None:
        user_id = str(task["user_id"])
        token = issue_user_token(user_id, ttl_seconds=900, scopes=["chat", "vision"])
        body = {
            "user_id": user_id,
            "query": task["instruction"],
            "conversation_id": task["conversation_id"],
            "metadata": {"channel": task["channel"], "scheduled_task": True},
        }
        collected: list[str] = []
        images: list[TurnImage] = []
        try:
            async with (
                httpx.AsyncClient(timeout=_CHAT_TIMEOUT_SECONDS) as client,
                client.stream(
                    "POST",
                    f"{self.chat.base_url}/api/v1/chat",
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                ) as response,
            ):
                response.raise_for_status()
                event = ""
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event = line[7:].strip()
                    elif line.startswith("data: "):
                        await self._consume(event, _loads(line[6:]), collected, images)
            for image in images:
                if image.data_base64 is None:
                    fetched = await self.chat._fetch_artifact(
                        user_id, image.artifact_id, token
                    )
                    if fetched is not None:
                        image.data_base64, image.media_type = fetched
        except Exception as exc:
            logger.warning(
                "scheduled_task_turn_failed: %s: %s",
                type(exc).__name__,
                str(exc)[:200],
                extra={"user": user_id},
            )
            return None
        reply = "".join(collected).strip()
        carried = tuple(image for image in images if image.data_base64)
        if not reply and not carried:
            return None
        return TurnResult(reply, carried)

    # The same events the chat worker reads, minus remembering the
    # conversation: a task's thread must never become the person's live one.
    async def _consume(
        self, event: str, data: dict, collected: list, images: list
    ) -> None:
        if event == "delta" and isinstance(data.get("content"), str):
            collected.append(data["content"])
        elif event == "artifact_ready" and data.get("kind") == "diagram":
            rendered = await self.chat._render_diagram(data)
            if rendered is not None:
                images.append(rendered)
        elif event == "artifact_ready" and str(data.get("mime_type") or "").startswith(
            "image/"
        ):
            images.append(
                TurnImage(
                    artifact_id=str(data.get("id") or ""),
                    media_type=str(data["mime_type"]),
                )
            )

    # The person's active, approved iMessage address, or None.
    async def _address_for(self, user_id: str) -> str | None:
        from backend.models.discovery_subscriber import DiscoverySubscriber

        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(DiscoverySubscriber)
                .where(
                    DiscoverySubscriber.user_id == user_id,
                    DiscoverySubscriber.channel == "imessage",
                    DiscoverySubscriber.active.is_(True),
                    DiscoverySubscriber.approved_at.is_not(None),
                )
                .order_by(DiscoverySubscriber.created_at)
            )
        return str(row.address) if row else None


# The loop the discovery worker process hosts alongside its own.
async def run_task_loop() -> None:
    from backend.core.dependencies import _invoke_discovery_tool

    runner = TaskRunner(_invoke_discovery_tool)
    logger.info("scheduled_tasks_started", extra={"worker_id": runner.worker_id})
    while True:
        try:
            await runner.enqueue_due()
            while await runner.run_once():
                pass
        except Exception:
            logger.exception("scheduled_tasks_tick_failed")
        await asyncio.sleep(settings.SCHEDULED_TASKS_POLL_SECONDS)
