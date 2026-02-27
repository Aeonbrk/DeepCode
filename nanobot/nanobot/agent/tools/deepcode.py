"""
DeepCode integration tools for nanobot.

These tools allow nanobot to interact with the DeepCode backend API
for paper-to-code reproduction, chat-based code generation, and task management.

Communication: HTTP requests to DeepCode's FastAPI backend.
In Docker Compose: nanobot -> http://deepcode:8000/api/v1/...
"""

import asyncio
import os
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool


def _get_deepcode_url() -> str:
    """Get DeepCode API base URL from environment."""
    return os.environ.get("DEEPCODE_API_URL", "http://deepcode:8000")


_MAX_RETRIES = 2
_BASE_RETRY_DELAY_SECONDS = 0.5
_TRANSIENT_STATUS_CODES = {502, 503, 504}

_SHARED_CLIENTS: dict[str, httpx.AsyncClient] = {}


def _get_shared_client(api_url: str) -> httpx.AsyncClient:
    client = _SHARED_CLIENTS.get(api_url)
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        _SHARED_CLIENTS[api_url] = client
    return client


def _truncate(text: str, limit: int = 800) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _try_get_error_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if detail is not None:
            return _truncate(str(detail), 500)
    return None


def _format_http_status_error(e: httpx.HTTPStatusError) -> str:
    detail = _try_get_error_detail(e.response)
    if detail:
        return f"Error: DeepCode API returned status {e.response.status_code}: {detail}"
    return f"Error: DeepCode API returned status {e.response.status_code}."


async def _request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float | httpx.Timeout | None = None,
) -> httpx.Response:
    delay = _BASE_RETRY_DELAY_SECONDS
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.request(
                method,
                url,
                json=json,
                params=params,
                timeout=timeout,
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


class _DeepCodeToolBase(Tool):
    def __init__(self, api_url: str | None = None):
        self._api_url = api_url or _get_deepcode_url()

    def _get_client(self) -> httpx.AsyncClient:
        return _get_shared_client(self._api_url)

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> dict[str, Any]:
        url = f"{self._api_url}{path}"
        response = await _request_with_retries(
            self._get_client(),
            method,
            url,
            json=json,
            params=params,
            timeout=timeout,
        )
        try:
            return response.json()
        except ValueError:
            return {}


class DeepCodePaper2CodeTool(_DeepCodeToolBase):
    """Submit a paper (URL or file path) to DeepCode for automatic code reproduction."""

    def __init__(self, api_url: str | None = None):
        super().__init__(api_url=api_url)

    @property
    def name(self) -> str:
        return "deepcode_paper2code"

    @property
    def description(self) -> str:
        return (
            "Submit a research paper to DeepCode for automatic code reproduction. "
            "Accepts a paper URL (e.g. arxiv link) or a local file path. "
            "Returns a task ID for tracking progress. "
            "The code generation process runs in the background and may take 10-60 minutes. "
            "Use deepcode_status to check progress."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input_source": {
                    "type": "string",
                    "description": "Paper URL (e.g. https://arxiv.org/abs/...) or local file path",
                },
                "input_type": {
                    "type": "string",
                    "enum": ["url", "file"],
                    "description": "Type of input: 'url' for web links, 'file' for local files",
                },
                "enable_indexing": {
                    "type": "boolean",
                    "description": "Enable code reference indexing for enhanced quality (slower but better). Default: false",
                },
            },
            "required": ["input_source", "input_type"],
        }

    async def execute(
        self,
        input_source: str,
        input_type: str = "url",
        enable_indexing: bool = False,
        **kwargs: Any,
    ) -> str:
        try:
            data = await self._request_json(
                "POST",
                "/api/v1/workflows/paper-to-code",
                json={
                    "input_source": input_source,
                    "input_type": input_type,
                    "enable_indexing": enable_indexing,
                },
            )
            task_id = data.get("task_id", "unknown")
            return (
                f"Paper-to-code task submitted successfully!\n"
                f"Task ID: {task_id}\n"
                f"Status: {data.get('status', 'started')}\n"
                f"Input: {input_source}\n"
                f"Indexing: {'enabled' if enable_indexing else 'disabled (fast mode)'}\n\n"
                f"The code generation is running in the background. "
                f"Use deepcode_status with task_id='{task_id}' to check progress."
            )
        except httpx.ConnectError:
            return "Error: Cannot connect to DeepCode backend. Is the DeepCode service running?"
        except httpx.HTTPStatusError as e:
            return _format_http_status_error(e)
        except Exception as e:
            return f"Error submitting paper to DeepCode: {str(e)}"


class DeepCodeChat2CodeTool(_DeepCodeToolBase):
    """Submit text requirements to DeepCode for code generation."""

    def __init__(self, api_url: str | None = None):
        super().__init__(api_url=api_url)

    @property
    def name(self) -> str:
        return "deepcode_chat2code"

    @property
    def description(self) -> str:
        return (
            "Submit coding requirements to DeepCode for automatic code generation. "
            "Provide a text description of what you want to build (e.g. web app, algorithm, backend service). "
            "DeepCode will generate a complete implementation. "
            "Returns a task ID for tracking progress."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "requirements": {
                    "type": "string",
                    "description": "Detailed description of coding requirements",
                },
                "enable_indexing": {
                    "type": "boolean",
                    "description": "Enable code reference indexing for enhanced quality. Default: false",
                },
            },
            "required": ["requirements"],
        }

    async def execute(
        self,
        requirements: str,
        enable_indexing: bool = False,
        **kwargs: Any,
    ) -> str:
        try:
            data = await self._request_json(
                "POST",
                "/api/v1/workflows/chat-planning",
                json={
                    "requirements": requirements,
                    "enable_indexing": enable_indexing,
                },
            )
            task_id = data.get("task_id", "unknown")
            return (
                f"Chat-to-code task submitted successfully!\n"
                f"Task ID: {task_id}\n"
                f"Status: {data.get('status', 'started')}\n"
                f"Requirements: {requirements[:200]}{'...' if len(requirements) > 200 else ''}\n\n"
                f"The code generation is running in the background. "
                f"Use deepcode_status with task_id='{task_id}' to check progress."
            )
        except httpx.ConnectError:
            return "Error: Cannot connect to DeepCode backend. Is the DeepCode service running?"
        except httpx.HTTPStatusError as e:
            return _format_http_status_error(e)
        except Exception as e:
            return f"Error submitting requirements to DeepCode: {str(e)}"


class DeepCodeStatusTool(_DeepCodeToolBase):
    """Check the status and progress of a DeepCode task."""

    def __init__(self, api_url: str | None = None):
        super().__init__(api_url=api_url)

    @property
    def name(self) -> str:
        return "deepcode_status"

    @property
    def description(self) -> str:
        return (
            "Check the status and progress of a DeepCode code generation task. "
            "Provide the task_id returned by deepcode_paper2code or deepcode_chat2code. "
            "Returns current status, progress percentage, and result when complete."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to check status for",
                },
            },
            "required": ["task_id"],
        }

    async def execute(self, task_id: str, **kwargs: Any) -> str:
        try:
            data = await self._request_json(
                "GET",
                f"/api/v1/workflows/status/{task_id}",
                timeout=15.0,
            )

            status = data.get("status", "unknown")
            progress = data.get("progress", 0)
            message = data.get("message", "")
            result = data.get("result")
            error = data.get("error")

            lines = [
                f"Task ID: {task_id}",
                f"Status: {status}",
                f"Progress: {progress}%",
            ]

            if message:
                lines.append(f"Message: {message}")

            if status == "completed" and result:
                lines.append(f"\nResult:\n{result}")
            elif status == "error" and error:
                lines.append(f"\nError: {error}")
            elif status == "waiting_for_input":
                interaction = data.get("pending_interaction")
                if interaction:
                    lines.append("\nWaiting for user input:")
                    lines.append(f"  Type: {interaction.get('type', 'unknown')}")
                    lines.append(f"  Title: {interaction.get('title', '')}")
                    lines.append(f"  Description: {interaction.get('description', '')}")

            return "\n".join(lines)

        except httpx.ConnectError:
            return "Error: Cannot connect to DeepCode backend. Is the DeepCode service running?"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return f"Error: Task '{task_id}' not found. It may have expired."
            return _format_http_status_error(e)
        except Exception as e:
            return f"Error checking task status: {str(e)}"


class DeepCodeListTasksTool(_DeepCodeToolBase):
    """List active and recent DeepCode tasks."""

    def __init__(self, api_url: str | None = None):
        super().__init__(api_url=api_url)

    @property
    def name(self) -> str:
        return "deepcode_list_tasks"

    @property
    def description(self) -> str:
        return (
            "List all active and recent DeepCode code generation tasks. "
            "Shows task IDs, status, progress, and results summary."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of recent tasks to show. Default: 10",
                    "minimum": 1,
                    "maximum": 50,
                },
            },
        }

    async def execute(self, limit: int = 10, **kwargs: Any) -> str:
        try:
            active_data = await self._request_json(
                "GET",
                "/api/v1/workflows/active",
                timeout=15.0,
            )
            recent_data = await self._request_json(
                "GET",
                "/api/v1/workflows/recent",
                params={"limit": limit},
                timeout=15.0,
            )

            lines = []

            active_tasks = active_data.get("tasks", [])
            if active_tasks:
                lines.append(f"=== Active Tasks ({len(active_tasks)}) ===")
                for task in active_tasks:
                    lines.append(
                        f"  [{task.get('status', '?')}] {task.get('task_id', '?')} "
                        f"- {task.get('progress', 0)}% - {task.get('message', '')}"
                    )
                lines.append("")

            recent_tasks = recent_data.get("tasks", [])
            if recent_tasks:
                lines.append(f"=== Recent Tasks ({len(recent_tasks)}) ===")
                for task in recent_tasks:
                    status_icon = {
                        "completed": "done",
                        "error": "error",
                        "running": "running",
                        "cancelled": "cancelled",
                    }.get(task.get("status", ""), "?")
                    lines.append(
                        f"  [{status_icon}] {task.get('task_id', '?')} "
                        f"- {task.get('status', '?')} - {task.get('message', '')}"
                    )

            if not lines:
                return "No DeepCode tasks found."

            return "\n".join(lines)

        except httpx.ConnectError:
            return "Error: Cannot connect to DeepCode backend. Is the DeepCode service running?"
        except httpx.HTTPStatusError as e:
            return _format_http_status_error(e)
        except Exception as e:
            return f"Error listing tasks: {str(e)}"


class DeepCodeCancelTool(_DeepCodeToolBase):
    """Cancel a running DeepCode task."""

    def __init__(self, api_url: str | None = None):
        super().__init__(api_url=api_url)

    @property
    def name(self) -> str:
        return "deepcode_cancel"

    @property
    def description(self) -> str:
        return "Cancel a running DeepCode code generation task."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to cancel",
                },
            },
            "required": ["task_id"],
        }

    async def execute(self, task_id: str, **kwargs: Any) -> str:
        try:
            await self._request_json(
                "POST",
                f"/api/v1/workflows/cancel/{task_id}",
                timeout=15.0,
            )
            return f"Task '{task_id}' has been cancelled successfully."
        except httpx.ConnectError:
            return "Error: Cannot connect to DeepCode backend. Is the DeepCode service running?"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                return f"Error: Task '{task_id}' not found or cannot be cancelled."
            return _format_http_status_error(e)
        except Exception as e:
            return f"Error cancelling task: {str(e)}"


class DeepCodeRespondTool(_DeepCodeToolBase):
    """Respond to a DeepCode User-in-Loop interaction request."""

    def __init__(self, api_url: str | None = None):
        super().__init__(api_url=api_url)

    @property
    def name(self) -> str:
        return "deepcode_respond"

    @property
    def description(self) -> str:
        return (
            "Respond to a DeepCode User-in-Loop interaction. "
            "When a DeepCode task is waiting for user input (e.g. requirement clarification, "
            "plan review), use this tool to submit the user's response. "
            "First check deepcode_status to see the pending interaction details."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID that is waiting for input",
                },
                "action": {
                    "type": "string",
                    "enum": ["submit", "confirm", "modify", "skip", "cancel"],
                    "description": "User's action: submit answers, confirm plan, modify, skip, or cancel",
                },
                "data": {
                    "type": "object",
                    "description": "Response data (e.g. answers to questions, modification feedback)",
                },
                "skipped": {
                    "type": "boolean",
                    "description": "Whether the user chose to skip this interaction. Default: false",
                },
            },
            "required": ["task_id", "action"],
        }

    async def execute(
        self,
        task_id: str,
        action: str,
        data: dict | None = None,
        skipped: bool = False,
        **kwargs: Any,
    ) -> str:
        try:
            await self._request_json(
                "POST",
                f"/api/v1/workflows/respond/{task_id}",
                json={
                    "action": action,
                    "data": data or {},
                    "skipped": skipped,
                },
            )
            return (
                f"Response submitted successfully!\n"
                f"Task ID: {task_id}\n"
                f"Action: {action}\n"
                f"The workflow will now continue."
            )
        except httpx.ConnectError:
            return "Error: Cannot connect to DeepCode backend. Is the DeepCode service running?"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                detail = _try_get_error_detail(e.response)
                return f"Error: {detail or 'Unknown error'}"
            return _format_http_status_error(e)
        except Exception as e:
            return f"Error responding to interaction: {str(e)}"


# ============================================================
# Helper: create all DeepCode tools at once
# ============================================================


def create_all_tools(api_url: str | None = None) -> list[Tool]:
    """
    Create all DeepCode tools with the given API URL.

    Usage in AgentLoop._register_default_tools():
        deepcode_url = os.environ.get("DEEPCODE_API_URL")
        if deepcode_url:
            from nanobot.agent.tools.deepcode import create_all_tools
            for tool in create_all_tools(api_url=deepcode_url):
                self.tools.register(tool)
    """
    url = api_url or _get_deepcode_url()
    return [
        DeepCodePaper2CodeTool(api_url=url),
        DeepCodeChat2CodeTool(api_url=url),
        DeepCodeStatusTool(api_url=url),
        DeepCodeListTasksTool(api_url=url),
        DeepCodeCancelTool(api_url=url),
        DeepCodeRespondTool(api_url=url),
    ]
