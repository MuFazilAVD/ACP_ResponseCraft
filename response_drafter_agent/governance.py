"""Deterministic constitution and governance gates."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .knowledge import Evidence
from .logging_utils import get_logger

logger = get_logger(__name__)


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
        logger.debug(
            "[Constitution.__init__] Loaded | path=%s | rule_count=%d",
            self.path,
            len(self.rules),
        )

    def evaluate_request(self, query: str, context: dict[str, Any] | None) -> dict[str, Any]:
        logger.debug(
            "[evaluate_request] Evaluating query against authority rules | query_len=%d",
            len(query),
        )
        violations: list[dict[str, Any]] = []
        for rule_name, pattern in PROHIBITED_PATTERNS.items():
            if pattern.search(query):
                logger.debug(
                    "[evaluate_request] Prohibited pattern matched | rule=%s", rule_name
                )
                violations.append(
                    {
                        "rule": rule_name,
                        "severity": "critical",
                        "message": "The request asks for authority outside the agent charter.",
                    }
                )

        if any(pattern.search(query) for pattern in PII_PATTERNS):
            logger.debug("[evaluate_request] PII pattern matched — adding pii_minimization violation")
            violations.append(
                {
                    "rule": "pii_minimization",
                    "severity": "elevated",
                    "message": "Potential sensitive identifiers detected; redact before drafting.",
                }
            )

        if _contains_prompt_injection(query):
            logger.warning("[evaluate_request] Prompt injection attempt detected in query")
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

        if violations:
            logger.warning(
                "[evaluate_request] Violations found | authority_status=%s | count=%d | rules=%s",
                authority,
                len(violations),
                [v["rule"] for v in violations],
            )
        else:
            logger.info(
                "[evaluate_request] No violations | authority_status=%s", authority
            )

        return {
            "authority_status": authority,
            "violations": violations,
            "proposal_review_required": True,
        }

    def evaluate_grounding(self, evidence: list[Evidence]) -> dict[str, Any]:
        logger.debug(
            "[evaluate_grounding] Evaluating grounding | evidence_count=%d", len(evidence)
        )
        if not evidence:
            logger.warning(
                "[evaluate_grounding] No evidence retrieved — grounding_status=insufficient_evidence"
            )
            return {
                "grounding_status": "insufficient_evidence",
                "limitations": ["No approved supporting knowledge was retrieved."],
            }
        max_score = max(item.score for item in evidence)
        if len(evidence) == 1 or max_score < 0.25:
            logger.warning(
                "[evaluate_grounding] Limited evidence | evidence_count=%d | max_score=%.3f | "
                "grounding_status=limited_evidence",
                len(evidence),
                max_score,
            )
            return {
                "grounding_status": "limited_evidence",
                "limitations": ["Supporting knowledge is limited; SME validation is required."],
            }
        logger.info(
            "[evaluate_grounding] Well-grounded | evidence_count=%d | max_score=%.3f | "
            "grounding_status=grounded",
            len(evidence),
            max_score,
        )
        return {"grounding_status": "grounded", "limitations": []}

    def reflect(self, draft_answer: str, evidence: list[Evidence], authority: dict[str, Any]) -> dict[str, Any]:
        logger.debug(
            "[reflect] Running reflection | authority_status=%s | draft_len=%d | evidence_count=%d",
            authority.get("authority_status"),
            len(draft_answer),
            len(evidence),
        )
        findings: list[str] = []
        lower = draft_answer.lower()
        if authority["authority_status"] == "prohibited":
            findings.append("Draft avoids prohibited final approval or commercial commitment.")
            logger.debug("[reflect] Prohibited authority noted in findings")
        if not evidence and not any(phrase in lower for phrase in ("unavailable", "unable", "could not retrieve")):
            findings.append("Draft should explicitly state that approved supporting knowledge is unavailable.")
            logger.warning(
                "[reflect] Draft does not acknowledge missing evidence — flagging for revision"
            )
        if re.search(r"\bguarantee[sd]?|binding\b", lower):
            findings.append("Draft contains commitment language and must be revised before use.")
            logger.warning("[reflect] Commitment language detected in draft — requires_revision=True")
        requires_revision = any("must be revised" in item for item in findings)
        logger.info(
            "[reflect] Reflection result | requires_revision=%s | findings_count=%d",
            requires_revision,
            len(findings),
        )
        return {
            "reflection": findings or ["Draft passed deterministic grounding and authority checks."],
            "requires_revision": requires_revision,
        }

    def _load_rules(self) -> dict[str, Any]:
        if not self.path.exists():
            logger.warning(
                "[_load_rules] Constitution file not found — using empty rules | path=%s",
                self.path,
            )
            return {}
        try:
            import yaml

            parsed = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            rules = parsed if isinstance(parsed, dict) else {}
            logger.debug(
                "[_load_rules] Constitution rules loaded | path=%s | rule_count=%d",
                self.path,
                len(rules),
            )
            return rules
        except Exception as exc:
            logger.error(
                "[_load_rules] Failed to parse constitution file | path=%s | error=%s",
                self.path,
                exc.__class__.__name__,
            )
            return {}


def infer_intent(query: str) -> str:
    lowered = query.lower()
    if any(token in lowered for token in ("security", "compliance", "iso", "soc", "data protection")):
        intent = "security_and_compliance"
    elif any(token in lowered for token in ("methodology", "delivery", "governance", "transition")):
        intent = "delivery_methodology"
    elif any(token in lowered for token in ("business continuity", "disaster recovery", "bcp", "resilience")):
        intent = "business_continuity"
    elif any(token in lowered for token in ("staffing", "resourcing", "team", "skill")):
        intent = "staffing_and_resourcing"
    elif any(token in lowered for token in ("architecture", "cloud", "technology", "solution")):
        intent = "solution_architecture"
    else:
        intent = "general_capability"
    logger.debug("[infer_intent] Intent inferred | intent=%s | query_len=%d", intent, len(query))
    return intent


def classify_request_scope(query: str, intent: str) -> dict[str, Any]:
    logger.debug(
        "[classify_request_scope] Classifying scope | intent=%s | query_len=%d",
        intent,
        len(query),
    )
    stripped = query.strip()
    if GREETING_PATTERN.match(stripped):
        logger.info("[classify_request_scope] Scope classified as small_talk")
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
        logger.info("[classify_request_scope] Scope classified as in_scope | intent=%s", intent)
        return {
            "scope_status": "in_scope",
            "skip_retrieval": False,
            "skip_generation": False,
            "review_required": True,
            "deterministic_answer": None,
            "limitations": [],
        }

    logger.warning(
        "[classify_request_scope] Request classified as outside_agent_scope | intent=%s", intent
    )
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
    redaction_count = 0
    for pattern in PII_PATTERNS:
        new_text = pattern.sub("[REDACTED]", redacted)
        if new_text != redacted:
            redaction_count += 1
        redacted = new_text
    if redaction_count:
        logger.info(
            "[redact_sensitive_text] PII redacted | pattern_matches=%d | original_len=%d | redacted_len=%d",
            redaction_count,
            len(text),
            len(redacted),
        )
    else:
        logger.debug("[redact_sensitive_text] No PII detected | text_len=%d", len(text))
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
