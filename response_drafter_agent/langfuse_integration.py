"""Langfuse v4 integration helpers for prompt sync and trace observations."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
import contextvars
from typing import Any, Iterator

from .logging_utils import get_logger
from .settings import (
    DEFAULT_LANGFUSE_AUTH_CHECK_ON_SYNC,
    DEFAULT_LANGFUSE_BASE_URL,
    DEFAULT_LANGFUSE_FLUSH_ON_INVOKE,
    DEFAULT_LANGFUSE_PROJECT,
    DEFAULT_LANGFUSE_PROMPT_LABEL,
    DEFAULT_LANGFUSE_TRACING_ENABLED,
)

logger = get_logger(__name__)

_current_langfuse_observation = contextvars.ContextVar("langfuse_observation", default=None)


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
        if not self.enabled or self.observation is None:
            return
        try:
            self.observation.update(input=input, output=output)
        except Exception:
            return

    def error(self, exc: BaseException) -> None:
        message = str(exc)
        self.update(level="ERROR", status_message=message)

    def flush(self) -> None:
        flush_langfuse(self.client)


class LangfuseTelemetry:
    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.config = langfuse_config()
        self.client = build_langfuse_client(self.config)
        self.sdk_available = _langfuse_sdk_available()
        self.enabled = bool(self.client and self.config.tracing_enabled)
        if self.enabled:
            logger.info(
                "[LangfuseTelemetry.__init__] Langfuse telemetry ENABLED | "
                "service=%s | base_url=%s | project=%s | flush_on_invoke=%s",
                self.service_name,
                self.config.base_url,
                self.config.project,
                self.config.flush_on_invoke,
            )
        else:
            logger.warning(
                "[LangfuseTelemetry.__init__] Langfuse telemetry DISABLED | "
                "service=%s | sdk_available=%s | configured=%s | tracing_enabled=%s",
                self.service_name,
                self.sdk_available,
                self.config.configured,
                self.config.tracing_enabled,
            )

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
            logger.debug(
                "[observation] Langfuse disabled — yielding no-op handle | name=%s | type=%s",
                name,
                as_type,
            )
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
            parent = _current_langfuse_observation.get()
            if as_type in ("trace", "agent"):
                observation = self.client.trace(**kwargs)
            else:
                creator = parent if parent else self.client
                if as_type == "span":
                    observation = creator.span(**kwargs)
                elif as_type == "generation":
                    observation = creator.generation(**kwargs)
                else:
                    observation = creator.span(**kwargs)
        except Exception as exc:
            logger.error(
                "[observation] Failed to start Langfuse observation | name=%s | error=%s",
                name,
                exc.__class__.__name__,
            )
            yield LangfuseObservationHandle()
            return

        logger.debug(
            "[observation] Langfuse observation opened | name=%s | type=%s",
            name,
            as_type,
        )
        handle = LangfuseObservationHandle(
            client=self.client,
            observation=observation,
            enabled=True,
        )
        token = _current_langfuse_observation.set(observation)
        exc_info = (None, None, None)
        try:
            yield handle
        except Exception as exc:
            exc_info = sys.exc_info()
            logger.error(
                "[observation] Exception inside Langfuse observation | name=%s | error=%s | detail=%s",
                name,
                exc.__class__.__name__,
                str(exc)[:300],
            )
            handle.error(exc)
            raise
        finally:
            _current_langfuse_observation.reset(token)
            if hasattr(observation, "end"):
                try:
                    observation.end()
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
        logger.warning(
            "[build_langfuse_client] Langfuse not configured — client will not be created | "
            "public_key_set=%s | secret_key_set=%s | base_url=%s",
            bool(runtime.public_key),
            bool(runtime.secret_key),
            runtime.base_url,
        )
        return None
    try:
        from langfuse import Langfuse
    except Exception as exc:
        logger.error(
            "[build_langfuse_client] Langfuse SDK not importable | error=%s",
            exc.__class__.__name__,
        )
        return None

    kwargs: dict[str, Any] = {
        "public_key": runtime.public_key,
        "secret_key": runtime.secret_key,
        "host": runtime.base_url,
        "release": "0.1.0",
        "enabled": runtime.tracing_enabled,
    }
    kwargs = {key: value for key, value in kwargs.items() if value is not None}

    try:
        client = Langfuse(**kwargs)
        logger.info(
            "[build_langfuse_client] Langfuse client created | host=%s | project=%s",
            runtime.base_url,
            runtime.project,
        )
        return client
    except Exception as exc:
        logger.error(
            "[build_langfuse_client] Failed to create Langfuse client | error=%s | detail=%s",
            exc.__class__.__name__,
            str(exc)[:300],
        )
        return None


def langfuse_auth_check(client: Any) -> tuple[bool | None, str]:
    if client is None:
        logger.debug("[langfuse_auth_check] Skipped — client is None")
        return None, "Langfuse client unavailable or not configured."
    try:
        authenticated = bool(client.auth_check())
    except Exception as exc:
        logger.warning(
            "[langfuse_auth_check] Auth check raised exception | error=%s",
            exc.__class__.__name__,
        )
        return False, f"Langfuse auth check failed: {exc.__class__.__name__}"
    if authenticated:
        logger.info("[langfuse_auth_check] Langfuse auth check PASSED")
        return True, "Langfuse client authenticated."
    logger.warning("[langfuse_auth_check] Langfuse auth check FAILED")
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
