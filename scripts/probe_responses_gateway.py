#!/usr/bin/env python3
"""
Probe an OpenAI-compatible gateway for Responses API capabilities.

This script is intentionally small and dependency-light so you can run:

  python scripts/probe_responses_gateway.py

It tests:
1) responses.create (basic)
2) responses.create(previous_response_id=...) (continuation)
3) responses.retrieve(id) (polling/retrieve)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict, Optional


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


async def _probe(
    *,
    api_key: str,
    base_url: Optional[str],
    default_query: Optional[Dict[str, object]],
    model: str,
) -> Dict[str, Any]:
    from openai import AsyncOpenAI
    from utils.mcp_agent_compat import _normalize_responses_result

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        default_query=default_query,
    )

    result: Dict[str, Any] = {
        "base_url": base_url,
        "model": model,
        "create_ok": False,
        "create_id": None,
        "continuation_ok": False,
        "continuation_error": None,
        "retrieve_ok": False,
        "retrieve_error": None,
    }

    resp1 = await client.responses.create(
        model=model,
        input=[{"type": "message", "role": "user", "content": "probe: create"}],
        max_output_tokens=20,
    )
    norm1 = _normalize_responses_result(resp1)
    resp1_id = _get_field(norm1, "id")
    result["create_ok"] = True
    result["create_id"] = resp1_id

    if resp1_id:
        try:
            resp2 = await client.responses.create(
                model=model,
                previous_response_id=resp1_id,
                input=[
                    {"type": "message", "role": "user", "content": "probe: continuation"}
                ],
                max_output_tokens=20,
            )
            _ = _normalize_responses_result(resp2)
            result["continuation_ok"] = True
        except Exception as e:  # noqa: BLE001
            result["continuation_ok"] = False
            result["continuation_error"] = str(e)

        try:
            resp3 = await client.responses.retrieve(resp1_id)
            _ = _normalize_responses_result(resp3)
            result["retrieve_ok"] = True
        except Exception as e:  # noqa: BLE001
            result["retrieve_ok"] = False
            result["retrieve_error"] = str(e)

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--secrets",
        default="mcp_agent.secrets.yaml",
        help="Path to secrets YAML (default: mcp_agent.secrets.yaml)",
    )
    parser.add_argument("--model", default=None, help="Override model name")
    parser.add_argument(
        "--base-url-raw",
        default=None,
        help="Override OpenAI base_url_raw (endpoint-style allowed, e.g. .../responses)",
    )
    parser.add_argument("--api-key", default=None, help="Override API key")
    args = parser.parse_args()

    from utils.llm_utils import load_api_config
    from utils.openai_compat import get_openai_base_url_info

    cfg = load_api_config(args.secrets)
    openai_cfg = cfg.get("openai") if isinstance(cfg, dict) else {}
    openai_cfg = openai_cfg if isinstance(openai_cfg, dict) else {}

    api_key = (
        (args.api_key or "").strip()
        or (openai_cfg.get("api_key") or "").strip()
        or (os.environ.get("OPENAI_API_KEY") or "").strip()
    )
    if not api_key:
        raise SystemExit(
            "Missing OpenAI API key. Set openai.api_key in secrets, pass --api-key, or export OPENAI_API_KEY."
        )

    base_url = openai_cfg.get("base_url")
    base_url_raw = args.base_url_raw or openai_cfg.get("base_url_raw") or base_url
    default_query = openai_cfg.get("default_query")
    info = get_openai_base_url_info(base_url_raw)

    model = args.model or openai_cfg.get("default_model") or "gpt-5.2"

    # load_api_config already normalizes base_url for the official SDK; keep that.
    sdk_base_url = base_url or info.sdk_base_url

    out = {
        "input": {
            "secrets": args.secrets,
            "base_url_raw": base_url_raw,
            "sdk_base_url": sdk_base_url,
            "endpoint_hint": info.endpoint_hint.value,
            "default_query": default_query,
            "model": model,
        }
    }

    probe = asyncio.run(
        _probe(
            api_key=api_key,
            base_url=sdk_base_url,
            default_query=default_query if isinstance(default_query, dict) else None,
            model=model,
        )
    )
    out["probe"] = probe
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
