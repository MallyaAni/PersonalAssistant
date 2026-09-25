"""Collect display quotes for the backend lifetime without any account actions."""

import asyncio
import logging
import math
import time
from contextlib import suppress
from pathlib import Path

from backend.market import alpaca, deskrecord, session_price_snapshot

logger = logging.getLogger(__name__)


class SessionPriceCollector:
    """One bounded loop per process, coordinated by the shared snapshot writer."""

    # Keep quote collection isolated from all model, holding and trading services.
    def __init__(self, root, interval_seconds=15, enabled=True, collect=None):
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("A positive collection interval is required")
        self._root = Path(root)
        self._interval = interval_seconds
        self._enabled = enabled
        self._collect = collect or session_price_snapshot.collect
        self._task = None
        self._stop = None
        self._last_failure = None

    # Report failure transitions without exposing exception or provider data.
    def _observe(self, result):
        status = result.get("status") if isinstance(result, dict) else None
        if status in ("failed", "unavailable"):
            if status != self._last_failure:
                logger.warning("Display-price collection %s; will retry", status)
            self._last_failure = status
        elif status == "collected" and self._last_failure is not None:
            logger.info("Display-price snapshot publication recovered")
            self._last_failure = None

    # Read only the graded universe, then ask the shared writer for one due pass.
    def _collect_once(self):
        latest, _ = deskrecord.latest_pair(self._root)
        symbols = list((latest or {}).get("grades") or {})
        return self._collect(self._root, symbols, interval_seconds=self._interval)

    # Drain each threaded pass before another pass or process shutdown may finish.
    async def _loop(self):
        while not self._stop.is_set():
            started = time.monotonic()
            work = asyncio.create_task(asyncio.to_thread(self._collect_once))
            try:
                self._observe(await asyncio.shield(work))
            except asyncio.CancelledError:
                self._stop.set()
                # Cancelling to_thread does not stop its thread or release its lock.
                with suppress(Exception):
                    await work
                raise
            except Exception:
                self._observe({"status": "failed"})
            remaining = max(0.001, self._interval - (time.monotonic() - started))
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=remaining)

    # Start immediately when enabled and existing provider credentials are configured.
    def start(self):
        if not self._enabled or self._task is not None and not self._task.done():
            return
        if not session_price_snapshot.supported():
            logger.info(
                "Display-price collector inactive: safe file locking unavailable"
            )
            return
        try:
            alpaca.credentials()
        except Exception:
            logger.info("Display-price collector inactive: credentials unavailable")
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._loop())

    # Stop new passes promptly while allowing any already-started write to finish.
    async def stop(self):
        task = self._task
        if task is not None:
            self._stop.set()
            with suppress(asyncio.CancelledError):
                await task
            if self._task is task:
                self._task = None
