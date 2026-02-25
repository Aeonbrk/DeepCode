# System Overview

DeepCode is organized around a workflow engine that coordinates multiple agents
and MCP tool servers to transform an input (paper or requirements) into a
generated codebase.

## High-Level Architecture

```mermaid
flowchart TD
  U[User] --> EP[Entrypoints]

  subgraph EP[Entrypoints]
    DC[deepcode (console script)\n deepcode.py:main]
    CLI[Python CLI\n cli/main_cli.py:main]
    UI1[New UI (React + FastAPI)\n new_ui/*]
    UI2[Classic UI (Streamlit)\n ui/*]
    NB[nanobot (optional)\n nanobot/*]
  end

  DC --> WFE[Workflow Engine\n workflows/agent_orchestration_engine.py]
  CLI --> WFE
  UI1 --> WFE
  UI2 --> WFE
  NB -->|HTTP via DEEPCODE_API_URL| UI1

  WFE -->|plans + prompts| IMPL[Implementation Workflows\n workflows/code_implementation_workflow*.py]
  WFE -->|MCP| MCP[MCP Servers\n tools/* + npx/uvx servers]

  MCP --> OUT[Artifacts\n deepcode_lab/ uploads/ logs/]
  IMPL --> OUT
```

## Key Responsibilities

- Entrypoints
  - Select mode (Docker vs local vs CLI vs classic UI) and handle process startup.
  - Normalize inputs (`file://` paths, URLs, chat text).
- Workflow engine
  - Orchestrate phases (analysis, preprocessing, planning, optional indexing,
    implementation).
  - Choose which MCP servers are available per phase (tool filtering).
- MCP tool servers
  - Provide filesystem, downloading, git clone, indexing, segmentation, and
    command execution capabilities.
- Outputs
  - Generated code/workspaces: `deepcode_lab/`
  - Upload staging: `uploads/`
  - Logs: `logs/`
