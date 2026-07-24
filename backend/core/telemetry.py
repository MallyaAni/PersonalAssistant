"""Optional OpenTelemetry wiring for request and outbound-call tracing.

Tracing is off unless an operator configures it, and turning it on never
depends on a collector being reachable: an unreachable endpoint drops spans in
the background rather than failing a request. The application's own trace id is
attached to each span as an attribute, so the custom conversation trace and the
OpenTelemetry trace refer to the same turn.
"""

import logging
from typing import TYPE_CHECKING

from backend.config.settings import settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.sdk.trace.export import SpanExporter

logger = logging.getLogger(__name__)

# Attribute names kept in one place so a span consumer can rely on them.
TRACE_ID_ATTRIBUTE = "anios.trace_id"
USER_ID_ATTRIBUTE = "anios.user_id"
STEP_ATTRIBUTE = "anios.step"

_configured = False


# Configure the global tracer provider and instrument FastAPI and httpx once.
#
# httpx instrumentation is what makes this worth doing: every outbound call -
# LM Studio, Tavily, an HTTP MCP server - is auto-propagated with W3C
# trace-context and appears as a child span, so a slow turn can be attributed
# to the provider that caused it rather than guessed at.
def configure_telemetry(app: "FastAPI | None" = None) -> None:
    global _configured
    if _configured or not settings.OTEL_ENABLED:
        return

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": settings.OTEL_SERVICE_NAME,
            "service.version": "0.1.0",
        }
    )
    provider = TracerProvider(resource=resource)

    exporter = _build_exporter()
    if exporter is not None:
        # Batched and backgrounded, so exporting never blocks a request and a
        # dead collector degrades to dropped spans rather than errors.
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _instrument(app)
    _configured = True
    logger.info(
        "OpenTelemetry enabled (exporter=%s, endpoint=%s)",
        settings.OTEL_EXPORTER,
        settings.OTEL_EXPORTER_OTLP_ENDPOINT or "<none>",
    )


# Select the span exporter, tolerating a misconfiguration by exporting nothing.
def _build_exporter() -> "SpanExporter | None":
    if settings.OTEL_EXPORTER == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    if settings.OTEL_EXPORTER == "otlp":
        if not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
            logger.warning("OTEL_EXPORTER=otlp but no endpoint set; spans dropped")
            return None
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        return OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    return None


# Instrument the web framework and the HTTP client library.
def _instrument(app: "FastAPI | None") -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # /health is excluded so liveness polling does not flood the trace store.
        FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    HTTPXClientInstrumentor().instrument()
