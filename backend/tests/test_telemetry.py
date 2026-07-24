from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from backend.services.tracing import (
    LoggingConversationTracer,
    OpenTelemetryConversationTracer,
)


def test_disabled_tracer_is_a_transparent_passthrough():
    inner = LoggingConversationTracer()
    tracer = OpenTelemetryConversationTracer(inner)

    # With no active recording span, the adapter still returns a trace id and
    # logs, exactly as the inner tracer would, and never raises.
    trace_id = tracer.start_trace("ani.mallya")
    tracer.log_step(trace_id, "graph_execution", {"status": "started"})

    assert isinstance(trace_id, str)
    assert len(trace_id) == 36


def test_steps_become_events_on_the_active_span():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer_obj = provider.get_tracer("test")

    inner = LoggingConversationTracer()
    tracer = OpenTelemetryConversationTracer(inner)

    with tracer_obj.start_as_current_span("POST /api/v1/chat"):
        trace_id = tracer.start_trace("ani.mallya")
        tracer.log_step(trace_id, "graph_execution", {"status": "started"})
        tracer.log_step(trace_id, "graph_execution", {"status": "completed"})

    span = exporter.get_finished_spans()[0]
    events = [event.name for event in span.events]
    assert events == ["graph_execution", "graph_execution"]
    # The application trace id and user id are attached to the request span so
    # the two identifiers correlate.
    assert span.attributes["anios.trace_id"] == trace_id
    assert span.attributes["anios.user_id"] == "ani.mallya"


def test_step_metadata_never_carries_raw_user_text():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer_obj = provider.get_tracer("test")

    tracer = OpenTelemetryConversationTracer(LoggingConversationTracer())

    long_value = "x" * 500
    with tracer_obj.start_as_current_span("turn"):
        trace_id = tracer.start_trace("u")
        tracer.log_step(trace_id, "step", {"secret_like": long_value})

    event = exporter.get_finished_spans()[0].events[0]
    # Values are stringified and bounded, so nothing unbounded reaches a backend.
    assert len(event.attributes["anios.secret_like"]) <= 120


def test_configure_is_inert_when_disabled(monkeypatch):
    from backend.config.settings import settings
    from backend.core import telemetry

    monkeypatch.setattr(settings, "OTEL_ENABLED", False)
    monkeypatch.setattr(telemetry, "_configured", False)

    # Must not raise and must not instrument anything when tracing is off.
    telemetry.configure_telemetry(None)
    assert telemetry._configured is False
