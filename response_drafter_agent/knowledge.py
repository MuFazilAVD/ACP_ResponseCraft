"""Governed knowledge retrieval through MCP."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .logging_utils import get_logger
from .schemas import ToolCall
from .settings import (
    DEFAULT_MCP_PROPOSAL_KNOWLEDGE_TOOL,
    DEFAULT_MCP_PROPOSAL_KNOWLEDGE_TRANSPORT,
    DEFAULT_MCP_PROPOSAL_KNOWLEDGE_URL,
)

logger = get_logger(__name__)


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
        logger.debug(
            "[KnowledgeRetriever.__init__] Initialised | transport=%s | tool=%s | url=%s | api_key_set=%s",
            self.mcp_transport,
            self.mcp_tool,
            self.mcp_url,
            bool(self.mcp_api_key),
        )

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[Evidence], ToolCall]:
        started = time.perf_counter()
        request = {"query": query, "top_k": top_k, "filters": filters or {}}

        logger.info(
            "[retrieve] Starting retrieval | tool=%s | transport=%s | top_k=%d | query_len=%d",
            self.mcp_tool,
            self.mcp_transport,
            top_k,
            len(query),
        )

        if not self.mcp_url:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.error(
                "[retrieve] MCP endpoint URL is not configured | tool=%s | latency_ms=%d",
                self.mcp_tool,
                latency_ms,
            )
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
        tool_error = _tool_error_from_evidence(evidence)
        if error is None and tool_error:
            logger.error(
                "[retrieve] Tool execution error in evidence | tool=%s | latency_ms=%d | error=%s",
                self.mcp_tool,
                latency_ms,
                tool_error[:200],
            )
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
                },
                error=tool_error,
            )
        if error is None and _contains_mock_evidence(evidence):
            logger.warning(
                "[retrieve] Mock knowledge source detected and rejected | tool=%s | latency_ms=%d | "
                "evidence_count=%d",
                self.mcp_tool,
                latency_ms,
                len(evidence),
            )
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
            logger.info(
                "[retrieve] Retrieval successful | tool=%s | evidence_count=%d | latency_ms=%d | "
                "sources=%s",
                self.mcp_tool,
                len(evidence),
                latency_ms,
                [item.source_id for item in evidence],
            )
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
        logger.error(
            "[retrieve] MCP retrieval FAILED | tool=%s | error=%s | latency_ms=%d",
            self.mcp_tool,
            error,
            latency_ms,
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
        use_streamable = self._use_streamable_mcp()
        logger.debug(
            "[_retrieve_from_mcp] Routing MCP call | transport=%s | use_streamable=%s",
            self.mcp_transport,
            use_streamable,
        )
        if use_streamable:
            return await self._retrieve_from_streamable_mcp(request)
        return await self._retrieve_from_http_bridge(request)

    async def _retrieve_from_http_bridge(self, request: dict[str, Any]) -> tuple[list[Evidence], str | None]:
        headers = {"Content-Type": "application/json", "X-Agent-Key": "tcs-rfp-response-drafter"}
        if self.mcp_api_key:
            headers["Authorization"] = f"Bearer {self.mcp_api_key}"

        payload = {"input": {"query": request["query"]}}
        logger.debug(
            "[_retrieve_from_http_bridge] Sending HTTP POST | url=%s | query_len=%d",
            self.mcp_url,
            len(request["query"]),
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.mcp_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            logger.debug(
                "[_retrieve_from_http_bridge] HTTP response received | status_code=%s",
                response.status_code,
            )
            return self._normalise_mcp_results(data), None
        except Exception as exc:
            logger.error(
                "[_retrieve_from_http_bridge] HTTP request FAILED | url=%s | error=%s | detail=%s",
                self.mcp_url,
                exc.__class__.__name__,
                str(exc)[:300],
            )
            return [], exc.__class__.__name__

    async def _retrieve_from_streamable_mcp(self, request: dict[str, Any]) -> tuple[list[Evidence], str | None]:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except Exception as exc:
            logger.error(
                "[_retrieve_from_streamable_mcp] MCP client library unavailable | error=%s",
                exc.__class__.__name__,
            )
            return [], f"MCPClientUnavailable:{exc.__class__.__name__}"

        headers = {"X-Agent-Key": "tcs-rfp-response-drafter"}
        if self.mcp_api_key:
            headers["Authorization"] = f"Bearer {self.mcp_api_key}"

        logger.debug(
            "[_retrieve_from_streamable_mcp] Starting streamable MCP session | url=%s | tool=%s",
            self.mcp_url,
            self.mcp_tool,
        )
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
            logger.debug(
                "[_retrieve_from_streamable_mcp] Streamable MCP call succeeded | tool=%s",
                self.mcp_tool,
            )
            return self._normalise_mcp_results(data), None
        except Exception as exc:
            logger.error(
                "[_retrieve_from_streamable_mcp] Streamable MCP call FAILED | url=%s | error=%s | detail=%s",
                self.mcp_url,
                exc.__class__.__name__,
                str(exc)[:300],
            )
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
            if isinstance(rows, str):
                rows = [
                    {
                        "source_id": "mcp-text",
                        "title": str(data.get("tool") or "mcp-text"),
                        "content": rows,
                        "score": 1.0,
                        "metadata": {
                            key: value
                            for key, value in data.items()
                            if key != "results"
                        },
                    }
                ]
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
        logger.debug(
            "[_normalise_mcp_results] Normalisation complete | rows_in=%d | evidence_out=%d",
            len(rows) if isinstance(rows, list) else 0,
            len(evidence),
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


def _tool_error_from_evidence(evidence: list[Evidence]) -> str | None:
    for item in evidence:
        content = item.content.strip()
        if content.startswith("Error executing tool"):
            return content[:500]
    return None


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
