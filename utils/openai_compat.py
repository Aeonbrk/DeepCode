"""
Helpers for OpenAI-compatible gateways.

Some OpenAI-compatible gateways expose *endpoint* URLs like:
- https://<host>/.../responses
- https://<host>/.../chat/completions

The official OpenAI Python SDK expects `base_url` to be an API *root* (e.g. https://api.openai.com/v1)
and will append resource paths like `/chat/completions` or `/responses`.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit, urlunsplit

from dataclasses import dataclass
from enum import Enum


class OpenAIEndpointHint(str, Enum):
    ROOT = "root"
    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"


@dataclass(frozen=True)
class OpenAIBaseURLInfo:
    raw: str | None
    sdk_base_url: str | None
    endpoint_hint: OpenAIEndpointHint
    default_query: dict[str, object] | None


def _parse_default_query(query: str) -> dict[str, object] | None:
    if not query:
        return None
    parsed = parse_qs(query, keep_blank_values=True)
    if not parsed:
        return None
    out: dict[str, object] = {}
    for key, values in parsed.items():
        if not values:
            continue
        out[key] = values[0] if len(values) == 1 else values
    return out or None


def get_openai_base_url_info(base_url: str | None) -> OpenAIBaseURLInfo:
    """
    Return a normalized SDK base_url plus a hint about which endpoint was supplied.

    Examples:
    - ".../v1/chat/completions" -> sdk_base_url ".../v1", hint CHAT_COMPLETIONS
    - ".../v1/responses"        -> sdk_base_url ".../v1", hint RESPONSES
    - ".../api/v1"              -> sdk_base_url ".../api/v1", hint ROOT
    """
    if base_url is None:
        return OpenAIBaseURLInfo(
            raw=None,
            sdk_base_url=None,
            endpoint_hint=OpenAIEndpointHint.ROOT,
            default_query=None,
        )

    raw = base_url.strip()
    if not raw:
        return OpenAIBaseURLInfo(
            raw=base_url,
            sdk_base_url=None,
            endpoint_hint=OpenAIEndpointHint.ROOT,
            default_query=None,
        )

    # Prefer structured URL parsing so query strings don't break endpoint detection.
    # Example: ".../responses?api-version=..." should still be treated as RESPONSES.
    try:
        parts = urlsplit(raw)
    except Exception:
        parts = None

    if parts and parts.scheme and parts.netloc:
        default_query = _parse_default_query(parts.query)
        candidate_path = (parts.path or "").rstrip("/")

        suffixes: list[tuple[str, OpenAIEndpointHint]] = [
            ("/chat/completions", OpenAIEndpointHint.CHAT_COMPLETIONS),
            ("/responses", OpenAIEndpointHint.RESPONSES),
        ]

        for suffix, hint in suffixes:
            if candidate_path.endswith(suffix):
                root_path = candidate_path[: -len(suffix)].rstrip("/")
                sdk_base_url = urlunsplit(
                    (parts.scheme, parts.netloc, root_path, "", "")
                ).rstrip("/")
                return OpenAIBaseURLInfo(
                    raw=raw,
                    sdk_base_url=sdk_base_url or None,
                    endpoint_hint=hint,
                    default_query=default_query,
                )

        sdk_base_url = urlunsplit(
            (parts.scheme, parts.netloc, candidate_path, "", "")
        ).rstrip("/")
        return OpenAIBaseURLInfo(
            raw=raw,
            sdk_base_url=sdk_base_url or None,
            endpoint_hint=OpenAIEndpointHint.ROOT,
            default_query=default_query,
        )

    # Fallback: plain string handling (best-effort; cannot preserve query reliably).
    default_query = None
    if "?" in raw:
        try:
            default_query = _parse_default_query(raw.split("?", 1)[1].split("#", 1)[0])
        except Exception:
            default_query = None
    candidate = raw.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    suffixes: list[tuple[str, OpenAIEndpointHint]] = [
        ("/chat/completions", OpenAIEndpointHint.CHAT_COMPLETIONS),
        ("/responses", OpenAIEndpointHint.RESPONSES),
    ]
    for suffix, hint in suffixes:
        if candidate.endswith(suffix):
            root = candidate[: -len(suffix)].rstrip("/")
            return OpenAIBaseURLInfo(
                raw=raw,
                sdk_base_url=root or None,
                endpoint_hint=hint,
                default_query=default_query,
            )

    return OpenAIBaseURLInfo(
        raw=raw,
        sdk_base_url=candidate or None,
        endpoint_hint=OpenAIEndpointHint.ROOT,
        default_query=default_query,
    )


def normalize_openai_base_url_for_sdk(base_url: str | None) -> str | None:
    """Convenience wrapper returning only the SDK base_url."""
    return get_openai_base_url_info(base_url).sdk_base_url
