# Proposal Knowledge MCP Tool Contract

This is the temporary mock contract for `proposal-knowledge-mcp`. It intentionally keeps retrieval inputs stable while the real knowledgebase design is still open.

## Tool

- MCP server: `proposal-knowledge-mcp`
- Tool name: `search_proposal_knowledge`
- Capability entitlement: `capability:rfp_knowledge.search`
- Default hosted bridge endpoint: `https://d2brdeqy144bwg.cloudfront.net/poc185/acp-mcp/rd-mcp-server/tools/search_proposal_knowledge`
- Hosted contract endpoint: `https://d2brdeqy144bwg.cloudfront.net/poc185/acp-mcp/rd-mcp-server/contract`
- Local development MCP endpoint: `http://localhost:8121/mcp`

## Input

Hosted bridge request:

```json
{
  "input": {
    "query": "Describe your approach to application security controls."
  }
}
```

Local Streamable HTTP and local bridge development also support the richer MCP
arguments shape below, but the hosted `/contract` currently advertises only
`input.query`:

```json
{
  "query": "Describe your approach to application security controls.",
  "top_k": 5,
  "filters": {
    "intent": "security_and_compliance",
    "topics": ["security", "compliance"],
    "source_type": "local_mock",
    "source_ids": ["mock-security-001"]
  },
  "metadata_filters": {},
  "min_score": 0.0,
  "include_content": true
}
```

Required:

- `input.query`: natural-language RFP question or search phrase.

Optional for local/richer MCP implementations:

- `top_k`: integer from 1 to 10; default `5`.
- `filters.intent`: retrieval hint from the agent intent classifier.
- `filters.topics`: topic hints for hybrid retrieval later.
- `filters.source_type`: optional source category.
- `filters.source_ids`: optional allow-list of exact source ids.
- `metadata_filters`: future exact-match metadata constraints.
- `min_score`: float from 0 to 1.
- `include_content`: whether to return full mock content or a short snippet.

## Output

Hosted bridge response:

```json
{
  "tool": "search_proposal_knowledge",
  "results": "TCS's annual revenue is USD 25.7 billion."
}
```

The agent normalizes a hosted string `results` value into one evidence item.
Local Streamable HTTP and local bridge development may return richer ranked
results:

```json
{
  "query": "Describe your approach to application security controls.",
  "top_k": 5,
  "retrieval_mode": "mock_keyword",
  "result_count": 1,
  "results": [
    {
      "source_id": "mock-security-001",
      "title": "Security and Compliance Response Guidance",
      "content": "Security responses should be grounded...",
      "score": 0.625,
      "source_type": "local_mock",
      "metadata": {
        "topics": ["security", "compliance", "data protection", "controls"],
        "intent_hint": "security_and_compliance",
        "retrieval_mode": "mock_keyword"
      }
    }
  ]
}
```

## Local Hosting

The MCP server is self-contained under `rd-mcp-server/`. Its mock data lives at
`rd-mcp-server/knowledge/mock_knowledge.json`, so the folder can be copied to a
server and run independently of `response_drafter_agent/`.

```powershell
cd C:\AVDCodes\ResponseDraftACP\acp-agents\response-drafter
pip install -r rd-mcp-server/requirements.txt
python rd-mcp-server/server.py
```

The MCP endpoint is:

```text
http://localhost:8121/mcp
```

For a plain HTTP compatibility bridge while wiring ACP gateway adapters:

```powershell
uvicorn server:app --app-dir rd-mcp-server --host 0.0.0.0 --port 8121
```

Bridge endpoint:

```text
POST http://localhost:8121/tools/search_proposal_knowledge
```

For the Linux deployment folder, run from `/data/rd-mcp-server`:

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
MCP_MOCK_PORT=8005 ./start-rd-mcp.sh
```

For systemd, copy `rd-mcp-server/rd-mcp-server.service.example` to
`/etc/systemd/system/rd-mcp-server.service` after copying the folder to
`/data/rd-mcp-server`.
