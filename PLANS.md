# PLANS

## 2026-02-25: Initialize `llmdoc/` via `codemap/init-doc`

- **Owner**: Codex (local)
- **Difficulty**: 1 (Simple)
- **Rationale**:
  - Multi-file doc generation (`llmdoc/**`) but no public API/data-format changes.

### Plan

1. (done) Step 0: Reality-check key entrypoints and repo structure.
2. (done) Step 1: Run `codemap_scout` passes and collect reports under `llmdoc/agent/`.
3. (done) Step 3: Generate foundational docs (project overview + conventions).
4. (done) Step 4: Document a default set of core concepts
   (non-interactive init-doc run).
5. (done) Step 6: Generate `llmdoc/reference/CODEBASE_MAP.md` via `codemap/cartographer`.
6. (done) Step 7: Rebuild `llmdoc/index.md`.
7. (done) Step 5: Cleanup temporary scout reports (`llmdoc/agent/`).
8. (done) Verification: run `markdownlint-cli` on new `llmdoc/**/*.md`
   (+ `PLANS.md`).

### Evidence

- `llmdoc/` initialized with overview, architecture, guides, and reference docs.
- `llmdoc/reference/CODEBASE_MAP.md` generated with file/token totals from
  Cartographer scanner (`uv run scan-codebase.py`).
- Markdown lint: `markdownlint --fix` on `llmdoc/**/*.md` and `PLANS.md` (pass).
