"""
Compatibility shims for third-party dependencies.

This repo uses `mcp-agent` as a dependency. In some versions, `mcp_agent`'s
Pydantic settings restrict `openai.reasoning_effort` to a smaller enum than
OpenAI-compatible gateways support (e.g. `xhigh`).

We patch the relevant Pydantic models at runtime to accept the expanded set
without forking or modifying installed site-packages.
"""

from __future__ import annotations

import json
import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Optional, Literal, Any


_PATCHED_OPENAI_REASONING_EFFORT = False
_PATCHED_OPENAI_BASE_URL_ROUTING = False
_PATCHED_OPENAI_EXECUTOR_RAISE = False


def ensure_current_python_on_path() -> None:
    """
    Ensure child processes launched with `command: python` use the current interpreter.

    DeepCode spawns MCP servers based on `mcp_agent.config.yaml`. Many servers use
    `command: python`, which relies on `PATH` resolution. When the CLI is executed
    via an explicit interpreter path (e.g. `.venv/bin/python cli/main_cli.py`),
    the virtualenv's bin directory is *not* automatically prepended to `PATH`,
    and MCP servers may start under a different Python without required deps.

    We fix this by prepending `dirname(sys.executable)` to `PATH`.
    """
    try:
        bin_dir = os.path.dirname(sys.executable)
        if not bin_dir:
            return
        current = os.environ.get("PATH", "")
        parts = [p for p in current.split(os.pathsep) if p]
        if parts and os.path.normpath(parts[0]) == os.path.normpath(bin_dir):
            return
        os.environ["PATH"] = os.pathsep.join([bin_dir] + parts)
    except Exception:
        # Best-effort only; never break app startup for env hygiene.
        return


def _patch_pydantic_annotation(model_cls: type, field_name: str, annotation: object) -> bool:
    """
    Patch a Pydantic v2 model field annotation in-place and rebuild validators.

    Returns True if any change was applied.
    """
    changed = False

    # Update __annotations__ (Pydantic rebuilds schemas/validators from annotations)
    anns = getattr(model_cls, "__annotations__", None)
    if isinstance(anns, dict):
        if anns.get(field_name) is not annotation:
            anns[field_name] = annotation
            changed = True

    # Update model_fields annotation if present (helps with already-constructed FieldInfo)
    fields = getattr(model_cls, "model_fields", None)
    if isinstance(fields, dict) and field_name in fields:
        field_info = fields[field_name]
        if getattr(field_info, "annotation", None) is not annotation:
            try:
                field_info.annotation = annotation  # type: ignore[attr-defined]
            except Exception:
                # Best-effort: some FieldInfo implementations may forbid mutation.
                pass
            else:
                changed = True

    if changed:
        rebuild = getattr(model_cls, "model_rebuild", None)
        if callable(rebuild):
            rebuild(force=True)

    return changed


def patch_mcp_agent_openai_reasoning_effort() -> None:
    """
    Expand allowed `reasoning_effort` values in `mcp_agent` config models.

    Target:
    - `mcp_agent.config.OpenAISettings.reasoning_effort`
    - `mcp_agent.workflows.llm.augmented_llm.RequestParams.reasoning_effort`

    This is intentionally "pass-through": it enables config validation, but does
    not coerce/downgrade values if the upstream provider rejects them.
    """
    global _PATCHED_OPENAI_REASONING_EFFORT
    if _PATCHED_OPENAI_REASONING_EFFORT:
        return

    try:
        from mcp_agent.config import OpenAISettings
        from mcp_agent.workflows.llm.augmented_llm import RequestParams
    except Exception:
        # mcp_agent isn't installed/available in this runtime.
        return

    ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
    OptionalReasoningEffort = Optional[ReasoningEffort]

    changed_any = False
    changed_any |= _patch_pydantic_annotation(
        OpenAISettings, "reasoning_effort", ReasoningEffort
    )
    changed_any |= _patch_pydantic_annotation(
        RequestParams, "reasoning_effort", OptionalReasoningEffort
    )

    if changed_any:
        _PATCHED_OPENAI_REASONING_EFFORT = True


def patch_mcp_agent_openai_executor_raise_on_error() -> None:
    """
    Ensure OpenAI LLM calls fail loudly instead of returning empty strings.

    `mcp-agent`'s default asyncio executor returns exceptions as values
    (`BaseException`) instead of raising them. In `OpenAIAugmentedLLM.generate`,
    a `BaseException` response causes the loop to `break` and return the partial
    responses list (often empty), which then turns into an empty string via
    `generate_str()` with no actionable error context.

    For DeepCode's workflow we prefer explicit failures: patch each
    `OpenAIAugmentedLLM` instance to raise when `executor.execute()` returns a
    `BaseException`.
    """
    global _PATCHED_OPENAI_EXECUTOR_RAISE
    if _PATCHED_OPENAI_EXECUTOR_RAISE:
        return

    try:
        from mcp_agent.workflows.llm.augmented_llm_openai import OpenAIAugmentedLLM
    except Exception:
        return

    orig_init = OpenAIAugmentedLLM.__init__

    if getattr(orig_init, "_deepcode_executor_raise_patch", False):
        _PATCHED_OPENAI_EXECUTOR_RAISE = True
        return

    def _init_patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        orig_init(self, *args, **kwargs)
        executor = getattr(self, "executor", None)
        if executor is None:
            return

        orig_execute = getattr(executor, "execute", None)
        if not callable(orig_execute):
            return

        # Avoid double-wrapping on the same instance.
        if getattr(orig_execute, "_deepcode_raises_baseexception", False):
            return

        async def _execute_patched(*a, **kw):  # type: ignore[no-untyped-def]
            result = await orig_execute(*a, **kw)
            if isinstance(result, BaseException):
                raise result
            return result

        setattr(_execute_patched, "_deepcode_raises_baseexception", True)
        executor.execute = _execute_patched  # type: ignore[assignment]

    setattr(_init_patched, "_deepcode_executor_raise_patch", True)
    OpenAIAugmentedLLM.__init__ = _init_patched  # type: ignore[method-assign]
    _PATCHED_OPENAI_EXECUTOR_RAISE = True


def _chat_content_to_text(content: Any) -> str:
    """
    Best-effort conversion from Chat Completions `content` to plain text.

    For gateway compatibility we prefer robustness over perfect multimodal fidelity.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    parts.append(part["text"])
                    continue
                # Some parts may embed nested structures (e.g. images). Keep a marker.
                if part.get("type") == "image_url":
                    parts.append("[image]")
                    continue
            parts.append(str(part))
        return "\n".join(p for p in parts if p)
    return str(content)


def _to_plain_json(value: Any) -> Any:
    """
    Best-effort conversion of OpenAI/Pydantic types to plain JSON-compatible objects.

    This is used for `extra_body` passthrough when bridging ChatCompletions -> Responses.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    # Pydantic/OpenAI types usually expose `model_dump()`.
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            value = model_dump()
        except Exception:
            # Fall back to string repr if we can't safely dump.
            return str(value)

    if isinstance(value, Mapping):
        return {str(k): _to_plain_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain_json(v) for v in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_plain_json(v) for v in value]

    return str(value)


def _convert_chat_response_format_to_responses_text_format(
    response_format: Any,
) -> dict | None:
    """
    Convert Chat Completions `response_format` into Responses API `text.format`.

    Chat payload uses:
      { "type": "json_schema", "json_schema": { "name": ..., "schema": ..., "strict": ... } }

    Responses payload uses:
      { "type": "json_schema", "name": ..., "schema": ..., "strict": ... }
    """
    if response_format is None:
        return None

    rf = _to_plain_json(response_format)
    if not isinstance(rf, dict):
        return None

    rf_type = rf.get("type")
    if rf_type == "json_schema":
        js = rf.get("json_schema") or {}
        if not isinstance(js, dict):
            return None
        out: dict[str, Any] = {
            "type": "json_schema",
            "name": js.get("name") or "StructuredOutput",
            "schema": js.get("schema") or {},
        }
        if js.get("description"):
            out["description"] = js["description"]
        if js.get("strict") is not None:
            out["strict"] = js["strict"]
        return out

    # JSON mode (legacy)
    if rf_type == "json_object":
        return {"type": "json_object"}

    # Plain text
    if rf_type == "text":
        return {"type": "text"}

    return None


def _convert_chat_payload_to_responses_payload(chat_payload: dict) -> dict:
    """
    Convert a ChatCompletions-style payload to a Responses API payload.

    This enables OpenAI-compatible gateways exposing `/responses` to work with
    `mcp-agent`'s ChatCompletions-based tool loop.
    """
    model = chat_payload.get("model")
    messages = chat_payload.get("messages") or []

    # Extract system prompt(s) into `instructions`.
    instructions_parts: list[str] = []
    input_items: list[dict] = []

    for msg in messages:
        if not isinstance(msg, dict):
            msg = getattr(msg, "model_dump", lambda **_: dict(msg))()

        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            text = _chat_content_to_text(content)
            if text:
                instructions_parts.append(text)
            continue

        # Assistant tool calls (chat format) -> Responses tool call items.
        tool_calls = msg.get("tool_calls") if role == "assistant" else None
        if tool_calls:
            # Preserve assistant text content if present.
            assistant_text = _chat_content_to_text(content)
            if assistant_text:
                input_items.append(
                    {"type": "message", "role": "assistant", "content": assistant_text}
                )
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    tool_call = getattr(tool_call, "model_dump", lambda **_: dict(tool_call))()
                fn = tool_call.get("function") or {}
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.get("id") or "",
                        "name": fn.get("name") or "",
                        "arguments": fn.get("arguments") or "",
                    }
                )
            continue

        if role == "tool":
            tool_call_id = msg.get("tool_call_id") or ""
            tool_text = _chat_content_to_text(content)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_call_id,
                    "output": tool_text,
                }
            )
            continue

        # Regular user/assistant messages.
        input_items.append(
            {"type": "message", "role": role or "user", "content": _chat_content_to_text(content)}
        )

    tools_in = chat_payload.get("tools") or []
    tools_out: list[dict] = []
    for tool in tools_in:
        if not isinstance(tool, dict):
            tool = getattr(tool, "model_dump", lambda **_: dict(tool))()
        if tool.get("type") != "function":
            continue
        fn = tool.get("function") or {}
        tools_out.append(
            {
                "type": "function",
                "name": fn.get("name") or "",
                "description": fn.get("description"),
                "parameters": _to_plain_json(fn.get("parameters")),
                "strict": None,
            }
        )

    payload: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "instructions": "\n\n".join(instructions_parts) if instructions_parts else None,
        "tools": tools_out if tools_out else None,
    }

    # Token + reasoning controls (map from chat fields).
    max_out = chat_payload.get("max_completion_tokens") or chat_payload.get("max_tokens")
    if max_out is not None:
        payload["max_output_tokens"] = max_out

    reasoning_effort = chat_payload.get("reasoning_effort")
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}

    # Tool behavior parity (when present in the chat payload).
    if chat_payload.get("tool_choice") is not None:
        payload["tool_choice"] = _to_plain_json(chat_payload["tool_choice"])
    if chat_payload.get("parallel_tool_calls") is not None:
        payload["parallel_tool_calls"] = chat_payload["parallel_tool_calls"]

    # Common optional fields.
    if chat_payload.get("temperature") is not None:
        payload["temperature"] = chat_payload["temperature"]
    if chat_payload.get("top_p") is not None:
        payload["top_p"] = chat_payload["top_p"]
    if chat_payload.get("metadata") is not None:
        payload["metadata"] = _to_plain_json(chat_payload["metadata"])
    if chat_payload.get("user") is not None:
        payload["user"] = chat_payload["user"]
    if chat_payload.get("stream") is not None:
        payload["stream"] = chat_payload["stream"]

    # Structured outputs mapping: ChatCompletions `response_format` -> Responses `text.format`.
    text_cfg: dict[str, Any] = {}
    text_format = _convert_chat_response_format_to_responses_text_format(
        chat_payload.get("response_format")
    )
    if text_format is not None:
        text_cfg["format"] = text_format

    # Chat Completions has `verbosity`, Responses expects it under `text`.
    if chat_payload.get("verbosity") is not None:
        text_cfg["verbosity"] = chat_payload["verbosity"]

    if text_cfg:
        payload["text"] = text_cfg

    # Pass through unknown fields via `extra_body` to avoid silently dropping
    # gateway-specific params. This also preserves `stop`, which Responses doesn't
    # model in the official schema but some gateways accept.
    known_keys = {
        "model",
        "messages",
        "tools",
        "user",
        "max_completion_tokens",
        "max_tokens",
        "reasoning_effort",
        "temperature",
        "top_p",
        "metadata",
        "tool_choice",
        "parallel_tool_calls",
        "stream",
        "response_format",
        "verbosity",
        "stop",
    }
    extra_body: dict[str, Any] = {}

    stop = chat_payload.get("stop")
    if stop is not None:
        extra_body["stop"] = _to_plain_json(stop)

    for k, v in chat_payload.items():
        if k in known_keys:
            continue
        extra_body[k] = _to_plain_json(v)

    if extra_body:
        payload["extra_body"] = extra_body

    # Remove Nones to keep the SDK strict signature happy.
    return {k: v for k, v in payload.items() if v is not None}


def _normalize_responses_result(response: Any) -> Any:
    """
    Normalize gateway Responses return value into an object/dict-like payload.

    Some OpenAI-compatible providers return SSE text body even on
    non-streaming `responses.create` calls. In that case the SDK may return
    a raw `str` containing `event:/data:` lines.
    """
    if not isinstance(response, str):
        return response

    completed_response: dict[str, Any] | None = None
    output_text_done_parts: list[str] = []
    output_items: list[dict[str, Any]] = []

    blocks = response.split("\n\n")
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        data_lines = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if not data_lines:
            continue
        data_str = "\n".join(data_lines).strip()
        if not data_str or data_str == "[DONE]":
            continue
        try:
            payload = json.loads(data_str)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        payload_type = payload.get("type")
        if payload_type == "response.completed":
            candidate = payload.get("response")
            if isinstance(candidate, dict):
                completed_response = candidate
            continue

        if payload_type == "response.output_text.done":
            text = payload.get("text")
            if isinstance(text, str) and text:
                output_text_done_parts.append(text)
            continue

        if payload_type == "response.output_item.done":
            item = payload.get("item")
            if isinstance(item, dict):
                output_items.append(item)

    if completed_response is not None:
        return completed_response

    if output_text_done_parts or output_items:
        return {
            "id": "",
            "object": "response",
            "created_at": 0,
            "model": "",
            "output_text": "\n".join(output_text_done_parts) if output_text_done_parts else "",
            "output": output_items,
        }

    return response


def _get_responses_field(response: Any, field: str, default: Any = None) -> Any:
    if isinstance(response, dict):
        return response.get(field, default)
    return getattr(response, field, default)


async def _wait_for_responses_completion(
    client: Any,
    response: Any,
    timeout_seconds: int = 20,
    poll_interval_seconds: float = 1.0,
) -> Any:
    """
    Poll `responses.retrieve` when initial create response is not finalized.
    """
    normalized = _normalize_responses_result(response)
    response_id = _get_responses_field(normalized, "id")
    if not response_id:
        return response

    status = _get_responses_field(normalized, "status")
    text = _extract_responses_text(normalized)
    if text.strip():
        return normalized
    if status not in {"in_progress", "queued"}:
        return normalized

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    latest = normalized
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(poll_interval_seconds)
        try:
            polled = await client.responses.retrieve(response_id)
        except Exception:
            break
        latest = _normalize_responses_result(polled)
        status = _get_responses_field(latest, "status")
        text = _extract_responses_text(latest)
        if text.strip():
            return latest
        if status in {"completed", "failed", "cancelled"}:
            return latest

    return latest


def _extract_responses_text(response: Any) -> str:
    """
    Extract assistant text from a Responses API result.

    Priority:
    1) `response.output_text` (when provider populates it)
    2) `response.output[*].content[*].text` for message outputs
    """
    normalized = _normalize_responses_result(response)
    try:
        output_text = getattr(normalized, "output_text", None)
        if output_text is None and isinstance(normalized, dict):
            output_text = normalized.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
    except Exception:
        pass

    output = getattr(normalized, "output", None)
    if output is None:
        raw_response = _to_plain_json(normalized)
        if isinstance(raw_response, dict):
            output = raw_response.get("output")
    if not isinstance(output, list):
        output = _to_plain_json(output)
        if not isinstance(output, list):
            return ""

    parts: list[str] = []
    for item in output:
        raw_item = _to_plain_json(item)
        if not isinstance(raw_item, dict):
            continue
        if raw_item.get("type") != "message":
            continue
        if raw_item.get("role") not in (None, "assistant"):
            continue

        content = raw_item.get("content")
        if isinstance(content, str):
            if content.strip():
                parts.append(content)
            continue
        if not isinstance(content, list):
            continue

        for part in content:
            raw_part = _to_plain_json(part)
            if isinstance(raw_part, str):
                if raw_part.strip():
                    parts.append(raw_part)
                continue
            if not isinstance(raw_part, dict):
                continue
            part_type = raw_part.get("type")
            if part_type not in (None, "output_text", "text"):
                continue
            text = raw_part.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)

    return "\n".join(parts)


def _extract_responses_function_calls(response: Any) -> list[dict[str, str]]:
    """
    Extract function calls from a Responses API result in a normalized form.
    """
    normalized = _normalize_responses_result(response)
    output = getattr(normalized, "output", None)
    if output is None:
        raw_response = _to_plain_json(normalized)
        if isinstance(raw_response, dict):
            output = raw_response.get("output")
    if not isinstance(output, list):
        output = _to_plain_json(output)
        if not isinstance(output, list):
            return []

    calls: list[dict[str, str]] = []
    for item in output:
        raw_item = _to_plain_json(item)
        if not isinstance(raw_item, dict):
            continue
        if raw_item.get("type") != "function_call":
            continue
        calls.append(
            {
                "call_id": str(raw_item.get("call_id") or ""),
                "name": str(raw_item.get("name") or ""),
                "arguments": str(raw_item.get("arguments") or ""),
            }
        )
    return calls


def _responses_to_chat_completion(response: Any) -> Any:
    """Convert an OpenAI Responses API `Response` into a Chat Completions `ChatCompletion`."""
    from openai.types.chat import ChatCompletion
    from openai.types.chat.chat_completion import Choice
    from openai.types.chat.chat_completion_message import ChatCompletionMessage
    from openai.types.chat import ChatCompletionMessageToolCall
    from openai.types.chat.chat_completion_message_function_tool_call import Function
    from openai.types.completion_usage import CompletionUsage

    normalized = _normalize_responses_result(response)
    if isinstance(normalized, str):
        normalized_text = normalized.strip()
        if not normalized_text:
            raise ValueError("Empty raw string response from Responses API")
        lowered = normalized_text.lower()
        if "<html" in lowered or "bad gateway" in lowered or "error code 502" in lowered:
            raise ValueError("Gateway returned HTML error body for Responses API request")
        # Defensive fallback for providers that return plain text payloads.
        normalized = {
            "id": "",
            "object": "response",
            "created_at": 0,
            "model": "",
            "output_text": normalized_text,
            "output": [],
            "usage": None,
        }

    tool_calls: list[ChatCompletionMessageToolCall] = []
    for function_call in _extract_responses_function_calls(normalized):
        tool_calls.append(
            ChatCompletionMessageToolCall(
                id=function_call["call_id"],
                type="function",
                function=Function(
                    name=function_call["name"],
                    arguments=function_call["arguments"],
                ),
            )
        )

    output_text = _extract_responses_text(normalized)

    msg = ChatCompletionMessage(
        role="assistant",
        content=output_text or None,
        tool_calls=tool_calls or None,
    )

    finish_reason = "tool_calls" if tool_calls else "stop"
    choice = Choice(index=0, finish_reason=finish_reason, message=msg)

    usage = CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    try:
        usage_payload = getattr(normalized, "usage", None)
        if usage_payload is None and isinstance(normalized, dict):
            usage_payload = normalized.get("usage")
        if usage_payload is not None:
            u = usage_payload
            prompt_tokens = getattr(u, "input_tokens", 0) or 0
            completion_tokens = getattr(u, "output_tokens", 0) or 0
            total_tokens = getattr(u, "total_tokens", None)
            if isinstance(u, dict):
                prompt_tokens = u.get("input_tokens", prompt_tokens) or 0
                completion_tokens = u.get("output_tokens", completion_tokens) or 0
                total_tokens = u.get("total_tokens", total_tokens)
            if total_tokens is None:
                total_tokens = prompt_tokens + completion_tokens
            usage = CompletionUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
    except Exception:
        usage = CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    created = 0
    try:
        created_at = getattr(normalized, "created_at", 0)
        if isinstance(normalized, dict):
            created_at = normalized.get("created_at", created_at)
        created = int(created_at or 0)
    except Exception:
        created = 0

    return ChatCompletion(
        id=(normalized.get("id", "") if isinstance(normalized, dict) else getattr(normalized, "id", "")),
        object="chat.completion",
        created=created,
        model=(normalized.get("model", "") if isinstance(normalized, dict) else getattr(normalized, "model", "")),
        choices=[choice],
        usage=usage,
    )


def _ensure_chat_completion_usage(response: Any) -> Any:
    """
    Ensure ChatCompletion-like responses always include `usage`.

    Some OpenAI-compatible gateways omit usage metadata entirely; upstream
    `mcp-agent` currently dereferences `response.usage.prompt_tokens` directly.
    """
    from openai.types.completion_usage import CompletionUsage

    usage = getattr(response, "usage", None)
    if usage is not None:
        # Normalize partially-filled usage fields to avoid None arithmetic.
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0)
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens
        try:
            if (
                prompt_tokens == usage.prompt_tokens
                and completion_tokens == usage.completion_tokens
                and total_tokens == usage.total_tokens
            ):
                return response
        except Exception:
            pass
    else:
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

    normalized_usage = CompletionUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )
    model_copy = getattr(response, "model_copy", None)
    if callable(model_copy):
        try:
            return model_copy(update={"usage": normalized_usage})
        except Exception:
            pass

    # Secondary fallback: rebuild from dumped data for immutable objects.
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        try:
            from openai.types.chat import ChatCompletion

            data = model_dump()
            if isinstance(data, dict):
                data["usage"] = normalized_usage.model_dump()
                return ChatCompletion.model_validate(data)
        except Exception:
            pass

    try:
        response.usage = normalized_usage
    except Exception:
        pass
    return response


def patch_mcp_agent_openai_base_url_routing() -> None:
    """
    Make `mcp-agent` tolerate endpoint-style OpenAI base URLs.

    - If `openai.base_url` ends with `/chat/completions`, normalize it to the SDK
      base URL root so the SDK doesn't double-append.
    - If it ends with `/responses`, route the request through the Responses API
      and convert back into a ChatCompletions shape so upstream code keeps working.
    """
    global _PATCHED_OPENAI_BASE_URL_ROUTING
    if _PATCHED_OPENAI_BASE_URL_ROUTING:
        return

    try:
        import json

        from openai import (
            AsyncOpenAI,
            AuthenticationError,
            BadRequestError,
            NotFoundError,
            PermissionDeniedError,
            UnprocessableEntityError,
        )
        from mcp_agent.executor.errors import to_application_error
        from mcp_agent.executor.workflow_task import workflow_task
        from mcp_agent.tracing.telemetry import telemetry
        from mcp_agent.utils.common import ensure_serializable
        from mcp_agent.utils.pydantic_type_serializer import deserialize_model
        from mcp_agent.workflows.llm.augmented_llm_openai import (
            OpenAICompletionTasks,
            RequestCompletionRequest,
            RequestStructuredCompletionRequest,
        )
        from utils.openai_compat import get_openai_base_url_info, OpenAIEndpointHint
    except Exception:
        return

    non_retryable = (
        AuthenticationError,
        PermissionDeniedError,
        BadRequestError,
        NotFoundError,
        UnprocessableEntityError,
    )

    orig_request_structured_completion_task = (
        OpenAICompletionTasks.request_structured_completion_task
    )

    async def _request_completion_task_patched(
        request: RequestCompletionRequest,
    ):
        info = get_openai_base_url_info(getattr(request.config, "base_url", None))
        config = request.config
        if info.sdk_base_url != getattr(config, "base_url", None):
            config = config.model_copy(update={"base_url": info.sdk_base_url})

        async with AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            default_query=info.default_query,
            http_client=config.http_client if hasattr(config, "http_client") else None,
            default_headers=config.default_headers
            if hasattr(config, "default_headers")
            else None,
        ) as client:
            # Default path: call Chat Completions exactly like mcp-agent does, but
            # with normalized base_url to avoid double-appending.
            if info.endpoint_hint != OpenAIEndpointHint.RESPONSES:
                last_exc: Exception | None = None
                for attempt in range(1, 6):
                    try:
                        response = await client.chat.completions.create(
                            **request.payload
                        )
                        return ensure_serializable(
                            _ensure_chat_completion_usage(response)
                        )
                    except non_retryable as exc:
                        raise to_application_error(exc, non_retryable=True) from exc
                    except Exception as exc:
                        last_exc = exc
                        if attempt >= 5:
                            raise
                        await asyncio.sleep(min(2**attempt, 8))
                if last_exc is not None:
                    raise last_exc

            # `/responses` gateway: convert payload and bridge back to a ChatCompletion.
            last_exc = None
            for attempt in range(1, 6):
                try:
                    responses_payload = _convert_chat_payload_to_responses_payload(
                        request.payload
                    )
                    resp = await client.responses.create(**responses_payload)
                    resp = await _wait_for_responses_completion(client, resp)
                    completion = _responses_to_chat_completion(resp)
                    if (
                        completion.choices
                        and completion.choices[0].message.content is None
                        and completion.choices[0].message.tool_calls is None
                    ):
                        raise ValueError("Responses API returned no assistant content")
                    return ensure_serializable(_ensure_chat_completion_usage(completion))
                except non_retryable as exc:
                    raise to_application_error(exc, non_retryable=True) from exc
                except Exception as exc:
                    last_exc = exc
                    if attempt >= 5:
                        raise
                    await asyncio.sleep(min(2**attempt, 8))
            if last_exc is not None:
                raise last_exc

    async def _request_structured_completion_task_patched(
        request: RequestStructuredCompletionRequest,
    ):
        info = get_openai_base_url_info(getattr(request.config, "base_url", None))
        config = request.config
        if info.sdk_base_url != getattr(config, "base_url", None):
            config = config.model_copy(update={"base_url": info.sdk_base_url})
        # Default path: keep using mcp-agent's existing structured output task
        # (Chat Completions), but with normalized base_url.
        if info.endpoint_hint != OpenAIEndpointHint.RESPONSES:
            return await orig_request_structured_completion_task(
                RequestStructuredCompletionRequest(
                    config=config,
                    response_model=request.response_model,
                    serialized_response_model=request.serialized_response_model,
                    response_str=request.response_str,
                    model=request.model,
                    user=request.user,
                    strict=request.strict,
                )
            )

        # `/responses` gateway: route through Responses API and then validate the
        # returned JSON against the requested response model.
        if request.response_model is not None:
            response_model = request.response_model
        elif request.serialized_response_model is not None:
            response_model = deserialize_model(request.serialized_response_model)
        else:
            raise ValueError(
                "Either response_model or serialized_response_model must be provided for structured completion."
            )

        schema = response_model.model_json_schema()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": getattr(response_model, "__name__", "StructuredOutput"),
                "schema": schema,
                "strict": request.strict,
            },
        }

        async with AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            default_query=info.default_query,
            http_client=config.http_client if hasattr(config, "http_client") else None,
            default_headers=config.default_headers
            if hasattr(config, "default_headers")
            else None,
        ) as client:
            chat_payload = {
                "model": request.model,
                "messages": [{"role": "user", "content": request.response_str}],
                "response_format": response_format,
            }
            if request.user:
                chat_payload["user"] = request.user

            last_exc = None
            for attempt in range(1, 6):
                try:
                    responses_payload = _convert_chat_payload_to_responses_payload(
                        chat_payload
                    )
                    resp = await client.responses.create(**responses_payload)
                    resp = await _wait_for_responses_completion(client, resp)
                    break
                except non_retryable as exc:
                    raise to_application_error(exc, non_retryable=True) from exc
                except Exception as exc:
                    last_exc = exc
                    if attempt >= 5:
                        raise
                    await asyncio.sleep(min(2**attempt, 8))
            if last_exc is not None and "resp" not in locals():
                raise last_exc

        output_text = _extract_responses_text(resp)
        if not output_text:
            raise ValueError("No structured content returned by model")

        try:
            data = json.loads(output_text)
        except Exception:
            return response_model.model_validate_json(output_text)
        return response_model.model_validate(data)

    # Preserve workflow_task + telemetry metadata so mcp-agent executors keep
    # treating these as tasks (important for non-asyncio engines too).
    decorated_completion = workflow_task(retry_policy={"maximum_attempts": 3})(
        telemetry.traced()(_request_completion_task_patched)
    )
    decorated_structured = workflow_task(retry_policy={"maximum_attempts": 3})(
        telemetry.traced()(_request_structured_completion_task_patched)
    )

    OpenAICompletionTasks.request_completion_task = staticmethod(  # type: ignore[method-assign]
        decorated_completion
    )
    OpenAICompletionTasks.request_structured_completion_task = staticmethod(  # type: ignore[method-assign]
        decorated_structured
    )

    _PATCHED_OPENAI_BASE_URL_ROUTING = True
