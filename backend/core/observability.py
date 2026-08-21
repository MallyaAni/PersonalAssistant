"""Persist per-turn context measurements where deploys cannot erase them.

The context budget logs a summary line on every turn, and the line works -
`setup_logging` in main.py configures INFO to stdout, and an authenticated
turn through the live server prints it. What does not work is *keeping* it:
`docker compose logs` dies with the container, this repository rebuilds the
backend many times a day, and the whole point of the measurement is a
distribution that accumulates until enforcement floors can be set from it.
Thirteen real conversation turns happened in the two days after the budget
shipped, and every one of their measurements went down with a rebuild.

So each report is also appended, one JSON object per line, to a file on a
named volume. A named volume outlives `up --build`, the writer is a sync
graph node that cannot await a database, and the reader is a percentile
calculation - JSONL is exactly enough.

A diagnostic note recorded for the next person who probes this: checking a
logger's effective level through `docker compose exec python -c ...` starts
a fresh interpreter in which main.py never ran, and reports WARNING no
matter what the server is doing. That wrong reading cost this module a
logging-configuration feature it did not need, deleted the same hour it was
written. Judge the server by sending it a real request and reading its logs.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from backend.config.settings import settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.core.context_budget import BudgetReport

logger = logging.getLogger(__name__)


def record_context_report(report: "BudgetReport", trace_id: str) -> None:
    """Append one turn's measurement. Never raises into the turn.

    Measurement is an improvement to a turn, not a requirement of one, so
    every failure path logs and returns.
    """
    path = str(settings.CONTEXT_REPORT_PATH or "").strip()
    if not path:
        return
    try:
        row = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "trace_id": trace_id,
            **report.as_dict(),
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    except OSError:
        logger.warning("Context report could not be persisted", exc_info=True)
