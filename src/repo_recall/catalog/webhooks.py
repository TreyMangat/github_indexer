from __future__ import annotations

import hashlib
import hmac
from typing import Optional


def verify_github_webhook_signature(
    *,
    body: bytes,
    secret: Optional[str],
    signature_header: Optional[str],
) -> bool:
    if not secret:
        # Explicitly allow unsigned mode for local dev.
        return True
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.strip())
