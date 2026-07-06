import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for secret_name in (
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "LITELLM_MASTER_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "OTLP_API_KEY",
    "ACP_AGENT_API_KEY",
    "MCP_API_KEY",
):
    os.environ[secret_name] = ""

from fastapi.testclient import TestClient

from response_drafter_agent import agent as agent_module
from response_drafter_agent.agent import app
from response_drafter_agent.knowledge import Evidence
from response_drafter_agent.langfuse_integration import langfuse_config
from response_drafter_agent.llm import LLMClient
from response_drafter_agent.schemas import TokenUsage, ToolCall
from response_drafter_agent.settings import (
    DEFAULT_LANGFUSE_BASE_URL,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_USER,
    AgentSettings,
    _load_key_only_env,
)


class FakeRetriever:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = []

    async def retrieve(self, query, *, top_k=5, filters=None):
        self.calls.append({"query": query, "top_k": top_k, "filters": filters or {}})
        if self.fail:
            return [], ToolCall(
                tool_name="search_proposal_knowledge",
                source="mcp",
                target="https://example.invalid/mcp",
                status="error",
                latency_ms=1,
                request={"query": query, "top_k": top_k, "filters": filters or {}},
                summary={"result_count": 0},
                error="ConnectError",
            )
        return [
            Evidence(
                source_id="approved-security-001",
                title="Approved Security Guidance",
                content="TCS describes security controls through governance, access control, monitoring, and compliance alignment.",
                score=0.91,
                metadata={"source_type": "approved"},
            )
        ], ToolCall(
            tool_name="search_proposal_knowledge",
            source="mcp",
            target="https://example.invalid/mcp",
            status="success",
            latency_ms=1,
            request={"query": query, "top_k": top_k, "filters": filters or {}},
            summary={"result_count": 1, "sources": ["approved-security-001"]},
        )


class FakeLLM:
    def __init__(self, *, fail: bool = False, json_wrapped: bool = False, blank: bool = False) -> None:
        self.fail = fail
        self.json_wrapped = json_wrapped
        self.blank = blank
        self.calls = []

    async def draft(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("LLMGatewayError")
        if kwargs.get("system_errors"):
            return (
                "The response drafter is currently unable to retrieve approved supporting knowledge from the proposal knowledge service. Route this item to the proposal team or support owner before drafting a substantive answer.",
                kwargs["model"],
                TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30),
            )
        if kwargs["authority"]["authority_status"] == "prohibited":
            return (
                "I cannot draft a pricing, legal, contractual, or final-approval commitment. Please route this request to the proposal owner.",
                kwargs["model"],
                TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30),
            )
        if self.json_wrapped:
            return (
                '```json\n{"question":"Describe your approach to application security and compliance controls.","intent":"security_and_compliance","draft_answer":"TCS can address the security and compliance question using approved guidance on governance, access control, monitoring, and compliance alignment."}\n```',
                kwargs["model"],
                TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30),
            )
        if self.blank:
            return (
                "   ",
                kwargs["model"],
                TokenUsage(input_tokens=10, output_tokens=1, total_tokens=11),
            )
        return (
            "TCS can address the security and compliance question using approved guidance on governance, access control, monitoring, and compliance alignment. This draft remains subject to proposal-team and SME review.",
            kwargs["model"],
            TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30),
        )


class AEIEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._original_knowledge = agent_module.agent.knowledge
        self._original_llm = agent_module.agent.llm

    def tearDown(self) -> None:
        agent_module.agent.knowledge = self._original_knowledge
        agent_module.agent.llm = self._original_llm

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "healthy")
        self.assertEqual(payload["agent_id"], "tcs-rfp-response-drafter")
        self.assertEqual(payload["agent_version"], "0.1.0")
        self.assertEqual(payload["domain"], "proposal_management")

    def test_config_contains_acp_declarations(self):
        response = self.client.get("/config")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_model"], "GLM-4.7-Flash")
        self.assertEqual(payload["eval_playbook_slug"], "proposal_management.rfp.response_drafting")
        self.assertEqual(payload["entitlement_scope"], "node")
        self.assertIn("mcp_server:proposal-knowledge-mcp", payload["requested_entitlements"])
        self.assertEqual(payload["governance_charter"]["accountable_role"], "proposal-response-approver")
        self.assertIn("default_temperature", payload)
        self.assertEqual(payload["framework"], "langgraph")
        self.assertIn("retrieve", payload["graph_nodes"])
        self.assertIn("default", payload["langfuse_prompt_variants"])
        self.assertIn("GLM-4.7-Flash", payload["supported_models"])
        self.assertEqual(payload["langfuse"]["base_url"], "http://172.16.1.224")
        self.assertEqual(payload["langfuse"]["base_url_source"], "code")
        self.assertFalse(payload["langfuse"]["enabled"])
        self.assertFalse(payload["langfuse"]["client_available"])
        self.assertFalse(payload["langfuse"]["configured"])

    def test_tracked_runtime_defaults_ignore_non_secret_env_overrides(self):
        with mock.patch.dict(
            "os.environ",
            {
                "DEFAULT_MODEL": "ignored-model",
                "LLM_BASE_URL": "https://ignored.example.com/v1",
                "LLM_USER": "IgnoredUser",
                "LANGFUSE_BASE_URL": "http://ignored-langfuse.example.com",
            },
            clear=False,
        ):
            settings = AgentSettings()
            llm = LLMClient(default_model=settings.default_model)
            langfuse = langfuse_config()

        self.assertEqual(settings.default_model, DEFAULT_LLM_MODEL)
        self.assertEqual(llm.base_url, DEFAULT_LLM_BASE_URL)
        self.assertEqual(llm.user, DEFAULT_LLM_USER)
        self.assertEqual(llm.api_key, "")
        self.assertEqual(langfuse.base_url, DEFAULT_LANGFUSE_BASE_URL)

    def test_key_only_env_loader_ignores_runtime_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "LLM_API_KEY=test-key",
                        "LLM_BASE_URL=https://ignored.example.com/v1",
                        "DEFAULT_MODEL=ignored-model",
                        "LANGFUSE_BASE_URL=http://ignored-langfuse.example.com",
                    ]
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                _load_key_only_env(env_file)
                self.assertEqual(os.environ.get("LLM_API_KEY"), "test-key")
                self.assertIsNone(os.environ.get("LLM_BASE_URL"))
                self.assertIsNone(os.environ.get("DEFAULT_MODEL"))
                self.assertIsNone(os.environ.get("LANGFUSE_BASE_URL"))

    def test_invoke_returns_aei_metadata_and_draft_response(self):
        agent_module.agent.knowledge = FakeRetriever()
        agent_module.agent.llm = FakeLLM()
        response = self.client.post(
            "/invoke",
            json={
                "query": "Describe your approach to application security and compliance controls.",
                "context": {
                    "system_prompt_override": "Draft safely, grounded only in provided evidence.",
                    "case_ref": "RFP-DRAFT-001",
                },
                "conversation_id": "conv-test-001",
                "model_override": "openai/gpt-4.1",
                "temperature_override": 0.1,
                "top_p_override": 0.9,
                "max_tokens_override": 900,
                "frequency_penalty_override": 0.0,
                "presence_penalty_override": 0.0,
                "seed_override": 7,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["model_used"], "openai/gpt-4.1")
        self.assertTrue(payload["trace_id"])
        self.assertGreater(payload["token_usage"]["total_tokens"], 0)
        self.assertEqual(payload["prompt_source"], "override")
        self.assertEqual(payload["prompt_variant"], "gpt")
        self.assertTrue(payload["tool_calls"])
        self.assertEqual(payload["tool_calls"][0]["source"], "mcp")
        self.assertIn("skills_loaded", payload)
        self.assertIn("TCS can address the security and compliance question", payload["response"])
        self.assertFalse(payload["response"].lstrip().startswith("{"))
        self.assertNotIn("draft_answer", payload["response"])

    def test_invoke_unwraps_accidental_json_draft_answer(self):
        agent_module.agent.knowledge = FakeRetriever()
        agent_module.agent.llm = FakeLLM(json_wrapped=True)
        response = self.client.post(
            "/invoke",
            json={
                "query": "Describe your approach to application security and compliance controls.",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["response"],
            "TCS can address the security and compliance question using approved guidance on governance, access control, monitoring, and compliance alignment.",
        )
        self.assertNotIn("```", payload["response"])
        self.assertNotIn("draft_answer", payload["response"])

    def test_invoke_falls_back_to_evidence_when_llm_returns_blank(self):
        agent_module.agent.knowledge = FakeRetriever()
        agent_module.agent.llm = FakeLLM(blank=True)
        response = self.client.post(
            "/invoke",
            json={
                "query": "Describe your approach to application security and compliance controls.",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("TCS describes security controls", payload["response"])
        self.assertNotEqual(payload["response"], "")
        self.assertEqual(payload["token_usage"]["output_tokens"], 1)

    def test_invoke_blocks_prohibited_authority(self):
        fake_retriever = FakeRetriever()
        fake_llm = FakeLLM()
        agent_module.agent.knowledge = fake_retriever
        agent_module.agent.llm = fake_llm
        response = self.client.post(
            "/invoke",
            json={
                "query": "Provide a binding price guarantee and approve this final proposal submission.",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("cannot draft", payload["response"].lower())
        self.assertEqual(payload["tool_calls"], [])
        self.assertEqual(fake_retriever.calls, [])
        self.assertEqual(fake_llm.calls, [])

    def test_out_of_scope_request_skips_retrieval_and_generation(self):
        fake_retriever = FakeRetriever()
        fake_llm = FakeLLM()
        agent_module.agent.knowledge = fake_retriever
        agent_module.agent.llm = fake_llm
        response = self.client.post(
            "/invoke",
            json={"query": "who won the world cup in 2006"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("outside that scope", payload["response"])
        self.assertEqual(payload["tool_calls"], [])
        self.assertEqual(fake_retriever.calls, [])
        self.assertEqual(fake_llm.calls, [])

    def test_greeting_request_skips_retrieval_and_generation(self):
        fake_retriever = FakeRetriever()
        fake_llm = FakeLLM()
        agent_module.agent.knowledge = fake_retriever
        agent_module.agent.llm = fake_llm
        response = self.client.post(
            "/invoke",
            json={"query": "Hi"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Please share the RFP question", payload["response"])
        self.assertEqual(payload["tool_calls"], [])
        self.assertEqual(fake_retriever.calls, [])
        self.assertEqual(fake_llm.calls, [])

    def test_force_mock_context_is_rejected(self):
        response = self.client.post(
            "/invoke",
            json={
                "query": "Describe your approach to security controls.",
                "context": {"force_mock": True},
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("force_mock is no longer supported", response.json()["detail"])

    def test_retrieval_error_returns_deterministic_dependency_message(self):
        fake_llm = FakeLLM()
        agent_module.agent.knowledge = FakeRetriever(fail=True)
        agent_module.agent.llm = fake_llm
        response = self.client.post(
            "/invoke",
            json={"query": "Describe your approach to security controls."},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["tool_calls"][0]["status"], "error")
        self.assertEqual(fake_llm.calls, [])
        self.assertIn("unable to retrieve", payload["response"].lower())

    def test_llm_error_surfaces_as_invoke_failure(self):
        agent_module.agent.knowledge = FakeRetriever()
        agent_module.agent.llm = FakeLLM(fail=True)
        response = self.client.post(
            "/invoke",
            json={"query": "Describe your approach to security controls."},
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("LLMGatewayError", response.json()["detail"])

    def test_missing_live_llm_key_surfaces_as_invoke_failure(self):
        agent_module.agent.knowledge = FakeRetriever()
        agent_module.agent.llm = LLMClient(default_model=AgentSettings().default_model)
        response = self.client.post(
            "/invoke",
            json={"query": "Describe your approach to security controls."},
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("Live LLM mode requires", response.json()["detail"])

    def test_prompts_sync_without_credentials_is_safe(self):
        response = self.client.post("/prompts/sync")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["prompt_name"], "tcs-rfp-response-drafter-system")
        self.assertIn(payload["status"], {"skipped", "unchanged", "created", "updated"})
        self.assertIn("default", payload["variants"])


if __name__ == "__main__":
    unittest.main()
