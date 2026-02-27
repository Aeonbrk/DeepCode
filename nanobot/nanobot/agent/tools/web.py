"""Web tools: web_search and web_fetch."""

import asyncio
import html
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from nanobot.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks
MAX_FETCH_BYTES = int(os.environ.get("NANOBOT_WEB_MAX_FETCH_BYTES", "3000000"))
_MAX_RETRIES = 2
_BASE_RETRY_DELAY_SECONDS = 0.5
_TRANSIENT_STATUS_CODES = {429, 502, 503, 504}


async def _request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float | httpx.Timeout | None = None,
) -> httpx.Response:
    delay = _BASE_RETRY_DELAY_SECONDS
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.request(
                method, url, headers=headers, params=params, timeout=timeout
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            if (
                e.response.status_code in _TRANSIENT_STATUS_CODES
                and attempt < _MAX_RETRIES
            ):
                await asyncio.sleep(delay)
                delay *= 2
                continue
            raise
        except httpx.RequestError:
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            raise


async def _read_bytes_limited(
    response: httpx.Response, *, max_bytes: int
) -> tuple[bytes, bool]:
    buf = bytearray()
    truncated = False
    async for chunk in response.aiter_bytes():
        remaining = max_bytes - len(buf)
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            buf.extend(chunk[:remaining])
            truncated = True
            break
        buf.extend(chunk)
    return bytes(buf), truncated


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


class WebSearchTool(Tool):
    """Search the web using Brave Search API."""

    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {
                "type": "integer",
                "description": "Results (1-10)",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
    }

    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self.max_results = max_results
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            return "Error: BRAVE_API_KEY not configured"

        try:
            n = min(max(count or self.max_results, 1), 10)
            r = await _request_with_retries(
                self._get_client(),
                "GET",
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": n},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.api_key,
                },
                timeout=10.0,
            )

            results = r.json().get("web", {}).get("results", [])
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Readability."""

    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100},
        },
        "required": ["url"],
    }

    def __init__(self, max_chars: int = 50000):
        self.max_chars = max_chars
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def execute(
        self,
        url: str,
        extract_mode: str = "markdown",
        max_chars: int | None = None,
        **kwargs: Any,
    ) -> str:
        from readability import Document

        # Backward compatibility for callers using camelCase argument names
        if "extractMode" in kwargs and extract_mode == "markdown":
            extract_mode = kwargs["extractMode"]
        if "maxChars" in kwargs and max_chars is None:
            max_chars = kwargs["maxChars"]

        max_chars = max_chars or self.max_chars

        # Validate URL before fetching
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url})

        try:
            client = self._get_client()
            async with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as r:
                r.raise_for_status()

                content_length = r.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > MAX_FETCH_BYTES:
                            return json.dumps(
                                {
                                    "error": "Response too large",
                                    "url": url,
                                    "max_bytes": MAX_FETCH_BYTES,
                                    "content_length": int(content_length),
                                }
                            )
                    except ValueError:
                        pass

                raw_bytes, truncated_bytes = await _read_bytes_limited(
                    r, max_bytes=MAX_FETCH_BYTES
                )

            ctype = r.headers.get("content-type", "")
            raw_text = raw_bytes.decode(r.encoding or "utf-8", errors="replace")

            # JSON
            if "application/json" in ctype:
                if truncated_bytes:
                    return json.dumps(
                        {
                            "error": "JSON response too large",
                            "url": url,
                            "max_bytes": MAX_FETCH_BYTES,
                        }
                    )
                text, extractor = json.dumps(json.loads(raw_text), indent=2), "json"
            # HTML
            elif "text/html" in ctype or raw_text[:256].lower().startswith(("<!doctype", "<html")):
                doc = Document(raw_text)
                content = (
                    self._to_markdown(doc.summary())
                    if extract_mode == "markdown"
                    else _strip_tags(doc.summary())
                )
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                text, extractor = raw_text, "raw"

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps(
                {
                    "url": url,
                    "finalUrl": str(r.url),
                    "status": r.status_code,
                    "extractor": extractor,
                    "truncatedBytes": truncated_bytes,
                    "truncated": truncated,
                    "length": len(text),
                    "text": text,
                }
            )
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})

    def _to_markdown(self, html: str) -> str:
        """Convert HTML to markdown."""
        # Convert links, headings, lists before stripping tags
        text = re.sub(
            r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
            lambda m: f"[{_strip_tags(m[2])}]({m[1]})",
            html,
            flags=re.I,
        )
        text = re.sub(
            r"<h([1-6])[^>]*>([\s\S]*?)</h\1>",
            lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n',
            text,
            flags=re.I,
        )
        text = re.sub(
            r"<li[^>]*>([\s\S]*?)</li>", lambda m: f"\n- {_strip_tags(m[1])}", text, flags=re.I
        )
        text = re.sub(r"</(p|div|section|article)>", "\n\n", text, flags=re.I)
        text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.I)
        return _normalize(_strip_tags(text))
