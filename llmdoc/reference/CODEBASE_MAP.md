---
last_mapped: 2026-02-25T13:53:02Z
last_mapped_commit: 76d30cdac88217ff5919ddd2b93b5546946ded84
language: en
total_files: 259
total_tokens: 468238
---

# Codebase Map

This is a structural navigation map for the DeepCode repository.

If you are new to the repo, start with:

1. `llmdoc/overview/project-overview.md`
2. `llmdoc/architecture/system-overview.md`
3. `workflows/agent_orchestration_engine.py`

## System Overview

```mermaid
flowchart TD
  U[User] --> EP[Entrypoints]

  subgraph EP[Entrypoints]
    DC[deepcode\n deepcode.py:main]
    CLI[cli/main_cli.py:main]
    UI1[new_ui (FastAPI + React)]
    UI2[ui (Streamlit)]
    NB[nanobot (optional)]
  end

  DC --> WFE[workflows/agent_orchestration_engine.py]
  CLI --> WFE
  UI1 --> WFE
  UI2 --> WFE
  NB -->|HTTP| UI1

  WFE --> MCP[MCP servers\n tools/* + npx/uvx]
  WFE --> IMPL[Implementation\n workflows/code_implementation_workflow*.py]

  MCP --> OUT[deepcode_lab/ uploads/ logs/]
  IMPL --> OUT
```

## Directory Structure

Top-level layout (purpose-first):

- `assets/`: Images/media used by READMEs and demos.
- `cli/`: Interactive and non-interactive Python CLI.
- `config/`: Workflow-side MCP tool definition catalogs.
- `deepcode_docker/`: Dockerfile, compose, and entrypoint scripts.
- `nanobot/`: A sibling agent product integrated via Docker.
- `new_ui/`: New web UI (FastAPI backend + React frontend).
- `prompts/`: Prompt templates (the control surface for agents).
- `schema/`: JSON schema for `mcp_agent.config.yaml`.
- `tools/`: Local MCP server implementations and utilities.
- `ui/`: Classic Streamlit UI.
- `utils/`: Shared helpers (LLM config, file processing, logging).
- `workflows/`: Orchestration engine and workflow implementations.

## Module Guide

### Root

**Purpose**: Packaging, main launcher, and global config.

**Key files**:

- `deepcode.py`: top-level launcher (`deepcode` console script).
- `README.md`: main documentation.
- `requirements.txt`: Python dependencies.
- `mcp_agent.config.yaml`: MCP + LLM runtime config.
- `mcp_agent.secrets.yaml`: secrets (gitignored).
- `setup.py`: packaging + console entrypoint (`deepcode=deepcode:main`).

### `cli/` (Python CLI)

**Purpose**: Provide an interactive terminal UX and direct pipeline invocation.

**Entrypoints**:

- `cli/main_cli.py:main`: argument parsing and mode routing.
- `cli/cli_app.py:CLIApp`: interactive session loop and high-level UX.
- `cli/workflows/cli_workflow_adapter.py:CLIWorkflowAdapter`: bridges CLI to
  `workflows/agent_orchestration_engine.py`.

**Typical flow**:

- CLI parses `--file/--url/--chat/--requirement`.
- CLI initializes MCP runtime.
- Adapter calls one of:
  - `execute_multi_agent_research_pipeline` (file/url)
  - `execute_chat_based_planning_pipeline` (chat)
  - `execute_requirement_analysis_workflow` (requirement)

### `workflows/` (Orchestration And Pipelines)

**Purpose**: Core multi-agent workflow orchestration.

**Primary orchestrator**:

- `workflows/agent_orchestration_engine.py`

Key public entrypoints:

- `execute_multi_agent_research_pipeline`
- `execute_chat_based_planning_pipeline`
- `execute_requirement_analysis_workflow`

**Implementation workflows**:

- `workflows/code_implementation_workflow.py:CodeImplementationWorkflow`
- `workflows/code_implementation_workflow_index.py:CodeImplementationWorkflowWithIndex`

**Agents (submodules)**:

- `workflows/agents/`: segmentation, requirement analysis, memory agents, etc.

**Plugins (user-in-loop)**:

- `workflows/plugins/`: hook points and integration used by the New UI.

### `tools/` (MCP Servers)

**Purpose**: Local MCP server processes providing tools.

Configured in:

- `mcp_agent.config.yaml:mcp.servers.*`

Examples:

- `tools/code_implementation_server.py`: file operations and command execution.
- `tools/document_segmentation_server.py`: segment/stream large documents.
- `tools/git_command.py`: clone/download repos.
- `tools/pdf_downloader.py`: download/move/convert documents.
- `tools/command_executor.py`: execute shell commands (stdio MCP server).

### `new_ui/` (FastAPI + React)

**Purpose**: Modern web UI for running workflows, streaming progress, and
user-in-loop interactions.

Backend:

- `new_ui/backend/main.py`: FastAPI app and router mounting.
- `new_ui/backend/services/workflow_service.py`: calls workflow entrypoints.

Frontend:

- `new_ui/frontend/src/main.tsx`: React entry.
- `new_ui/frontend/src/App.tsx`: routes.

Dev scripts:

- `new_ui/scripts/start_dev.sh`

### `ui/` (Classic Streamlit UI)

**Purpose**: Legacy UI that directly dispatches into workflows.

Entrypoints:

- `ui/streamlit_app.py:main`

Workflow bridge:

- `ui/handlers.py:process_input_async` (routes `chat` vs non-chat).

### `deepcode_docker/` (Docker Packaging)

**Purpose**: Build and run DeepCode as a containerized web app.

Key files:

- `deepcode_docker/Dockerfile`: builds frontend assets and bundles Python app.
- `deepcode_docker/docker-compose.yml`: runs DeepCode + nanobot.
- `deepcode_docker/docker-entrypoint.sh`: starts uvicorn or CLI mode.

### `nanobot/` (Optional Integrated Agent)

**Purpose**: Separate agent product that can call DeepCode workflows via HTTP.

Integration points:

- `deepcode_docker/docker-compose.yml`: sets `DEEPCODE_API_URL` for nanobot.
- `nanobot/nanobot/agent/loop.py`: registers DeepCode tools when env is set.
- `nanobot/nanobot/agent/tools/deepcode.py`: DeepCode HTTP tool client.

### `config/` And `schema/`

**Purpose**: Tool-definition catalogs and config schema.

- `config/mcp_tool_definitions.py`: workflow-side tool schemas.
- `config/mcp_tool_definitions_index.py`: index-focused tool schemas.
- `schema/mcp-agent.config.schema.json`: JSON schema for
  `mcp_agent.config.yaml`.

### `prompts/` And `utils/`

**Purpose**: Prompt templates and shared helpers.

- `prompts/code_prompts.py`: major prompt strings used by orchestrators.
- `utils/llm_utils.py`: provider selection, token limits, adaptive configs.
- `utils/file_processor.py`: file/url normalization and workspace plumbing.

## Navigation Guide

Common tasks and where to start:

- Run or debug the main pipeline:
  `workflows/agent_orchestration_engine.py`
- Change LLM provider/models or MCP servers:
  `mcp_agent.config.yaml`
- Add a new MCP tool server:
  1. Implement server under `tools/`
  2. Register it in `mcp_agent.config.yaml:mcp.servers.*`
  3. If workflows need static tool schema, update `config/mcp_tool_definitions*.py`
- Modify the New UI API:
  `new_ui/backend/api/routes/*` and `new_ui/backend/services/*`
- Modify the Classic UI:
  `ui/layout.py`, `ui/components.py`, and `ui/handlers.py`
