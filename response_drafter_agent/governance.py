"""Deterministic constitution and governance gates."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .knowledge import Evidence


PROHIBITED_PATTERNS = {
    "pricing_or_discount": re.compile(r"\b(price|pricing|discount|rate card|commercial quote|cost guarantee)\b", re.I),
    "legal_or_contractual_commitment": re.compile(r"\b(warranty|indemnity|contract term|legally commit|binding commitment|guarantee|guaranteed|penalty)\b", re.I),
    "final_approval_or_submission": re.compile(r"\b(approve|sign off|submit final|final submission|authorize)\b", re.I),
    "unsupported_capability": re.compile(r"\b(invent|assume capability|make up|unsupported claim)\b", re.I),
}

PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
]

GREETING_PATTERN = re.compile(
    r"^\s*(hi|hello|hey|good morning|good afternoon|good evening|thanks|thank you)\s*[.!?]*\s*$",
    re.I,
)

PROPOSAL_SCOPE_PATTERN = re.compile(
    r"\b("
    r"tcs|rfp|rfi|proposal|tender|bid|response|draft|capability|capabilities|"
    r"security|cyber|cybersecurity|compliance|iso|soc|data protection|policy|controls|"
    r"methodology|delivery|transition|business continuity|disaster recovery|bcp|resilience|"
    r"staffing|resourcing|team|skills|architecture|cloud|technology|solution|managed service"
    r")\b",
    re.I,
)


class Constitution:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.rules = self._load_rules()

    def evaluate_request(self, query: str, context: dict[str, Any] | None) -> dict[str, Any]:
        violations: list[dict[str, Any]] = []
        for rule_name, pattern in PROHIBITED_PATTERNS.items():
            if pattern.search(query):
                violations.append(
                    {
                        "rule": rule_name,
                        "severity": "critical",
                        "message": "The request asks for authority outside the agent charter.",
                    }
                )

        if any(pattern.search(query) for pattern in PII_PATTERNS):
            violations.append(
                {
                    "rule": "pii_minimization",
                    "severity": "elevated",
                    "message": "Potential sensitive identifiers detected; redact before drafting.",
                }
            )

        if _contains_prompt_injection(query):
            violations.append(
                {
                    "rule": "prompt_injection_defense",
                    "severity": "elevated",
                    "message": "Embedded instructions attempting to override the agent policy were detected.",
                }
            )

        if any(v["severity"] == "critical" for v in violations):
            authority = "prohibited"
        elif violations:
            authority = "human_review_required"
        else:
            authority = "within_agent_authority"

        return {
            "authority_status": authority,
            "violations": violations,
            "proposal_review_required": True,
        }

    def evaluate_grounding(self, evidence: list[Evidence]) -> dict[str, Any]:
        if not evidence:
            return {
                "grounding_status": "insufficient_evidence",
                "limitations": ["No approved supporting knowledge was retrieved."],
            }
        if len(evidence) == 1 or max(item.score for item in evidence) < 0.25:
            return {
                "grounding_status": "limited_evidence",
                "limitations": ["Supporting knowledge is limited; SME validation is required."],
            }
        return {"grounding_status": "grounded", "limitations": []}

    def reflect(self, draft_answer: str, evidence: list[Evidence], authority: dict[str, Any]) -> dict[str, Any]:
        findings: list[str] = []
        lower = draft_answer.lower()
        if authority["authority_status"] == "prohibited":
            findings.append("Draft avoids prohibited final approval or commercial commitment.")
        if not evidence and not any(phrase in lower for phrase in ("unavailable", "unable", "could not retrieve")):
            findings.append("Draft should explicitly state that approved supporting knowledge is unavailable.")
        if re.search(r"\bguarantee[sd]?|binding\b", lower):
            findings.append("Draft contains commitment language and must be revised before use.")
        return {
            "reflection": findings or ["Draft passed deterministic grounding and authority checks."],
            "requires_revision": any("must be revised" in item for item in findings),
        }

    def _load_rules(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            import yaml

            parsed = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


def infer_intent(query: str) -> str:
    lowered = query.lower()
    if any(token in lowered for token in ("security", "compliance", "iso", "soc", "data protection")):
        return "security_and_compliance"
    if any(token in lowered for token in ("methodology", "delivery", "governance", "transition")):
        return "delivery_methodology"
    if any(token in lowered for token in ("business continuity", "disaster recovery", "bcp", "resilience")):
        return "business_continuity"
    if any(token in lowered for token in ("staffing", "resourcing", "team", "skill")):
        return "staffing_and_resourcing"
    if any(token in lowered for token in ("architecture", "cloud", "technology", "solution")):
        return "solution_architecture"
    return "general_capability"


def classify_request_scope(query: str, intent: str) -> dict[str, Any]:
    stripped = query.strip()
    if GREETING_PATTERN.match(stripped):
        return {
            "scope_status": "small_talk",
            "skip_retrieval": True,
            "skip_generation": True,
            "review_required": False,
            "deterministic_answer": (
                "Hello. I can help draft RFP and proposal responses using approved TCS "
                "knowledge. Please share the RFP question you want drafted."
            ),
            "limitations": [],
        }

    if intent != "general_capability" or PROPOSAL_SCOPE_PATTERN.search(stripped):
        return {
            "scope_status": "in_scope",
            "skip_retrieval": False,
            "skip_generation": False,
            "review_required": True,
            "deterministic_answer": None,
            "limitations": [],
        }

    return {
        "scope_status": "outside_agent_scope",
        "skip_retrieval": True,
        "skip_generation": True,
        "review_required": False,
        "deterministic_answer": (
            "I can only help with RFP and proposal-response drafting grounded in approved "
            "TCS knowledge. This request is outside that scope, so I cannot answer it here. "
            "Please provide an RFP question or route the item to the appropriate source."
        ),
        "limitations": ["Request is outside the response drafter scope; retrieval was not performed."],
    }


def redact_sensitive_text(text: str) -> str:
    redacted = text
    for pattern in PII_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _contains_prompt_injection(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "ignore previous instructions",
            "ignore the system prompt",
            "override your policy",
            "developer message",
            "reveal your prompt",
        )
    )
