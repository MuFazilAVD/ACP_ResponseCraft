# TCS RFP Response Drafter

ACP/AEI-conformant RAG + Tools agent for drafting grounded answers to RFP questions.

## What It Does

- Accepts an individual RFP question through `POST /invoke`.
- Classifies intent and information needs.
- Retrieves approved proposal knowledge through a governed MCP endpoint when configured.
- Uses the standard ACP LiteLLM-compatible Gemini gateway by default.
- Drafts an answer for proposal-team and SME review.
- Blocks pricing, legal, contractual, commercial commitment, and final submission authority.
- Returns AEI prompt metadata, token usage, trace id, tool calls, and skills loaded.
- Does not expose runtime mock drafting or local mock retrieval. If LLM, MCP, or another dependency fails, the response surfaces the failure instead of pretending a grounded draft was produced.

## Local Setup

```powershell
cd C:\AVDCodes\ResponseDraftACP\acp-agents\response-drafter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

The `.env` file is intentionally keys-only and is loaded by the app on startup with an allow-list. Runtime defaults such as model names, URLs, prompt labels, transports, and generation settings are tracked in `response_drafter_agent/settings.py` so config migrations are visible in git. Non-key entries left in `.env` are ignored.

The default LLM is `GLM-4.7-Flash` through `https://d2brdeqy144bwg.cloudfront.net/myllm/v1/` with request user `AgentStudio`. Add `LLM_API_KEY` or `OPENAI_API_KEY` for live LLM testing. Runtime mock LLM responses are not supported.

## Run

```powershell
uvicorn response_drafter_agent.main:app --host 0.0.0.0 --port 8110
```

Register the internal HTTP runtime with ACP after the service is reachable:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "https://your-acp.example.com/api/agents/register" `
  -ContentType "application/json" `
  -Body '{"endpoint_url":"http://your-agent-host:8110"}'
```

## AEI Endpoints

- `GET /health`
- `GET /config`
- `POST /invoke`
- `POST /prompts/sync`

Example invoke:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8110/invoke" `
  -ContentType "application/json" `
  -Body '{"query":"Describe your approach to security controls and compliance."}'
```

## PromptHub

Prompts live under `response_drafter_agent/prompts/*.md`.

`POST /prompts/sync` syncs local prompt variants to Langfuse v4 when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are configured. The default self-hosted endpoint is tracked in code as `http://172.16.1.224`. Without credentials it returns `skipped` and keeps local prompts as the source.

At invoke time, the agent creates a Langfuse `agent` observation named `responsecraft-agent` and a nested `generation` observation named `responsecraft-generate`, then flushes at the end of the request according to the tracked setting in `response_drafter_agent/settings.py`.

## Governed Retrieval

The temporary MCP server exposes `search_proposal_knowledge` while the real knowledgebase and hybrid retrieval strategy are still being designed. The tool contract is documented in `mcp-tool-contract.md`.

The contract-test MCP server is an independently deployable unit under `rd-mcp-server/`. Its mock knowledge file lives inside that folder at `rd-mcp-server/knowledge/mock_knowledge.json`; runtime invoke rejects evidence marked as mock.

Run the local contract-test MCP server:

```powershell
python rd-mcp-server/server.py
```

Local contract-test MCP endpoint:

```text
http://localhost:8121/mcp
```

By default, the response drafter points at the hosted MCP endpoint:

```text
https://d2brdeqy144bwg.cloudfront.net/poc185/acp-mcp/rd-mcp-server/mcp
```

The default hosted MCP endpoint, transport, and tool name are tracked in `response_drafter_agent/settings.py`. Change those constants, not `.env`, when moving between MCP endpoints so the migration is reviewable. Use `http_bridge` only for gateway adapters that expose the compatibility bridge payload. The requested entitlement profile is declared in `/config` and documented in `entitlements.md`.

The invoke path rejects `context.force_mock` and local mock retrieval. If an MCP response is marked as mock evidence, including the contract-test server's mock data, the agent treats it as a dependency error and asks the LLM to explain that approved knowledge could not be retrieved.

Before evaluation or pre-production, install `langchain-openai`, reconcile and compile entitlements, then test with:

```text
ENTITLEMENT_ENFORCEMENT=enforce
```

## Tests

```powershell
python -m unittest discover -s tests
```

## Certification Assets

- Planning and progress: `plan.md`, `tracker.md`
- Governance: `governance.md`
- Entitlements: `entitlements.md`
- Constitution: `response_drafter_agent/config/constitution.yaml`
- Starter golden dataset: `golden-dataset/rfp_response_drafter_golden.json`
