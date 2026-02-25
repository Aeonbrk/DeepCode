# Configuration

DeepCode configuration is primarily driven by two files in the repo root.

## `mcp_agent.config.yaml`

This file controls:

- MCP servers (process launch): `mcp.servers.*`
  - Local Python servers under `tools/*.py`
  - External servers via `npx` (for example filesystem and Brave search)
  - External servers via `uvx` (fetch server)
- Default search backend: `default_search_server`
- Document segmentation settings: `document_segmentation.enabled` and
  `document_segmentation.size_threshold_chars`
- LLM provider routing: `llm_provider` and provider model names
- Logging: `logger.*` (including JSONL files under `logs/`)

Schema:

- `schema/mcp-agent.config.schema.json`

## `mcp_agent.secrets.yaml`

This file contains API keys and provider credentials.

- OpenAI: `openai.api_key` (and optional `openai.base_url`)
- Google: `google.api_key`
- Anthropic: `anthropic.api_key`

This file is gitignored by default.

Template:

- `mcp_agent.secrets.yaml.example`

## Docker Configuration

`deepcode_docker/docker-compose.yml` mounts both config and secrets into the
container as read-only files.

It also mounts persistent folders:

- `deepcode_lab/` (generated workspaces)
- `uploads/` (uploaded files)
- `logs/` (JSONL logs)

## Nanobot Configuration (Docker)

When running the integrated DeepCode + nanobot stack, nanobot reads its own
config from:

- `nanobot_config.json` (mounted to `/root/.nanobot/config.json`)

`DEEPCODE_API_URL` is injected into the nanobot container so it can call DeepCode
HTTP APIs.
