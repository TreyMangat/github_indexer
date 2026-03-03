# PRFactory integration

Repo Recall is intentionally a separate service, but it ships with small connector helpers so PRFactory can
consume the index as a **cache/hint layer**.

## Integration options

### Option A (recommended): HTTP adapter

Run Repo Recall as its own service and let PRFactory call it over HTTP.

1. Start Repo Recall (local):

```bash
# in repo-recall
docker compose up --build
```

2. In PRFactory, set env vars:

```bash
INDEXER_BASE_URL=http://localhost:8080
INDEXER_AUTH_TOKEN=  # optional, only if Repo Recall AUTH_MODE=api_token
```

3. Use the adapter:

```python
from repo_recall.connectors.prfactory import RepoRecallHttpAdapter

indexer = RepoRecallHttpAdapter.from_env()
resp = indexer.search("Where do we handle webhook retries?")

best = resp.results[0] if resp.results else None

catalog = indexer.suggest_repos_and_branches(
    actor_id="U123",
    query="payments",
    top_k_repos=5,
    top_k_branches_per_repo=5,
)
```

### Option B: Shared Postgres (in-process)

If you later merge deployments and want to avoid HTTP hops, PRFactory can connect to the same Postgres instance
and call the `repo_recall.retrieval.search.search_repos` function directly.

This couples runtime dependencies more tightly; HTTP is preferred for now.

## Auth compatibility

Repo Recall supports a PRFactory-style auth header:

- When `AUTH_MODE=api_token`, send either:
  - `X-FF-Token: <token>` (PRFactory convention)
  - or `Authorization: Bearer <token>`

## Expected usage in the PRFactory flow

Typical usage:

- intake/spec validation: suggest a repo candidate list
- intake branch selection: suggest ranked branch candidates with reason codes
- build planning: fetch evidence chunks to ground code generation
- reviewer UX: show "why this repo" evidence in Slack/UI

If `catalog/suggest` returns `auth_required=true`, redirect the user to `connect_url`
and stop build progression until OAuth is connected.

## Token handling (production)

Recommended:
- PRFactory sends a short-lived actor OAuth token on sync/suggest requests when available.
- Repo Recall stores tokens in short-lived memory cache only.
- Configure `GITHUB_TOKEN_BROKER_URL` so background sweeps can resolve actor tokens
  without persisting raw credentials in Postgres.

Local demo:
- enable `ENABLE_CATALOG_DEV_ENDPOINTS=true`
- use `POST /api/indexer/catalog/dev/token` and `POST /api/indexer/catalog/dev/seed`
