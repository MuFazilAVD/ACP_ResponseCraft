-- Active: 1779177650048@@127.0.0.1@3306
# TCS RFP Response Drafter - Build Tracker

## Progress

- [x] Read agent requirements.
- [x] Read Agent Blueprint skill.
- [x] Read ACP Control Plane guide (`ACP-Control-Plane.txt.txt`).
- [x] Read required Agent Blueprint section docs.
- [x] Read LangGraph reference implementation.
- [x] Read only the matching RAG + Tools archetype blueprint.
- [x] Select safest archetype and record justification in `plan.md`.
- [x] Draft governance charter in `governance.md`.
- [x] Draft requested entitlements in `entitlements.md`.
- [x] Implement AEI service.
- [x] Add local prompts and Langfuse sync.
- [x] Add MCP/local retrieval path.
- [x] Add OTel `gen_ai.*` tracing hooks.
- [x] Add golden dataset.
- [x] Add smoke tests for all AEI endpoints.
- [x] Make `rd-mcp-server/` independently deployable with its own mock knowledge, requirements, start script, and systemd example.
- [x] Verify hosted `proposal-knowledge-mcp` over Streamable HTTP and wire it as the response drafter's default MCP tool endpoint.
- [x] Run local tests.
- [x] Complete final conformance checklist.

## Conformance Checklist

- [x] AEI endpoints `/health`, `/config`, `/invoke`, `/prompts/sync` implemented and validated.
- [x] `/invoke` passes `model_override`, `context.system_prompt_override`, and all generation overrides through.
- [x] `/config` reports default generation parameters.
- [x] `requested_entitlements` and `entitlement_scope` declared.
- [x] Governance charter declared with LOB, accountable IdP role, action classes, risk tiers, and oversight.
- [x] Golden dataset exists and is bound to `proposal_management.rfp.response_drafting`.
- [x] Tool access is declared as entitlements and emitted in `tool_calls[]`.
- [x] OTel `gen_ai.*` spans wired and `trace_id` plus `token_usage` returned.
- [x] Prompts externalized under `prompts/*.md` and syncable to Langfuse.
- [x] System prompt includes role, anti-capability, output contract, grounding rules, refusal boundaries, prompt-injection defense, and length budget.
- [x] Deployment path documented for internal HTTP registration.

## Resolved Gaps

- [x] Standard LiteLLM-compatible Gemini default is wired via `langchain_openai.ChatOpenAI` (`GLM-4.7-Flash`, `https://d2brdeqy144bwg.cloudfront.net/myllm/v1/`, request user `AgentStudio`). Operators only need `LLM_API_KEY`/`OPENAI_API_KEY` if the gateway requires authentication.
- [x] Langfuse v4 integration is wired for PromptHub sync, `auth_check()` on sync, root `responsecraft-agent` observations, nested `responsecraft-generate` observations, trace IO, error status, and flush. Default host is `http://172.16.1.224`; secrets remain environment-only.
- [x] Contract-test `proposal-knowledge-mcp` server is implemented as an independent unit under `rd-mcp-server/` with a `search_proposal_knowledge` tool over Streamable HTTP plus a compatibility bridge. The server owns `rd-mcp-server/knowledge/mock_knowledge.json`, `requirements.txt`, `start-rd-mcp.sh`, and `rd-mcp-server.service.example`; runtime invoke rejects evidence marked as mock.
- [x] Hosted MCP endpoint is verified and wired as the default response drafter retrieval tool: `https://d2brdeqy144bwg.cloudfront.net/poc185/acp-mcp/rd-mcp-server/mcp`. `ClientSession.call_tool("search_proposal_knowledge", ...)` returned ranked results, and the agent retrieval layer records the call as `source: "mcp"`.
- [x] Runtime configuration boundary cleaned up: `.env.example` now contains keys/secrets only and the app allow-loads only those keys from `.env`, while model names, URLs, prompt labels, MCP transport/tool settings, generation defaults, and Langfuse behavior are tracked in `response_drafter_agent/settings.py`.
- [x] Removed the live LLM placeholder key fallback; missing LLM credentials now fail clearly instead of sending `not-required` to the gateway.
- [x] Live LLM local smoke completed by operator with real key; LLM integration is no longer a pending gap.
- [x] Runtime mock behavior removed from invoke: `context.force_mock` is rejected, local mock knowledge fallback is disabled, local LLM draft fallback is removed, LLM errors return invoke failures, and MCP retrieval errors or mock-marked evidence are passed to the LLM as visible dependency issues.

## Latest Verification

- [x] 2026-06-29: `response-drafter` was linked directly to `MuFazilAVD/ACP_ResponseCraft.git` as the repo working tree; `.gitignore` excludes `.env`, `.env.*`, `env/`, `venv/`, `.venv/`, Python caches, test caches, and build artifacts while preserving `.env.example`.
- [x] 2026-06-29: `.\venv\Scripts\python.exe -m unittest discover -s tests` passed locally with 16 tests after removing runtime mock response paths.
- [x] 2026-06-29: `.\venv\Scripts\python.exe -m compileall response_drafter_agent` passed.
- [x] 2026-06-29: Langfuse SDK surface verified in the project venv for `Langfuse(...)`, `auth_check`, `create_prompt`, `get_prompt`, `flush`, `start_as_current_observation`, `set_current_trace_io`, and `update_current_span`.
- [x] 2026-06-29: Mocked Langfuse PromptHub sync created all 4 prompt variants, flushed versions, and resolved the synced prompt as `source=langfuse`.
- [x] 2026-06-29: Mocked invoke tracing created `responsecraft-agent` and nested `responsecraft-generate` observations, trace IO updates, usage details, and flush.

## Completion Route Map

- [ ] Add real keys/secrets for ACP, Langfuse, OTLP, MCP, and optional LLM gateway credentials in `.env`.
- [ ] Start the AEI service with code-owned runtime defaults and register its URL with ACP.
- [ ] Inspect ACP entitlement reconciliation for `tcs-rfp-response-drafter`; resolve any over-request and compile grants.
- [ ] Register/validate `proposal-knowledge-mcp` in ACP and prove retrieval under `ENTITLEMENT_ENFORCEMENT=enforce` with non-mock approved evidence.
- [ ] Sync prompts to Langfuse and verify prompt versions plus invoke-time trace observations.
- [ ] Verify live OTLP export with `gen_ai.*` spans.
- [ ] Launch ACP readiness/certification against `proposal_management.rfp.response_drafting`.
- [ ] Re-run local tests and the conformance checklist after any platform-driven prompt, model, entitlement, governance, or tool change.

## Known External Gaps

- Live Langfuse auth, prompt sync, and trace ingestion must be verified in a network environment that can reach `http://172.16.1.224`, using real `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`.
- Hosted contract-test MCP is reachable, but runtime invoke rejects mock-marked evidence; ACP MCP resource registration, real approved evidence, and grant compilation still need platform validation. The final hybrid retrieval internals will be designed after the knowledgebase, chunking, and metadata strategy are ready.
- ACP entitlement reconciliation, compilation, readiness run, and certification require the platform API.
- MCP gateway enforcement under `ENTITLEMENT_ENFORCEMENT=enforce` must be verified after ACP compiles the grants.
- OTLP export must be verified with live collector credentials.
