"""
Code Stream WebSocket Handler
Provides real-time streaming of generated code
"""

import asyncio
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app_utils.ws_security import is_ws_origin_allowed
from services.workflow_service import workflow_service
from settings import settings


router = APIRouter()


@router.websocket("/code-stream/{task_id}")
async def code_stream_websocket(websocket: WebSocket, task_id: str):
    """
    WebSocket endpoint for real-time code streaming.

    Streams generated code as it's being written, similar to ChatGPT.

    Message format:
    {
        "type": "code_chunk" | "file_start" | "file_end" | "complete",
        "task_id": str,
        "content": str,  # Code content for code_chunk
        "filename": str | null,  # For file_start/file_end
        "timestamp": str
    }
    """
    origin = websocket.headers.get("origin")
    if not is_ws_origin_allowed(
        origin,
        allowed_origins=settings.cors_origins,
        debug=settings.debug,
        env=settings.env,
    ):
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "error",
                "task_id": task_id,
                "error": "WebSocket origin not allowed",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        await websocket.close(code=1008)
        return

    await websocket.accept()

    task = workflow_service.get_task(task_id)
    # Subscribe to get our own queue for this task
    queue = workflow_service.subscribe(task_id)

    if not task:
        await websocket.send_json(
            {
                "type": "error",
                "task_id": task_id,
                "error": "Task not found",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        await websocket.close()
        return

    try:
        # Track current file being streamed
        current_file = None

        # Code-stream channel is non-authoritative for terminal state.
        # If task is already terminal, close immediately and let workflow WS be the source of truth.
        if task.status in ("completed", "error", "cancelled"):
            await websocket.close()
            return

        if queue:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=60.0)

                    # Transform progress messages into code stream format
                    if message.get("type") == "progress":
                        msg_text = message.get("message", "")

                        # Detect file creation events
                        if "Creating file:" in msg_text or "Writing:" in msg_text:
                            filename = msg_text.split(":")[-1].strip()
                            if current_file:
                                await websocket.send_json(
                                    {
                                        "type": "file_end",
                                        "task_id": task_id,
                                        "filename": current_file,
                                        "timestamp": datetime.utcnow().isoformat(),
                                    }
                                )
                            current_file = filename
                            await websocket.send_json(
                                {
                                    "type": "file_start",
                                    "task_id": task_id,
                                    "filename": filename,
                                    "timestamp": datetime.utcnow().isoformat(),
                                }
                            )

                    elif message.get("type") == "code_chunk":
                        # Direct code chunk forwarding
                        await websocket.send_json(
                            {
                                "type": "code_chunk",
                                "task_id": task_id,
                                "content": message.get("content", ""),
                                "filename": message.get("filename"),
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )

                    elif message.get("type") in ("complete", "error", "cancelled"):
                        msg_type = message.get("type")
                        print(
                            f"[CodeStreamWS] Workflow finished: task={task_id[:8]}... type={msg_type}"
                        )
                        if current_file:
                            await websocket.send_json(
                                {
                                    "type": "file_end",
                                    "task_id": task_id,
                                    "filename": current_file,
                                    "timestamp": datetime.utcnow().isoformat(),
                                    }
                                )
                        # Do not forward terminal events from code-stream channel to avoid
                        # duplicating workflow terminal handling on the frontend.
                        # Wait a bit before closing to ensure frontend processes the message
                        await asyncio.sleep(0.5)
                        await websocket.close()
                        break

                except asyncio.TimeoutError:
                    await websocket.send_json(
                        {
                            "type": "heartbeat",
                            "task_id": task_id,
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    )

    except WebSocketDisconnect:
        pass
    finally:
        # Unsubscribe from task updates
        if queue:
            workflow_service.unsubscribe(task_id, queue)
