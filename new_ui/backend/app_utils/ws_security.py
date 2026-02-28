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
    allow_missing_origin: bool = False,
) -> bool:
    """
    Best-effort Origin allowlist.

    Notes:
    - Browsers always send Origin. Non-browser clients may not.
    - Missing Origin is denied by default.
    - Set `allow_missing_origin=True` only for trusted internal clients.
    """
    _ = debug, env
    if origin is None:
        return allow_missing_origin
    return origin in allowed_origins
