"""
No-network smoke test for OpenAI base_url endpoint-style configuration.

This repo supports OpenAI-compatible gateways where `openai.base_url` may be set to:
- ".../chat/completions"
- ".../responses"

The official OpenAI SDK expects a root base_url and appends resource paths.

Run:
  uv run python tools/smoke_openai_base_url_compat.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from openai import AsyncOpenAI

# Ensure repo root is importable when running as a script (sys.path[0] is /tools).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.openai_compat import get_openai_base_url_info


def _chat_completion_json(model: str, content: str) -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": "cmpl_test",
        "object": "chat.completion",
        "created": now,
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _responses_json(model: str, output_text: str) -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": now,
        "model": model,
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": output_text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _responses_json_without_usage(model: str, output_text: str) -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": "resp_test_no_usage",
        "object": "response",
        "created_at": now,
        "model": model,
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": output_text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
    }


def _responses_json_partial_usage(model: str, output_text: str) -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": "resp_test_partial_usage",
        "object": "response",
        "created_at": now,
        "model": model,
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": output_text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 3,
            "output_tokens": 5,
            # intentionally omit total_tokens to test fallback behavior
        },
    }


async def _assert_chat_endpoint(raw_base_url: str) -> None:
    info = get_openai_base_url_info(raw_base_url)
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        assert request.url.path.endswith("/chat/completions"), request.url.path
        if "?" in raw_base_url:
            assert request.url.query, "expected query parameters to be preserved"
        return httpx.Response(
            200,
            json=_chat_completion_json(model="gpt-5.2", content="ok-chat"),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AsyncOpenAI(
            api_key="sk-test",
            base_url=info.sdk_base_url,
            default_query=info.default_query,
            http_client=http_client,
        )
        completion = await client.chat.completions.create(
            model="gpt-5.2",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=16,
        )

    print(f"raw_base_url={raw_base_url}")
    print(f"  sdk_base_url={info.sdk_base_url}")
    print(f"  called={seen.get('url')}")
    print(f"  content={completion.choices[0].message.content!r}")


async def _assert_responses_endpoint(raw_base_url: str) -> None:
    info = get_openai_base_url_info(raw_base_url)
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        assert request.url.path.endswith("/responses"), request.url.path
        if "?" in raw_base_url:
            assert request.url.query, "expected query parameters to be preserved"
        return httpx.Response(
            200,
            json=_responses_json(model="gpt-5.2", output_text="ok-responses"),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AsyncOpenAI(
            api_key="sk-test",
            base_url=info.sdk_base_url,
            default_query=info.default_query,
            http_client=http_client,
        )
        resp = await client.responses.create(
            model="gpt-5.2",
            input=[{"type": "message", "role": "user", "content": "hi"}],
            max_output_tokens=16,
        )

    print(f"raw_base_url={raw_base_url}")
    print(f"  sdk_base_url={info.sdk_base_url}")
    print(f"  called={seen.get('url')}")
    print(f"  output_text={resp.output_text!r}")


async def _assert_mcp_agent_responses_bridge(raw_base_url: str) -> None:
    """
    Validate the mcp-agent patch can call a `/responses` gateway but returns a
    ChatCompletions-shaped object to the upstream loop.
    """
    from mcp_agent.config import OpenAISettings
    from mcp_agent.workflows.llm.augmented_llm_openai import (
        OpenAICompletionTasks,
        RequestCompletionRequest,
    )

    from utils.mcp_agent_compat import (
        patch_mcp_agent_openai_base_url_routing,
        patch_mcp_agent_openai_reasoning_effort,
    )

    patch_mcp_agent_openai_reasoning_effort()
    patch_mcp_agent_openai_base_url_routing()

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        assert request.url.path.endswith("/responses"), request.url.path
        body = json.loads(request.content.decode("utf-8") or "{}")
        assert body.get("stop") == ["END"], body
        assert body.get("trace_id") == "t-123", body
        text = body.get("text") or {}
        fmt = (text.get("format") if isinstance(text, dict) else None) or {}
        assert fmt.get("type") == "json_schema", fmt
        assert fmt.get("name") == "TestSchema", fmt
        return httpx.Response(
            200,
            json=_responses_json(model="gpt-5.2", output_text="ok-bridge"),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        cfg = OpenAISettings(api_key="sk-test", base_url=raw_base_url)
        cfg.http_client = http_client  # type: ignore[attr-defined]

        assert getattr(OpenAICompletionTasks.request_completion_task, "is_workflow_task", False)

        request = RequestCompletionRequest(
            config=cfg,
            payload={
                "model": "gpt-5.2",
                "messages": [{"role": "user", "content": "hi"}],
                "max_completion_tokens": 16,
                "reasoning_effort": "xhigh",
                "stop": ["END"],
                "trace_id": "t-123",
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "TestSchema",
                        "schema": {
                            "type": "object",
                            "properties": {"ok": {"type": "boolean"}},
                            "required": ["ok"],
                            "additionalProperties": False,
                        },
                        "strict": True,
                    },
                },
            },
        )
        completion = await OpenAICompletionTasks.request_completion_task(request)

    print(f"raw_base_url={raw_base_url}")
    print(f"  called={seen.get('url')}")
    print(f"  bridged_content={completion.choices[0].message.content!r}")


async def _assert_mcp_agent_responses_bridge_without_usage(raw_base_url: str) -> None:
    """
    Validate bridge behavior when gateway omits `usage`.
    """
    from mcp_agent.config import OpenAISettings
    from mcp_agent.workflows.llm.augmented_llm_openai import (
        OpenAICompletionTasks,
        RequestCompletionRequest,
    )

    from utils.mcp_agent_compat import (
        patch_mcp_agent_openai_base_url_routing,
        patch_mcp_agent_openai_reasoning_effort,
    )

    patch_mcp_agent_openai_reasoning_effort()
    patch_mcp_agent_openai_base_url_routing()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses"), request.url.path
        return httpx.Response(
            200,
            json=_responses_json_without_usage(model="gpt-5.2", output_text="ok-no-usage"),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        cfg = OpenAISettings(api_key="sk-test", base_url=raw_base_url)
        cfg.http_client = http_client  # type: ignore[attr-defined]

        request = RequestCompletionRequest(
            config=cfg,
            payload={
                "model": "gpt-5.2",
                "messages": [{"role": "user", "content": "hi"}],
                "max_completion_tokens": 16,
                "reasoning_effort": "xhigh",
            },
        )
        completion = await OpenAICompletionTasks.request_completion_task(request)

    assert completion.usage is not None
    assert completion.usage.prompt_tokens == 0
    assert completion.usage.completion_tokens == 0
    assert completion.usage.total_tokens == 0
    print("responses bridge without usage: usage normalized to zeros")


async def _assert_mcp_agent_responses_bridge_partial_usage(raw_base_url: str) -> None:
    """
    Validate bridge behavior when gateway returns partial usage metadata.
    """
    from mcp_agent.config import OpenAISettings
    from mcp_agent.workflows.llm.augmented_llm_openai import (
        OpenAICompletionTasks,
        RequestCompletionRequest,
    )

    from utils.mcp_agent_compat import (
        patch_mcp_agent_openai_base_url_routing,
        patch_mcp_agent_openai_reasoning_effort,
    )

    patch_mcp_agent_openai_reasoning_effort()
    patch_mcp_agent_openai_base_url_routing()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses"), request.url.path
        return httpx.Response(
            200,
            json=_responses_json_partial_usage(
                model="gpt-5.2", output_text="ok-partial-usage"
            ),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        cfg = OpenAISettings(api_key="sk-test", base_url=raw_base_url)
        cfg.http_client = http_client  # type: ignore[attr-defined]

        request = RequestCompletionRequest(
            config=cfg,
            payload={
                "model": "gpt-5.2",
                "messages": [{"role": "user", "content": "hi"}],
                "max_completion_tokens": 16,
                "reasoning_effort": "xhigh",
            },
        )
        completion = await OpenAICompletionTasks.request_completion_task(request)

    assert completion.usage is not None
    assert completion.usage.prompt_tokens == 3
    assert completion.usage.completion_tokens == 5
    assert completion.usage.total_tokens == 8
    print("responses bridge partial usage: total_tokens derived correctly")


async def main() -> None:
    await _assert_chat_endpoint("https://example.com/codex/v1/chat/completions")
    await _assert_chat_endpoint(
        "https://example.com/codex/v1/chat/completions?api-version=2024-10-01"
    )
    await _assert_responses_endpoint("https://example.com/codex/v1/responses")
    await _assert_responses_endpoint(
        "https://example.com/codex/v1/responses?api-version=2024-10-01"
    )
    await _assert_mcp_agent_responses_bridge("https://example.com/codex/v1/responses")
    await _assert_mcp_agent_responses_bridge_without_usage(
        "https://example.com/codex/v1/responses"
    )
    await _assert_mcp_agent_responses_bridge_partial_usage(
        "https://example.com/codex/v1/responses"
    )


if __name__ == "__main__":
    asyncio.run(main())
