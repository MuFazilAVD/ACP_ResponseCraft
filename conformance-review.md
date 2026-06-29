# Final ACP/AEI Conformance Review

Review date: 2026-06-29

Rubric source: `agent-blueprint/conformance.md`

## Result

Status: **Locally conformant, platform validation pending**

The agent satisfies the local AEI, prompt, governance, entitlement declaration, default LLM wiring, golden dataset, and test requirements. The live LLM local smoke has passed. Remaining gaps require the user's real ACP, MCP gateway enforcement, private-network Langfuse, and OTLP services.

## Checklist

| Area | Status | Evidence |
| --- | --- | --- |
| AEI endpoints | Pass | `GET /health`, `GET /config`, `POST /invoke`, `POST /prompts/sync` implemented in `response_drafter_agent/agent.py`; smoke tested with FastAPI TestClient and local HTTP startup. |
| Overrides | Pass | `model_override`, `context.system_prompt_override`, and generation overrides are accepted by `InvokeRequest`, forwarded into graph state, and applied in the `ChatOpenAI` LLM adapter. |
| LLM | Pass locally | Default model is `GLM-4.7-Flash` through the ACP LiteLLM-compatible gateway at `https://d2brdeqy144bwg.cloudfront.net/myllm/v1/` with request user `AgentStudio`; operator completed local live LLM smoke with a real key. Runtime mock LLM drafting is disabled, and LLM failures return invoke errors. |
| Entitlements | Pass locally; ACP reconciliation pending | `requested_entitlements` and `entitlement_scope` are returned from `/config` and documented in `entitlements.md`. ACP reconciliation and compile require platform access. |
| Charter | Pass | `governance_charter` is returned from `/config` and documented in `governance.md`; accountable role is `proposal-response-approver`. |
| Golden dataset | Pass locally; certification pending | Starter dataset exists at `golden-dataset/rfp_response_drafter_golden.json` with `target_eval_slugs` bound to `proposal_management.rfp.response_drafting`. ACP readiness/certification run still pending. |
| Tools | Pass locally; gateway enforcement pending | `proposal-knowledge-mcp` server exists as a self-contained unit under `rd-mcp-server/` with `search_proposal_knowledge` over Streamable HTTP and a compatibility bridge. Runtime local mock retrieval is disabled. Retrieval uses MCP only, emits `tool_calls[]`, and treats mock-marked evidence or retrieval failures as visible dependency errors. ACP MCP gateway registration and enforce-mode test require platform access. |
| OTel | Pass locally; collector verification pending | Manual `gen_ai.*` span hooks exist for invoke, graph nodes, retrieval, generation, guardrail checks, and render. Local fallback returns trace ids without OTel packages. Live OTLP export requires credentials and collector endpoint. |
| Langfuse | Code verified; private-network live auth pending | Langfuse v4 integration uses the code-owned host `http://172.16.1.224`, env-only keys, `auth_check()` on prompt sync, root `agent` observations, nested `generation` observations, trace IO, error status, and `flush()`. SDK signatures and mocked PromptHub/tracing flows passed locally; live credentials plus private-network access are required to verify ingestion. |
| Prompts | Pass | Prompt variants live under `response_drafter_agent/prompts/*.md`; `/prompts/sync` safely syncs to Langfuse when credentials exist. |
| System prompt | Pass | Prompts include role framing, anti-capability, exact output contract, grounding rules, refusal boundaries, prompt-injection defense, and length budget. |
| Deploy | Pass locally; ACP registration pending | Internal HTTP runtime starts with Uvicorn and was checked on port 8110. ACP registration by URL remains an external platform step. |

## Test Evidence

- `python -m unittest discover -s tests`
- `python -m compileall response_drafter_agent`
- `python -m unittest discover -s tests` with Langfuse `4.11.0` injected on `PYTHONPATH`
- Streamable HTTP MCP smoke: started `rd-mcp-server/server.py` on port 8122 in an isolated venv with `mcp>=1.28,<2`, called `search_proposal_knowledge` via `ClientSession.call_tool`, and received ranked structured results.
- Hosted Streamable HTTP MCP smoke: called `https://d2brdeqy144bwg.cloudfront.net/poc185/acp-mcp/rd-mcp-server/mcp` via `ClientSession.call_tool` and received ranked structured results.
- Result: 16 tests passed on 2026-06-29 in the project venv after removing runtime mock response paths.
- Mocked Langfuse PromptHub sync created all prompt variants and resolved the synced default prompt as `source=langfuse`.
- Mocked invoke tracing created root `responsecraft-agent` and nested `responsecraft-generate` observations with trace IO, usage details, and flush.
- Local HTTP startup check: `/health`, `/config`, and `/invoke` returned successfully; `/invoke` returned a trace id and one tool call.

## Remaining Required Platform Steps

1. Add real keys/secrets only in `.env` for Langfuse, OTLP, ACP/MCP, and optional LLM gateway authentication.
2. Start the service and register it with ACP.
3. Inspect entitlement reconciliation for `tcs-rfp-response-drafter`.
4. Register the MCP server with ACP, compile entitlement grants, and test MCP retrieval under `ENTITLEMENT_ENFORCEMENT=enforce` with non-mock approved evidence.
5. Sync prompts to Langfuse and verify prompt versions plus trace observations in `/invoke`.
6. Launch readiness/certification using the starter golden dataset.
7. Re-run conformance after any prompt, model, entitlement, or governance change.
