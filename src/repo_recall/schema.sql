-- Repo Recall schema
-- Requires pgvector extension (extension name: vector)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS repos (
  id UUID PRIMARY KEY,
  source TEXT NOT NULL,            -- e.g. 'local' or 'git'
  source_ref TEXT NOT NULL,        -- local path or git URL
  name TEXT NOT NULL,
  default_branch TEXT,
  indexed_commit_sha TEXT,
  last_commit_at TIMESTAMPTZ,
  indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  languages JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary TEXT,
  embedding vector(1536),
  UNIQUE (source, source_ref)
);

CREATE TABLE IF NOT EXISTS files (
  id UUID PRIMARY KEY,
  repo_id UUID NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  language TEXT,
  is_key_file BOOLEAN NOT NULL DEFAULT false,
  size_bytes BIGINT NOT NULL,
  sha256 TEXT NOT NULL,
  indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  summary TEXT,
  embedding vector(1536),
  UNIQUE (repo_id, path)
);

CREATE TABLE IF NOT EXISTS chunks (
  id UUID PRIMARY KEY,
  repo_id UUID NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  file_id UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  start_line INT,
  end_line INT,
  content_type TEXT NOT NULL, -- 'code' | 'doc' | 'config'
  text TEXT NOT NULL,
  text_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED,
  embedding vector(1536),
  UNIQUE (file_id, chunk_index)
);

-- Full-text search index
CREATE INDEX IF NOT EXISTS chunks_text_tsv_idx ON chunks USING GIN (text_tsv);

-- Vector indexes (approx NN)
-- Note: for best performance, tune `lists` and `ivfflat.probes` for your dataset size.
CREATE INDEX IF NOT EXISTS chunks_embedding_ivfflat_idx
  ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS repos_embedding_ivfflat_idx
  ON repos USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

CREATE INDEX IF NOT EXISTS files_embedding_ivfflat_idx
  ON files USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- Index runs (for UI-triggered indexing jobs)
CREATE TABLE IF NOT EXISTS index_runs (
  id UUID PRIMARY KEY,
  repo_id UUID REFERENCES repos(id) ON DELETE SET NULL,
  repo_ref TEXT NOT NULL,
  operation TEXT NOT NULL,          -- 'index' | 'update'
  status TEXT NOT NULL,             -- 'queued' | 'running' | 'succeeded' | 'failed'
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  error TEXT
);

CREATE INDEX IF NOT EXISTS index_runs_created_at_idx ON index_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS index_runs_repo_id_idx ON index_runs (repo_id);

-- ---------------------------------------------------------------------------
-- GitHub repo/branch catalog (separate schema, shared Postgres instance)
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS indexer_catalog;

CREATE TABLE IF NOT EXISTS indexer_catalog.github_repositories (
  id UUID PRIMARY KEY,
  github_repo_id BIGINT NOT NULL UNIQUE,
  owner TEXT NOT NULL,
  name TEXT NOT NULL,
  full_name TEXT NOT NULL UNIQUE,
  private BOOLEAN NOT NULL DEFAULT true,
  archived BOOLEAN NOT NULL DEFAULT false,
  disabled BOOLEAN NOT NULL DEFAULT false,
  default_branch TEXT,
  pushed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ,
  last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_token_owner TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS github_repositories_owner_idx
  ON indexer_catalog.github_repositories (owner);
CREATE INDEX IF NOT EXISTS github_repositories_updated_at_idx
  ON indexer_catalog.github_repositories (updated_at DESC);

CREATE TABLE IF NOT EXISTS indexer_catalog.github_branches (
  id UUID PRIMARY KEY,
  repo_id UUID NOT NULL REFERENCES indexer_catalog.github_repositories(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  head_sha TEXT,
  is_default BOOLEAN NOT NULL DEFAULT false,
  protected BOOLEAN NOT NULL DEFAULT false,
  last_commit_at TIMESTAMPTZ,
  last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_generated BOOLEAN NOT NULL DEFAULT false,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (repo_id, name)
);

CREATE INDEX IF NOT EXISTS github_branches_repo_idx
  ON indexer_catalog.github_branches (repo_id);
CREATE INDEX IF NOT EXISTS github_branches_recent_idx
  ON indexer_catalog.github_branches (last_commit_at DESC);

CREATE TABLE IF NOT EXISTS indexer_catalog.github_actor_repo_access (
  id UUID PRIMARY KEY,
  actor_id TEXT NOT NULL,
  repo_id UUID NOT NULL REFERENCES indexer_catalog.github_repositories(id) ON DELETE CASCADE,
  permission TEXT NOT NULL DEFAULT 'read',
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (actor_id, repo_id)
);

CREATE INDEX IF NOT EXISTS github_actor_repo_access_actor_idx
  ON indexer_catalog.github_actor_repo_access (actor_id);
CREATE INDEX IF NOT EXISTS github_actor_repo_access_last_seen_idx
  ON indexer_catalog.github_actor_repo_access (last_seen_at DESC);

CREATE TABLE IF NOT EXISTS indexer_catalog.github_index_runs (
  id UUID PRIMARY KEY,
  actor_id TEXT,
  scope TEXT NOT NULL, -- full | incremental | webhook
  repo_id UUID REFERENCES indexer_catalog.github_repositories(id) ON DELETE SET NULL,
  status TEXT NOT NULL, -- queued | running | succeeded | failed
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  error TEXT,
  metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS github_index_runs_created_idx
  ON indexer_catalog.github_index_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS github_index_runs_actor_idx
  ON indexer_catalog.github_index_runs (actor_id);

CREATE TABLE IF NOT EXISTS indexer_catalog.github_webhook_deliveries (
  id UUID PRIMARY KEY,
  delivery_id TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ,
  status TEXT NOT NULL, -- received | processed | duplicate | failed
  error TEXT,
  payload_json JSONB
);

CREATE INDEX IF NOT EXISTS github_webhook_deliveries_received_idx
  ON indexer_catalog.github_webhook_deliveries (received_at DESC);

CREATE TABLE IF NOT EXISTS indexer_catalog.github_sync_cursors (
  id UUID PRIMARY KEY,
  actor_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  org TEXT,
  cursor_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  etag TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (actor_id, scope, org)
);

CREATE INDEX IF NOT EXISTS github_sync_cursors_actor_idx
  ON indexer_catalog.github_sync_cursors (actor_id);
