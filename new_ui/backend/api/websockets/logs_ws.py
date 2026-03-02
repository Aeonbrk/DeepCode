"""
Logs WebSocket Handler
Provides real-time log streaming
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app_utils.redaction import redact_text
from app_utils.ws_security import is_ws_origin_allowed
from settings import PROJECT_ROOT, settings


router = APIRouter()

LOG_POLL_INTERVAL_S = 0.5
LOG_DIR_SCAN_INTERVAL_S = 2.0
MAX_LOG_LINES_PER_TICK = 500


def _get_newest_log_file(logs_dir: Path) -> Path | None:
    try:
        candidates = list(logs_dir.glob("*.jsonl"))
    except Exception:
        return None
    if not candidates:
        return None
    try:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except Exception:
        return None


def _get_session_log_file(
    logs_dir: Path, session_id: str, *, strict_session: bool
) -> Path | None:
    session = (session_id or "").strip()
    if not session:
        if strict_session:
            return None
        return _get_newest_log_file(logs_dir)

    exact = logs_dir / f"{session}.jsonl"
    if session and exact.exists():
        return exact

    if strict_session:
        return None

    try:
        candidates = list(logs_dir.glob("*.jsonl"))
    except Exception:
        return None
    if not candidates:
        return None

    matching = [path for path in candidates if session and session in path.name]
    if matching:
        try:
            return max(matching, key=lambda p: p.stat().st_mtime)
        except Exception:
            return matching[-1]

    return _get_newest_log_file(logs_dir)


def _read_new_log_lines(
    log_file: Path, last_position: int, *, max_lines: int
) -> tuple[list[str], int]:
    if last_position < 0:
        last_position = 0

    try:
        size = log_file.stat().st_size
    except FileNotFoundError:
        return [], 0

    # Handle log rotation/truncation.
    if size < last_position:
        last_position = 0

    lines: list[str] = []
    with open(log_file, "r", encoding="utf-8") as f:
        f.seek(last_position)
        for _ in range(max_lines):
            line = f.readline()
            if not line:
                break
            lines.append(line)
        new_position = f.tell()

    return lines, new_position


@router.websocket("/logs/{session_id}")
async def logs_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time log streaming.

    Streams log entries from the logs directory.

    Message format:
    {
        "type": "log",
        "level": "INFO" | "WARNING" | "ERROR" | "DEBUG",
        "message": str,
        "namespace": str,
        "timestamp": str
    }
    """
    origin = websocket.headers.get("origin")
    if not is_ws_origin_allowed(
        origin,
        allowed_origins=settings.cors_origins,
        debug=settings.debug,
        env=settings.env,
        allow_missing_origin=settings.allow_ws_without_origin,
    ):
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "error",
                "code": "WS_ORIGIN_NOT_ALLOWED",
                "message": "WebSocket origin not allowed",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        await websocket.close(code=1008)
        return

    if not settings.enable_logs_ws:
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "error",
                "code": "LOG_STREAMING_DISABLED",
                "message": "Log streaming is disabled on this server",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        await websocket.close(code=1008)
        return

    await websocket.accept()

    logs_dir = PROJECT_ROOT / "logs"
    last_position = 0
    current_log_file = None
    last_scan_ts = 0.0
    strict_session = settings.strict_logs_ws_session
    strict_missing_since: float | None = None
    strict_wait_seconds = max(1.0, float(settings.strict_logs_ws_wait_seconds))

    try:
        while True:
            try:
                # Find the most recent log file
                now_ts = asyncio.get_running_loop().time()
                if logs_dir.exists():
                    if current_log_file is None or (now_ts - last_scan_ts) >= LOG_DIR_SCAN_INTERVAL_S:
                        last_scan_ts = now_ts
                        newest_log = await asyncio.to_thread(
                            _get_session_log_file,
                            logs_dir,
                            session_id,
                            strict_session=strict_session,
                        )
                        if newest_log is not None:
                            strict_missing_since = None
                            if newest_log != current_log_file:
                                current_log_file = newest_log
                                last_position = 0
                        else:
                            current_log_file = None
                            if strict_session:
                                if strict_missing_since is None:
                                    strict_missing_since = now_ts
                                elif (
                                    now_ts - strict_missing_since
                                ) >= strict_wait_seconds:
                                    await websocket.send_json(
                                        {
                                            "type": "error",
                                            "code": "SESSION_LOG_NOT_FOUND",
                                            "message": (
                                                f"No log stream found for session '{session_id}'"
                                            ),
                                            "timestamp": datetime.utcnow().isoformat(),
                                        }
                                    )
                                    await websocket.close(code=1008)
                                    return
                            else:
                                strict_missing_since = None
                elif strict_session:
                    if strict_missing_since is None:
                        strict_missing_since = now_ts
                    elif (now_ts - strict_missing_since) >= strict_wait_seconds:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "SESSION_LOG_NOT_FOUND",
                                "message": (
                                    f"No log stream found for session '{session_id}'"
                                ),
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        await websocket.close(code=1008)
                        return

                if current_log_file:
                    try:
                        new_lines, last_position = await asyncio.to_thread(
                            _read_new_log_lines,
                            current_log_file,
                            last_position,
                            max_lines=MAX_LOG_LINES_PER_TICK,
                        )

                        for raw_line in new_lines:
                            line = raw_line.strip()
                            if not line:
                                continue

                            try:
                                log_entry = json.loads(line)
                                await websocket.send_json(
                                    {
                                        "type": "log",
                                        "level": log_entry.get("level", "INFO"),
                                        "message": redact_text(
                                            str(log_entry.get("message", ""))
                                        ),
                                        "namespace": log_entry.get("namespace", ""),
                                        "timestamp": log_entry.get(
                                            "timestamp",
                                            datetime.utcnow().isoformat(),
                                        ),
                                    }
                                )
                            except json.JSONDecodeError:
                                # Raw text log
                                await websocket.send_json(
                                    {
                                        "type": "log",
                                        "level": "INFO",
                                        "message": redact_text(line),
                                        "namespace": "",
                                        "timestamp": datetime.utcnow().isoformat(),
                                    }
                                )

                    except Exception as e:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": redact_text(
                                    f"Error reading log file: {str(e)}"
                                ),
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )

                # Wait before checking for more logs
                await asyncio.sleep(LOG_POLL_INTERVAL_S)

            except asyncio.CancelledError:
                break

    except WebSocketDisconnect:
        pass
