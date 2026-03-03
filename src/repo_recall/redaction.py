from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionStats:
    """Statistics about redactions performed."""

    replacements: int = 0


# --- High-signal secret patterns ---

# Private key blocks (multi-line)
_PEM_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.MULTILINE,
)

# Common API token formats
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
_GITHUB_TOKEN = re.compile(r"\b(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_SLACK_TOKEN = re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")
_AWS_ACCESS_KEY_ID = re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")
_GOOGLE_API_KEY = re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")

# JWT (very common)
_JWT = re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b")

# Bearer <token>
_BEARER = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9\-_.=]{20,})")

# URLs that embed basic auth, e.g. postgres://user:pass@host/db
_URL_BASIC_AUTH = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s]+)@")


# Config-style key-value redaction
_ENV_LINE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Z][A-Z0-9_]{1,120})\s*=\s*(?P<val>.*)$")
_YAML_LINE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_\-]{1,120})\s*:\s*(?P<val>.+)$"
)
_JSON_KV = re.compile(
    r'("(?P<key>[^"]*(?:password|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)[^"]*)"\s*:\s*)"(?P<val>[^"]*)"',
    re.IGNORECASE,
)

_SENSITIVE_KEYWORDS = (
    "PASSWORD",
    "PASS",
    "SECRET",
    "TOKEN",
    "API_KEY",
    "APIKEY",
    "ACCESS_KEY",
    "PRIVATE_KEY",
    "CLIENT_SECRET",
)


def _is_sensitive_key(key: str) -> bool:
    k = key.upper()
    return any(word in k for word in _SENSITIVE_KEYWORDS)


def _looks_like_secret_value(value: str) -> bool:
    v = value.strip().strip("'\"")
    if not v:
        return False
    if "[REDACTED" in v:
        return False
    if v.lower() in {"true", "false", "null", "none"}:
        return False
    # Avoid redacting obvious placeholders.
    if any(tok in v.lower() for tok in {"changeme", "your_", "<", ">"}):
        return False
    # Heuristic: long-ish, no spaces.
    if len(v) < 12:
        return False
    if " " in v:
        return False
    return True


def redact_secrets(text: str) -> tuple[str, RedactionStats]:
    """Redact secrets from text.

    This is intentionally conservative: it targets high-signal token formats and
    config-style assignments.
    """

    if not text:
        return text, RedactionStats(replacements=0)

    replacements = 0

    def _sub(pat: re.Pattern[str], repl: str, s: str) -> str:
        nonlocal replacements
        out, n = pat.subn(repl, s)
        replacements += n
        return out

    # 1) Multi-line private key blocks
    text = _sub(_PEM_PRIVATE_KEY_BLOCK, "[REDACTED_PEM_PRIVATE_KEY]", text)

    # 2) High-signal token formats
    text = _sub(_OPENAI_KEY, "[REDACTED_OPENAI_KEY]", text)
    text = _sub(_GITHUB_TOKEN, "[REDACTED_GITHUB_TOKEN]", text)
    text = _sub(_SLACK_TOKEN, "[REDACTED_SLACK_TOKEN]", text)
    text = _sub(_AWS_ACCESS_KEY_ID, "[REDACTED_AWS_ACCESS_KEY_ID]", text)
    text = _sub(_GOOGLE_API_KEY, "[REDACTED_GOOGLE_API_KEY]", text)
    text = _sub(_JWT, "[REDACTED_JWT]", text)
    text = _sub(_BEARER, "Bearer [REDACTED_BEARER_TOKEN]", text)
    text = _sub(_URL_BASIC_AUTH, r"\1\2:[REDACTED]@", text)

    # 3) JSON key-value redaction (password/token/etc)
    def _json_repl(m: re.Match[str]) -> str:
        return f'{m.group(1)}"[REDACTED]"'

    new_text, n_json = _JSON_KV.subn(_json_repl, text)
    replacements += n_json
    text = new_text

    # 4) Line-wise env / yaml redaction (best effort)
    lines = text.splitlines(keepends=True)
    out_lines: list[str] = []
    for line in lines:
        # ENV-style: only uppercase keys to avoid clobbering code (`token = ...`).
        m_env = _ENV_LINE.match(line.rstrip("\n"))
        if m_env:
            key = m_env.group("key")
            val = m_env.group("val")
            if _is_sensitive_key(key) and _looks_like_secret_value(val):
                # Preserve inline comments if present.
                val_part, sep, comment = val.partition("#")
                redacted = "[REDACTED]"
                if sep:
                    out_lines.append(f"{m_env.group('indent')}{key}={redacted} {sep}{comment}\n")
                else:
                    out_lines.append(f"{m_env.group('indent')}{key}={redacted}\n")
                replacements += 1
                continue

        # YAML-style: case-insensitive sensitive keys, but only redact if the value
        # looks like a real secret.
        m_yaml = _YAML_LINE.match(line.rstrip("\n"))
        if m_yaml:
            key = m_yaml.group("key")
            val = m_yaml.group("val")
            if _is_sensitive_key(key) and _looks_like_secret_value(val):
                out_lines.append(f"{m_yaml.group('indent')}{key}: [REDACTED]\n")
                replacements += 1
                continue

        out_lines.append(line)

    return "".join(out_lines), RedactionStats(replacements=replacements)
