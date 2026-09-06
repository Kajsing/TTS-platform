# Service Center voice library implementation

Status: T2 installation foundation implemented, 2026-09-06. The desktop voice
tab, expanded catalog, preview and service-default controls are **not yet
implemented**. This document records the local bridge contract for that UI.

## Local boundary

`tts_service.model_manager` is a fixed-purpose local subprocess, not an HTTP or
MCP server. The desktop will select the trusted repository/Python runtime using
the existing launcher configuration, with fixed argument lists and no shell
interpolation. Python remains responsible for the catalog, assets and manifest;
the existing CLI implementation is reused. No new network management endpoint,
authentication mode or synthesis backend is introduced.

Commands:

```text
python -m tts_service.model_manager list --repo-root <repository>
python -m tts_service.model_manager install --repo-root <repository>
    --package-id <catalog-id> --catalog-fingerprint <reviewed-sha256> --accept-license
```

Paths are fixed beneath that root: `models/catalog.json`, `models/MANIFEST.json`
and `config/config.toml`. The bridge accepts no arbitrary artifact URL, manifest
path, overwrite, removal or combined activation option. Installation requires
explicit package-specific license acceptance and the exact reviewed catalog
fingerprint. Its parsed catalog snapshot is pinned for the operation.

`list` reads bounded catalog/manifest metadata and checks installed asset paths.
It does not load native models, warm up synthesis, change config, download
artifacts or contact the running service. It separates `installed_voices` from
downloadable `packages`, including language, family, size, source/license URLs,
conflicts and availability reasons. `assets_present` is not service readiness
or an audio-quality assertion. Config output contains only validity and the
configured default voice, never tokens or raw config errors.

## Progress and cancellation contract

Each stdout line is JSON with `contract_version: 1` and an `event`:

- `result`: `data` contains inventory or the committed installation outcome.
- `progress`: `phase`, nullable `completed`/`total` byte counts, and `cancellable`.
- `cancelled`: staging was cancelled before commit; previous voices are unchanged.
- `failed`: a sanitized phase-specific message; refresh actual state before retry.

Exit codes are 0 for success, 2 for cancellation, 1 for operation failure.
Invalid CLI arguments remain ordinary argparse errors. Stdout is the protocol;
do not infer success from the process starting or a progress percentage.

Phases are resolving, downloading, verifying, extracting, committing, completed.
Download/verification byte progress is throttled. Extraction is indeterminate
because streaming archives do not provide a reliable overall uncompressed total.
Do not present each extracted file's size as overall installation progress.

The desktop keeps stdin open and writes `{"cancel":true}` followed by a newline
to cancel. EOF, malformed input or oversized input also cancel staging. The
operation checks cancellation between bounded download/hash/extraction chunks;
network I/O has a 10-second inactivity timeout and a cooperative 30-minute
operation budget. OS I/O/DNS can delay a checkpoint; this is not a hard wall-clock
kill deadline. The host must retain the helper handle while awaiting cancellation.

Commit is non-cancellable. A cancellation arriving before its last checkpoint
still cancels; one arriving after commit begins cannot undo a committed package.
Do not kill the helper or release serialization because a UI observation timer
expired. Refresh inventory after an uncertain/lost terminal result. Closing the
voice dialog must not discard the install owner or create a second writer.

## Publication and preservation

The installer keeps existing URL/redirect/peer checks, SHA-256 checks and archive
path/type/size quotas. Downloads and extraction are staged. The GUI path also
requires structural backend validation and nonempty assets of the expected file
or directory type. These checks do not claim that ONNX loading or audible
synthesis has passed.

Before publication, compare the original manifest bytes under a nonblocking
cross-process lock. A concurrent change aborts rather than overwriting it. CLI
removal uses that same lock. Write the full manifest to a flushed same-directory
temporary file and replace it atomically; preserve unknown root fields and
unrelated voice entries. Invalid entries are rejected, never silently discarded.
On a caught publication failure, remove the newly staged package and restore the
previous package where explicit legacy CLI overwrite was requested. The GUI
does not offer overwrite. Redirected package directories are rejected.

This is failure/cancellation-safe staging, not a power-loss transaction across
multiple filesystem paths. A forced OS/process termination can leave a staging
or backup directory for review; the UI must not silently delete/reuse uncertain
directories. The tiny persistent `.MANIFEST.json.lock` is intentional, avoiding
lock-inode races; it contains no credentials and is Git-ignored.

Catalog entries may provide `voices`, a list of unique IDs, names, languages and
nonnegative `speaker_id` values. All variants inherit the package's verified
assets/license. Include the package ID as its default voice for existing CLI
compatibility. One package publishes all entries in one manifest replacement.
CLI removal refuses to delete shared assets while other voice entries reference
them; explicit overwrite refuses to drop unlisted dependent voices.

Installation returns `activation: restart_required`; it neither edits the
configured default nor changes the active service. The future UI must distinguish
service-default selection from Reader's saved voice preference and use the
existing activity-aware explicit restart path. Preview must avoid overlapping
Reader playback or active exports.

## Remaining T2 work

- Connect the local bridge to the WPF installed/package library and progress UI.
- Expand the catalog only with primary-source artifact hashes, accurate sizes,
  supported model layouts and voice-specific license terms.
- Add guarded fixed-text preview and clearly separated service-default selection.
- Test helper lifetime, cancellation and install states in the desktop, then
  publish and smoke-test the exact Reader shortcut target while safely closed.

No real model download, license acceptance or production voice/config mutation
is needed for automated smoke tests; use synthetic archives and isolated roots.
