"""AEI-conformant TCS RFP Response Drafter agent."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import FastAPI, HTTPException

from .governance import Constitution, classify_request_scope, infer_intent, redact_sensitive_text
from .graph import build_graph
from .knowledge import KnowledgeRetriever
from .langfuse_integration import LangfuseTelemetry, usage_details_from_token_usage
from .llm import LLMClient
from .prompts import PromptManager, PromptResolution
from .schemas import (
    AgentConfigResponse,
    AgentHealthResponse,
    DraftResponse,
    InvokeRequest,
    InvokeResponse,
    PromptSyncResponse,
    SkillLoad,
    TokenUsage,
)
from .settings import (
    BASE_DIR,
    GOVERNANCE_CHARTER,
    REQUESTED_ENTITLEMENTS,
    AgentSettings,
)
from .telemetry import Telemetry


logger = logging.getLogger(__name__)


class ResponseDrafterAgent:
    def __init__(self, settings: AgentSettings | None = None) -> None:
        self.settings = settings or AgentSettings()
        self.telemetry = Telemetry(service_name=self.settings.agent_id)
        self.langfuse = LangfuseTelemetry(service_name=self.settings.agent_id)
        self.prompts = PromptManager(
            prompt_dir=BASE_DIR / "prompts",
            prompt_name=self.settings.langfuse_prompt_name,
            prompt_label=self.settings.langfuse_prompt_label,
            langfuse_client=self.langfuse.client,
        )
        self.constitution = Constitution(BASE_DIR / "config" / "constitution.yaml")
        self.knowledge = KnowledgeRetriever()
        self.llm = LLMClient(default_model=self.settings.default_model)
        self.graph = build_graph(self)

    async def health(self) -> AgentHealthResponse:
        return AgentHealthResponse(
            status="healthy",
            agent_id=self.settings.agent_id,
            agent_name=self.settings.name,
            agent_version=self.settings.version,
            domain=self.settings.domain,
        )

    def config(self) -> AgentConfigResponse:
        supported = list(dict.fromkeys([self.settings.default_model, *self.settings.supported_models]))
        langfuse_status = self.langfuse.status()
        langfuse_ready = bool(langfuse_status["client_available"])
        return AgentConfigResponse(
            agent_id=self.settings.agent_id,
            name=self.settings.name,
            version=self.settings.version,
            description=self.settings.description,
            domain=self.settings.domain,
            default_model=self.settings.default_model,
            supported_models=supported,
            eval_playbook_slug=self.settings.eval_playbook_slug,
            langfuse_prompt_name=self.settings.langfuse_prompt_name,
            langfuse_prompt_label=self.settings.langfuse_prompt_label,
            langfuse_prompt_variants=self.prompts.prompt_name_map(),
            prompt_source="langfuse" if langfuse_ready else "local",
            langfuse=langfuse_status,
            requested_entitlements=list(REQUESTED_ENTITLEMENTS),
            entitlement_scope=self.settings.entitlement_scope,
            governance_charter=GOVERNANCE_CHARTER,
            default_temperature=self.settings.default_temperature,
            default_top_p=self.settings.default_top_p,
            default_max_tokens=self.settings.default_max_tokens,
            default_frequency_penalty=self.settings.default_frequency_penalty,
            default_presence_penalty=self.settings.default_presence_penalty,
            framework=self.settings.framework,
            graph_nodes=list(self.settings.graph_nodes),
        )

    def sync_prompts(self) -> PromptSyncResponse:
        return self.prompts.sync()

    async def invoke(self, body: InvokeRequest) -> InvokeResponse:
        started = time.perf_counter()
        context = body.context or {}
        if context.get("force_mock") is not None:
            raise ValueError("context.force_mock is no longer supported; invoke uses live configured services only.")
        # requested_model = body.model_override or self.settings.default_model
        requested_model = "GLM-4.7-Flash"
        redacted_query = redact_sensitive_text(body.query).strip()
        system_prompt_override = context.get("system_prompt_override")
        if system_prompt_override is not None:
            system_prompt_override = str(system_prompt_override)

        langfuse_input = {
            "query": redacted_query,
            "conversation_id": body.conversation_id,
            "model": requested_model,
            "case_ref": context.get("case_ref"),
            "run_id": context.get("run_id"),
        }
        with self.langfuse.observation(
            name="responsecraft-agent",
            as_type="agent",
            input=langfuse_input,
            metadata={
                "agent_id": self.settings.agent_id,
                "domain": self.settings.domain,
                "framework": self.settings.framework,
            },
            version=self.settings.version,
        ) as langfuse_span:
            langfuse_span.set_trace_io(input=langfuse_input)
            with self.telemetry.span(
                "agent.invoke",
                {
                    "gen_ai.operation.name": "agent.invoke",
                    "gen_ai.system": "agentic_control_plane",
                    "gen_ai.request.model": requested_model,
                    "agent.id": self.settings.agent_id,
                    "agent.domain": self.settings.domain,
                    "conversation_id": body.conversation_id,
                    "case_ref": context.get("case_ref"),
                    "run_id": context.get("run_id"),
                },
            ) as span:
                initial_state: dict[str, Any] = {
                    "query": body.query,
                    "context": context,
                    "conversation_id": body.conversation_id,
                    "model": requested_model,
                    "system_prompt_override": system_prompt_override,
                    "temperature": (
                        body.temperature_override
                        if body.temperature_override is not None
                        else self.settings.default_temperature
                    ),
                    "top_p": body.top_p_override if body.top_p_override is not None else self.settings.default_top_p,
                    "max_tokens": (
                        body.max_tokens_override
                        if body.max_tokens_override is not None
                        else self.settings.default_max_tokens
                    ),
                    "frequency_penalty": (
                        body.frequency_penalty_override
                        if body.frequency_penalty_override is not None
                        else self.settings.default_frequency_penalty
                    ),
                    "presence_penalty": (
                        body.presence_penalty_override
                        if body.presence_penalty_override is not None
                        else self.settings.default_presence_penalty
                    ),
                    "seed": body.seed_override,
                    "governance_action": body.governance_action,
                    "trace_id": span.trace_id,
                    "tool_calls": [],
                    "system_errors": [],
                    "skills_loaded": self._skills_from_context(context),
                }
                final_state = await self.graph.ainvoke(initial_state)
                token_usage: TokenUsage = final_state.get("token_usage") or TokenUsage()
                span.set_attribute("gen_ai.response.model", final_state.get("model_used") or requested_model)
                span.set_attribute("gen_ai.usage.input_tokens", token_usage.input_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", token_usage.output_tokens)

            prompt: PromptResolution = final_state["prompt_resolution"]
            response = InvokeResponse(
                response=final_state["response_text"],
                model_used=final_state.get("model_used") or requested_model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                token_usage=token_usage,
                trace_id=final_state.get("trace_id") or span.trace_id,
                prompt_name=prompt.prompt_name,
                prompt_version=prompt.prompt_version,
                prompt_label=prompt.prompt_label,
                prompt_variant=prompt.prompt_variant,
                prompt_source=prompt.source,
                tool_calls=final_state.get("tool_calls", []),
                skills_loaded=final_state.get("skills_loaded", []),
            )
            langfuse_output = {
                "model_used": response.model_used,
                "prompt_name": response.prompt_name,
                "prompt_version": response.prompt_version,
                "prompt_label": response.prompt_label,
                "prompt_variant": response.prompt_variant,
                "prompt_source": response.prompt_source,
                "authority_status": final_state.get("authority", {}).get("authority_status"),
                "grounding_status": final_state.get("grounding", {}).get("grounding_status"),
                "scope_status": final_state.get("scope", {}).get("scope_status"),
                "response": response.response,
            }
            langfuse_span.update(
                output=langfuse_output,
                metadata={"otel_trace_id": response.trace_id},
                usage_details=usage_details_from_token_usage(response.token_usage),
            )
            langfuse_span.set_trace_io(input=langfuse_input, output=langfuse_output)
            if self.langfuse.config.flush_on_invoke:
                langfuse_span.flush()
            return response

    async def plan_node(self, state: dict[str, Any]) -> dict[str, Any]:
        with self.telemetry.span(
            "agent.plan",
            {
                "gen_ai.operation.name": "agent.step",
                "agent.node": "plan",
            },
            trace_id=state.get("trace_id"),
        ):
            question = redact_sensitive_text(state["query"]).strip()
            intent = infer_intent(question)
            scope = classify_request_scope(question, intent)
            state["question_for_model"] = question
            state["intent"] = intent
            state["scope"] = scope
            if scope["scope_status"] == "in_scope":
                state["plan"] = [
                    "Classify RFP question intent.",
                    "Retrieve approved knowledge.",
                    "Draft a grounded answer for proposal-team review.",
                    "Reflect for authority and grounding compliance.",
                ]
            else:
                state["plan"] = [
                    "Classify request scope.",
                    "Return deterministic scoped response without retrieval or generation.",
                ]
        return state

    async def reason_node(self, state: dict[str, Any]) -> dict[str, Any]:
        with self.telemetry.span(
            "agent.reason",
            {
                "gen_ai.operation.name": "agent.step",
                "agent.node": "reason",
            },
            trace_id=state.get("trace_id"),
        ):
            authority = self.constitution.evaluate_request(state["query"], state.get("context"))
            scope = dict(state.get("scope") or classify_request_scope(state["question_for_model"], state["intent"]))
            if authority["authority_status"] == "prohibited":
                scope.update(
                    {
                        "scope_status": "prohibited_authority",
                        "skip_retrieval": True,
                        "skip_generation": True,
                        "review_required": True,
                        "deterministic_answer": (
                            "I cannot draft pricing, legal, contractual, warranty, final-approval, "
                            "or proposal-submission commitments. Please route this request to the "
                            "proposal owner or the accountable SME."
                        ),
                        "limitations": [
                            "Request asks for authority outside the response drafter charter; retrieval was not performed."
                        ],
                    }
                )
            elif scope.get("scope_status") == "outside_agent_scope":
                authority = {
                    **authority,
                    "authority_status": "outside_agent_scope",
                    "violations": [
                        *authority.get("violations", []),
                        {
                            "rule": "agent_scope",
                            "severity": "low",
                            "message": "The request is outside the RFP response drafter scope.",
                        },
                    ],
                    "proposal_review_required": False,
                }
            state["authority"] = authority
            state["scope"] = scope
            state["information_needs"] = _information_needs_for_intent(state["intent"])
        return state

    async def retrieve_node(self, state: dict[str, Any]) -> dict[str, Any]:
        with self.telemetry.span(
            "agent.retrieve",
            {
                "gen_ai.operation.name": "retrieval",
                "agent.node": "retrieve",
                "gen_ai.system": "mcp",
            },
            trace_id=state.get("trace_id"),
        ) as span:
            if state.get("scope", {}).get("skip_retrieval"):
                span.set_attribute("retrieval.skipped", True)
                span.set_attribute("retrieval.skip_reason", state.get("scope", {}).get("scope_status"))
                state["evidence"] = []
                return state

            evidence, tool_call = await self.knowledge.retrieve(
                state["question_for_model"],
                top_k=5,
                filters={"intent": state["intent"]},
            )
            span.set_attribute("retrieval.result_count", len(evidence))
            span.set_attribute("tool.name", tool_call.tool_name)
            span.set_attribute("tool.status", tool_call.status)
            state["evidence"] = evidence
            state["tool_calls"] = [*state.get("tool_calls", []), tool_call]
            print(
                "[response-drafter.invoke] tool_output="
                + json.dumps(
                    {
                        "trace_id": state.get("trace_id"),
                        "tool_name": tool_call.tool_name,
                        "status": tool_call.status,
                        "target": tool_call.target,
                        "latency_ms": tool_call.latency_ms,
                        "error": tool_call.error,
                        "evidence": [
                            {
                                "source_id": item.source_id,
                                "title": item.title,
                                "score": item.score,
                                "content": item.content,
                                "metadata": item.metadata,
                            }
                            for item in evidence
                        ],
                    },
                    ensure_ascii=True,
                    default=str,
                ),
                flush=True,
            )
            if tool_call.status != "success":
                state["system_errors"] = [
                    *state.get("system_errors", []),
                    {
                        "component": "proposal_knowledge_retrieval",
                        "tool": tool_call.tool_name,
                        "source": tool_call.source,
                        "target": tool_call.target,
                        "error": tool_call.error or "unknown_error",
                    },
                ]
        return state

    async def act_node(self, state: dict[str, Any]) -> dict[str, Any]:
        prompt = self.prompts.resolve(
            state["model"],
            system_prompt_override=state.get("system_prompt_override"),
        )
        system_errors = state.get("system_errors", [])
        scope = state.get("scope", {})
        if scope.get("skip_generation"):
            grounding = {
                "grounding_status": "not_applicable",
                "limitations": list(scope.get("limitations") or []),
            }
            state["prompt_resolution"] = prompt
            state["grounding"] = grounding
            state["draft_answer"] = str(scope.get("deterministic_answer") or "")
            state["model_used"] = state["model"]
            state["token_usage"] = TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0)
            return state

        if system_errors:
            grounding = {
                "grounding_status": "retrieval_error",
                "limitations": [
                    "Approved supporting knowledge could not be retrieved because a configured dependency returned an error."
                ],
            }
            state["prompt_resolution"] = prompt
            state["grounding"] = grounding
            state["draft_answer"] = (
                "The response drafter is currently unable to retrieve approved supporting "
                "knowledge from the proposal knowledge service. Please route this item to "
                "the proposal team or support owner before drafting a substantive answer."
            )
            state["model_used"] = state["model"]
            state["token_usage"] = TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0)
            return state
        else:
            grounding = self.constitution.evaluate_grounding(state.get("evidence", []))
        generation_params = {
            "temperature": state.get("temperature"),
            "top_p": state.get("top_p"),
            "max_tokens": state.get("max_tokens"),
            "frequency_penalty": state.get("frequency_penalty"),
            "presence_penalty": state.get("presence_penalty"),
            "seed": state.get("seed"),
        }

        with self.telemetry.span(
            "agent.generate",
            {
                "gen_ai.operation.name": "chat",
                "agent.node": "act",
                "gen_ai.system": "llm_gateway",
                "gen_ai.request.model": state["model"],
                "gen_ai.request.temperature": generation_params["temperature"],
                "gen_ai.request.max_tokens": generation_params["max_tokens"],
            },
            trace_id=state.get("trace_id"),
        ) as span:
            with self.langfuse.observation(
                name="responsecraft-generate",
                as_type="generation",
                input={
                    "question": state["question_for_model"],
                    "intent": state["intent"],
                    "prompt_name": prompt.prompt_name,
                    "prompt_variant": prompt.prompt_variant,
                    "evidence_sources": [
                        item.source_id for item in state.get("evidence", [])
                    ],
                },
                model=state["model"],
                model_parameters={
                    key: value
                    for key, value in generation_params.items()
                    if value is not None
                },
                metadata={
                    "prompt_source": prompt.source,
                    "authority_status": state["authority"]["authority_status"],
                    "grounding_status": grounding["grounding_status"],
                    "system_error_count": len(system_errors),
                },
            ) as langfuse_generation:
                draft, model_used, usage = await self.llm.draft(
                    question=state["question_for_model"],
                    intent=state["intent"],
                    evidence=state.get("evidence", []),
                    authority=state["authority"],
                    grounding=grounding,
                    prompt=prompt,
                    model=state["model"],
                    generation_params=generation_params,
                    system_errors=system_errors,
                )
                draft = _extract_draft_answer_text(draft)
                if not draft.strip():
                    draft = _fallback_answer_from_evidence(
                        state.get("evidence", []),
                        grounding,
                    )
                langfuse_generation.update(
                    output=draft,
                    model=model_used,
                    usage_details=usage_details_from_token_usage(usage),
                )
            span.set_attribute("gen_ai.response.model", model_used)
            span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)

        state["prompt_resolution"] = prompt
        state["grounding"] = grounding
        state["draft_answer"] = draft
        state["model_used"] = model_used
        state["token_usage"] = usage
        return state

    async def reflect_node(self, state: dict[str, Any]) -> dict[str, Any]:
        with self.telemetry.span(
            "agent.reflect",
            {
                "gen_ai.operation.name": "guardrail_check",
                "agent.node": "reflect",
            },
            trace_id=state.get("trace_id"),
        ):
            reflection = self.constitution.reflect(
                state["draft_answer"],
                state.get("evidence", []),
                state["authority"],
            )
            state["reflection"] = reflection
        return state

    async def render_node(self, state: dict[str, Any]) -> dict[str, Any]:
        with self.telemetry.span(
            "agent.render",
            {
                "gen_ai.operation.name": "agent.step",
                "agent.node": "render",
            },
            trace_id=state.get("trace_id"),
        ):
            limitations = [
                *state["grounding"].get("limitations", []),
                *[
                    violation["message"]
                    for violation in state["authority"].get("violations", [])
                ],
            ]
            if state.get("reflection", {}).get("requires_revision"):
                limitations.extend(state["reflection"].get("reflection", []))

            draft = DraftResponse(
                question=state["question_for_model"],
                intent=state["intent"],
                draft_answer=state["draft_answer"],
                grounding_status=state["grounding"]["grounding_status"],
                authority_status=state["authority"]["authority_status"],
                review_required=bool(state.get("scope", {}).get("review_required", True)),
                limitations=list(dict.fromkeys(limitations)),
                evidence_sources=[item.source_id for item in state.get("evidence", [])],
            )
            state["debug_payload"] = draft.model_dump()
            logger.debug(
                "response_drafter_debug=%s",
                json.dumps(state["debug_payload"], ensure_ascii=True, sort_keys=True),
            )
            state["response_text"] = draft.draft_answer
        return state

    def _skills_from_context(self, context: dict[str, Any]) -> list[SkillLoad]:
        raw = context.get("skills_loaded") or context.get("skills") or []
        if not isinstance(raw, list):
            return []
        skills: list[SkillLoad] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            text = str(item.get("instructions") or item.get("instructions_text") or "")
            skills.append(
                SkillLoad(
                    name=name,
                    description=item.get("description"),
                    trigger_mode=str(item.get("trigger_mode") or "skill_fabric"),
                    matched_keywords=[str(v) for v in item.get("matched_keywords", [])],
                    tokens_injected=max(0, len(text) // 4),
                    estimated_tokens_saved=max(0, len(text) // 2),
                    supporting_files=[str(v) for v in item.get("supporting_files", [])],
                )
            )
        return skills


def _information_needs_for_intent(intent: str) -> list[str]:
    needs = {
        "security_and_compliance": [
            "security controls",
            "compliance attestations",
            "data protection practices",
        ],
        "delivery_methodology": [
            "delivery lifecycle",
            "governance model",
            "transition approach",
        ],
        "business_continuity": [
            "resilience practices",
            "continuity planning",
            "disaster recovery governance",
        ],
        "staffing_and_resourcing": [
            "role model",
            "skills and staffing approach",
            "knowledge transfer",
        ],
        "solution_architecture": [
            "reference architecture",
            "technology capabilities",
            "implementation approach",
        ],
    }
    return needs.get(intent, ["approved capability description", "proposal-safe differentiators"])


def _extract_draft_answer_text(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    for _ in range(3):
        candidate = _strip_code_fence(text)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return text

        if isinstance(parsed, dict):
            for key in ("draft_answer", "answer", "response"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    next_text = value.strip()
                    if next_text == text:
                        return next_text
                    text = next_text
                    break
                if isinstance(value, dict):
                    text = json.dumps(value, ensure_ascii=True)
                    break
            else:
                return text
            continue

        if isinstance(parsed, str) and parsed.strip():
            text = parsed.strip()
            continue
        return text
    return text


def _fallback_answer_from_evidence(evidence: list[Any], grounding: dict[str, Any]) -> str:
    for item in evidence:
        content = str(getattr(item, "content", "") or "").strip()
        if content:
            limitations = [
                str(value).strip()
                for value in grounding.get("limitations", [])
                if str(value).strip()
            ]
            if limitations:
                return f"{content}\n\nNote: {' '.join(limitations)}"
            return content
    return (
        "Approved supporting knowledge was retrieved, but the language model returned an empty draft. "
        "Please route this item to the proposal team or support owner before using the response."
    )


def _strip_code_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if len(lines) >= 3 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


agent = ResponseDrafterAgent()


def create_app() -> FastAPI:
    app = FastAPI(title=agent.settings.name, version=agent.settings.version)

    @app.get("/health", response_model=AgentHealthResponse)
    async def health() -> AgentHealthResponse:
        return await agent.health()

    @app.get("/config", response_model=AgentConfigResponse)
    async def config() -> AgentConfigResponse:
        return agent.config()

    @app.post("/invoke", response_model=InvokeResponse)
    async def invoke(body: InvokeRequest) -> InvokeResponse:
        try:
            return await agent.invoke(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Invoke failed: {exc}") from exc

    @app.post("/prompts/sync", response_model=PromptSyncResponse)
    async def prompts_sync() -> PromptSyncResponse:
        return agent.sync_prompts()

    return app


app = create_app()
