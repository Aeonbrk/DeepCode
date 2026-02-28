#!/usr/bin/env python3
"""
Command Executor MCP Tool / 命令执行器 MCP 工具

专门负责执行LLM生成的shell命令来创建文件树结构
Specialized in executing LLM-generated shell commands to create file tree structures
"""

import asyncio
import os
import re
import selectors
import signal
import subprocess
import time
from pathlib import Path
from typing import List, Dict
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio

# 创建MCP服务器实例 / Create MCP server instance
app = Server("command-executor")


def _get_env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < minimum:
        return default
    return value


_MAX_OUTPUT_CHARS = _get_env_int("DEEPCODE_SHELL_MAX_OUTPUT_CHARS", 20000, minimum=1000)
_MAX_CAPTURE_BYTES = _get_env_int(
    "DEEPCODE_SHELL_MAX_CAPTURE_BYTES",
    _MAX_OUTPUT_CHARS * 8,
    minimum=4096,
)
_REDACTION_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bAuthorization:\s*Bearer\s+[^\s]+"), "Authorization: Bearer ***"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_\.=:+/]{10,}"), "Bearer ***"),
    (re.compile(r"\bsk-proj-[A-Za-z0-9]{10,}\b"), "sk-proj-***"),
    (re.compile(r"\bsk-[A-Za-z0-9]{10,}\b"), "sk-***"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{10,}\b"), "sk-ant-***"),
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{10,}\b"), "AIza***"),
    (
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:API_KEY|ACCESS_KEY|SECRET_KEY|TOKEN|PASSWORD)[A-Z0-9_]*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s]+)"
        ),
        r"\1=***",
    ),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "-----BEGIN PRIVATE KEY-----***-----END PRIVATE KEY-----",
    ),
]


def _redact_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _REDACTION_RULES:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "\n... (truncated)\n"


def _sanitize_output(value: str) -> str:
    if not value:
        return ""
    return _truncate_text(_redact_text(value), _MAX_OUTPUT_CHARS)


def _append_capped_chunk(buffer: bytearray, chunk: bytes, limit_bytes: int) -> bool:
    if len(buffer) >= limit_bytes:
        return True
    remaining = limit_bytes - len(buffer)
    if len(chunk) > remaining:
        buffer.extend(chunk[:remaining])
        return True
    buffer.extend(chunk)
    return False


def _decode_output(buffer: bytearray, *, truncated: bool) -> str:
    data = bytes(buffer)
    text = data.decode("utf-8", errors="replace")
    if truncated:
        text += "\n... (output truncated at capture limit)\n"
    return text


def _run_command_capped_output(
    command: str, working_directory: str, timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    def _terminate_process_tree(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if hasattr(os, "killpg"):
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except Exception:
            process.kill()

    process = subprocess.Popen(
        command,
        shell=True,
        cwd=working_directory,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout_seconds
    output_limit_hit = False
    stdout_truncated = False
    stderr_truncated = False
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    selector = selectors.DefaultSelector()

    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    if process.stderr is not None:
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")

    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_tree(process)
                process.wait(timeout=1)
                raise subprocess.TimeoutExpired(command, timeout_seconds)

            events = selector.select(timeout=min(0.1, remaining))
            if not events:
                continue

            for key, _ in events:
                stream = key.fileobj
                chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
                if not chunk:
                    selector.unregister(stream)
                    continue

                if key.data == "stdout":
                    stdout_truncated = (
                        _append_capped_chunk(stdout_buffer, chunk, _MAX_CAPTURE_BYTES)
                        or stdout_truncated
                    )
                else:
                    stderr_truncated = (
                        _append_capped_chunk(stderr_buffer, chunk, _MAX_CAPTURE_BYTES)
                        or stderr_truncated
                    )

                if (stdout_truncated or stderr_truncated) and not output_limit_hit:
                    output_limit_hit = True
                    _terminate_process_tree(process)
    finally:
        selector.close()

    try:
        result_code = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        result_code = process.wait(timeout=1)

    stdout_text = _decode_output(stdout_buffer, truncated=stdout_truncated)
    stderr_text = _decode_output(stderr_buffer, truncated=stderr_truncated)
    if output_limit_hit:
        stderr_text += "\n... (process killed after output limit exceeded)\n"

    return subprocess.CompletedProcess(
        args=command,
        returncode=result_code if result_code is not None else 1,
        stdout=stdout_text,
        stderr=stderr_text,
    )


@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    列出可用工具 / List available tools
    """
    return [
        types.Tool(
            name="execute_commands",
            description="""
            执行shell命令列表来创建文件树结构
            Execute shell command list to create file tree structure

            Args:
                commands: 要执行的shell命令列表（每行一个命令）
                working_directory: 执行命令的工作目录

            Returns:
                命令执行结果和详细报告
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "commands": {
                        "type": "string",
                        "title": "Commands",
                        "description": "要执行的shell命令列表，每行一个命令",
                    },
                    "working_directory": {
                        "type": "string",
                        "title": "Working Directory",
                        "description": "执行命令的工作目录",
                    },
                },
                "required": ["commands", "working_directory"],
            },
        ),
        types.Tool(
            name="execute_single_command",
            description="""
            执行单个shell命令
            Execute single shell command

            Args:
                command: 要执行的单个命令
                working_directory: 执行命令的工作目录

            Returns:
                命令执行结果
            """,
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "title": "Command",
                        "description": "要执行的单个shell命令",
                    },
                    "working_directory": {
                        "type": "string",
                        "title": "Working Directory",
                        "description": "执行命令的工作目录",
                    },
                },
                "required": ["command", "working_directory"],
            },
        ),
    ]


@app.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """
    处理工具调用 / Handle tool calls
    """
    try:
        if name == "execute_commands":
            return await execute_command_batch(
                arguments.get("commands", ""), arguments.get("working_directory", ".")
            )
        elif name == "execute_single_command":
            return await execute_single_command(
                arguments.get("command", ""), arguments.get("working_directory", ".")
            )
        else:
            raise ValueError(f"未知工具 / Unknown tool: {name}")

    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"工具执行错误 / Error executing tool {name}: {_sanitize_output(str(e))}",
            )
        ]


async def execute_command_batch(
    commands: str, working_directory: str
) -> list[types.TextContent]:
    """
    执行多个shell命令 / Execute multiple shell commands

    Args:
        commands: 命令列表，每行一个命令 / Command list, one command per line
        working_directory: 工作目录 / Working directory

    Returns:
        执行结果 / Execution results
    """
    try:
        # 确保工作目录存在 / Ensure working directory exists
        Path(working_directory).mkdir(parents=True, exist_ok=True)

        # 分割命令行 / Split command lines
        command_lines = [
            cmd.strip() for cmd in commands.strip().split("\n") if cmd.strip()
        ]

        if not command_lines:
            return [
                types.TextContent(
                    type="text", text="没有提供有效命令 / No valid commands provided"
                )
            ]

        results = []
        stats = {"successful": 0, "failed": 0, "timeout": 0}

        for i, command in enumerate(command_lines, 1):
            try:
                display_command = _redact_text(command)
                # 执行命令 / Execute command
                result = await asyncio.to_thread(
                    _run_command_capped_output,
                    command,
                    working_directory,
                    30,
                )

                if result.returncode == 0:
                    results.append(f"✅ Command {i}: {display_command}")
                    if result.stdout.strip():
                        results.append(
                            f"   输出 / Output: {_sanitize_output(result.stdout.strip())}"
                        )
                    stats["successful"] += 1
                else:
                    results.append(f"❌ Command {i}: {display_command}")
                    if result.stderr.strip():
                        results.append(
                            f"   错误 / Error: {_sanitize_output(result.stderr.strip())}"
                        )
                    stats["failed"] += 1

            except subprocess.TimeoutExpired:
                results.append(f"⏱️ Command {i} 超时 / timeout: {display_command}")
                stats["timeout"] += 1
            except Exception as e:
                results.append(
                    f"💥 Command {i} 异常 / exception: {display_command} - {_sanitize_output(str(e))}"
                )
                stats["failed"] += 1

        # 生成执行报告 / Generate execution report
        summary = generate_execution_summary(working_directory, command_lines, stats)
        final_result = summary + "\n" + "\n".join(results)

        return [types.TextContent(type="text", text=final_result)]

    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"批量命令执行失败 / Failed to execute command batch: {_sanitize_output(str(e))}",
            )
        ]


async def execute_single_command(
    command: str, working_directory: str
) -> list[types.TextContent]:
    """
    执行单个shell命令 / Execute single shell command

    Args:
        command: 要执行的命令 / Command to execute
        working_directory: 工作目录 / Working directory

    Returns:
        执行结果 / Execution result
    """
    try:
        # 确保工作目录存在 / Ensure working directory exists
        Path(working_directory).mkdir(parents=True, exist_ok=True)

        # 执行命令 / Execute command
        result = await asyncio.to_thread(
            _run_command_capped_output,
            command,
            working_directory,
            30,
        )

        # 格式化输出 / Format output
        output = format_single_command_result(command, working_directory, result)

        return [types.TextContent(type="text", text=output)]

    except subprocess.TimeoutExpired:
        return [
            types.TextContent(
                type="text",
                text=f"⏱️ 命令超时 / Command timeout: {_redact_text(command)}",
            )
        ]
    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"💥 命令执行错误 / Command execution error: {_sanitize_output(str(e))}",
            )
        ]


def generate_execution_summary(
    working_directory: str, command_lines: List[str], stats: Dict[str, int]
) -> str:
    """
    生成执行总结 / Generate execution summary

    Args:
        working_directory: 工作目录 / Working directory
        command_lines: 命令列表 / Command list
        stats: 统计信息 / Statistics

    Returns:
        格式化的总结 / Formatted summary
    """
    return f"""
命令执行总结 / Command Execution Summary:
{'='*50}
工作目录 / Working Directory: {working_directory}
总命令数 / Total Commands: {len(command_lines)}
成功 / Successful: {stats['successful']}
失败 / Failed: {stats['failed']}
超时 / Timeout: {stats['timeout']}

详细结果 / Detailed Results:
{'-'*50}"""


def format_single_command_result(
    command: str, working_directory: str, result: subprocess.CompletedProcess
) -> str:
    """
    格式化单命令执行结果 / Format single command execution result

    Args:
        command: 执行的命令 / Executed command
        working_directory: 工作目录 / Working directory
        result: 执行结果 / Execution result

    Returns:
        格式化的结果 / Formatted result
    """
    display_command = _redact_text(command)
    output = f"""
单命令执行 / Single Command Execution:
{'='*40}
工作目录 / Working Directory: {working_directory}
命令 / Command: {display_command}
返回码 / Return Code: {result.returncode}

"""

    if result.returncode == 0:
        output += "✅ 状态 / Status: SUCCESS / 成功\n"
        if result.stdout.strip():
            output += f"输出 / Output:\n{_sanitize_output(result.stdout.strip())}\n"
    else:
        output += "❌ 状态 / Status: FAILED / 失败\n"
        if result.stderr.strip():
            output += f"错误 / Error:\n{_sanitize_output(result.stderr.strip())}\n"

    return output


async def main():
    """
    运行MCP服务器 / Run MCP server
    """
    # 通过stdio运行服务器 / Run server via stdio
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="command-executor",
                server_version="1.0.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
