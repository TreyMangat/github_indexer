# Operations

## Database migrations

This MVP uses a simple SQL schema initializer:
- `repo-recall init-db`

For production you may want Alembic migrations, but a single schema file keeps the control-plane simple.

## Backups

- Back up Postgres regularly.
- In Docker, the volume is `repo_recall_pgdata`.

## Observability

Repo Recall logs:
- indexing stages per repo
- chunk counts
- DB insert/update stats

For production, add:
- structured logs (JSON)
- Prometheus metrics endpoint
- tracing around embedding calls and DB queries

## Incremental indexing

When updating an already-indexed repo, Repo Recall uses **git diffs** (commit-to-commit) to decide which files need reindexing.

If the repo is a local path and the working tree is dirty, Repo Recall also includes staged/unstaged/untracked changes using working-tree diffs.

## Secret redaction

By default, Repo Recall redacts high-signal secrets before storing chunk text and before sending any text to an embedding provider:

```bash
export ENABLE_SECRET_REDACTION=true
```

