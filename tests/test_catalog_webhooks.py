from __future__ import annotations

import hashlib
import hmac

from repo_recall.catalog.webhooks import verify_github_webhook_signature


def test_webhook_signature_valid() -> None:
    body = b'{"event":"push"}'
    secret = "super-secret"
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    sig = f"sha256={digest}"
    assert verify_github_webhook_signature(body=body, secret=secret, signature_header=sig)


def test_webhook_signature_invalid() -> None:
    body = b"{}"
    assert not verify_github_webhook_signature(
        body=body,
        secret="super-secret",
        signature_header="sha256=wrong",
    )


def test_webhook_signature_dev_mode_no_secret() -> None:
    assert verify_github_webhook_signature(body=b"{}", secret=None, signature_header=None)
