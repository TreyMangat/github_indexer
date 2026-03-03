# Roadmap

This roadmap is written for an end-to-end “repo recall” system that ultimately powers:
- **repo selection** for a user prompt
- **PR creation** against the best candidate repo (later)
- Slack bot integration (later)

## Phase 0 — MVP (this repo)

✅ Clone/open repos, discover files, chunk, embed, store into Postgres + pgvector  
✅ Hybrid retrieval (vector + lexical)  
✅ CLI + FastAPI search endpoint  
✅ Control-plane contract + risk gate + CI fanout  

Deliverable: you can index repositories and search for the best repo for a prompt.

## Phase 1 — Indexing quality

- Add language-aware chunkers beyond Python (TS/Go/Rust)
- Add secret redaction / allowlist patterns before embedding
- Add file-level and repo-level summaries (optionally LLM-assisted)
- Add incremental indexing via `git diff` instead of file sha only
- Add repository “capabilities” extraction (frameworks, DBs, tooling, deploy targets)

Deliverable: higher recall and cleaner evidence.

## Phase 2 — Retrieval quality

- Add reranking:
  - light heuristics (path boosts: /src, /docs, etc.)
  - cross-encoder (optional)
  - LLM judge reranking (optional)
- Add query parsing:
  - language/framework detection
  - filters: org/team, language, recency
- Add “best repo for PR” scoring (signals):
  - recent activity
  - tests present
  - CI green
  - owner/team tags

Deliverable: reliable selection of the best repo to modify.

## Phase 3 — Developer UX

- Add `repo-recall explain` to show why a repo was chosen
- Add `repo-recall inspect <repo>` to print summaries and key files
- Add interactive terminal UI (optional)
- Add export formats for downstream agents (JSON schema)

Deliverable: humans trust + debug the system.

## Phase 4 — Slack bot integration (later)

- Provide a stable HTTP API for the Slack bot
- Add auth + rate limiting
- Add “workspace contexts”:
  - user/team preferences
  - pinned repos
  - project scopes

Deliverable: Slack bot can call `/search` and show results.

## Phase 5 — PR agent integration (later)

- Bot generates a change plan + files to modify
- Bot uses repo recall evidence as grounding
- Bot creates a branch and PR
- Preflight policy gate + checks enforce safe merges

Deliverable: end-to-end “prompt → PR” loop.

## Phase 6 — Scale & security

- Connection pooling for Postgres
- Batch embeddings (OpenAI Batch API) for large corpora
- Caching and dedupe for embeddings
- Multi-tenant isolation + RLS
- Observability (metrics, tracing)
- Performance tuning and index maintenance

