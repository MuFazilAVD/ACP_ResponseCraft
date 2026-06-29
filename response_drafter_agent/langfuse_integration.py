"""Langfuse v4 integration helpers for prompt sync and trace observations."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from .settings import (
    DEFAULT_LANGFUSE_AUTH_CHECK_ON_SYNC,
    DEFAULT_LANGFUSE_BASE_URL,
    DEFAULT_LANGFUSE_FLUSH_ON_INVOKE,
    DEFAULT_LANGFUSE_PROJECT,
    DEFAULT_LANGFUSE_PROMPT_LABEL,
    DEFAULT_LANGFUSE_TRACING_ENABLED,
)


@dataclass(frozen=True)
class LangfuseRuntimeConfig:
    base_url: str
    public_key: str
    secret_key: str
    project: str
    prompt_label: str
    tracing_enabled: bool
    flush_on_invoke: bool
    auth_check_on_sync: bool

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.public_key and self.secret_key)


@dataclass
class LangfuseObservationHandle:
    client: Any = None
    observation: Any = None
    enabled: bool = False

    def update(self, **kwargs: Any) -> None:
        if not self.enabled or self.observation is None:
            return
        payload = {key: value for key, value in kwargs.items() if value is not None}
        if not payload:
            return
        try:
            self.observation.update(**payload)
        except Exception:
            return

    def set_trace_io(self, *, input: Any | None = None, output: Any | None = None) -> None:
        if not self.enabled or self.client is None:
            return
        try:
            self.client.set_current_trace_io(input=input, output=output)
        except Exception:
            return

    def error(self, exc: BaseException) -> None:
        message = str(exc)
        self.update(level="ERROR", status_message=message)
        if self.client is None:
            return
        try:
            self.client.update_current_span(level="ERROR", status_message=message)
        except Exception:
            return

    def flush(self) -> None:
        flush_langfuse(self.client)


class LangfuseTelemetry:
    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.config = langfuse_config()
        self.client = build_langfuse_client(self.config)
        self.sdk_available = _langfuse_sdk_available()
        self.enabled = bool(self.client and self.config.tracing_enabled)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "configured": self.config.configured,
            "client_available": self.client is not None,
            "sdk_available": self.sdk_available,
            "base_url": self.config.base_url,
            "base_url_source": "code",
            "public_key_configured": bool(self.config.public_key),
            "secret_key_configured": bool(self.config.secret_key),
            "project": self.config.project,
            "prompt_label": self.config.prompt_label,
            "tracing_enabled": self.config.tracing_enabled,
            "auth_check_on_sync": self.config.auth_check_on_sync,
        }

    def auth_check(self) -> tuple[bool | None, str]:
        return langfuse_auth_check(self.client)

    @contextmanager
    def observation(
        self,
        *,
        name: str,
        as_type: str = "span",
        input: Any | None = None,
        output: Any | None = None,
        metadata: Any | None = None,
        version: str | None = None,
        model: str | None = None,
        model_parameters: dict[str, Any] | None = None,
        usage_details: dict[str, int] | None = None,
    ) -> Iterator[LangfuseObservationHandle]:
        if not self.enabled:
            yield LangfuseObservationHandle()
            return

        kwargs: dict[str, Any] = {
            "name": name,
            "as_type": as_type,
            "input": input,
            "output": output,
            "metadata": metadata,
            "version": version,
            "model": model,
            "model_parameters": model_parameters,
            "usage_details": usage_details,
        }
        kwargs = {key: value for key, value in kwargs.items() if value is not None}

        try:
            manager = self.client.start_as_current_observation(**kwargs)
            observation = manager.__enter__()
        except Exception:
            yield LangfuseObservationHandle()
            return

        handle = LangfuseObservationHandle(
            client=self.client,
            observation=observation,
            enabled=True,
        )
        exc_info = (None, None, None)
        try:
            yield handle
        except Exception as exc:
            exc_info = sys.exc_info()
            handle.error(exc)
            raise
        finally:
            try:
                manager.__exit__(*exc_info)
            except Exception:
                pass


def langfuse_config() -> LangfuseRuntimeConfig:
    return LangfuseRuntimeConfig(
        base_url=DEFAULT_LANGFUSE_BASE_URL.rstrip("/"),
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "").strip(),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY", "").strip(),
        project=DEFAULT_LANGFUSE_PROJECT,
        prompt_label=DEFAULT_LANGFUSE_PROMPT_LABEL,
        tracing_enabled=DEFAULT_LANGFUSE_TRACING_ENABLED,
        flush_on_invoke=DEFAULT_LANGFUSE_FLUSH_ON_INVOKE,
        auth_check_on_sync=DEFAULT_LANGFUSE_AUTH_CHECK_ON_SYNC,
    )


def build_langfuse_client(config: LangfuseRuntimeConfig | None = None):
    runtime = config or langfuse_config()
    if not runtime.configured:
        return None
    try:
        from langfuse import Langfuse
    except Exception:
        return None

    kwargs: dict[str, Any] = {
        "public_key": runtime.public_key,
        "secret_key": runtime.secret_key,
        "base_url": runtime.base_url,
        "tracing_enabled": runtime.tracing_enabled,
        "environment": DEFAULT_LANGFUSE_PROJECT,
        "release": "0.1.0",
    }
    kwargs = {key: value for key, value in kwargs.items() if value is not None}

    tracer_provider = _current_tracer_provider()
    if tracer_provider is not None:
        kwargs["tracer_provider"] = tracer_provider

    try:
        return Langfuse(**kwargs)
    except TypeError:
        kwargs.pop("base_url", None)
        kwargs["host"] = runtime.base_url
        try:
            return Langfuse(**kwargs)
        except Exception:
            return None
    except Exception:
        return None


def langfuse_auth_check(client: Any) -> tuple[bool | None, str]:
    if client is None:
        return None, "Langfuse client unavailable or not configured."
    try:
        authenticated = bool(client.auth_check())
    except Exception as exc:
        return False, f"Langfuse auth check failed: {exc.__class__.__name__}"
    if authenticated:
        return True, "Langfuse client authenticated."
    return False, "Langfuse auth check failed."


def flush_langfuse(client: Any) -> None:
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        return


def usage_details_from_token_usage(token_usage: Any) -> dict[str, int]:
    details: dict[str, int] = {}
    input_tokens = getattr(token_usage, "input_tokens", None)
    output_tokens = getattr(token_usage, "output_tokens", None)
    total_tokens = getattr(token_usage, "total_tokens", None)
    if isinstance(input_tokens, int):
        details["input_tokens"] = input_tokens
    if isinstance(output_tokens, int):
        details["output_tokens"] = output_tokens
    if isinstance(total_tokens, int):
        details["total_tokens"] = total_tokens
    return details


def _langfuse_sdk_available() -> bool:
    try:
        import langfuse  # noqa: F401
    except Exception:
        return False
    return True


def _current_tracer_provider() -> Any | None:
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
    except Exception:
        return None
    if provider.__class__.__name__ == "ProxyTracerProvider":
        return None
    return provider
