# V1 Delivery Plan (Codex-Executed)

## Purpose

This plan defines how to reach a shareable **v1** of the local TTS platform where a non-developer can:

1. install and run the local service,
2. choose and download a voice model,
3. install the Chrome extension and use it end-to-end.

The plan assumes implementation work is primarily executed by **Codex** (agent-driven delivery), with human review at milestone boundaries.

---

## Baseline and Scope

Current repository status indicates strong MVP coverage (service API, jobs, streaming contract, CLI, extension prototype) with a short list of remaining Phase 7 gaps around chunk heuristics, incremental streaming behavior, cancellation semantics, and documentation.

### In scope for v1

- Local service packaging and lifecycle management.
- Voice model catalog, download, verification, installation, and activation.
- Chrome extension installability and first-run setup quality.
- Operational hardening (security defaults, observability, diagnostics).
- Release process, versioning, and support docs.

### Out of scope for v1

- Multi-machine orchestration.
- Cloud deployment.
- Distributed job queue/storage.
- Full reader-mode pipeline overhaul.
- Broad UX redesign beyond first-run and reliability improvements.

---

## Operating Model: Codex-First Delivery

To make the schedule predictable when coding is handled by Codex, each milestone is structured as:

1. **Spec packet** (human-owned): concise acceptance criteria + constraints.
2. **Codex implementation cycle**:
   - create/update code,
   - update tests,
   - run lint/tests,
   - produce commit + PR.
3. **Human review gate**:
   - API/UX/security check,
   - merge or request a focused follow-up PR.
4. **Pilot validation** in a clean environment.

### Rules for Codex execution

- Keep PRs small and scoped to one acceptance target.
- Preserve architecture boundaries (API/application/domain/infrastructure).
- Avoid contract-breaking changes unless explicitly approved.
- Add/adjust tests for all behavior changes.
- Update user-facing docs whenever setup or flows change.

---

## Milestones and Timeline (8 weeks)

## Milestone 1 — Service Productization Baseline (Week 1-2)

**Goal:** move from dev-oriented startup to user-installable local service behavior.

### Deliverables

- Close remaining Phase 7 must-do items that block external use.
- Define and freeze v1 public API/WS contract.
- Improve startup/readiness diagnostics for predictable support outcomes.
- Align status docs so repository truth is consistent.

### Codex task slices

- Slice 1: docs + task board synchronization.
- Slice 2: cancellation semantics test coverage and contract clarification.
- Slice 3: streaming behavior adjustments and metrics assertions.
- Slice 4: chunk-plan heuristic improvements with focused tests.

### Exit criteria

- No open “must-fix before external user” items.
- CI test/lint baseline green.

---

## Milestone 2 — Local Service Packaging (Week 3-4)

**Goal:** one predictable install/start path for non-developers.

### Deliverables

- Installer/bootstrap command for supported OS targets.
- Service lifecycle commands: install, start, stop, status, uninstall.
- Automatic config bootstrap (token file, config file, sane defaults).
- Health diagnostics command that explains failures in plain language.

### Codex task slices

- Slice 1: packaging command design and CLI UX spec.
- Slice 2: bootstrap implementation and config/token generation.
- Slice 3: OS-specific service wrappers (priority: one OS first, then expand).
- Slice 4: smoke tests and troubleshooting docs.

### Exit criteria

- Fresh machine setup succeeds via documented steps without manual code edits.

---

## Milestone 3 — Model Catalog and Download Manager (Week 5)

**Goal:** users can select and install models from a supported catalog.

### Deliverables

- Catalog format (id, language, quality, size, checksum, license, source URL).
- Download + checksum verification + unpack/install flow.
- Manifest update flow and default-voice activation.
- Status UI/CLI output for install progress and failures.

### Codex task slices

- Slice 1: catalog schema + validation.
- Slice 2: downloader + integrity checks.
- Slice 3: install path + manifest update integration.
- Slice 4: tests for success/failure/corrupt artifact cases.

### Exit criteria

- User can install a model and successfully synthesize without manual file placement.

---

## Milestone 4 — Chrome Extension Installability and First-Run UX (Week 6)

**Goal:** straightforward extension setup for external users.

### Deliverables

- Updated extension install guide (step-by-step, copy-safe).
- First-run checklist in popup: base URL, token validation, voice discovery, test playback.
- Clear allow-list guidance and error hints.
- Recovery behavior validation (stop/restart/reopen).

### Codex task slices

- Slice 1: popup state and first-run status panel.
- Slice 2: health/voice/auth test workflow and errors.
- Slice 3: integration cleanup for offscreen playback recovery.
- Slice 4: extension validation script enhancements.

### Exit criteria

- A new user can install extension and play selection audio in <10 minutes.

---

## Milestone 5 — Release Hardening and v1 Launch (Week 7-8)

**Goal:** confidence and supportability for sharing with others.

### Deliverables

- Cross-platform test matrix for service + extension flow.
- Performance and reliability thresholds (first audio latency, stream stability).
- Security baseline review for localhost assumptions.
- Versioned release (`v1.0.0`), changelog, rollback instructions.

### Codex task slices

- Slice 1: benchmark/reporting consolidation.
- Slice 2: security and config defaults pass.
- Slice 3: release notes + installation docs.
- Slice 4: final launch checklist automation.

### Exit criteria

- Go/No-Go checklist passes with at least one external pilot user.

---

## Go/No-Go Checklist for v1.0.0

All items must pass:

- Service install/start/stop/status works on supported platforms.
- Model selection/download/install/activation works with validation.
- Chrome extension setup and playback works on clean profile.
- `/v1/health` clearly reports degraded vs ready state.
- Critical paths are covered by automated tests.
- Security defaults are safe for localhost sharing use case.
- User docs are complete: install, update, troubleshoot, uninstall.

---

## Artifact Plan (What Codex should produce each week)

For each accepted scope packet, Codex should deliver:

1. One focused PR per slice.
2. Updated tests and command outputs.
3. Updated docs for any changed workflow.
4. A short “operator notes” section in PR body:
   - what changed,
   - what to verify manually,
   - known limitations.

Recommended PR size target: **200-500 LOC** net change whenever possible.

---

## Risk Register and Mitigations

- **Risk:** contract drift while moving quickly.
  - **Mitigation:** explicit contract freeze + schema tests on API/WS payloads.
- **Risk:** model download failures or corrupt artifacts.
  - **Mitigation:** checksum verification + resumable downloads + clear rollback.
- **Risk:** extension breaks due to browser constraints.
  - **Mitigation:** preserve current auth compatibility pattern; expand troubleshooting.
- **Risk:** large Codex-generated PRs become hard to review.
  - **Mitigation:** enforce small slices and milestone gates.

---

## Immediate Next Actions (This Week)

1. Create milestone board issues from this plan.
2. Label blockers as `v1-critical`.
3. Start Milestone 1 Slice 1 (docs/task alignment) and Slice 2 (cancellation semantics tests).
4. Schedule first external pilot test date after Milestone 3 completion.

