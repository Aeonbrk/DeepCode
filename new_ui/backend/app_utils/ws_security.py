"""
WebSocket security helpers.

This backend is often run locally without auth. We still want to reduce
accidental data leakage when the server is bound to non-local interfaces.
"""

from __future__ import annotations


def is_ws_origin_allowed(
    origin: str | None,
    *,
    allowed_origins: list[str],
    debug: bool,
    env: str,
) -> bool:
    """
    Best-effort Origin allowlist.

    Notes:
    - Browsers always send Origin. Non-browser clients may not.
    - In Docker mode, treat missing Origin as disallowed to reduce accidental exposure.
    """
    if origin is None:
        return bool(debug) and env != "docker"
    return origin in allowed_origins

