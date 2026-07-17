"""LLM gateway adapter."""

from __future__ import annotations

import json
import os
import time as _time
from typing import Any

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - live LLM mode reports this clearly.
    ChatOpenAI = None  # type: ignore[assignment]
    AIMessage = HumanMessage = SystemMessage = ToolMessage = None  # type: ignore[assignment,misc]

from .knowledge import Evidence, search_proposal_knowledge
from .logging_utils import get_logger
from .prompts import PromptResolution
from .schemas import ToolCall, TokenUsage
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

    # ------------------------------------------------------------------
    # LLM-driven agentic loop (primary path)
    # ------------------------------------------------------------------

    async def run_agent(
        self,
        *,
        query: str,
        prompt: PromptResolution,
        model: str,
        generation_params: dict[str, Any],
        max_iterations: int = 3,
    ) -> tuple[str, str, TokenUsage, list[Evidence], list[ToolCall]]:
        """Run the LLM in an agentic tool-calling loop.

        The LLM is bound with the ``search_proposal_knowledge`` tool.  It
        reasons autonomously, calls the tool if it decides retrieval is needed,
        receives the tool output, and produces the final answer.

        Returns:
            (final_text, model_used, token_usage, evidence_list, tool_calls)
        """
        if ChatOpenAI is None:
            logger.error("[run_agent] langchain-openai is not installed — live LLM mode unavailable")
            raise RuntimeError(
                "langchain-openai is required for live LLM mode. "
                "Install requirements.txt and configure a live LLM key."
            )
        if not self.api_key:
            logger.error(
                "[run_agent] No LLM API key configured — cannot call LLM | "
                "Checked: LLM_API_KEY, OPENAI_API_KEY, LITELLM_MASTER_KEY"
            )
            raise RuntimeError(
                "Live LLM mode requires LLM_API_KEY, OPENAI_API_KEY, or LITELLM_MASTER_KEY. "
                "Add the key to .env and restart the service."
            )

        logger.info(
            "[run_agent] Starting agentic loop | model=%s | query_len=%d | "
            "prompt_source=%s | prompt_variant=%s | temperature=%s | max_tokens=%s | max_iterations=%d",
            model,
            len(query),
            prompt.source,
            prompt.prompt_variant,
            generation_params.get("temperature"),
            generation_params.get("max_tokens"),
            max_iterations,
        )

        base_llm = self._chat_model(model=model, generation_params=generation_params)

        logger.info("Constructed ChatOpenAI object")

        try:
            logger.info("Model           : %s", base_llm.model_name)
        except Exception:
            pass

        try:
            logger.info("Model kwargs    : %s", base_llm.model_kwargs)
        except Exception:
            pass

        try:
            logger.info("Default params  : %s", base_llm._default_params)
        except Exception:
            pass

        # Bind the MCP knowledge tool so the LLM can call it natively.
        llm_with_tools = base_llm.bind_tools([search_proposal_knowledge])

        messages: list[Any] = [
            SystemMessage(content=prompt.text),
            HumanMessage(content=query),
        ]

        all_evidence: list[Evidence] = []
        all_tool_calls: list[ToolCall] = []
        cumulative_input_tokens = 0
        cumulative_output_tokens = 0
        model_used = model
        final_text = ""

        for iteration in range(max_iterations):
            logger.debug(
                "[run_agent] Iteration %d | message_count=%d",
                iteration + 1,
                len(messages),
            )

            # ---- LLM call -----------------------------------------------
            logger.info("=" * 80)
            logger.info("MESSAGE HISTORY")
            logger.info("=" * 80)

            for i, msg in enumerate(messages):
                try:
                    logger.info("[%d] %s: %s", i, type(msg).__name__, msg.content)
                except Exception:
                    logger.info("[%d] %s: %s", i, type(msg).__name__, str(msg))

            logger.info("=" * 80)
            logger.info("Calling ainvoke()")
            logger.info("=" * 80)
            response: AIMessage = await llm_with_tools.ainvoke(messages)

            logger.info("=" * 80)
            logger.info("RAW AI MESSAGE")
            logger.info("=" * 80)
            logger.info("%s", response)

            logger.info("=" * 60)
            logger.info("CONTENT")
            logger.info("=" * 60)
            logger.info("%s", response.content)

            logger.info("=" * 60)
            logger.info("TOOL CALLS")
            logger.info("=" * 60)
            logger.info("%s", getattr(response, "tool_calls", None))

            logger.info("=" * 60)
            logger.info("INVALID TOOL CALLS")
            logger.info("=" * 60)
            logger.info("%s", getattr(response, "invalid_tool_calls", None))

            logger.info("=" * 60)
            logger.info("USAGE METADATA")
            logger.info("=" * 60)
            logger.info("%s", getattr(response, "usage_metadata", None))

            logger.info("=" * 60)
            logger.info("RESPONSE METADATA")
            logger.info("=" * 60)
            logger.info("%s", getattr(response, "response_metadata", None))

            logger.info("=" * 60)
            logger.info("ADDITIONAL KWARGS")
            logger.info("=" * 60)
            logger.info("%s", getattr(response, "additional_kwargs", None))

            logger.info("=" * 60)
            logger.info("MESSAGE ID")
            logger.info("=" * 60)
            logger.info("%s", getattr(response, "id", None))
            
            usage = _usage_from_message(response)
            cumulative_input_tokens += usage.input_tokens or 0
            cumulative_output_tokens += usage.output_tokens or 0

            response_metadata = getattr(response, "response_metadata", {}) or {}
            model_used = str(
                response_metadata.get("model_name")
                or response_metadata.get("model")
                or model
            )

            # Check if the LLM wants to call a tool.
            tool_calls_from_llm = getattr(response, "tool_calls", None) or []

            if not tool_calls_from_llm:
                # No tool call — this is the final answer.
                final_text = _message_text(getattr(response, "content", ""))
                logger.info(
                    "[run_agent] Final answer received | iteration=%d | model_used=%s | "
                    "input_tokens=%d | output_tokens=%d | answer_len=%d",
                    iteration + 1,
                    model_used,
                    cumulative_input_tokens,
                    cumulative_output_tokens,
                    len(final_text),
                )
                break

            # ---- Tool execution -----------------------------------------
            logger.info(
                "[run_agent] LLM requested %d tool call(s) | iteration=%d",
                len(tool_calls_from_llm),
                iteration + 1,
            )
            messages.append(response)  # Add AI message with tool_calls

            for tc in tool_calls_from_llm:
                tc_name = tc.get("name", "")
                tc_args = tc.get("args", {})
                tc_id = tc.get("id", "tool-call")

                logger.info(
                    "[run_agent] Executing tool | tool=%s | args=%s",
                    tc_name,
                    json.dumps(tc_args, ensure_ascii=True)[:200],
                )

                if tc_name == "search_proposal_knowledge":
                    _started = _time.perf_counter()
                    try:
                        tool_result_str: str = await search_proposal_knowledge.ainvoke(tc_args)
                        _latency_ms = int((_time.perf_counter() - _started) * 1000)

                        # Parse evidence items from the JSON string result.
                        try:
                            raw_items: list[dict[str, Any]] = json.loads(tool_result_str)
                        except json.JSONDecodeError:
                            raw_items = []

                        from .knowledge import Evidence as _Evidence
                        evidence_batch = [
                            _Evidence(
                                source_id=str(item.get("source_id", f"mcp-{i}")),
                                title=str(item.get("title", "")),
                                content=str(item.get("content", "")),
                                score=float(item.get("score", 1.0)),
                                metadata={},
                            )
                            for i, item in enumerate(raw_items)
                            if isinstance(item, dict) and item.get("content")
                        ]
                        all_evidence.extend(evidence_batch)

                        tool_call_record = ToolCall(
                            tool_name="search_proposal_knowledge",
                            source="mcp",
                            target=str(os.getenv("MCP_URL", "")),
                            status="success",
                            latency_ms=_latency_ms,
                            request={"query": tc_args.get("query", "")},
                            summary={
                                "result_count": len(evidence_batch),
                                "sources": [e.source_id for e in evidence_batch],
                            },
                        )
                        all_tool_calls.append(tool_call_record)

                        logger.info(
                            "[run_agent] Tool returned %d evidence items | latency_ms=%d",
                            len(evidence_batch),
                            _latency_ms,
                        )
                        tool_output = tool_result_str

                    except Exception as exc:
                        _latency_ms = int((_time.perf_counter() - _started) * 1000)
                        logger.error(
                            "[run_agent] Tool execution FAILED | tool=%s | error=%s | latency_ms=%d",
                            tc_name,
                            exc.__class__.__name__,
                            _latency_ms,
                        )
                        tool_call_record = ToolCall(
                            tool_name="search_proposal_knowledge",
                            source="mcp",
                            target="",
                            status="error",
                            latency_ms=_latency_ms,
                            request={"query": tc_args.get("query", "")},
                            summary={"result_count": 0},
                            error=exc.__class__.__name__,
                        )
                        all_tool_calls.append(tool_call_record)
                        tool_output = json.dumps({"error": str(exc)})
                else:
                    logger.warning("[run_agent] Unknown tool requested by LLM | tool=%s", tc_name)
                    tool_output = json.dumps({"error": f"Unknown tool: {tc_name}"})

                messages.append(
                    ToolMessage(content=tool_output, tool_call_id=tc_id)
                )

            # After all tool results are appended, loop back to let LLM synthesize.

        else:
            # Reached max iterations without a final text response.
            logger.warning(
                "[run_agent] Max iterations (%d) reached without final answer — using last content",
                max_iterations,
            )
            last_msg = messages[-1] if messages else None
            if last_msg is not None:
                final_text = _message_text(getattr(last_msg, "content", ""))

        token_usage = TokenUsage(
            input_tokens=cumulative_input_tokens or None,
            output_tokens=cumulative_output_tokens or None,
            total_tokens=(cumulative_input_tokens + cumulative_output_tokens) or None,
        )
        if token_usage.total_tokens is None:
            token_usage = _estimate_usage(query, final_text, prompt.text)

        return final_text, model_used, token_usage, all_evidence, all_tool_calls

    # ------------------------------------------------------------------
    # Legacy draft() — retained for backward compatibility
    # ------------------------------------------------------------------

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

        return (text, model_used, usage)

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