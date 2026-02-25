# Coding Conventions

This document describes conventions that are either enforced by repo tooling or
observed in the current codebase.

## Python Formatting And Linting

This repo uses `pre-commit` with Ruff.

- Pre-commit config: `.pre-commit-config.yaml`
- Hooks:
  - `ruff-format`
  - `ruff` with `--fix` and `--ignore=E402`

Recommended workflow:

```bash
pre-commit run -a
```

Notes:

- There is no root-level Ruff config file (`pyproject.toml`, `ruff.toml`, etc.).
  Ruff defaults apply unless configured elsewhere.
- Several modules explicitly set `PYTHONDONTWRITEBYTECODE=1` to avoid `.pyc`
  generation (for example `deepcode.py`, `cli/main_cli.py`).

## Python Style

Observed patterns:

- Prefer explicit, named orchestration entrypoints for workflows (for example
  `workflows/agent_orchestration_engine.py:execute_multi_agent_research_pipeline`).
- Async-first workflow orchestration using `asyncio` and `async def`.
- Configuration is YAML-based and typically loaded through helpers under `utils/`.

## Frontend Conventions (New UI)

The New UI is in `new_ui/`.

- Backend: FastAPI (`new_ui/backend/*`)
- Frontend: React + TypeScript + Vite (`new_ui/frontend/*`)

Local dev relies on Node tooling; see `new_ui/README.md` for the project
structure and scripts.

## Secrets And Credentials

Do not commit secrets.

- `mcp_agent.secrets.yaml` is gitignored.
- `nanobot_config.json` is gitignored.

When adding new providers or keys, keep secrets in those files or in environment
variables, and ensure logs do not print secret values.
