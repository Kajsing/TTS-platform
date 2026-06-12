# Implement

This file is the Codex runbook for day-to-day work in this repository.

## Operating Rules

- Read `Prompt.md`, `Plan.md`, and `Documentation.md` before making changes.
- Follow `Plan.md` milestone by milestone.
- Keep diffs tightly scoped.
- Do not expand scope without recording why in `Documentation.md`.
- Run validation after every milestone.
- If validation fails, fix it immediately before moving on.
- Continuously update `Documentation.md` while working.
- When uncertain, prefer preserving existing behavior over broad rewrites.
- Do not treat intermediate progress as completion.
- After validation passes, commit and push the completed slice by default.
- Before finishing, verify every "done when" criterion in `Prompt.md` or mark what remains in `Documentation.md`.

## Repo Rules To Preserve

- Keep code and code comments in English.
- Keep architecture layers separate: API, application, domain, infrastructure.
- Add or update tests when behavior changes.
- Do not introduce backend-specific logic into API contracts.
- Treat localhost security as part of the product baseline.
- Preserve Windows as the target runtime platform and avoid Linux-only assumptions just because the current loop may be running in WSL.
- Keep CLI and benchmark flows on the public service contract.
- Keep browser-specific behavior inside `apps/chrome_extension/` unless the existing localhost auth/origin contract explicitly requires a small accommodation.

## Loop Checklist

1. Open `docs/codex/Prompt.md`, `docs/codex/Plan.md`, and `docs/codex/Documentation.md`.
2. Pick the first incomplete milestone in `Plan.md`.
3. Record the current target and any assumptions in `Documentation.md`.
4. Implement the smallest reviewable slice that moves that milestone forward.
5. Add or update tests if behavior changed.
6. Run the milestone validation commands.
7. If anything fails, fix it before doing new work.
8. Update `Documentation.md` with what changed, what passed, and what remains.
9. Commit the completed slice with a focused message.
10. Push the branch to `origin`.

## Scope Control

- Do not silently delete important instructions from older docs.
- If older docs conflict, preserve the strongest current source and record the conflict explicitly in `Documentation.md`.
- Do not invent requirements that are not supported by repo docs, code, or tests.
- Do not rewrite unrelated parts of the app to make a milestone feel cleaner.
- Prefer additive documentation and focused refactors over broad structural churn.

## Finish Checklist

- Confirm the current milestone acceptance criteria are satisfied.
- Confirm the relevant validation commands passed, or record exactly what did not pass.
- Update `Documentation.md` so the next Codex loop can resume without re-discovery.
- Check `Prompt.md` done-when criteria and mark anything still missing.
- Commit and push the run unless validation failed, credentials are missing, the
  branch/remote state is unsafe, or the user explicitly asked not to.
- Report the pushed branch and commit hash.
