# Repo Recall — Git repo indexer + recall API

Repo Recall indexes your git repositories (code + docs + key config files) and lets you **recall the best candidate repo** for a prompt.
It’s designed to later plug into a Slack bot / PR agent workflow (e.g., PRFactory).

This repository is set up using the **“Code Factory” control-plane pattern**:
a single machine-readable contract governs risk tiers and required checks, with a **preflight policy gate** running before expensive CI fanout.

## What you get

- **Indexer**: clone/open repos, extract key files, chunk content, embed, and store into Postgres + pgvector (incremental updates use git diffs).
- **Hybrid search**: semantic (vectors) + lexical (Postgres full-text) + metadata filters.
- **CLI**:
  - `repo-recall init-db`
  - `repo-recall index ...`
  - `repo-recall update ...`
  - `repo-recall search ...`
  - `repo-recall serve`
- **FastAPI service**:
  - `POST /search` returns ranked repos with evidence chunks
  - health endpoints: `GET /health`, `GET /health/ready`, `GET /health/runtime`
- **Built-in UI** (verification/debugging): `GET /ui`
  - Search UI
  - Index stats
  - List indexed repos
  - Trigger quick index runs (background threadpool)
- **PRFactory connectors**:
  - `repo_recall.connectors.prfactory.RepoRecallHttpAdapter` (HTTP)
  - `repo_recall.connectors.prfactory.RepoRecallMockAdapter` (tests/local)
- **Secret redaction** (best effort): redact high-signal secrets before storing text and before embedding.
- **Production controls**:
  - `control/contract.yml` defines risk tiers and required checks
  - `scripts/risk_policy_gate.py` enforces the contract in CI
  - GitHub Actions workflow runs **preflight gate → lint/typecheck/tests**

## Quickstart (local dev)

### 1) Start Postgres + pgvector + API
```bash
docker compose up -d --build
```

Open the UI:
- `http://localhost:8080/ui`
- `http://localhost:8080/ui/catalog` (repo/branch catalog UI)

### 2) Configure environment
Copy `.env.example` to `.env` and edit values:
```bash
cp .env.example .env
export $(cat .env | xargs)
```

### 3) Initialize DB schema
```bash
repo-recall init-db
```

### 4) Index a repo
Index a local path:
```bash
repo-recall index --repo /path/to/my/repo
```

Index a remote repo (Git URL):
```bash
repo-recall index --repo https://github.com/org/project.git
```

### 5) Search
```bash
repo-recall search "Where do we handle webhook retries?"
```

### 6) Run the API
```bash
repo-recall serve --host 0.0.0.0 --port 8080
```

Then:
```bash
curl -X POST http://localhost:8080/search \
  -H "Content-Type: application/json" \
  -d '{"query":"oauth token refresh logic","top_k_repos":5}'
```

## PRFactory integration

See `docs/INTEGRATION_PRFACTORY.md`.

The recommended integration is HTTP:

```python
from repo_recall.connectors.prfactory import RepoRecallHttpAdapter

indexer = RepoRecallHttpAdapter(base_url="http://repo-recall:8080", token=None)
resp = indexer.search("Where do we handle webhook retries?")
```

Catalog suggestions (repo + branch):

```python
resp = indexer.suggest_repos_and_branches(
    actor_id="U123",
    query="payments",
    top_k_repos=5,
    top_k_branches_per_repo=5,
)
```

Environment variables (PRFactory-friendly):

- `INDEXER_BASE_URL` (in PRFactory)
- `INDEXER_AUTH_TOKEN` (optional)

Repo Recall auth:
- `AUTH_MODE=disabled` (default)
- `AUTH_MODE=api_token` with `API_AUTH_TOKEN=...`

When auth is enabled, clients may send either:
- `X-FF-Token: <token>` (PRFactory convention)
- or `Authorization: Bearer <token>`

## Risk policy contract (control plane)

See:
- `control/contract.yml` — one machine-readable contract
- `docs/POLICY.md` — how risk tiers map to checks
- `.github/workflows/ci.yml` — preflight gate first, then fanout jobs

## Notes

- `MOCK_MODE=true` disables embeddings (lexical-only) even if `OPENAI_API_KEY` is set.
- This is an MVP intended to be extended with:
  - hierarchical summaries (repo/file summaries)
  - reranking (cross-encoder or LLM judge)
  - Slack bot integration
  - PR automation

## GitHub catalog APIs

Repo Recall now includes an actor-scoped GitHub repo/branch catalog cache:

- `POST /api/indexer/catalog/suggest`
- `GET /api/indexer/catalog/repos`
- `GET /api/indexer/catalog/repos/{repo_id}/branches`
- `POST /api/indexer/catalog/sync`
- `GET /api/indexer/catalog/runs`
- `GET /api/indexer/catalog/runs/{run_id}`
- `POST /api/indexer/webhooks/github`

Catalog UI actions:
- Actor-scoped suggest (`catalog/suggest`)
- Sync queueing (`catalog/sync`)
- Repo/branch browsing
- Run history

Environment flags:

- `ENABLE_CATALOG=true`
- `GITHUB_API_BASE_URL=https://api.github.com`
- `GITHUB_WEBHOOK_SECRET=...`
- `GITHUB_CONNECT_URL_TEMPLATE=/connect/github?actor_id={actor_id}`
- `CATALOG_SYNC_INTERVAL_SECONDS=3600`

Optional industrial integration:
- `GITHUB_TOKEN_BROKER_URL` (actor token broker endpoint)
- `GITHUB_TOKEN_BROKER_AUTH_TOKEN` (service token for broker auth)

Local demo-only tools:
- `ENABLE_CATALOG_DEV_ENDPOINTS=true`
- then run `powershell -ExecutionPolicy Bypass -File .\scripts\catalog_demo.ps1`

## Free webhook URL without owning a domain (dev)

If you do not own a domain, use `smee.io` as a free webhook relay.
This gives you a stable public webhook URL and forwards requests to your local API.

1. Create a relay channel:

```text
https://smee.io/new
```

2. Keep your API running on `http://localhost:8080`.

3. Start the forwarder:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_github_webhook_proxy.ps1 -ChannelUrl "https://smee.io/<your-channel-id>"
```

4. In GitHub webhook settings, set:
- Webhook URL: `https://smee.io/<your-channel-id>`
- Secret: same value as `GITHUB_WEBHOOK_SECRET` in `.env`

5. Repo Recall receives the forwarded webhook at:
- `http://localhost:8080/api/indexer/webhooks/github`

Note: this is intended for local development/testing, not production.

## License
MIT
