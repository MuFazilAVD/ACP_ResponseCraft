"""Mock proposal knowledge MCP server.

Run the MCP server directly:
    python rd-mcp-server/server.py

Or run the ASGI wrapper with the compatibility HTTP bridge:
    uvicorn server:app --app-dir rd-mcp-server --host 0.0.0.0 --port 8121
"""

from __future__ import annotations

import contextlib
import os
from typing import Any, Annotated

from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mock_retrieval import search_mock_knowledge

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - server still exposes compatibility bridge.
    FastMCP = None


SERVER_NAME = "proposal-knowledge-mcp"
TOOL_NAME = "search_proposal_knowledge"


def create_mcp_server():
    if FastMCP is None:
        raise RuntimeError("Install the MCP SDK with `pip install \"mcp>=1.28,<2\"`.")

    mcp = FastMCP(
        SERVER_NAME,
        stateless_http=True,
        json_response=True,
        host=os.getenv("MCP_MOCK_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_MOCK_PORT", "8121")),
    )

    @mcp.tool()
    def search_proposal_knowledge(
        query: Annotated[str, Field(min_length=1, max_length=4000)],
        top_k: Annotated[int, Field(ge=1, le=10)] = 5,
        filters: dict[str, Any] | None = None,
        metadata_filters: dict[str, Any] | None = None,
        min_score: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0,
        include_content: bool = True,
    ) -> dict[str, Any]:
        """Search approved proposal knowledge and return ranked evidence snippets."""

        return search_mock_knowledge(
            query=query,
            top_k=top_k,
            filters=filters,
            metadata_filters=metadata_filters,
            min_score=min_score,
            include_content=include_content,
        )

    return mcp


_mcp = create_mcp_server() if FastMCP is not None else None


async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "healthy",
            "server_name": SERVER_NAME,
            "tool": TOOL_NAME,
            "mcp_enabled": _mcp is not None,
        }
    )


async def tool_contract(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "tool": TOOL_NAME,
            "input": {
                "query": "string, required, natural-language RFP question or search phrase",
                "top_k": "integer, optional, 1..10, default 5",
                "filters": {
                    "intent": "optional retrieval hint such as security_and_compliance",
                    "topics": "optional list of topic hints",
                    "source_type": "optional source type filter",
                    "source_ids": "optional list of source ids",
                },
                "metadata_filters": "optional exact-match metadata constraints",
                "min_score": "optional float 0..1",
                "include_content": "optional boolean, default true",
            },
            "output": {
                "results": [
                    {
                        "source_id": "string",
                        "title": "string",
                        "content": "string when include_content=true",
                        "score": "float",
                        "source_type": "string",
                        "metadata": "object",
                    }
                ]
            },
        }
    )


async def bridge_search(request: Request) -> JSONResponse:
    body = await request.json()
    arguments = body.get("input") if isinstance(body, dict) else {}
    if not isinstance(arguments, dict):
        arguments = body.get("arguments") if isinstance(body, dict) else {}
    if not isinstance(arguments, dict):
        arguments = body if isinstance(body, dict) else {}
    result = search_mock_knowledge(
        query=str(arguments.get("query") or ""),
        top_k=int(arguments.get("top_k") or 5),
        filters=arguments.get("filters") if isinstance(arguments.get("filters"), dict) else {},
        metadata_filters=(
            arguments.get("metadata_filters")
            if isinstance(arguments.get("metadata_filters"), dict)
            else {}
        ),
        min_score=float(arguments.get("min_score") or 0.0),
        include_content=bool(arguments.get("include_content", True)),
    )
    return JSONResponse(
        {
            "tool": TOOL_NAME,
            "structuredContent": result,
            "results": result["results"],
        }
    )


@contextlib.asynccontextmanager
async def lifespan(_: Starlette):
    if _mcp is None:
        yield
        return
    async with _mcp.session_manager.run():
        yield


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/contract", tool_contract, methods=["GET"]),
    Route("/tools/search_proposal_knowledge", bridge_search, methods=["POST"]),
]
if _mcp is not None:
    routes.append(Mount("/", app=_mcp.streamable_http_app()))

app = Starlette(routes=routes, lifespan=lifespan)


def main() -> None:
    if _mcp is None:
        raise RuntimeError("Install the MCP SDK with `pip install \"mcp>=1.28,<2\"`.")
    _mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
