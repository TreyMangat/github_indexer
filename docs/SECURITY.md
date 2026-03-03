# Security

## Secrets

- Never commit API keys.
- `.env` is ignored by git.
- CI should use GitHub Secrets for `OPENAI_API_KEY` (if used).

## Indexing private repos

If indexing private repos:
- Store the Postgres volume on encrypted disk.
- Restrict network access to the DB.
- Consider row-level security (RLS) if you have multiple users/tenants.

## Redaction (recommended)

Repo Recall includes a best-effort **secret redaction step** to reduce the chance of leaking secrets into:

- the local index database (chunk text)
- external embedding providers (if enabled)

It is enabled by default:

```bash
export ENABLE_SECRET_REDACTION=true
```

You can disable it only if you understand the risk:

```bash
export ENABLE_SECRET_REDACTION=false
```

What gets redacted (best effort, high-signal patterns):

- PEM private key blocks
- Common API token formats (OpenAI, GitHub, Slack)
- JWTs
- Bearer tokens
- Basic-auth credentials embedded in URLs (e.g. `postgresql://user:pass@...`)
- Config-style key/value assignments with sensitive keys (e.g. `*_PASSWORD=...`)

Additionally, the indexer excludes common secret file patterns by default (e.g. `.env`, `.aws/`, `*.pem`).

