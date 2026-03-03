from __future__ import annotations

from repo_recall.redaction import redact_secrets


def test_redacts_pem_private_key_block() -> None:
    text = "hello\n-----BEGIN RSA PRIVATE KEY-----\nabc\ndef\n-----END RSA PRIVATE KEY-----\nbye\n"

    out, stats = redact_secrets(text)
    assert "[REDACTED_PEM_PRIVATE_KEY]" in out
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert stats.replacements >= 1


def test_redacts_common_tokens() -> None:
    slack_token = "-".join(
        [
            "xox" + "b",
            "123456789012",
            "123456789012",
            "abcdefghijklmnopqrstuvwx",
        ]
    )
    text = f"slack={slack_token}"
    out, _ = redact_secrets(text)
    assert "[REDACTED_SLACK_TOKEN]" in out


def test_redacts_sensitive_env_assignments() -> None:
    text = "DATABASE_PASSWORD=supersecretvalue123\n"
    out, _ = redact_secrets(text)
    assert "DATABASE_PASSWORD=[REDACTED]" in out


def test_redacts_basic_auth_in_urls() -> None:
    text = "DATABASE_URL=postgresql://user:passw0rd@localhost:5432/db\n"
    out, _ = redact_secrets(text)
    assert "postgresql://user:[REDACTED]@localhost" in out
