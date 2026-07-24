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


class OpenTelemetryConversationTracer(ConversationTracer):
    """Decorate the ambient request span with domain steps, and keep logging.

    Span lifecycle is owned by the FastAPI instrumentation, so this adapter
    never opens or closes a span and cannot leak one. It annotates whatever
    span is already active for the request: the application trace id as an
    attribute, so the two identifiers correlate, and each step as a span event.
    Metadata values are coerced to strings and never include query, argument,
    or result text, so a trace backend receives structure, not user content.
    """

    # Wrap a logging tracer so console visibility is preserved when tracing is on.
    def __init__(self, inner: ConversationTracer) -> None:
        self.inner = inner

    # Start the domain trace and stamp its id onto the active request span.
    def start_trace(self, user_id: str) -> str:
        from opentelemetry import trace

        from backend.core.telemetry import TRACE_ID_ATTRIBUTE, USER_ID_ATTRIBUTE

        trace_id = self.inner.start_trace(user_id)
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute(TRACE_ID_ATTRIBUTE, trace_id)
            span.set_attribute(USER_ID_ATTRIBUTE, user_id)
        return trace_id

    # Record one step as a span event and as a log line.
    def log_step(
        self,
        trace_id: str,
        step_name: str,
        metadata: dict[str, Any],
    ) -> None:
        from opentelemetry import trace

        from backend.core.telemetry import STEP_ATTRIBUTE, TRACE_ID_ATTRIBUTE

        span = trace.get_current_span()
        if span.is_recording():
            span.add_event(
                step_name,
                attributes={
                    STEP_ATTRIBUTE: step_name,
                    TRACE_ID_ATTRIBUTE: trace_id,
                    # Structure only; values are stringified and bounded so no
                    # user content reaches the trace backend.
                    **{
                        f"anios.{key}": str(value)[:120]
                        for key, value in metadata.items()
                    },
                },
            )
        self.inner.log_step(trace_id, step_name, metadata)
