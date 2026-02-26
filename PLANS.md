# ExecPlan: new_ui Frontend + Backend Stability/Bundle Optimization (2026-02-26)

Status: In Progress
Owner: Codex
Scope: `new_ui/frontend/**`, `new_ui/backend/**`

## Constraints

- Do not modify `vendor/`
- Keep backward compatibility for REST API paths/fields
- Prefer low-risk and reversible changes
- No new frontend dependencies unless strictly required

## Difficulty Assessment

- Score: 4
- Level: Complex
- Rationale:
  - Cross-module refactor touching 3+ files/shared abstractions: Yes
  - Concurrency/cancellation/WebSocket lifecycle behavior: Yes
  - Ambiguous integration contracts between workflow WS and code-stream WS: Yes
  - Compatibility risk for runtime protocol (`cancelled` terminal event): Yes

## Planned Waves

1. Wave 1 implementation (parallel, disjoint ownership)

- Frontend worker: lint config fixes, task recovery route, real navigation
  blocking, lazy route imports, pure function extraction + vitest smoke test
- Backend worker: execution lock + cwd guard, cancellation
  semantics/checkpoints, websocket terminal semantics, code-stream dedupe,
  config atomic write, respond route plugin check

1. Wave 2 review (parallel, read-only)

- Frontend adversarial review for routing/state/test regressions
- Backend adversarial review for lock/cancel/ws protocol regressions

1. Verification

- Frontend: `npm run build`, `npm run lint`, `npm run test -- --run`
- Backend: `python -m compileall -q new_ui/backend`

## Acceptance Criteria

- Frontend lint passes with explicit ESLint config and no warnings
- Navigation guard blocks SPA route transitions and supports proceed/reset
- `/chat-planning` recovery navigation bug fixed to `/chat`
- Route-level lazy loading is in place and build chunk profile improves
- Backend workflow execution serialized via global lock around workflow execution
- Cancellation is terminal and cannot regress to progress/completed updates
- Workflow WebSocket closes on `complete|error|cancelled`
- Code-stream WS no longer forwards generic progress messages
- Config writes are atomic and safe (`yaml.safe_dump` + temp file + replace)
