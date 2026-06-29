"""Governed knowledge retrieval through MCP."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .schemas import ToolCall
from .settings import (
    DEFAULT_MCP_PROPOSAL_KNOWLEDGE_TOOL,
    DEFAULT_MCP_PROPOSAL_KNOWLEDGE_TRANSPORT,
    DEFAULT_MCP_PROPOSAL_KNOWLEDGE_URL,
)


@dataclass(frozen=True)
class Evidence:
    source_id: str
    title: str
    content: str
    score: float
    metadata: dict[str, Any]


class KnowledgeRetriever:
    def __init__(self) -> None:
        self.mcp_url = DEFAULT_MCP_PROPOSAL_KNOWLEDGE_URL
        self.mcp_tool = DEFAULT_MCP_PROPOSAL_KNOWLEDGE_TOOL
        self.mcp_transport = DEFAULT_MCP_PROPOSAL_KNOWLEDGE_TRANSPORT
        self.mcp_api_key = os.getenv("MCP_API_KEY") or os.getenv("ACP_AGENT_API_KEY") or ""

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[Evidence], ToolCall]:
        started = time.perf_counter()
        request = {"query": query, "top_k": top_k, "filters": filters or {}}

        if not self.mcp_url:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return [], ToolCall(
                tool_name=self.mcp_tool,
                source="mcp",
                target="",
                status="error",
                latency_ms=latency_ms,
                request=request,
                summary={"result_count": 0},
                error="MCPEndpointMissing",
            )

        evidence, error = await self._retrieve_from_mcp(request)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if error is None and _contains_mock_evidence(evidence):
            return [], ToolCall(
                tool_name=self.mcp_tool,
                source="mcp",
                target=self.mcp_url,
                status="error",
                latency_ms=latency_ms,
                request=request,
                summary={
                    "result_count": len(evidence),
                    "sources": [item.source_id for item in evidence],
                    "rejected_reason": "mock_knowledge_source",
                },
                error="MockKnowledgeSourceReturned",
            )
        if error is None:
            return evidence, ToolCall(
                tool_name=self.mcp_tool,
                source="mcp",
                target=self.mcp_url,
                status="success",
                latency_ms=latency_ms,
                request=request,
                summary={
                    "result_count": len(evidence),
                    "sources": [item.source_id for item in evidence],
                },
            )
        return [], ToolCall(
            tool_name=self.mcp_tool,
            source="mcp",
            target=self.mcp_url,
            status="error",
            latency_ms=latency_ms,
            request=request,
            summary={"result_count": 0},
            error=error,
        )

    async def _retrieve_from_mcp(self, request: dict[str, Any]) -> tuple[list[Evidence], str | None]:
        if self._use_streamable_mcp():
            return await self._retrieve_from_streamable_mcp(request)
        return await self._retrieve_from_http_bridge(request)

    async def _retrieve_from_http_bridge(self, request: dict[str, Any]) -> tuple[list[Evidence], str | None]:
        headers = {"Content-Type": "application/json", "X-Agent-Key": "tcs-rfp-response-drafter"}
        if self.mcp_api_key:
            headers["Authorization"] = f"Bearer {self.mcp_api_key}"

        payload = {
            "tool": self.mcp_tool,
            "arguments": request,
            "metadata": {"agent_key": "tcs-rfp-response-drafter"},
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.mcp_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            return self._normalise_mcp_results(data), None
        except Exception as exc:
            return [], exc.__class__.__name__

    async def _retrieve_from_streamable_mcp(self, request: dict[str, Any]) -> tuple[list[Evidence], str | None]:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except Exception as exc:
            return [], f"MCPClientUnavailable:{exc.__class__.__name__}"

        headers = {"X-Agent-Key": "tcs-rfp-response-drafter"}
        if self.mcp_api_key:
            headers["Authorization"] = f"Bearer {self.mcp_api_key}"

        try:
            async with httpx.AsyncClient(timeout=30.0, headers=headers) as http_client:
                async with streamable_http_client(self.mcp_url, http_client=http_client) as (
                    read_stream,
                    write_stream,
                    _,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.call_tool(self.mcp_tool, arguments=request)
            data = getattr(result, "structuredContent", None)
            if data is None:
                data = {"content": [item.model_dump() for item in getattr(result, "content", [])]}
            return self._normalise_mcp_results(data), None
        except Exception as exc:
            return [], exc.__class__.__name__

    def _use_streamable_mcp(self) -> bool:
        if self.mcp_transport in {"streamable_http", "streamable-http", "mcp"}:
            return True
        if self.mcp_transport in {"http_bridge", "http-bridge", "bridge", "rest"}:
            return False
        return self.mcp_url.rstrip("/").endswith("/mcp")

    def _normalise_mcp_results(self, data: Any) -> list[Evidence]:
        if isinstance(data, dict) and "content" in data:
            data = _extract_mcp_content(data)

        if isinstance(data, dict):
            rows = (
                data.get("results")
                or data.get("documents")
                or data.get("items")
                or data.get("matches")
                or []
            )
        elif isinstance(data, list):
            rows = data
        else:
            rows = []

        evidence: list[Evidence] = []
        for index, row in enumerate(rows[:10]):
            if not isinstance(row, dict):
                continue
            content = str(row.get("content") or row.get("text") or row.get("snippet") or "").strip()
            if not content:
                continue
            source_id = str(row.get("source_id") or row.get("id") or f"mcp-{index + 1}")
            evidence.append(
                Evidence(
                    source_id=source_id,
                    title=str(row.get("title") or source_id),
                    content=content,
                    score=float(row.get("score") or row.get("relevance") or 1.0),
                    metadata={
                        key: value
                        for key, value in row.items()
                        if key not in {"content", "text", "snippet"}
                    },
                )
            )
        return evidence


def _contains_mock_evidence(evidence: list[Evidence]) -> bool:
    for item in evidence:
        metadata = item.metadata or {}
        nested = metadata.get("metadata") if isinstance(metadata.get("metadata"), dict) else {}
        values = (
            str(metadata.get("source_type") or ""),
            str(metadata.get("retrieval_mode") or ""),
            str(nested.get("source_type") or ""),
            str(nested.get("retrieval_mode") or ""),
        )
        if any("mock" in value.lower() for value in values):
            return True
    return False


def _extract_mcp_content(data: dict[str, Any]) -> Any:
    content = data.get("structuredContent")
    if content:
        return content
    entries = data.get("content") or []
    if isinstance(entries, list):
        texts = []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("type") == "text":
                texts.append(str(entry.get("text") or ""))
        joined = "\n".join(texts).strip()
        if joined:
            try:
                return json.loads(joined)
            except json.JSONDecodeError:
                return {"results": [{"source_id": "mcp-text", "content": joined}]}
    return data
