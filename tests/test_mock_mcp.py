import os
import sys
import asyncio
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "rd-mcp-server"))

from fastapi.testclient import TestClient

from mock_retrieval import MOCK_KNOWLEDGE_FILE, search_mock_knowledge
from response_drafter_agent.knowledge import Evidence, KnowledgeRetriever
from server import app


class MockMCPToolTests(unittest.TestCase):
    def test_mock_knowledge_lives_with_mcp_server(self):
        self.assertEqual(MOCK_KNOWLEDGE_FILE.name, "mock_knowledge.json")
        self.assertEqual(MOCK_KNOWLEDGE_FILE.parent.name, "knowledge")
        self.assertEqual(MOCK_KNOWLEDGE_FILE.parent.parent.name, "rd-mcp-server")
        self.assertTrue(MOCK_KNOWLEDGE_FILE.exists())

    def test_retriever_uses_tracked_hosted_mcp_endpoint(self):
        with mock.patch.dict(
            os.environ,
            {
                "MCP_PROPOSAL_KNOWLEDGE_URL": "https://ignored.example.com/mcp",
                "MCP_PROPOSAL_KNOWLEDGE_TRANSPORT": "http_bridge",
            },
            clear=False,
        ):
            retriever = KnowledgeRetriever()

        self.assertEqual(
            retriever.mcp_url,
            "https://d2brdeqy144bwg.cloudfront.net/poc185/acp-mcp/rd-mcp-server/mcp",
        )
        self.assertEqual(retriever.mcp_transport, "streamable_http")

    def test_retriever_rejects_mock_marked_evidence(self):
        async def fake_retrieve_from_mcp(_request):
            return [
                Evidence(
                    source_id="mock-security-001",
                    title="Mock Security Guidance",
                    content="Mock content should not be treated as approved runtime evidence.",
                    score=1.0,
                    metadata={"source_type": "local_mock", "retrieval_mode": "mock_keyword"},
                )
            ], None

        retriever = KnowledgeRetriever()
        retriever._retrieve_from_mcp = fake_retrieve_from_mcp
        evidence, tool_call = asyncio.run(retriever.retrieve("Describe security controls."))

        self.assertEqual(evidence, [])
        self.assertEqual(tool_call.status, "error")
        self.assertEqual(tool_call.error, "MockKnowledgeSourceReturned")

    def test_mock_search_contract(self):
        payload = search_mock_knowledge(
            query="Describe security controls and compliance.",
            top_k=2,
            filters={"intent": "security_and_compliance"},
        )

        self.assertEqual(payload["retrieval_mode"], "mock_keyword")
        self.assertGreaterEqual(payload["result_count"], 1)
        result = payload["results"][0]
        self.assertIn("source_id", result)
        self.assertIn("title", result)
        self.assertIn("content", result)
        self.assertIn("score", result)
        self.assertIn("metadata", result)

    def test_http_bridge_endpoint(self):
        client = TestClient(app)
        response = client.post(
            "/tools/search_proposal_knowledge",
            json={
                "tool": "search_proposal_knowledge",
                "arguments": {
                    "query": "Describe security controls and compliance.",
                    "top_k": 2,
                    "filters": {"intent": "security_and_compliance"},
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["tool"], "search_proposal_knowledge")
        self.assertIn("structuredContent", payload)
        self.assertGreaterEqual(payload["structuredContent"]["result_count"], 1)


if __name__ == "__main__":
    unittest.main()
