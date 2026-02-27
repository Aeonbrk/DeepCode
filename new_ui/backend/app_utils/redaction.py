"""
Redaction helpers for UI-facing logs/errors.

Goal: reduce accidental sensitive data exposure in WebSocket streams and API
error messages. This is not a substitute for authentication and network
boundary controls.
"""

from __future__ import annotations

import re


_REDACTION_RULES: list[tuple[re.Pattern[str], str]] = [
    # Explicit header forms
    (re.compile(r"(?i)\bAuthorization:\s*Bearer\s+[^\s]+"), "Authorization: Bearer ***"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_\.=:+/]{10,}"), "Bearer ***"),
    # OpenAI-style keys (including project keys)
    (re.compile(r"\bsk-proj-[A-Za-z0-9]{10,}\b"), "sk-proj-***"),
    (re.compile(r"\bsk-[A-Za-z0-9]{10,}\b"), "sk-***"),
    # Anthropic-style keys
    (re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{10,}\b"), "sk-ant-***"),
    # Google API keys
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{10,}\b"), "AIza***"),
    # Common env var assignments (keep the key name, redact the value)
    (
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:API_KEY|ACCESS_KEY|SECRET_KEY|TOKEN|PASSWORD)[A-Z0-9_]*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s]+)"
        ),
        r"\1=***",
    ),
    # Private key material
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "-----BEGIN PRIVATE KEY-----***-----END PRIVATE KEY-----",
    ),
]


def redact_text(value: str | None) -> str:
    """Best-effort sensitive string redaction for UI-visible messages."""
    if not value:
        return ""

    redacted = value
    for pattern, replacement in _REDACTION_RULES:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_payload(value):
    """Recursively redact strings in JSON-like payloads."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_payload(item) for key, item in value.items()}
    return value
