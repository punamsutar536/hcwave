"""OpenTelemetry setup and LLM tracing helpers.

Traces go to Application Insights through the Azure Monitor distro, where
Microsoft Foundry tracing and evaluations read them. Any OTLP backend (Grafana
Tempo, Jaeger, Datadog...) works by switching ``telemetry.exporter: otlp``.

LLM spans follow the OpenTelemetry GenAI semantic conventions
(``gen_ai.*`` attributes). Prompt and completion text is recorded only when
``telemetry.capture_llm_content`` is true, because it can contain PHI.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from typing import Any

from opentelemetry import trace

from hcwave.config.schema import TelemetrySection

_log = logging.getLogger(__name__)
_tracer = trace.get_tracer("hcwave")
_capture_content = False


def configure_telemetry(section: TelemetrySection) -> None:
    """Installs the configured exporter. Safe to call once per process.

    Args:
        section: The ``telemetry`` configuration section.
    """
    global _capture_content
    _capture_content = section.capture_llm_content
    if not section.enabled or section.exporter == "none":
        return
    try:
        if section.exporter == "azure_monitor":
            if not section.connection_string:
                _log.warning("telemetry: no Application Insights connection string; skipping")
                return
            from azure.monitor.opentelemetry import configure_azure_monitor

            configure_azure_monitor(
                connection_string=section.connection_string,
                resource_attributes={"service.name": section.service_name},
            )
        elif section.exporter in {"otlp", "console"}:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,
                ConsoleSpanExporter,
            )

            provider = TracerProvider(
                resource=Resource.create({"service.name": section.service_name})
            )
            if section.exporter == "otlp":
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

                exporter: Any = OTLPSpanExporter(endpoint=section.otlp_endpoint or None)
            else:
                exporter = ConsoleSpanExporter()
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
    except ImportError as exc:  # Optional extra not installed.
        _log.warning("telemetry exporter %s unavailable: %s", section.exporter, exc)


def instrument_fastapi(app: Any) -> None:
    """Adds request tracing to a FastAPI app when instrumentation is installed."""
    with contextlib.suppress(ImportError):
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")


@contextlib.contextmanager
def llm_span(operation: str, system: str, model: str, **attributes: Any) -> Iterator[Any]:
    """Wraps an LLM call in a GenAI-convention span.

    Args:
        operation: ``chat`` or ``embeddings``.
        system: Provider family, e.g. ``az.ai.openai`` or ``anthropic``.
        model: Requested model/deployment.
        **attributes: Extra span attributes (e.g. ``hcwave.profile``).

    Yields:
        The active span; callers may add usage attributes to it.
    """
    with _tracer.start_as_current_span(f"{operation} {model}") as span:
        span.set_attribute("gen_ai.operation.name", operation)
        span.set_attribute("gen_ai.system", system)
        span.set_attribute("gen_ai.request.model", model)
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span


def record_llm_content(span: Any, prompt: str, completion: str) -> None:
    """Attaches prompt/completion text to a span if content capture is on."""
    if _capture_content:
        span.set_attribute("gen_ai.prompt", prompt[:4000])
        span.set_attribute("gen_ai.completion", completion[:4000])


def get_tracer() -> Any:
    """Returns the platform tracer for custom spans."""
    return _tracer
