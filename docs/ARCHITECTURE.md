# Architecture

Repo Recall is built around a simple but extensible data model:

- **Repo** → **File** → **Chunk**

It’s designed to be deployed as a standalone service and later integrated into orchestration systems
(e.g., PRFactory) as a hint/cache layer.

## Storage

- Postgres holds metadata and chunk text.
- pgvector stores embeddings (vector columns).
- Postgres full-text search (`tsvector`) provides lexical retrieval.

## Services

- **Indexer (CLI)**: `repo-recall index|update` for bulk ingestion
- **API (FastAPI)**:
  - `POST /search` and `/api/indexer/search`
  - `GET /api/indexer/repos`, `/api/indexer/stats`
  - Index jobs for the UI: `/api/indexer/index`, `/api/indexer/runs`
  - GitHub catalog: `/api/indexer/catalog/*` + `/api/indexer/webhooks/github`
- **UI**: `GET /ui` (calls the JSON endpoints)
  - Catalog UI: `GET /ui/catalog`

## Indexing pipeline

1. Clone or open repo
2. Discover files (respect `.gitignore` + internal ignore patterns)
3. Extract key files (README, manifests, CI)
4. Chunk docs + code
5. (Optional) Embed chunks
6. Store into DB

### Incremental updates

Incremental indexing uses git diffs (plus working tree diffs when a local repo is dirty) to avoid re-reading
and re-embedding the entire repo.

## Retrieval pipeline

1. Embed query (if enabled)
2. Vector search over chunks
3. Lexical search over chunks
4. Merge + score results
5. Aggregate chunk scores into repo scores
6. Return ranked repos + evidence chunks

## Integration (PRFactory)

Repo Recall ships with a tiny adapter in `repo_recall.connectors.prfactory`:

- `RepoRecallHttpAdapter` for HTTP calls
- `RepoRecallMockAdapter` for deterministic tests

See `docs/INTEGRATION_PRFACTORY.md`.

## GitHub catalog cache

The catalog layer stores actor-scoped GitHub visibility and branch metadata in
`indexer_catalog.*` tables. Sync happens via:

- webhook-triggered targeted updates
- hourly reconciliation sweeps
- manual sync endpoint (`POST /api/indexer/catalog/sync`)

Token resolution:
- request-supplied short-lived actor token
- in-memory actor token cache
- optional broker fallback (`GITHUB_TOKEN_BROKER_URL`)

## Notes

- Current chunking is pragmatic and language-agnostic with a Python-aware improvement.
- Secrets are redacted (best effort) before storing chunks and before sending text to an embedder.
- Later phases can add:
  - file-level summaries (and embeddings)
  - reranking with a cross-encoder or LLM judge
  - advanced scheduling/webhooks
