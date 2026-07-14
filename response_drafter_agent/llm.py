"""LLM gateway adapter."""

from __future__ import annotations

import json
import os
from typing import Any

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - live LLM mode reports this clearly.
    ChatOpenAI = None

from .knowledge import Evidence
from .logging_utils import get_logger
from .prompts import PromptResolution
from .schemas import TokenUsage
from .settings import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_LLM_USER,
)

logger = get_logger(__name__)


class LLMClient:
    def __init__(self, default_model: str) -> None:
        self.default_model = default_model or DEFAULT_LLM_MODEL
        self.base_url = DEFAULT_LLM_BASE_URL
        self.api_key = (
            os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("LITELLM_MASTER_KEY")
            or ""
        )
        self.provider = DEFAULT_LLM_PROVIDER
        self.user = DEFAULT_LLM_USER
        logger.info(
            "[LLMClient.__init__] LLM client initialised | provider=%s | base_url=%s | "
            "default_model=%s | api_key_set=%s",
            self.provider,
            self.base_url,
            self.default_model,
            bool(self.api_key),
        )
        if not self.api_key:
            logger.warning(
                "[LLMClient.__init__] No LLM API key found in environment | "
                "Checked: LLM_API_KEY, OPENAI_API_KEY, LITELLM_MASTER_KEY | "
                "Live generation will fail until a key is configured."
            )

    async def draft(
        self,
        *,
        question: str,
        intent: str,
        evidence: list[Evidence],
        authority: dict[str, Any],
        grounding: dict[str, Any],
        prompt: PromptResolution,
        model: str,
        generation_params: dict[str, Any],
        system_errors: list[dict[str, Any]] | None = None,
    ) -> tuple[str, str, TokenUsage]:
        if ChatOpenAI is None:
            logger.error(
                "[draft] langchain-openai is not installed — live LLM mode unavailable"
            )
            raise RuntimeError(
                "langchain-openai is required for live LLM mode. "
                "Install requirements.txt and configure a live LLM key."
            )
        if not self.api_key:
            logger.error(
                "[draft] No LLM API key configured — cannot call LLM | "
                "Checked: LLM_API_KEY, OPENAI_API_KEY, LITELLM_MASTER_KEY"
            )
            raise RuntimeError(
                "Live LLM mode requires LLM_API_KEY, OPENAI_API_KEY, or LITELLM_MASTER_KEY. "
                "Add the key to .env and restart the service."
            )

        logger.info(
            "[draft] Initiating LLM call | model=%s | intent=%s | question_len=%d | "
            "evidence_count=%d | prompt_source=%s | prompt_variant=%s | "
            "temperature=%s | max_tokens=%s",
            model,
            intent,
            len(question),
            len(evidence),
            prompt.source,
            prompt.prompt_variant,
            generation_params.get("temperature"),
            generation_params.get("max_tokens"),
        )

        client = self._chat_model(model=model, generation_params=generation_params)
        user_payload = json.dumps(
            {
                "question": question,
                "intent": intent,
                "deterministic_authority": authority,
                "deterministic_grounding": grounding,
                "system_errors": system_errors or [],
                "evidence": [
                    {
                        "source_id": item.source_id,
                        "title": item.title,
                        "content": item.content,
                        "score": item.score,
                    }
                    for item in evidence
                ],
            },
            ensure_ascii=True,
        )
        message = await client.ainvoke(
            [
                ("system", prompt.text),
                ("user", user_payload),
            ]
        )
        text = _message_text(getattr(message, "content", ""))
        usage = _usage_from_message(message)
        if usage.total_tokens is None:
            logger.debug(
                "[draft] Token usage not in response — estimating | question_len=%d | "
                "answer_len=%d | prompt_len=%d",
                len(question),
                len(text),
                len(prompt.text),
            )
            usage = _estimate_usage(question, text, prompt.text)
        response_metadata = getattr(message, "response_metadata", {}) or {}
        model_used = str(response_metadata.get("model_name") or response_metadata.get("model") or model)

        if not text.strip():
            logger.warning(
                "[draft] LLM returned empty content | model=%s | model_used=%s | "
                "input_tokens=%s | output_tokens=%s",
                model,
                model_used,
                usage.input_tokens,
                usage.output_tokens,
            )
        else:
            logger.info(
                "[draft] LLM response received | model_used=%s | input_tokens=%s | "
                "output_tokens=%s | total_tokens=%s | answer_len=%d",
                model_used,
                usage.input_tokens,
                usage.output_tokens,
                usage.total_tokens,
                len(text),
            )

        return (
            text,
            model_used,
            usage,
        )

    def _chat_model(self, *, model: str, generation_params: dict[str, Any]):
        kwargs: dict[str, Any] = {
            "openai_api_base": self.base_url,
            "model": model or self.default_model,
            "api_key": self.api_key,
            "extra_body": {
                "user": self.user,
            },
        }
        for key in (
            "temperature",
            "top_p",
            "max_tokens",
            "frequency_penalty",
            "presence_penalty",
            "seed",
        ):
            value = generation_params.get(key)
            if value is not None:
                kwargs[key] = value
        logger.debug(
            "[_chat_model] ChatOpenAI client constructed | model=%s | base_url=%s | params=%s",
            kwargs["model"],
            self.base_url,
            {k: v for k, v in kwargs.items() if k not in {"api_key", "extra_body"}},
        )
        return ChatOpenAI(**kwargs)


def _estimate_usage(question: str, answer: str, prompt: str) -> TokenUsage:
    input_tokens = max(1, (len(question) + len(prompt)) // 4)
    output_tokens = max(1, len(answer) // 4)
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _usage_from_message(message: Any) -> TokenUsage:
    usage_metadata = getattr(message, "usage_metadata", None) or {}
    response_metadata = getattr(message, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage", {}) or {}

    input_tokens = usage_metadata.get("input_tokens", token_usage.get("prompt_tokens"))
    output_tokens = usage_metadata.get("output_tokens", token_usage.get("completion_tokens"))
    total_tokens = usage_metadata.get("total_tokens", token_usage.get("total_tokens"))
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
