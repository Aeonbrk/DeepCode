"""
Workflow Service - Integration with existing DeepCode workflows

NOTE: This module uses lazy imports for DeepCode modules (workflows, mcp_agent).
sys.path is configured in main.py at startup. Background tasks share the same
sys.path, so DeepCode modules will be found correctly as long as there are
no naming conflicts (config.py -> settings.py, utils/ -> app_utils/).
"""

import asyncio
import uuid
import os
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from contextlib import contextmanager

from settings import CONFIG_PATH, PROJECT_ROOT
from app_utils.redaction import redact_payload, redact_text

SUBSCRIBER_QUEUE_MAXSIZE = 500
MAX_STORED_TASKS = 500
TASK_RETENTION_SECONDS = 6 * 60 * 60  # 6 hours


@dataclass
class WorkflowTask:
    """Represents a running workflow task"""

    task_id: str
    status: str = "pending"  # pending | running | waiting_for_input | completed | error | cancelled
    progress: int = 0
    message: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    # User-in-Loop support
    pending_interaction: Optional[Dict[str, Any]] = (
        None  # Current interaction request waiting for user
    )


class WorkflowService:
    """Service for managing workflow execution"""

    def __init__(self):
        self._tasks: Dict[str, WorkflowTask] = {}
        # Changed: Each task can have multiple subscriber queues
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._execution_lock = asyncio.Lock()
        # User-in-Loop plugin integration (lazy loaded)
        self._plugin_integration = None
        self._plugin_enabled = True  # Can be disabled via config

    def _prune_tasks(self) -> None:
        """Bound in-memory task/subscriber retention to avoid unbounded growth."""
        terminal_statuses = {"completed", "error", "cancelled"}
        now = datetime.utcnow()

        # Prune terminal tasks older than retention, but don't delete tasks with subscribers.
        for task_id, task in list(self._tasks.items()):
            if task.status not in terminal_statuses:
                continue
            if self._subscribers.get(task_id):
                continue
            if not task.completed_at:
                continue
            if (now - task.completed_at).total_seconds() > TASK_RETENTION_SECONDS:
                self.cleanup_task(task_id)

        # Cap total stored tasks (prefer deleting oldest terminal tasks with no subscribers).
        if len(self._tasks) <= MAX_STORED_TASKS:
            return

        terminal_candidates: list[tuple[datetime, str]] = []
        for task_id, task in self._tasks.items():
            if task.status not in terminal_statuses:
                continue
            if self._subscribers.get(task_id):
                continue
            timestamp = task.completed_at or task.started_at or datetime.min
            terminal_candidates.append((timestamp, task_id))

        terminal_candidates.sort(key=lambda item: item[0])
        for _, task_id in terminal_candidates:
            if len(self._tasks) <= MAX_STORED_TASKS:
                break
            self.cleanup_task(task_id)

    def _get_plugin_integration(self):
        """Lazy load the plugin integration system."""
        if self._plugin_integration is None and self._plugin_enabled:
            try:
                from workflows.plugins.integration import WorkflowPluginIntegration

                self._plugin_integration = WorkflowPluginIntegration(self)
                print("[WorkflowService] Plugin integration initialized")
            except ImportError as e:
                print(f"[WorkflowService] Plugin system not available: {e}")
                self._plugin_enabled = False
        return self._plugin_integration

    def create_task(self) -> WorkflowTask:
        """Create a new workflow task"""
        task_id = str(uuid.uuid4())
        task = WorkflowTask(task_id=task_id)
        self._tasks[task_id] = task
        self._subscribers[task_id] = []
        self._prune_tasks()
        return task

    def get_task(self, task_id: str) -> Optional[WorkflowTask]:
        """Get task by ID"""
        return self._tasks.get(task_id)

    def subscribe(self, task_id: str) -> Optional[asyncio.Queue]:
        """Subscribe to a task's progress updates. Returns a new queue for this subscriber."""
        if task_id not in self._subscribers:
            print(f"[Subscribe] Failed: task={task_id[:8]}... not found in subscribers")
            return None
        queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE)
        self._subscribers[task_id].append(queue)
        print(
            f"[Subscribe] Success: task={task_id[:8]}... total_subscribers={len(self._subscribers[task_id])}"
        )
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue):
        """Unsubscribe from a task's progress updates."""
        if task_id in self._subscribers and queue in self._subscribers[task_id]:
            self._subscribers[task_id].remove(queue)
            print(
                f"[Unsubscribe] task={task_id[:8]}... remaining={len(self._subscribers[task_id])}"
            )

    async def _broadcast(self, task_id: str, message: Dict[str, Any]):
        """Broadcast a message to all subscribers of a task."""
        self._broadcast_nowait(task_id, message)

    def _broadcast_nowait(self, task_id: str, message: Dict[str, Any]) -> None:
        """Broadcast without awaiting; must run on the event loop thread."""
        if task_id in self._subscribers:
            subscriber_count = len(self._subscribers[task_id])
            print(
                f"[Broadcast] task={task_id[:8]}... type={message.get('type')} subscribers={subscriber_count}"
            )
            for queue in self._subscribers[task_id]:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    msg_type = message.get("type")
                    is_critical = msg_type in {
                        "complete",
                        "error",
                        "cancelled",
                        "interaction_required",
                    }

                    if is_critical:
                        # Drop backlog so the critical state reaches the frontend.
                        try:
                            while True:
                                queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        try:
                            queue.put_nowait(message)
                        except asyncio.QueueFull:
                            pass
                    else:
                        # For high-frequency updates, keep the most recent by dropping one.
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        try:
                            queue.put_nowait(message)
                        except asyncio.QueueFull:
                            pass
                except Exception as e:
                    print(f"[Broadcast] Failed to send to queue: {e}")
        else:
            print(
                f"[Broadcast] No subscribers for task={task_id[:8]}... type={message.get('type')}"
            )

    def get_progress_queue(self, task_id: str) -> Optional[asyncio.Queue]:
        """Get progress queue for a task (deprecated, use subscribe instead)"""
        # For backwards compatibility, create a subscriber queue
        return self.subscribe(task_id)

    async def _create_progress_callback(
        self, task_id: str
    ) -> Callable[[int, str], None]:
        """Create a progress callback that broadcasts to all subscribers"""
        task = self._tasks.get(task_id)
        loop = asyncio.get_running_loop()

        def callback(progress: int, message: str):
            if task and (task.cancel_event.is_set() or task.status == "cancelled"):
                return
            safe_message = redact_text(message)
            if task:
                task.progress = progress
                task.message = safe_message

            msg = {
                "type": "progress",
                "task_id": task_id,
                "progress": progress,
                "message": safe_message,
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Avoid unbounded task creation under high-frequency progress updates.
            # call_soon_threadsafe is safe even if callback is invoked from a worker thread.
            try:
                loop.call_soon_threadsafe(self._broadcast_nowait, task_id, msg)
            except RuntimeError:
                # Event loop not available (for example during shutdown); best-effort drop.
                return

        return callback

    @contextmanager
    def _project_root_cwd(self):
        """Temporarily switch CWD to project root and safely restore it."""
        original_cwd = os.getcwd()
        try:
            if original_cwd != str(PROJECT_ROOT):
                os.chdir(PROJECT_ROOT)
            yield
        finally:
            try:
                current_cwd = os.getcwd()
            except OSError:
                current_cwd = None
            if current_cwd != original_cwd:
                os.chdir(original_cwd)

    def _is_cancelled(self, task: Optional[WorkflowTask]) -> bool:
        return bool(task and (task.cancel_event.is_set() or task.status == "cancelled"))

    def _cancellation_checkpoint(
        self, task: Optional[WorkflowTask], reason: str = "Cancelled by user"
    ) -> None:
        if self._is_cancelled(task):
            raise asyncio.CancelledError(reason)

    async def _finalize_cancelled(
        self, task_id: str, task: Optional[WorkflowTask], reason: str
    ) -> Dict[str, Any]:
        if task:
            task.cancel_event.set()
            task.status = "cancelled"
            task.message = reason
            if task.completed_at is None:
                task.completed_at = datetime.utcnow()
        cancelled_message = {
            "type": "cancelled",
            "task_id": task_id,
            "reason": redact_text(reason),
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._broadcast(task_id, cancelled_message)
        return {"status": "cancelled", "reason": reason}

    async def execute_paper_to_code(
        self,
        task_id: str,
        input_source: str,
        input_type: str,
        enable_indexing: bool = False,
    ) -> Dict[str, Any]:
        """Execute paper-to-code workflow"""
        # Lazy imports - DeepCode modules found via sys.path set in main.py
        from mcp_agent.app import MCPApp
        from workflows.agent_orchestration_engine import (
            execute_multi_agent_research_pipeline,
        )

        task = self._tasks.get(task_id)
        if not task:
            return {"status": "error", "error": "Task not found"}

        async with self._execution_lock:
            self._cancellation_checkpoint(task)
            task.status = "running"
            task.started_at = datetime.utcnow()

            try:
                progress_callback = await self._create_progress_callback(task_id)

                with self._project_root_cwd():
                    # Create MCP app context with explicit config path
                    # Compat: allow OpenAI reasoning_effort values (e.g. xhigh) used by
                    # some OpenAI-compatible gateways.
                    from utils.mcp_agent_compat import (
                        ensure_current_python_on_path,
                        patch_mcp_agent_openai_reasoning_effort,
                        patch_mcp_agent_openai_base_url_routing,
                        patch_mcp_agent_openai_executor_raise_on_error,
                    )

                    ensure_current_python_on_path()
                    patch_mcp_agent_openai_reasoning_effort()
                    patch_mcp_agent_openai_base_url_routing()
                    patch_mcp_agent_openai_executor_raise_on_error()
                    self._cancellation_checkpoint(task)
                    app = MCPApp(name="paper_to_code", settings=str(CONFIG_PATH))

                    async with app.run() as agent_app:
                        logger = agent_app.logger
                        context = agent_app.context

                        # Add current working directory to filesystem server args
                        context.config.mcp.servers["filesystem"].args.extend(
                            [os.getcwd()]
                        )

                        # Execute the pipeline
                        result = await execute_multi_agent_research_pipeline(
                            input_source,
                            logger,
                            progress_callback,
                            enable_indexing=enable_indexing,
                        )
                        self._cancellation_checkpoint(task)
                        if self._is_cancelled(task):
                            return await self._finalize_cancelled(
                                task_id, task, task.message or "Cancelled by user"
                            )

                        task.status = "completed"
                        task.progress = 100
                        task.result = redact_payload(
                            {
                                "status": "success",
                                "repo_result": result,
                            }
                        )
                        task.completed_at = datetime.utcnow()

                        # Broadcast completion signal to all subscribers
                        await self._broadcast(
                            task_id,
                            {
                                "type": "complete",
                                "task_id": task_id,
                                "status": "success",
                                "result": redact_payload(task.result),
                            },
                        )
                        # Give WebSocket handlers time to receive the completion message
                        await asyncio.sleep(0.5)
                        self._prune_tasks()

                        return task.result

            except asyncio.CancelledError as e:
                return await self._finalize_cancelled(task_id, task, str(e))
            except Exception as e:
                if self._is_cancelled(task):
                    return await self._finalize_cancelled(
                        task_id, task, "Cancelled by user"
                    )
                task.status = "error"
                task.error = redact_text(str(e))
                task.completed_at = datetime.utcnow()

                # Broadcast error signal to all subscribers
                await self._broadcast(
                    task_id,
                    {
                        "type": "error",
                        "task_id": task_id,
                        "error": redact_text(str(e)),
                    },
                )
                self._prune_tasks()

                return {"status": "error", "error": redact_text(str(e))}

    async def execute_chat_planning(
        self,
        task_id: str,
        requirements: str,
        enable_indexing: bool = False,
        enable_user_interaction: bool = True,  # Enable User-in-Loop by default
    ) -> Dict[str, Any]:
        """Execute chat-based planning workflow"""
        # Lazy imports - DeepCode modules found via sys.path set in main.py
        from mcp_agent.app import MCPApp
        from workflows.agent_orchestration_engine import (
            execute_chat_based_planning_pipeline,
        )

        task = self._tasks.get(task_id)
        if not task:
            return {"status": "error", "error": "Task not found"}

        async with self._execution_lock:
            self._cancellation_checkpoint(task)
            task.status = "running"
            task.started_at = datetime.utcnow()

            try:
                progress_callback = await self._create_progress_callback(task_id)

                with self._project_root_cwd():
                    # Create MCP app context with explicit config path
                    # Compat: allow OpenAI reasoning_effort values (e.g. xhigh) used by
                    # some OpenAI-compatible gateways.
                    from utils.mcp_agent_compat import (
                        ensure_current_python_on_path,
                        patch_mcp_agent_openai_reasoning_effort,
                        patch_mcp_agent_openai_base_url_routing,
                        patch_mcp_agent_openai_executor_raise_on_error,
                    )

                    ensure_current_python_on_path()
                    patch_mcp_agent_openai_reasoning_effort()
                    patch_mcp_agent_openai_base_url_routing()
                    patch_mcp_agent_openai_executor_raise_on_error()
                    self._cancellation_checkpoint(task)
                    app = MCPApp(name="chat_planning", settings=str(CONFIG_PATH))

                    async with app.run() as agent_app:
                        logger = agent_app.logger
                        context = agent_app.context

                        # Add current working directory to filesystem server args
                        context.config.mcp.servers["filesystem"].args.extend(
                            [os.getcwd()]
                        )

                        # --- User-in-Loop: Before Planning Hook ---
                        final_requirements = requirements
                        plugin_integration = self._get_plugin_integration()

                        if enable_user_interaction and plugin_integration:
                            try:
                                from workflows.plugins import InteractionPoint

                                # Create plugin context
                                plugin_context = plugin_integration.create_context(
                                    task_id=task_id,
                                    user_input=requirements,
                                    requirements=requirements,
                                    enable_indexing=enable_indexing,
                                )

                                # Run BEFORE_PLANNING plugins (requirement analysis)
                                plugin_context = await plugin_integration.run_hook(
                                    InteractionPoint.BEFORE_PLANNING, plugin_context
                                )
                                self._cancellation_checkpoint(task)

                                # Check if workflow was cancelled by user
                                if plugin_context.get("workflow_cancelled"):
                                    reason = plugin_context.get(
                                        "cancel_reason", "Cancelled by user"
                                    )
                                    return await self._finalize_cancelled(
                                        task_id, task, reason
                                    )

                                # Use potentially enhanced requirements
                                final_requirements = plugin_context.get(
                                    "requirements", requirements
                                )
                                print(
                                    f"[WorkflowService] Requirements after plugin: {len(final_requirements)} chars"
                                )

                            except Exception as plugin_error:
                                print(
                                    f"[WorkflowService] Plugin error (continuing without): {plugin_error}"
                                )
                                # Continue without plugin enhancement

                        # Execute the pipeline with (possibly enhanced) requirements
                        result = await execute_chat_based_planning_pipeline(
                            final_requirements,
                            logger,
                            progress_callback,
                            enable_indexing=enable_indexing,
                        )
                        self._cancellation_checkpoint(task)
                        if self._is_cancelled(task):
                            return await self._finalize_cancelled(
                                task_id, task, task.message or "Cancelled by user"
                            )

                        task.status = "completed"
                        task.progress = 100
                        task.result = redact_payload(
                            {
                                "status": "success",
                                "repo_result": result,
                            }
                        )
                        task.completed_at = datetime.utcnow()

                    # Broadcast completion signal to all subscribers
                    await self._broadcast(
                        task_id,
                        {
                            "type": "complete",
                            "task_id": task_id,
                            "status": "success",
                            "result": redact_payload(task.result),
                        },
                    )
                    # Give WebSocket handlers time to receive the completion message
                    await asyncio.sleep(0.5)
                    self._prune_tasks()

                    return task.result

            except asyncio.CancelledError as e:
                return await self._finalize_cancelled(task_id, task, str(e))
            except Exception as e:
                if self._is_cancelled(task):
                    return await self._finalize_cancelled(
                        task_id, task, "Cancelled by user"
                    )
                task.status = "error"
                task.error = redact_text(str(e))
                task.completed_at = datetime.utcnow()

                # Broadcast error signal to all subscribers
                await self._broadcast(
                    task_id,
                    {
                        "type": "error",
                        "task_id": task_id,
                        "error": redact_text(str(e)),
                    },
                )
                self._prune_tasks()

                return {"status": "error", "error": redact_text(str(e))}

    def cancel_task(self, task_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a running task"""
        task = self._tasks.get(task_id)
        if not task or task.status not in ("pending", "running", "waiting_for_input"):
            return False

        previous_status = task.status
        task.cancel_event.set()
        task.status = "cancelled"
        task.message = reason
        task.completed_at = datetime.utcnow()

        if previous_status == "waiting_for_input":
            plugin = self._get_plugin_integration()
            if plugin is not None:
                try:
                    plugin.submit_response(
                        task_id=task_id,
                        action="skip",
                        data={},
                        skipped=True,
                    )
                except Exception as plugin_error:
                    print(
                        f"[WorkflowService] Failed to unblock pending interaction during cancel: {plugin_error}"
                    )

        cancelled_message = {
            "type": "cancelled",
            "task_id": task_id,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        }
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._broadcast(task_id, cancelled_message))
        except RuntimeError:
            asyncio.run(self._broadcast(task_id, cancelled_message))

        self._prune_tasks()
        return True

    def cleanup_task(self, task_id: str):
        """Clean up task resources"""
        if task_id in self._tasks:
            del self._tasks[task_id]
        if task_id in self._subscribers:
            del self._subscribers[task_id]

    def get_active_tasks(self) -> List[WorkflowTask]:
        """Get all tasks that are currently running"""
        return [task for task in self._tasks.values() if task.status == "running"]

    def get_recent_tasks(self, limit: int = 10) -> List[WorkflowTask]:
        """Get recent tasks sorted by start time (newest first)"""
        self._prune_tasks()
        tasks = list(self._tasks.values())
        # Sort by started_at descending (newest first)
        tasks.sort(key=lambda t: t.started_at or datetime.min, reverse=True)
        return tasks[:limit]


# Global service instance
workflow_service = WorkflowService()
