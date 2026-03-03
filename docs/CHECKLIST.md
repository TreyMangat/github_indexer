# End-to-end checklist

Use this as the “done means done” checklist for a production rollout.

## Repo ingestion

- [ ] Support local paths and git URLs
- [ ] Repo cache directory configured and writable
- [ ] Fetch/pull behavior defined for remote repos
- [ ] Handle auth (SSH keys / GitHub tokens) for private repos
- [ ] Record source + source_ref uniquely in DB

## File discovery & extraction

- [ ] Respect `.gitignore`
- [ ] Exclude common build artifacts (node_modules, dist, build, etc.)
- [ ] Skip binary files reliably
- [ ] Max file size cutoff configurable
- [ ] Key files detected (README, manifests, CI, contract)

## Chunking

- [ ] Language-agnostic line chunking with overlap
- [ ] Markdown heading chunking
- [ ] Python AST chunking for top-level defs
- [ ] Chunk metadata stored (file path, line ranges, type)

## Embeddings

- [ ] Embedding provider interface (pluggable)
- [ ] OpenAI embeddings implementation with retries and batching
- [ ] Newline normalization before embedding
- [ ] Handle embedding failures (degrade to lexical-only)

## Storage (Postgres + pgvector)

- [ ] Schema created idempotently
- [ ] Repos/files/chunks tables with correct constraints
- [ ] Full-text search index created (GIN on tsvector)
- [ ] Vector indexes created (ivfflat/hnsw)
- [ ] Prune strategy (deleted files) defined

## Retrieval

- [ ] Vector search query implemented
- [ ] Lexical search query implemented
- [ ] Merge + normalize + score across modalities
- [ ] Aggregate chunk hits into repo results
- [ ] Return evidence snippets for justification

## Interfaces

- [ ] CLI for init/index/update/search/serve
- [ ] FastAPI `/search` endpoint (with optional auth token)
- [ ] Health endpoint

## CI / control plane

- [ ] Machine-readable contract present (`control/contract.yml`)
- [ ] Preflight risk policy gate runs on PRs
- [ ] Conditional fanout checks (lint/typecheck/tests/security)
- [ ] Docs drift rules enforced

## Security & privacy

- [ ] Secret redaction before embedding (recommended)
- [ ] Sensitive paths excluded (e.g., `.env`, keys, vault dirs)
- [ ] DB protected (network ACLs, encryption at rest, backups)
- [ ] API protected (auth token, rate limiting)

## Ops

- [ ] Backups configured
- [ ] Monitoring/logging configured
- [ ] Runbook for reindexing and index maintenance
- [ ] Cost controls (batching, caching, limits)

