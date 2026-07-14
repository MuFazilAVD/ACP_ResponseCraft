"""Tracked runtime settings and ACP declarations.

Only secrets and API keys should come from environment variables. Stable runtime
choices such as URLs, model names, labels, and generation defaults live here so
they are versioned with the code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR.parent / ".env"
SECRET_ENV_NAMES = frozenset(
    {
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "LITELLM_MASTER_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "OTLP_API_KEY",
        "ACP_AGENT_API_KEY",
        "MCP_API_KEY",
        "PROPOSAL_KNOWLEDGE_API_KEY",
        "APPROVED_CAPABILITY_LIBRARY_API_KEY",
        "SECURITY_COMPLIANCE_LIBRARY_API_KEY",
        # AWS / DynamoDB credentials
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "DYNAMODB_REGION",
    }
)
DEFAULT_AGENT_HOST = "0.0.0.0"
DEFAULT_AGENT_PORT = 8110
DEFAULT_DYNAMODB_REGION = "ap-south-1"
DEFAULT_LLM_PROVIDER = "litellm"
DEFAULT_LLM_BASE_URL = "https://d2brdeqy144bwg.cloudfront.net/myllm/v1/"
DEFAULT_LLM_MODEL = "GLM-4.7-Flash"
DEFAULT_LLM_USER = "AgentStudio"
DEFAULT_MCP_PROPOSAL_KNOWLEDGE_URL = (
    "https://d2brdeqy144bwg.cloudfront.net/poc185/acp-mcp/rd-mcp-server/tools/search_proposal_knowledge"
)
DEFAULT_MCP_PROPOSAL_KNOWLEDGE_TRANSPORT = "http_bridge"
DEFAULT_MCP_PROPOSAL_KNOWLEDGE_TOOL = "search_proposal_knowledge"
DEFAULT_LANGFUSE_BASE_URL = "http://172.16.1.224"
DEFAULT_LANGFUSE_PROJECT = "proposal-management"
DEFAULT_LANGFUSE_PROMPT_LABEL = "production"
DEFAULT_LANGFUSE_TRACING_ENABLED = True
DEFAULT_LANGFUSE_FLUSH_ON_INVOKE = True
DEFAULT_LANGFUSE_AUTH_CHECK_ON_SYNC = True
DEFAULT_OTLP_ENDPOINT = ""
DEFAULT_OTLP_AUTH_HEADER = "Authorization"
DEFAULT_OTLP_AUTH_SCHEME = "Bearer"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 1400


def _load_key_only_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in SECRET_ENV_NAMES:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_key_only_env(ENV_FILE)


GOVERNANCE_CHARTER = {
    "lob": "proposal_management",
    "accountable_role": "proposal-response-approver",
    "action_classes": [
        {
            "action_class": "analyze_rfp_question",
            "plain_label": "Analyze an incoming RFP question",
            "risk_tier": "low",
            "required_oversight": "autonomous",
        },
        {
            "action_class": "retrieve_approved_knowledge",
            "plain_label": "Retrieve approved proposal knowledge",
            "risk_tier": "low",
            "required_oversight": "autonomous",
        },
        {
            "action_class": "draft_rfp_response",
            "plain_label": "Draft a response for proposal-team review",
            "risk_tier": "low",
            "required_oversight": "autonomous",
        },
        {
            "action_class": "flag_insufficient_evidence",
            "plain_label": "Flag insufficient supporting knowledge",
            "risk_tier": "low",
            "required_oversight": "autonomous",
        },
        {
            "action_class": "make_commercial_commitment",
            "plain_label": "Make pricing, legal, contractual, or delivery commitments",
            "risk_tier": "critical",
            "required_oversight": "prohibited",
        },
        {
            "action_class": "approve_or_submit_proposal",
            "plain_label": "Approve or submit a final proposal response",
            "risk_tier": "critical",
            "required_oversight": "prohibited",
        },
    ],
    "delegation_policy": {
        "can_delegate": False,
        "max_depth": 0,
        "allowed_target_agent_ids": [],
    },
}


REQUESTED_ENTITLEMENTS = [
    "mcp_server:proposal-knowledge-mcp",
    "capability:rfp_knowledge.search",
    "capability:proposal_content.read",
    "capability:approved_capability_library.read",
    "capability:security_compliance_library.read",
    "enterprise_api:llm_gateway.chat_completions",
    "telemetry:langfuse.prompt_sync",
    "telemetry:langfuse.traces_write",
    "telemetry:otlp.traces_write",
]


@dataclass(frozen=True)
class AgentSettings:
    agent_id: str = "tcs-rfp-response-drafter"
    name: str = "TCS RFP Response Drafter"
    version: str = "0.1.0"
    description: str = (
        "Grounded RAG + Tools agent that drafts responses to RFP questions "
        "for proposal-team and SME review."
    )
    domain: str = "proposal_management"
    eval_playbook_slug: str = "proposal_management.rfp.response_drafting"
    default_model: str = DEFAULT_LLM_MODEL
    supported_models: tuple[str, ...] = (
        DEFAULT_LLM_MODEL,
        "vertex_ai/gemini-2.5-flash",
        "openai/gpt-4.1",
        "anthropic/claude-sonnet-4-6",
    )
    langfuse_prompt_name: str = "tcs-rfp-response-drafter-system"
    langfuse_prompt_label: str = DEFAULT_LANGFUSE_PROMPT_LABEL
    default_temperature: float = DEFAULT_TEMPERATURE
    default_top_p: float | None = None
    default_max_tokens: int | None = DEFAULT_MAX_TOKENS
    default_frequency_penalty: float | None = None
    default_presence_penalty: float | None = None
    entitlement_scope: str = "node"
    framework: str = "langgraph"
    graph_nodes: tuple[str, ...] = (
        "plan",
        "reason",
        "retrieve",
        "act",
        "reflect",
        "render",
    )
