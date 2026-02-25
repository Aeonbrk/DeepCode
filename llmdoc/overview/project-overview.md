# Project Overview

DeepCode is an agentic coding/research automation project. It focuses on turning
research papers (PDF/URL) or natural-language requirements (chat) into a working
codebase via a multi-agent orchestration pipeline.

## What You Run

DeepCode exposes multiple user-facing entrypoints.

### Docker (default `deepcode`)

- Docker stack definition: `deepcode_docker/docker-compose.yml`
- Container entrypoint: `deepcode_docker/docker-entrypoint.sh`
- Web app: FastAPI backend serving a built React frontend (New UI)

The container runs:

- `python -m uvicorn new_ui.backend.main:app ...`

### Local New UI (`deepcode --local`)

- Launcher: `deepcode.py:main`
- Backend: `new_ui/backend/main.py` (FastAPI)
- Frontend: `new_ui/frontend/*` (React + Vite)

Local dev starts two processes:

- Backend on `http://localhost:8000`
- Frontend on `http://localhost:5173`

### Classic Streamlit UI (`deepcode --classic`)

- Streamlit UI lives under `ui/`
- Orchestration bridge: `ui/handlers.py` dispatches into
  `workflows/agent_orchestration_engine.py`

### Python CLI (`python cli/main_cli.py ...`)

- CLI router: `cli/main_cli.py:main`
- Primary CLI app: `cli/cli_app.py:CLIApp`
- Workflow adapter: `cli/workflows/cli_workflow_adapter.py:CLIWorkflowAdapter`

Key CLI input flags:

- `--file/-f` (local file)
- `--url/-u` (paper URL)
- `--chat/-t` (requirements)
- `--requirement/-r` (guided requirement analysis)

### Nanobot Integration (Docker)

This repo includes a `nanobot/` service wired to call DeepCode over HTTP.

- Compose service: `deepcode_docker/docker-compose.yml` (`nanobot`)
- nanobot registers DeepCode tools when `DEEPCODE_API_URL` is set:
  `nanobot/nanobot/agent/loop.py`
- DeepCode tool implementations (HTTP client):
  `nanobot/nanobot/agent/tools/deepcode.py`

## Core Pipeline

The central orchestrator is:

- `workflows/agent_orchestration_engine.py:execute_multi_agent_research_pipeline`

Related entrypoints:

- Chat pipeline:
  `workflows/agent_orchestration_engine.py:execute_chat_based_planning_pipeline`
- Requirement analysis:
  `workflows/agent_orchestration_engine.py:execute_requirement_analysis_workflow`

Implementation is handled by:

- `workflows/code_implementation_workflow.py:CodeImplementationWorkflow`
- `workflows/code_implementation_workflow_index.py:CodeImplementationWorkflowWithIndex`

## Configuration And Secrets

- Runtime config: `mcp_agent.config.yaml`
  - MCP server processes (`mcp.servers.*`)
  - LLM provider selection (`llm_provider`) and model names
  - Document segmentation settings (`document_segmentation.*`)
- Secrets: `mcp_agent.secrets.yaml` (gitignored)
  - Provider API keys (OpenAI/Google/Anthropic)
  - Optional OpenAI-compatible `base_url`

## Outputs And Artifacts

Default persistent outputs are stored under gitignored folders:

- `deepcode_lab/`: workspaces / generated code artifacts
- `uploads/`: uploaded files (UI)
- `logs/`: runtime logs (JSONL)
