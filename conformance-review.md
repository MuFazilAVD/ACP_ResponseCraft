# Final ACP/AEI Conformance Review

Review date: 2026-07-06

Rubric source: `agent-blueprint/conformance.md`

## Result

Status: **Answer-only runtime shape implemented; ACP conformance gap open**

The agent now returns an answer-only public `/invoke` body, `{"response": "..."}`, for the runtime UI contract. That matches the current product requirement but intentionally omits the full AEI metadata envelope (`model_used`, `latency_ms`, `token_usage`, `trace_id`, prompt fields, `tool_calls`, and `skills_loaded`) from the HTTP response. Formal ACP conformance requires restoring that envelope or adding an ACP-compatible adapter before review.

## Checklist

| Area | Status | Evidence |
| --- | --- | --- |
| AEI endpoints | Partial | `GET /health`, `GET /config`, `POST /invoke`, `POST /prompts/sync` are implemented in `response_drafter_agent/agent.py`, but `/invoke` now serializes only `{"response": "..."}` instead of the full AEI metadata envelope. |
| Overrides | Partial | `context.system_prompt_override` and generation overrides are accepted and forwarded. `model_override` remains a known contract gap because `InvokeRequest.model_override` is disabled and invoke currently hardcodes `GLM-4.7-Flash`. |
| LLM | Pass locally | Default model is `GLM-4.7-Flash` through the ACP LiteLLM-compatible gateway at `https://d2brdeqy144bwg.cloudfront.net/myllm/v1/` with request user `AgentStudio`; operator completed local live LLM smoke with a real key. Runtime mock LLM drafting is disabled, and LLM failures return invoke errors. |
| Entitlements | Pass locally; ACP reconciliation pending | `requested_entitlements` and `entitlement_scope` are returned from `/config` and documented in `entitlements.md`. ACP reconciliation and compile require platform access. |
| Charter | Pass | `governance_charter` is returned from `/config` and documented in `governance.md`; accountable role is `proposal-response-approver`. |
| Golden dataset | Pass locally; certification pending | Starter dataset exists at `golden-dataset/rfp_response_drafter_golden.json` with `target_eval_slugs` bound to `proposal_management.rfp.response_drafting`. ACP readiness/certification run still pending. |
| Tools | Partial; hosted bridge broader validation pending | `proposal-knowledge-mcp` server exists as a self-contained unit under `rd-mcp-server/` with `search_proposal_knowledge` over Streamable HTTP and a compatibility bridge. Runtime default points at the hosted `/tools/search_proposal_knowledge` bridge and sends the `/contract` `input.query` body. In-scope retrieval uses MCP and records tool diagnostics internally/logs them, but `tool_calls[]` is no longer returned in the public `/invoke` body. |
| OTel | Partial; collector verification pending | Manual `gen_ai.*` span hooks exist for invoke, graph nodes, retrieval, generation, guardrail checks, and render. Trace ids and token usage are retained internally, but no longer returned in the public `/invoke` body. Live OTLP export requires credentials and collector endpoint. |
| Langfuse | Operator verified in private env; formal evidence capture pending | Langfuse v4 integration uses the code-owned host `http://172.16.1.224`, env-only keys, `auth_check()` on prompt sync, root `agent` observations, nested `generation` observations, trace IO, error status, and `flush()`. SDK signatures and mocked PromptHub/tracing flows passed locally; on 2026-06-30 the operator confirmed real-credential Langfuse integration is working and the prompt is synced. Keep prompt version and trace evidence with the formal review package. |
| Prompts | Pass | Prompt variants live under `response_drafter_agent/prompts/*.md`; `/prompts/sync` safely syncs to Langfuse when credentials exist. The model contract now requires plain draft-answer text only, with no JSON/code-fence envelope. |
| System prompt | Pass | Prompts include role framing, anti-capability, exact output contract, grounding rules, refusal boundaries, prompt-injection defense, and length budget. |
| Deploy | Pass locally; ACP registration pending | Internal HTTP runtime starts with Uvicorn and was checked on port 8110. A systemd unit example for the `/data/acp-agents/response-drafter` server deployment on port 8006 now lives at `deploy/response-drafter.service.example`. Actual service start and ACP registration by URL remain external platform steps. |

## Test Evidence

- `python -m unittest discover -s tests`
- `python -m compileall response_drafter_agent`
- `python -m unittest discover -s tests` with Langfuse `4.11.0` injected on `PYTHONPATH`
- Streamable HTTP MCP smoke: started `rd-mcp-server/server.py` on port 8122 in an isolated venv with `mcp>=1.28,<2`, called `search_proposal_knowledge` via `ClientSession.call_tool`, and received ranked structured results.
- Hosted bridge smoke on 2026-07-02: POSTing `{"input":{"query":"What is the annual revenue of TCS?"}}` to `/tools/search_proposal_knowledge` returned a real `results` string, which the agent normalizes into evidence.
- Result: 16 tests passed on 2026-06-29 in the project venv after removing runtime mock response paths.
- Result: 19 tests passed on 2026-06-30 in the project venv after adding scoped guardrail, answer-only response rendering, deterministic retrieval-error handling, and JSON-output unwrapping coverage.
- `python -m compileall response_drafter_agent` passed on 2026-06-30.
- Mocked Langfuse PromptHub sync created all prompt variants and resolved the synced default prompt as `source=langfuse`.
- Mocked invoke tracing created root `responsecraft-agent` and nested `responsecraft-generate` observations with trace IO, usage details, and flush.
- Local HTTP startup check: `/health`, `/config`, and `/invoke` returned successfully before the answer-only body change.
- 2026-07-06: `.\venv\Scripts\python.exe -m compileall response_drafter_agent` passed after changing `/invoke` to serialize only `{"response": "..."}`.
- 2026-07-06: `.\venv\Scripts\python.exe -m unittest discover -s tests` passed with 21 tests after updating output-shape coverage.
- 2026-06-30 operator report: private `.env` contains real LLM and Langfuse credentials; live LLM calls and Langfuse integration are working; the agent prompt is synced to PromptHub.

## Remaining Required Platform Steps

1. Add or confirm real keys/secrets only in `.env` for OTLP, ACP/MCP, and any optional enterprise API authentication. LLM and Langfuse credentials are already present in the operator's private environment.
2. Start the service on port 8006 using `deploy/response-drafter.service.example` and register it with ACP.
3. Inspect entitlement reconciliation for `tcs-rfp-response-drafter`.
4. Register the MCP server with ACP, compile entitlement grants, and test MCP retrieval under `ENTITLEMENT_ENFORCEMENT=enforce` with non-mock approved evidence.
5. Retain private-environment Langfuse prompt-version and trace-observation evidence for formal review.
6. Launch readiness/certification using the starter golden dataset.
7. Re-run conformance after any prompt, model, entitlement, or governance change.
8. Restore the full AEI invoke metadata envelope, or provide an ACP-compatible adapter, before formal ACP conformance review.
