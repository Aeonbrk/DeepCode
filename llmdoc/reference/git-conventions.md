# Git Conventions

This repo does not define strict commit or branch conventions in code.
These are pragmatic defaults to keep history readable.

## Branching

- Use short-lived feature branches for non-trivial work.
- Keep `main` (or the default branch) in a releasable state.

## Commits

- Prefer small, reviewable commits.
- Write commit subjects in imperative mood (for example: "Add New UI status API").
- Include the "why" in the commit body when behavior changes.

## Generated Or Large Artifacts

Do not commit:

- Workspaces and generated outputs (`deepcode_lab/`)
- Logs (`logs/`)
- Secrets (`mcp_agent.secrets.yaml`, `nanobot_config.json`)

These are already covered by `.gitignore`.
