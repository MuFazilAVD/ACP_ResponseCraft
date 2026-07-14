"""Small OTel wrapper that emits gen_ai.* spans when OTel is installed."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from .logging_utils import get_logger
from .settings import (
    DEFAULT_OTLP_AUTH_HEADER,
    DEFAULT_OTLP_AUTH_SCHEME,
    DEFAULT_OTLP_ENDPOINT,
)

logger = get_logger(__name__)


@dataclass
class SpanHandle:
    trace_id: str
    _span: Any = None

    def set_attribute(self, key: str, value: Any) -> None:
        if self._span is not None and value is not None:
            self._span.set_attribute(key, value)

    def record_exception(self, exc: BaseException) -> None:
        if self._span is not None:
            self._span.record_exception(exc)


class Telemetry:
    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.enabled = False
        self._trace = None
        self._tracer = None
        logger.debug(
            "[Telemetry.__init__] Initialising OTel telemetry | service_name=%s",
            self.service_name,
        )
        self._init_otel()

    def _init_otel(self) -> None:
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
        except Exception as exc:
            logger.debug(
                "[_init_otel] OpenTelemetry SDK not installed — tracing disabled | error=%s",
                exc.__class__.__name__,
            )
            return

        try:
            endpoint = DEFAULT_OTLP_ENDPOINT
            otlp_api_key = os.getenv("OTLP_API_KEY", "").strip()
            provider = TracerProvider(
                resource=Resource.create(
                    {
                        "service.name": self.service_name,
                        "service.version": "0.1.0",
                    }
                )
            )
            if endpoint:
                exporter_kwargs: dict[str, Any] = {"endpoint": endpoint}
                if otlp_api_key:
                    exporter_kwargs["headers"] = {
                        DEFAULT_OTLP_AUTH_HEADER: f"{DEFAULT_OTLP_AUTH_SCHEME} {otlp_api_key}",
                    }
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs)))
                logger.info(
                    "[_init_otel] OTel exporter configured | endpoint=%s | auth_key_set=%s",
                    endpoint,
                    bool(otlp_api_key),
                )
            else:
                logger.warning(
                    "[_init_otel] No OTLP_ENDPOINT configured — spans will not be exported "
                    "(set DEFAULT_OTLP_ENDPOINT or OTLP_ENDPOINT env var)"
                )
            trace.set_tracer_provider(provider)
            self._trace = trace
            self._tracer = trace.get_tracer(self.service_name)
            self.enabled = True
            logger.info(
                "[_init_otel] OTel tracing ENABLED | service_name=%s | endpoint=%s",
                self.service_name,
                endpoint or "(no exporter)",
            )
        except Exception as exc:
            logger.error(
                "[_init_otel] OTel initialisation FAILED | service_name=%s | error=%s",
                self.service_name,
                exc.__class__.__name__,
            )
            self._trace = None
            self._tracer = None
            self.enabled = False

    @contextmanager
    def span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> Iterator[SpanHandle]:
        if self._tracer is None:
            handle = SpanHandle(trace_id=trace_id or uuid.uuid4().hex)
            logger.debug(
                "[span] OTel not available — using no-op span | name=%s | trace_id=%s",
                name,
                handle.trace_id,
            )
            yield handle
            return

        with self._tracer.start_as_current_span(name) as span:
            for key, value in (attributes or {}).items():
                if value is not None:
                    span.set_attribute(key, value)
            ctx = span.get_span_context()
            handle = SpanHandle(trace_id=format(ctx.trace_id, "032x"), _span=span)
            logger.debug(
                "[span] OTel span opened | name=%s | trace_id=%s",
                name,
                handle.trace_id,
            )
            yield handle
            logger.debug("[span] OTel span closed | name=%s | trace_id=%s", name, handle.trace_id)
