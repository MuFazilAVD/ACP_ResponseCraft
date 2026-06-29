# Requested Entitlements

Entitlements are declared at birth in `/config` and reconciled by ACP against ontology placement. These are requests, not live access. Runtime access is governed by the compiled grant and the MCP gateway.

## Scope

- `entitlement_scope`: `node`
- `eval_playbook_slug`: `proposal_management.rfp.response_drafting`

## Requested Entitlements

```json
[
  "mcp_server:proposal-knowledge-mcp",
  "capability:rfp_knowledge.search",
  "capability:proposal_content.read",
  "capability:approved_capability_library.read",
  "capability:security_compliance_library.read",
  "enterprise_api:llm_gateway.chat_completions",
  "telemetry:langfuse.prompt_sync",
  "telemetry:langfuse.traces_write",
  "telemetry:otlp.traces_write"
]
```

## Enforcement Expectations

- Development can run with `ENTITLEMENT_ENFORCEMENT=off` and local mock knowledge.
- Evaluation and pre-production should run with `ENTITLEMENT_ENFORCEMENT=audit` first to detect missing grants.
- Production should run with `ENTITLEMENT_ENFORCEMENT=enforce`.
- The agent records every MCP or enterprise API access in `tool_calls[]`.
- Direct tool calls outside the ACP MCP gateway are not allowed for governed data access.

## ACP Follow-Up

After registration:

1. Inspect `GET /api/entitlements/reconciliation/tcs-rfp-response-drafter`.
2. Resolve any over-request through an explicit approval.
3. Compile grants with `POST /api/entitlements/compile/tcs-rfp-response-drafter`.
4. Smoke test retrieval under `ENTITLEMENT_ENFORCEMENT=enforce`.
