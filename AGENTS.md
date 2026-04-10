# AGENTS.md

## Golden Commands

```bash
python3 -m pytest -q
python3 -m ruff check .
python3 scripts/dev_run.py
```

## Codex Workflow Files

Use these files as the Codex workflow source of truth:

- `docs/codex/Prompt.md`: frozen project spec
- `docs/codex/Plan.md`: execution order and milestone acceptance criteria
- `docs/codex/Implement.md`: operating rules for Codex loops
- `docs/codex/Documentation.md`: live status, decisions, smoke commands, and resume context

## Engineering Rules

- Keep code and code comments in English.
- Keep architecture layers separate: API, application, domain, infrastructure.
- Prefer small, reviewable changes over broad rewrites.
- Add or update tests when behavior changes.
- Do not introduce backend-specific logic into API contracts.
- Treat localhost security as part of the product, not an optional extra.
- Treat Windows as the target runtime platform. Current Codex work may run inside WSL during development, so avoid Linux-only assumptions in code, paths, scripts, and docs.

## Definition of Done

- Code is implemented and understandable.
- Relevant tests exist and pass.
- Public contracts are explicit.
- Documentation is updated when architecture or workflow changes.
- Logging and failure modes are reasonable for the current phase.
