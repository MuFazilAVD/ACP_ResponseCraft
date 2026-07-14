"""Langfuse v4 integration helpers for prompt sync and trace observations."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
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
            logger.debug("LangfuseObservationHandle.update | payload_keys=%s", list(payload.keys()))
            self.observation.update(**payload)
        except Exception:
            logger.warning("LangfuseObservationHandle.update | failed to update observation", exc_info=True)
            return

    def set_trace_io(self, *, input: Any | None = None, output: Any | None = None) -> None:
        if not self.enabled or self.client is None:
            return
        try:
            logger.debug(
                "LangfuseObservationHandle.set_trace_io | input_present=%s | output_present=%s",
                input is not None,
                output is not None,
            )
            self.client.set_current_trace_io(input=input, output=output)
        except Exception:
            logger.warning("LangfuseObservationHandle.set_trace_io | failed to set trace I/O", exc_info=True)
            return

    def error(self, exc: BaseException) -> None:
        message = str(exc)
        logger.debug("LangfuseObservationHandle.error | marking observation as ERROR | message=%s", message)
        self.update(level="ERROR", status_message=message)
        if self.client is None:
            return
        try:
            self.client.update_current_span(level="ERROR", status_message=message)
        except Exception:
            logger.warning("LangfuseObservationHandle.error | failed to update current span", exc_info=True)
            return

    def flush(self) -> None:
        logger.debug("LangfuseObservationHandle.flush | triggering Langfuse flush")
        flush_langfuse(self.client)


class LangfuseTelemetry:
    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        logger.debug("LangfuseTelemetry.__init__ | service_name=%s | loading config", service_name)
        self.config = langfuse_config()
        self.client = build_langfuse_client(self.config)
        self.sdk_available = _langfuse_sdk_available()
        self.enabled = bool(self.client and self.config.tracing_enabled)
        logger.info(
            "LangfuseTelemetry.__init__ | service_name=%s | enabled=%s | configured=%s | sdk_available=%s | base_url=%s",
            self.service_name,
            self.enabled,
            self.config.configured,
            self.sdk_available,
            self.config.base_url,
        )

    def status(self) -> dict[str, Any]:
        logger.debug("LangfuseTelemetry.status | service_name=%s | fetching status", self.service_name)
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
        logger.debug("LangfuseTelemetry.auth_check | service_name=%s | running auth check", self.service_name)
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
            logger.debug("LangfuseTelemetry.observation | tracing disabled — yielding no-op handle | name=%s", name)
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

        logger.debug(
            "LangfuseTelemetry.observation | starting observation | name=%s | as_type=%s | kwarg_keys=%s",
            name,
            as_type,
            list(kwargs.keys()),
        )
        try:
            manager = self.client.start_as_current_observation(**kwargs)
            observation = manager.__enter__()
        except Exception:
            logger.warning("LangfuseTelemetry.observation | failed to start observation | name=%s", name, exc_info=True)
            yield LangfuseObservationHandle()
            return
        logger.debug("LangfuseTelemetry.observation | observation started successfully | name=%s", name)

        handle = LangfuseObservationHandle(
            client=self.client,
            observation=observation,
            enabled=True,
        )
        exc_info = (None, None, None)
        try:
            yield handle
        except Exception as exc:
            logger.error(
                "LangfuseTelemetry.observation | exception during observation | name=%s | error=%s: %s",
                name,
                type(exc).__name__,
                exc,
            )
            exc_info = sys.exc_info()
            handle.error(exc)
            raise
        finally:
            logger.debug("LangfuseTelemetry.observation | closing observation | name=%s", name)
            try:
                manager.__exit__(*exc_info)
            except Exception:
                logger.warning("LangfuseTelemetry.observation | failed to exit observation manager | name=%s", name, exc_info=True)


def langfuse_config() -> LangfuseRuntimeConfig:
    logger.debug("langfuse_config | building LangfuseRuntimeConfig from env and settings")
    config = LangfuseRuntimeConfig(
        base_url=DEFAULT_LANGFUSE_BASE_URL.rstrip("/"),
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "").strip(),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY", "").strip(),
        project=DEFAULT_LANGFUSE_PROJECT,
        prompt_label=DEFAULT_LANGFUSE_PROMPT_LABEL,
        tracing_enabled=DEFAULT_LANGFUSE_TRACING_ENABLED,
        flush_on_invoke=DEFAULT_LANGFUSE_FLUSH_ON_INVOKE,
        auth_check_on_sync=DEFAULT_LANGFUSE_AUTH_CHECK_ON_SYNC,
    )
    logger.debug(
        "langfuse_config | base_url=%s | project=%s | tracing_enabled=%s | configured=%s",
        config.base_url,
        config.project,
        config.tracing_enabled,
        config.configured,
    )
    return config


def build_langfuse_client(config: LangfuseRuntimeConfig | None = None):
    runtime = config or langfuse_config()
    logger.debug("build_langfuse_client | configured=%s | base_url=%s", runtime.configured, runtime.base_url)
    if not runtime.configured:
        logger.warning(
            "build_langfuse_client | Langfuse is not configured (missing base_url, public_key, or secret_key) — client will not be created"
        )
        return None
    try:
        from langfuse import Langfuse
    except Exception:
        logger.error("build_langfuse_client | failed to import langfuse SDK — is it installed?", exc_info=True)
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
        logger.debug("build_langfuse_client | attaching existing OpenTelemetry tracer_provider")
        kwargs["tracer_provider"] = tracer_provider

    try:
        logger.debug("build_langfuse_client | attempting to instantiate Langfuse client with base_url kwarg")
        return Langfuse(**kwargs)
    except TypeError:
        logger.warning("build_langfuse_client | TypeError with base_url kwarg — retrying with host kwarg")
        kwargs.pop("base_url", None)
        kwargs["host"] = runtime.base_url
        try:
            client = Langfuse(**kwargs)
            logger.debug("build_langfuse_client | Langfuse client created successfully using host kwarg")
            return client
        except Exception:
            logger.error("build_langfuse_client | failed to instantiate Langfuse client with host kwarg", exc_info=True)
            return None
    except Exception:
        logger.error("build_langfuse_client | unexpected error instantiating Langfuse client", exc_info=True)
        return None


def langfuse_auth_check(client: Any) -> tuple[bool | None, str]:
    if client is None:
        logger.warning("langfuse_auth_check | client is None — skipping auth check")
        return None, "Langfuse client unavailable or not configured."
    logger.debug("langfuse_auth_check | running auth check against Langfuse server")
    try:
        authenticated = bool(client.auth_check())
    except Exception as exc:
        logger.error("langfuse_auth_check | auth check raised exception | error=%s: %s", type(exc).__name__, exc)
        return False, f"Langfuse auth check failed: {exc.__class__.__name__}"
    if authenticated:
        logger.info("langfuse_auth_check | Langfuse client authenticated successfully")
        return True, "Langfuse client authenticated."
    logger.warning("langfuse_auth_check | Langfuse auth check returned False")
    return False, "Langfuse auth check failed."


def flush_langfuse(client: Any) -> None:
    if client is None:
        logger.debug("flush_langfuse | client is None — nothing to flush")
        return
    logger.debug("flush_langfuse | flushing Langfuse client")
    try:
        client.flush()
        logger.debug("flush_langfuse | flush completed successfully")
    except Exception:
        logger.warning("flush_langfuse | flush raised an exception — ignoring", exc_info=True)
        return


def usage_details_from_token_usage(token_usage: Any) -> dict[str, int]:
    logger.debug("usage_details_from_token_usage | extracting token usage from %s", type(token_usage).__name__)
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
    logger.debug("usage_details_from_token_usage | extracted=%s", details)
    return details


def _langfuse_sdk_available() -> bool:
    logger.debug("_langfuse_sdk_available | checking if langfuse SDK is importable")
    try:
        import langfuse  # noqa: F401
    except Exception:
        logger.warning("_langfuse_sdk_available | langfuse SDK is NOT available")
        return False
    logger.debug("_langfuse_sdk_available | langfuse SDK is available")
    return True


def _current_tracer_provider() -> Any | None:
    logger.debug("_current_tracer_provider | checking for active OpenTelemetry tracer provider")
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
    except Exception:
        logger.debug("_current_tracer_provider | opentelemetry not available or get_tracer_provider failed")
        return None
    if provider.__class__.__name__ == "ProxyTracerProvider":
        logger.debug("_current_tracer_provider | found ProxyTracerProvider — treating as no active provider")
        return None
    logger.debug("_current_tracer_provider | active tracer provider found | type=%s", type(provider).__name__)
    return provider

