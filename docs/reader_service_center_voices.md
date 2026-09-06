# Service Center voice library implementation

Status: T2 installation foundation and desktop voice tab implemented and
published, 2026-09-06. Deferred service-default selection is implemented too.
Catalog expansion and preview
remain **incomplete**. The whole Service Center goal remains active.

## Desktop use

### Service default, not Reader preference

Under **Installed**, select a voice with files present and choose **Use as
service default...**. Confirmation explicitly saves it for the next restart.
This changes only this installation's `config/config.toml` `tts.default_voice`;
it does not contact the service, interrupt current/paused reading or exports,
change Reader's preference, or trigger an automatic restart. Use the existing
idle-checked, confirmed **Restart service** separately. The configured default
in this tab is not proof that it is active; Overview reports the running default.

The fixed local bridge adds `set-default` with voice ID, manifest fingerprint and
config fingerprint. It requires an existing valid config and one installed voice
with present assets. Config/manifest changes invalidate the reviewed choice.
A manifest lock serializes registry operations and a config lock serializes
these saves. Conventional `[tts]` scalar layouts preserve comments and newlines;
unsupported dotted/inline/multiline layouts are refused. Reparsing verifies that
all other TOML values are identical. This is not a general config editor.

On Windows, an empty same-directory staging file receives the original DACL
before any config content is written. After flush and a final snapshot check,
`ReplaceFileW` preserves original security/attributes without IGNORE_ACL flags.
A private backup protects its documented partial-failure paths. Failed recovery
retains the `.config.toml.*.recovery` file for review; successful saves normally
remove it. Those local staging/lock/recovery files are excluded from Git.
EFS-encrypted configs and linked config files are refused rather than weakening
their protection. POSIX staging preserves file mode. External non-cooperating
editors can still race the last snapshot check; do not edit config concurrently.

Primary Windows behavior references: [GetFileSecurityW](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-getfilesecurityw),
[SetFileSecurityW](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-setfilesecurityw),
and [ReplaceFileW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew).
Tests cover custom protected DACLs on staging/final files, byte-preserving edits,
stale intent, missing assets, cancellation and caught replacement failures.

### Packages and installation

Open **Service Center > Voices**. Installed lists local voice metadata and file
presence separately from the running engine. Available packages shows the local
catalog, model family, language, size and availability. Select a package, open
its source/voice-license links and explicitly accept that package's license to
enable Download and install. Selection or inventory changes reset acceptance.
Already-installed/conflicting packages cannot be overwritten from this menu.

Progress and Cancel install remain visible after closing/reopening the panel:
the tray host owns the operation. Exiting Service Center is refused until the
helper actually exits, including after cancellation. Service lifecycle actions
are inhibited during model operations; the running service and Reader playback
are not changed by installation. Small windows can scroll to all review/actions.

The .NET adapter uses the launcher directory and the same Python preference as
`scripts/windows/run_service.ps1`: `TTS_PLATFORM_PYTHON`, local `.venv`, `py -3`,
then `python`. It sets the existing source paths and UTF-8 on the child only,
uses separate arguments without a shell and hides the helper console. It drains
bounded JSON lines/stderr, requires a compatible terminal event plus matching
exit code and retains serialization until real process exit. A read-only list
helper may be stopped on timeout; an installer is only cancelled through stdin.
Raw stderr/command lines are never surfaced as UI errors.

## Local boundary

`tts_service.model_manager` is a fixed-purpose local subprocess, not an HTTP or
MCP server. The desktop selects the trusted repository/Python runtime using
the existing launcher configuration, with fixed argument lists and no shell
interpolation. Python remains responsible for the catalog, assets and manifest;
the existing CLI implementation is reused. No new network management endpoint,
authentication mode or synthesis backend is introduced.

Commands:

```text
python -m tts_service.model_manager list --repo-root <repository>
python -m tts_service.model_manager install --repo-root <repository>
    --package-id <catalog-id> --catalog-fingerprint <reviewed-sha256> --accept-license
python -m tts_service.model_manager set-default --repo-root <repository>
    --voice-id <installed-id> --manifest-fingerprint <reviewed-sha256>
    --config-fingerprint <reviewed-sha256>
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
configured default voice and an opaque config fingerprint, never tokens or raw
config errors.

## Progress and cancellation contract

Each stdout line is JSON with `contract_version: 1` and an `event`:

- `result`: `data` contains inventory, committed installation, or saved default.
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
configured default nor changes the active service. The separate default control
distinguishes service configuration from Reader's saved voice preference. Use the
existing activity-aware explicit restart path to apply it. Preview must avoid overlapping
Reader playback or active exports.

## Remaining T2 work

- Expand the catalog only with primary-source artifact hashes, accurate sizes,
  supported model layouts and voice-specific license terms.
- Add guarded fixed-text preview. Deferred service-default selection is implemented
  and tested separately from Reader's own preference.
- Extend the desktop tests for preview behavior and rerun exact-shortcut
  publication after it is implemented. The current voice-library/default
  UI/helper lifetime and cancellation tests already pass.

No real model download, license acceptance or production voice/config mutation
is needed for automated smoke tests; use synthetic archives and isolated roots.
