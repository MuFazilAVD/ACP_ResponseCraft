"""Mock proposal knowledge retrieval used by local fallback and MCP server."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


SERVER_DIR = Path(__file__).resolve().parent
MOCK_KNOWLEDGE_FILE = Path(
    os.getenv("RD_MCP_KNOWLEDGE_FILE", SERVER_DIR / "knowledge" / "mock_knowledge.json")
)
STOP_WORDS = {"the", "and", "for", "with", "that", "this", "your", "you"}

INTENT_TERMS = {
    "security_and_compliance": {"security", "compliance", "controls", "audit", "data", "protection"},
    "delivery_methodology": {"delivery", "methodology", "governance", "transition", "quality"},
    "business_continuity": {"business", "continuity", "resilience", "disaster", "recovery", "bcp"},
    "staffing_and_resourcing": {"staffing", "resourcing", "skills", "onboarding", "knowledge", "transfer"},
    "solution_architecture": {"architecture", "cloud", "technology", "solution", "integration"},
}


def load_mock_documents(path: Path = MOCK_KNOWLEDGE_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    docs = parsed.get("documents", []) if isinstance(parsed, dict) else parsed
    return [doc for doc in docs if isinstance(doc, dict)]


def search_mock_knowledge(
    *,
    query: str,
    top_k: int = 5,
    filters: dict[str, Any] | None = None,
    metadata_filters: dict[str, Any] | None = None,
    min_score: float = 0.0,
    include_content: bool = True,
    documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keyword mock retrieval with a stable shape for the future hybrid tool."""

    top_k = max(1, min(int(top_k or 5), 10))
    filters = filters or {}
    metadata_filters = metadata_filters or {}
    intent = str(filters.get("intent") or "").strip()
    query_terms = _tokens(query)
    expanded_terms = set(query_terms)
    expanded_terms.update(INTENT_TERMS.get(intent, set()))

    rows = []
    for doc in documents if documents is not None else load_mock_documents():
        if not _matches_filters(doc, filters, metadata_filters):
            continue
        haystack = " ".join(
            [
                str(doc.get("title", "")),
                str(doc.get("content", "")),
                " ".join(str(topic) for topic in doc.get("topics", [])),
            ]
        )
        doc_terms = _tokens(haystack)
        overlap = len(expanded_terms.intersection(doc_terms))
        if overlap == 0:
            continue
        score = overlap / max(1, len(expanded_terms))
        if score < min_score:
            continue

        source_id = str(doc.get("source_id") or doc.get("id") or "mock-source")
        row = {
            "source_id": source_id,
            "title": str(doc.get("title") or source_id),
            "score": round(score, 4),
            "source_type": str(doc.get("source_type") or "mock_mcp"),
            "metadata": {
                "topics": doc.get("topics", []),
                "intent_hint": intent or None,
                "retrieval_mode": "mock_keyword",
            },
        }
        if include_content:
            row["content"] = str(doc.get("content") or "")
        else:
            row["snippet"] = str(doc.get("content") or "")[:240]
        rows.append(row)

    rows.sort(key=lambda item: item["score"], reverse=True)
    results = rows[:top_k]
    return {
        "query": query,
        "top_k": top_k,
        "filters": filters,
        "metadata_filters": metadata_filters,
        "retrieval_mode": "mock_keyword",
        "result_count": len(results),
        "results": results,
    }


def _matches_filters(
    doc: dict[str, Any],
    filters: dict[str, Any],
    metadata_filters: dict[str, Any],
) -> bool:
    source_ids = _string_set(filters.get("source_ids"))
    if source_ids and str(doc.get("source_id") or doc.get("id")) not in source_ids:
        return False

    source_type = str(filters.get("source_type") or "").strip()
    if source_type and str(doc.get("source_type") or "") != source_type:
        return False

    required_topics = _string_set(filters.get("topics"))
    doc_topics = _string_set(doc.get("topics"))
    if required_topics and not required_topics.intersection(doc_topics):
        return False

    for key, value in metadata_filters.items():
        candidate = doc.get(key)
        if candidate is None and isinstance(doc.get("metadata"), dict):
            candidate = doc["metadata"].get(key)
        if candidate != value:
            return False

    return True


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in STOP_WORDS
    }


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, list | tuple | set):
        return {str(item) for item in value}
    return {str(value)}
