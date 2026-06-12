# V1 Delivery Plan

## Purpose

This plan defines the remaining path to a shareable v1 of the local TTS
platform where a non-developer can:

1. install and run the local service,
2. choose, download, install, activate, and remove a voice model,
3. install the Chrome extension and use it end-to-end,
4. diagnose common setup failures without editing source code.

The plan is agent-friendly, but it should not assume a single Codex surface.
Codex may run locally in the CLI, desktop app, IDE, GitHub/cloud, or with
project-specific tools enabled. Durable repository rules live in `AGENTS.md`;
surface-specific capabilities are used when available and are reported in the
work summary.

## Baseline and Scope

The repository already has the MVP platform shape:

- localhost FastAPI service
- token auth, origin checks, and rate limiting
- sync, async job, and WebSocket streaming contracts
- CLI and benchmark tooling
- Chrome MV3 prototype
- manifest-backed voice discovery
- real-backend integration groundwork
- shared chunk planning
- early local model catalog/install/remove helpers

### In Scope for v1

- Local service packaging and lifecycle management.
- Voice model catalog, download, verification, installation, activation, and
  removal.
- Chrome extension installability and first-run setup quality.
- Operational hardening: security defaults, diagnostics, docs, and test
  coverage.
- Release process, versioning, changelog, and rollback instructions.

### Out of Scope for v1

- Multi-machine orchestration.
- Cloud deployment.
- Distributed job queue/storage.
- Full reader-mode pipeline overhaul.
- Broad UX redesign beyond first-run and reliability improvements.

## Agent Operating Model

Each work slice should be coherent and reviewable:

1. inspect the current worktree and relevant files,
2. implement the smallest vertical slice that satisfies the acceptance target,
3. add or update tests,
4. update docs for workflow or user-facing behavior changes,
5. run lint/tests or the documented local equivalent,
6. report commands, results, assumptions, deviations, and next steps.

Commit and PR behavior depends on the active user request and Codex surface:

- If the user explicitly asks for commits, create one focused commit per slice.
- If the user asks for a PR and GitHub tooling is available, open or prepare a
  PR according to the active GitHub workflow.
- If GitHub tooling is not available, provide a PR-ready message instead.
- If the user did not ask for commits, leave the worktree uncommitted and state
  exactly what changed.

Stop and ask before changing product direction, architecture, security model,
licensing model, paid/cloud dependency requirements, or destructive filesystem
state. Small local implementation details may be chosen autonomously when they
preserve the accepted plan and are documented in the summary.

## Validation Baseline

Canonical commands:

```bash
python3 -m ruff check .
python3 -m pytest -q
```

Windows equivalent when `python3` is unavailable:

```powershell
py -3 -m ruff check .
py -3 -m pytest -q
```

If a Codex bundled runtime is used because the shell has no usable Python,
report that substitution. Workflow updates should keep `TESTING.md` aligned
with the commands that actually work on supported developer machines.

## Milestone 1: Service Productization Baseline

Goal: move from dev-oriented startup to predictable local service behavior.

Deliverables:

- Close remaining Phase 7 items that block external use.
- Freeze the v1 HTTP and WebSocket contract.
- Improve startup/readiness diagnostics.
- Align status docs with repository truth.

Task slices:

- Docs and task-board synchronization.
- Cancellation semantics coverage and contract clarification.
- Streaming behavior and metrics assertions.
- Chunk-plan heuristic improvements with focused tests.

Exit criteria:

- No open "must fix before external user" items.
- Lint/test baseline is green.

## Milestone 2: Local Service Packaging

Goal: one predictable install/start path for non-developers.

Deliverables:

- Installer/bootstrap command for supported OS targets.
- Service lifecycle commands: install, start, stop, status, uninstall.
- Automatic config bootstrap for config file, token file, and safe defaults.
- Health diagnostics command that explains failures in plain language.

Task slices:

- Packaging command design and CLI UX spec.
- Bootstrap implementation and config/token generation.
- OS-specific service wrapper for the first supported OS.
- Smoke tests and troubleshooting docs.

Exit criteria:

- Fresh-machine setup succeeds via documented steps without manual source edits.

## Milestone 3: Model Catalog and Download Manager

Goal: users can select and manage models from a supported catalog.

Deliverables:

- Catalog format with id, language, quality, size, checksum, license, and source
  URL.
- Download, checksum verification, safe unpacking, and install flow.
- Manifest update flow and default-voice activation.
- Remove flow that cleans installed files and manifest entries.
- Status output for install progress and failures.

Task slices:

- Catalog schema and validation.
- Downloader and integrity checks.
- Install path and manifest update integration.
- Activation and removal flows.
- Tests for success, overwrite refusal, corrupt artifact, unsafe archive, and
  missing-model cases.

Exit criteria:

- User can install, activate, remove, and reinstall a model without manual file
  placement.

## Milestone 4: Chrome Extension Installability and First-Run UX

Goal: straightforward extension setup for external users.

Deliverables:

- Updated extension install guide.
- First-run checklist in the popup: base URL, token validation, voice discovery,
  and test playback.
- Clear allow-list guidance and error hints.
- Recovery behavior validation for stop, restart, and popup reopen.

Task slices:

- Popup state and first-run status panel.
- Health, voice, and auth test workflow.
- Offscreen playback recovery cleanup.
- Extension validation script improvements.

Exit criteria:

- A new user can install the extension and play selected text in under 10
  minutes.

## Milestone 5: Release Hardening and v1 Launch

Goal: confidence and supportability for sharing with others.

Deliverables:

- Cross-platform test matrix for service and extension flow.
- Performance and reliability thresholds.
- Security baseline review for localhost assumptions.
- Versioned release, changelog, and rollback instructions.

Task slices:

- Benchmark/reporting consolidation.
- Security and config-defaults pass.
- Release notes and installation docs.
- Launch checklist automation.

Exit criteria:

- Go/no-go checklist passes with at least one clean-environment pilot.

## Go/No-Go Checklist for v1.0.0

- Service install/start/stop/status works on supported platforms.
- Model selection/download/install/activation/removal works with validation.
- Chrome extension setup and playback works on a clean profile.
- `/v1/health` clearly reports degraded vs ready state.
- Critical paths are covered by automated tests.
- Security defaults are safe for the localhost sharing use case.
- User docs are complete: install, update, troubleshoot, uninstall.

## Current Next Actions

1. Finish and review the current model-management CLI slice.
2. Add `model-activate` with an explicit config-write strategy.
3. Start service packaging with a bootstrap/status command before OS service
   integration.
4. Keep `AGENTS.md`, `README.md`, and `TESTING.md` synchronized whenever the
   agent workflow or setup commands change.
