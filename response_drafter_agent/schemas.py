"""AEI request and response schemas for the TCS RFP Response Drafter."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class SkillLoad(BaseModel):
    name: str
    description: str | None = None
    trigger_mode: str = "auto"
    matched_keywords: list[str] = Field(default_factory=list)
    load_latency_ms: int = 0
    tokens_injected: int = 0
    estimated_tokens_saved: int = 0
    supporting_files: list[str] = Field(default_factory=list)


class ToolCall(BaseModel):
    tool_name: str
    source: str
    target: str
    status: str
    latency_ms: int
    request: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class InvokeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    context: dict[str, Any] | None = None
    conversation_id: str | None = None
    # model_override: str | None = None
    temperature_override: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p_override: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens_override: int | None = Field(default=None, ge=1, le=32000)
    frequency_penalty_override: float | None = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty_override: float | None = Field(default=None, ge=-2.0, le=2.0)
    seed_override: int | None = Field(default=None, ge=0)
    governance_action: dict[str, Any] | None = None


class InvokeResponse(BaseModel):
    response: str
    model_used: str
    latency_ms: int
    token_usage: TokenUsage
    trace_id: str
    prompt_name: str | None = None
    prompt_version: int | None = None
    prompt_label: str | None = None
    prompt_variant: str | None = None
    prompt_source: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    skills_loaded: list[SkillLoad] = Field(default_factory=list)


class AgentHealthResponse(BaseModel):
    status: str
    agent_id: str
    agent_name: str
    agent_version: str
    domain: str


class AgentConfigResponse(BaseModel):
    agent_id: str
    name: str
    version: str
    description: str
    domain: str
    default_model: str
    supported_models: list[str]
    eval_playbook_slug: str
    langfuse_prompt_name: str
    langfuse_prompt_label: str
    langfuse_prompt_variants: dict[str, str]
    prompt_source: str
    langfuse: dict[str, Any]
    requested_entitlements: list[str]
    entitlement_scope: str
    governance_charter: dict[str, Any]
    default_temperature: float | None = None
    default_top_p: float | None = None
    default_max_tokens: int | None = None
    default_frequency_penalty: float | None = None
    default_presence_penalty: float | None = None
    framework: str
    graph_nodes: list[str]


class PromptSyncResponse(BaseModel):
    status: str
    prompt_name: str | None = None
    prompt_version: int | None = None
    prompt_label: str | None = None
    source: str | None = None
    message: str | None = None
    variants: dict[str, str] = Field(default_factory=dict)


class DraftResponse(BaseModel):
    question: str
    intent: str
    draft_answer: str
    grounding_status: str
    authority_status: str
    review_required: bool
    limitations: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
