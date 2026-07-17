import logging
import uuid
from typing import Any

from backend.core.interfaces import ConversationTracer

logger = logging.getLogger(__name__)


class LoggingConversationTracer(ConversationTracer):
    def start_trace(self, user_id: str) -> str:
        return str(uuid.uuid4())

    def log_step(
        self,
        trace_id: str,
        step_name: str,
        metadata: dict[str, Any],
    ) -> None:
        logger.info(
            "Conversation trace %s | %s | %s",
            trace_id,
            step_name,
            metadata,
        )
