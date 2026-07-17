# TCS RFP Response Drafter - ACP/AEI Plan

## Contract Inputs Read

- `agent-requirements.md`: RFP question understanding, approved knowledge retrieval, grounded draft response generation, no commercial commitments, no pricing, no final proposal approval.
- `agent-blueprint/SKILL.md` and section docs: AEI contract, entitlements, governance charter, MCP/tools, prompts and loop, OTel instrumentation, golden dataset, deployment, system prompt, conformance checklist.
- `ACP-Control-Plane.txt.txt`: ACP registry, PromptHub lifecycle, readiness runs, AEI endpoints, entitlements, MCP gateway, earned autonomy, monitoring, drift, conformance.
- `agent-blueprint/reference-implementations/langgraph/README.md`: internal HTTP FastAPI AEI service wrapping a LangGraph-style state machine.
- `langgraph-blueprints/enterprise-agent-blueprint-langgraph-rag_tools.md`: RAG + Tools archetype only.

## Archetype Decision

Selected archetype: **RAG + Tools Agent**.

Justification: the requirements are centered on understanding an RFP question, retrieving approved organizational knowledge through an MCP tool, and producing a grounded draft for human proposal-team review. The agent is not allowed to approve submissions, make pricing or commercial commitments, or replace SME review. This fits a retrieval-grounded drafting workflow better than a full autonomous agent. It also benefits from explicit graph stages for traceable Plan-Reason-Act-Reflect evaluation.

Runtime pattern: **LangGraph-compatible internal HTTP AEI service**.

The implementation compiles a LangGraph state graph when `langgraph` is installed and falls back to the same deterministic node sequence for local development. The public contract remains the AEI HTTP surface, so ACP conformance is independent of the local fallback.

## Agent Identity

- `agent_id`: `tcs-rfp-response-drafter`
- `agent_name`: `TCS RFP Response Drafter`
- `version`: `0.1.0`
- `domain`: `proposal_management`
- `eval_playbook_slug`: `proposal_management.rfp.response_drafting`
- `framework`: `langgraph`
- `graph_nodes`: `plan`, `reason`, `retrieve`, `act`, `reflect`, `render`

## AEI Endpoints

- `GET /health`: liveness, identity, version, domain.
- `GET /config`: default model, supported models, prompt config, Langfuse config, default generation parameters, requested entitlements, entitlement scope, governance charter.
- `POST /invoke`: returns an answer-only public body, `{"response": "..."}`. The internal invoke result still records prompt metadata, trace id, token usage, tool calls, and skills loaded for tracing/logging, but those diagnostics are not serialized in the public response.
- `POST /prompts/sync`: syncs local `prompts/*.md` variants to Langfuse PromptHub when credentials are configured; otherwise reports a local-only skip.

## Plan-Reason-Act-Reflect Loop

1. `plan`: validate the RFP question, classify intent, identify topics and forbidden ask patterns.
2. `reason`: derive information needs and deterministic authority constraints.
3. `retrieve`: query the governed MCP knowledge source and emit a visible tool error when retrieval fails or mock evidence is returned.
4. `act`: run deterministic constitution/governance gates, then generate a draft answer grounded in retrieved evidence.
5. `reflect`: check grounding, unsupported claims, prohibited commitments, and whether SME/proposal-team review is required.
6. `render`: retain the full `DraftResponse` shape as a debug/trace payload and return only the draft answer text in the public `/invoke` response.

## Governance Posture

- Decision support only.
- The LLM may produce drafting narrative but never owns final authority, support level, or submission readiness.
- Deterministic logic assigns `grounding_status`, `authority_status`, and review requirements.
- Consequential or irreversible actions default to `human_approval` or `prohibited`.
- Final proposal submission, pricing, contract terms, legal warranties, and commercial commitments are outside agent authority.

## Tooling and Entitlements

Primary governed tool: `proposal-knowledge-mcp` via the ACP MCP gateway.

The temporary tool is `search_proposal_knowledge`, hosted from `rd-mcp-server/server.py`. The runtime default uses the hosted HTTP compatibility bridge at `/tools/search_proposal_knowledge` and sends the `/contract` schema body with `input.query`. Local Streamable HTTP development still supports `/mcp` and richer arguments such as `top_k`, optional `filters`, optional `metadata_filters`, `min_score`, and `include_content`.

Runtime local mock retrieval is disabled. Production and pre-production must register the MCP server/resource and compile the requested entitlement profile before running with ACP gateway enforcement enabled. If retrieval fails or returns mock-marked evidence, the error is passed to the LLM so the draft clearly states that approved supporting knowledge could not be retrieved.

## OTel and Langfuse

- Manual OTel `gen_ai.*` spans are emitted when OpenTelemetry packages are available. The OTLP endpoint is a tracked code setting; the token comes from `.env`.
- Trace ids are returned on every invocation. If no OTel SDK is available locally, the agent generates a stable local trace id.
- Langfuse v4 prompt sync and trace observations use the code-owned host `http://172.16.1.224` and are skipped safely when credentials are absent.
- `/invoke` records a root `agent` observation and nested `generation` observation while retaining ACP-required `gen_ai.*` OTel spans.

## LLM Default

- Standard default model: `gemini-2.5-flash-cto-lab`.
- Standard gateway: `https://d2brdeqy144bwg.cloudfront.net/myllm/v1/`.
- Runtime adapter: `langchain_openai.ChatOpenAI` with `extra_body={"user": "AgentStudio"}`.
- Runtime mock LLM responses are disabled; LLM errors surface as invoke failures.

## Configuration Boundary

- `.env` is keys-only: LLM, Langfuse, OTLP, ACP/MCP, and optional enterprise API credentials.
- Stable runtime defaults live in `response_drafter_agent/settings.py`: models, URLs, prompt labels, transports, generation defaults, and telemetry behavior.
- Endpoint/model migrations should be code changes so they are visible in git and reviewed alongside conformance docs.

## Completion Route Map

### Phase 0 - Operator Inputs

Goal: collect the secret values that should not be committed.

- Set real `.env` values for LLM, Langfuse, OTLP, ACP/MCP, and optional enterprise API keys.
- Change model names, URLs, prompt labels, transports, or generation defaults only in `response_drafter_agent/settings.py`.
- Confirm the service host URL ACP will call, for example `http://your-agent-host:8006`.

Exit criteria: the service can start with code-owned runtime defaults and no required secret is missing.

### Phase 1 - Register Agent Runtime

Goal: make ACP aware of the internal HTTP AEI service.

- Start the service with Gunicorn/Uvicorn on the chosen host and port.
- Verify `/health`, `/config`, `/invoke`, and `/prompts/sync` from the same network segment ACP will use.
- Register the agent URL with ACP using `POST /api/agents/register`.

Exit criteria: ACP can fetch `/health` and `/config` for `tcs-rfp-response-drafter`.

### Phase 2 - Reconcile And Compile Entitlements

Goal: turn declared access requests into an enforced least-privilege grant.

- Inspect entitlement reconciliation for `tcs-rfp-response-drafter`.
- Resolve any over-request through explicit approval.
- Compile grants after reconciliation is accepted.
- Register the `proposal-knowledge-mcp` resource/capability with ACP if it is not already present.

Exit criteria: the compiled grant includes the MCP server and `capability:rfp_knowledge.search`.

### Phase 3 - Enforce MCP Gateway Access

Goal: prove governed retrieval works through the ACP MCP gateway.

- Run first with `ENTITLEMENT_ENFORCEMENT=audit` to detect missing grants.
- Switch to `ENTITLEMENT_ENFORCEMENT=enforce`.
- Invoke a retrieval-backed RFP question and confirm the trace/log diagnostics include the governed MCP call.
- Confirm undeclared or ungranted MCP access is denied by the gateway.

Exit criteria: retrieval succeeds only through compiled entitlements, and denial behavior is observed for ungranted access.

### Phase 4 - Verify PromptHub, LLM, And Telemetry

Goal: confirm all live integrations produce platform-observable evidence.

- Run `/prompts/sync` with real Langfuse credentials and verify prompt versions.
- Invoke the agent with the live LLM gateway and verify the answer-only output contract plus configured model, token usage, and trace id in telemetry/log diagnostics.
- Verify Langfuse trace observations for root agent and nested generation events in the private network.
- Verify OTLP export reaches the live collector with `gen_ai.*` spans.

Exit criteria: PromptHub, Langfuse, LLM gateway, and OTLP collector all show successful live traffic.

### Phase 5 - Run Readiness And Certification

Goal: complete the formal ACP validation path.

- Bind the starter golden dataset to `proposal_management.rfp.response_drafting`.
- Launch the ACP readiness/certification run.
- Review failures by dimension, then adjust prompts, deterministic checks, data, or entitlements as needed.
- Re-run until the certification result is passing for the requested operating posture.

Exit criteria: ACP certification passes, with any autonomy limits still aligned to the governance charter.

### Phase 6 - Final Conformance Review

Goal: freeze the deployable state and close the known gaps.

- Re-run local tests after any changes made during certification.
- Re-run the conformance checklist after prompt, model, entitlement, governance, output-contract, or tool changes.
- Update `tracker.md`, `conformance-review.md`, and deployment notes with the final platform evidence.

Exit criteria: tracker has no remaining external gaps except intentional future work such as final hybrid retrieval design.
