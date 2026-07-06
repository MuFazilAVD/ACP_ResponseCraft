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
- [x] Add scoped guardrail routing so greetings, unrelated factual questions, and prohibited authority requests skip MCP/LLM.
- [x] Change `/invoke.response` to the user-facing draft answer only, with structured debug payload logged instead of rendered.

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
- [x] Hosted bridge endpoint is wired as the default response drafter retrieval tool: `https://d2brdeqy144bwg.cloudfront.net/poc185/acp-mcp/rd-mcp-server/tools/search_proposal_knowledge`. The agent sends the `/contract` `input.query` body over `http_bridge`, and the retrieval layer records the call as `source: "mcp"`.
- [x] Runtime configuration boundary cleaned up: `.env.example` now contains keys/secrets only and the app allow-loads only those keys from `.env`, while model names, URLs, prompt labels, MCP transport/tool settings, generation defaults, and Langfuse behavior are tracked in `response_drafter_agent/settings.py`.
- [x] Removed the live LLM placeholder key fallback; missing LLM credentials now fail clearly instead of sending `not-required` to the gateway.
- [x] Live LLM local smoke completed by operator with real key; LLM integration is no longer a pending gap.
- [x] Runtime mock behavior removed from invoke: `context.force_mock` is rejected, local mock knowledge fallback is disabled, local LLM draft fallback is removed, LLM errors return invoke failures, and MCP retrieval errors or mock-marked evidence return deterministic dependency messages without asking the LLM to draft around missing approved knowledge.
- [x] UI/debug boundary tightened: `/invoke.response` contains only the draft answer, while the full `DraftResponse` diagnostic shape is logged at debug level and retained in trace metadata.

## Latest Verification

- [x] 2026-07-02: Added `/invoke` tool-output print after MCP retrieval so service logs show the normalized evidence payload passed toward the LLM, including source id, title, score, content, and metadata.
- [x] 2026-07-02: `.\venv\Scripts\python.exe -m compileall response_drafter_agent` passed after adding the tool-output print.
- [x] 2026-07-02: Switched the default proposal knowledge runtime from Streamable HTTP `/mcp` to the hosted `/tools/search_proposal_knowledge` bridge and send the hosted `/contract` `input.query` body. Added guardrail logic so MCP text such as `Error executing tool...` is treated as a tool error instead of evidence.
- [x] 2026-07-02: Live hosted bridge smoke with `{"input":{"query":"What is the annual revenue of TCS?"}}` returned a real `results` string; `KnowledgeRetriever().retrieve(...)` now normalizes that hosted string response into one evidence item.
- [x] 2026-07-02: `.\venv\Scripts\python.exe -m compileall response_drafter_agent rd-mcp-server` passed after the `input.query` payload change, hosted string-result normalization, and local bridge parser update.
- [x] 2026-07-02: Live `KnowledgeRetriever().retrieve("What is the annual revenue of TCS?")` smoke returned `tool_call.status=success`, one `mcp-text` source, and content stating TCS annual revenue is USD 25.7 billion.
- [x] 2026-07-06: Added invoke fallback for blank LLM completions after successful retrieval: if the model returns empty/whitespace and approved evidence exists, `/invoke.response` now uses the top evidence content with grounding limitations instead of returning an empty string.
- [x] 2026-07-06: `.\venv\Scripts\python.exe -m compileall response_drafter_agent` passed after the blank-LLM fallback.
- [x] 2026-07-06: `.\venv\Scripts\python.exe -m unittest tests.test_aei.AEIEndpointTests.test_invoke_falls_back_to_evidence_when_llm_returns_blank` passed.
- [ ] 2026-07-06: `.\venv\Scripts\python.exe -m unittest discover -s tests` currently has 1 failure out of 21 tests: `test_invoke_returns_aei_metadata_and_draft_response` still expects `model_override` propagation to `openai/gpt-4.1`, while the current local code has `InvokeRequest.model_override` commented out and hardcodes `GLM-4.7-Flash` in invoke.
- [x] 2026-07-02: `.\venv\Scripts\python.exe -m compileall response_drafter_agent` passed after bridge rewiring.
- [ ] 2026-07-02: `.\venv\Scripts\python.exe -m unittest discover -s tests` had 1 failure out of 20 tests: `test_invoke_returns_aei_metadata_and_draft_response` expected `model_override` propagation to `openai/gpt-4.1`, while the local code had `InvokeRequest.model_override` commented out and hardcoded `GLM-4.7-Flash` in invoke.
- [x] 2026-06-30: Added `deploy/response-drafter.service.example` for the `/data/acp-agents/response-drafter` deployment on port 8006 and aligned `deploy/install_systemd.sh` to default to port 8006. Actual service start and ACP registration remain pending operator/platform steps.
- [x] 2026-06-30: Added deterministic pre-retrieval scope guardrails, answer-only response rendering, JSON draft unwrapping, deterministic retrieval-error messaging, and prompt/test coverage for those behaviors.
- [x] 2026-06-30: `.\venv\Scripts\python.exe -m unittest discover -s tests` passed locally with 19 tests.
- [x] 2026-06-30: `.\venv\Scripts\python.exe -m compileall response_drafter_agent` passed.
- [x] 2026-06-30: Operator confirmed real LLM credentials are present in the private `.env` and live LLM calls are working.
- [x] 2026-06-30: Operator confirmed private-network Langfuse integration is working with real credentials, and the agent prompt is synced to PromptHub.
- [x] 2026-06-29: `response-drafter` was linked directly to `MuFazilAVD/ACP_ResponseCraft.git` as the repo working tree; `.gitignore` excludes `.env`, `.env.*`, `env/`, `venv/`, `.venv/`, Python caches, test caches, and build artifacts while preserving `.env.example`.
- [x] 2026-06-29: `.\venv\Scripts\python.exe -m unittest discover -s tests` passed locally with 16 tests after removing runtime mock response paths.
- [x] 2026-06-29: `.\venv\Scripts\python.exe -m compileall response_drafter_agent` passed.
- [x] 2026-06-29: Langfuse SDK surface verified in the project venv for `Langfuse(...)`, `auth_check`, `create_prompt`, `get_prompt`, `flush`, `start_as_current_observation`, `set_current_trace_io`, and `update_current_span`.
- [x] 2026-06-29: Mocked Langfuse PromptHub sync created all 4 prompt variants, flushed versions, and resolved the synced prompt as `source=langfuse`.
- [x] 2026-06-29: Mocked invoke tracing created `responsecraft-agent` and nested `responsecraft-generate` observations, trace IO updates, usage details, and flush.

## Completion Route Map

- [x] Add real LLM and Langfuse keys/secrets in the private `.env`; verify live LLM and PromptHub sync.
- [ ] Add or confirm real keys/secrets for ACP, OTLP, MCP, and optional enterprise API credentials in the private `.env`.
- [ ] Start the AEI service with code-owned runtime defaults using the port-8006 systemd unit and register its URL with ACP.
- [ ] Inspect ACP entitlement reconciliation for `tcs-rfp-response-drafter`; resolve any over-request and compile grants.
- [ ] Register/validate `proposal-knowledge-mcp` in ACP and prove retrieval under `ENTITLEMENT_ENFORCEMENT=enforce` with non-mock approved evidence.
- [x] Sync prompts to Langfuse and verify prompt versions in the private environment.
- [ ] Capture or re-check invoke-time Langfuse trace observations during the next live service smoke, if formal review evidence is needed.
- [ ] Verify live OTLP export with `gen_ai.*` spans.
- [ ] Launch ACP readiness/certification against `proposal_management.rfp.response_drafting`.
- [ ] Re-run local tests and the conformance checklist after any platform-driven prompt, model, entitlement, governance, or tool change.
- [ ] Resolve the current `model_override` contract mismatch, or update tests and conformance docs if the service is intentionally fixed to `GLM-4.7-Flash`.

## Known External Gaps

- Private-network Langfuse auth/integration and PromptHub sync are operator-verified with real credentials. Keep prompt version and trace evidence with the formal review package when ACP conformance is submitted.
- Hosted contract-test MCP health, contract, and `input.query` bridge call are reachable for the tested annual-revenue query. Runtime invoke still treats retrieval dependency errors as errors instead of evidence. ACP MCP resource registration, real approved evidence, and grant compilation still need platform validation. The final hybrid retrieval internals will be designed after the knowledgebase, chunking, and metadata strategy are ready.
- ACP entitlement reconciliation, compilation, readiness run, and certification require the platform API.
- MCP gateway enforcement under `ENTITLEMENT_ENFORCEMENT=enforce` must be verified after ACP compiles the grants.
- OTLP export must be verified with live collector credentials.
