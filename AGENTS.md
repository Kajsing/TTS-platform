# AGENTS.md

## Scope

This file is the durable repository guidance for Codex and other coding agents.
Keep it short enough to load reliably. Put project-specific engineering rules
here; use a separate skill/plugin or project `.codex/` config only when a
workflow needs reusable tooling or mechanical enforcement.

## Golden Commands

```bash
python3 -m pytest -q
python3 -m ruff check .
python3 scripts/dev_run.py
```

On Windows, if `python3` resolves to the Microsoft Store alias or is missing,
use the equivalent commands with `py -3`:

```powershell
py -3 -m pytest -q
py -3 -m ruff check .
py -3 scripts/dev_run.py
```

If neither runner is available in the shell, use the Codex bundled Python
runtime when present and report the substitution in the final status.

## Engineering Rules

- Keep code and code comments in English.
- Keep architecture layers separate: API, application, domain, infrastructure.
- Prefer small, reviewable changes over broad rewrites.
- Add or update tests when behavior changes.
- Do not introduce backend-specific logic into API contracts.
- Treat localhost security as part of the product, not an optional extra.
- Use `rg`/`rg --files` for repository searches when available.
- Preserve public HTTP, WebSocket, CLI, and extension contracts unless the user
  explicitly accepts a breaking change.
- Keep model-download, archive-extraction, and path-handling code defensive by
  default. Reject unsafe archives instead of trying to repair them silently.
- Do not add project-local hooks, rules, MCP servers, or `.codex/` config unless
  the user asks for enforceable Codex configuration. Prefer documenting the
  workflow here first.

## Agent Workflow

- Before changing code, inspect the relevant existing files and current
  worktree status.
- Work in coherent vertical slices when the plan is clear: implementation,
  tests, docs, validation, and a concise status.
- Continue autonomously within an accepted plan as long as the product
  direction, architecture, security model, licensing model, and dependency model
  do not change.
- Stop and ask before changing product direction, introducing paid/cloud
  dependencies, changing security defaults, or making a destructive operation.
- Do not commit automatically unless the user explicitly asked for commits or
  the active plan requires them. When commits are requested, keep one clear goal
  per commit and leave a PR-ready summary.
- If local validation requires command substitutions because of the current
  machine, run the equivalent command and report both the attempted canonical
  command and the command that actually ran.
- After frontend or Chrome extension changes, run the repo-native checks and
  use the current Codex browser tooling for smoke testing when a local target is
  available.

## Documentation Rules

- Update `README.md`, `TESTING.md`, or extension docs when setup, validation, or
  user-facing workflows change.
- Update `SECURITY.md` when auth, origin, token, archive, path, or localhost
  trust assumptions change.
- Update `DECISIONS.md` for architecture, security, dependency, or workflow
  choices that future agents need to understand.
- If `DOCUMENTATION.md` or `.logs/` are added later, update them after each
  substantial milestone or complex implementation chunk.

## Definition of Done

- Code is implemented and understandable.
- Relevant tests exist and pass.
- Public contracts are explicit.
- Documentation is updated when architecture or workflow changes.
- Logging and failure modes are reasonable for the current phase.
