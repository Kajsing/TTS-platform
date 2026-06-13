# V1 Readiness Audit

This file tracks readiness for the local reader v1 goal: a Windows-friendly
localhost TTS service, local model-management flow, and Chrome extension reader
for long web-page text.

## Automated Gates

- `python3 scripts/release_check.py` runs ruff, pytest, security-default
  verification, local service bootstrap smoke, extension validation, extension
  packaging, and Windows bundle packaging.
- `python3 scripts/check_security_defaults.py` verifies fail-closed local
  service defaults and ignored local artifacts.
- `python3 scripts/check_extension.py` verifies manifest references,
  popup/offscreen assets, extension wiring, manifest policy, privacy/layering
  boundaries, and JavaScript syntax when `node` is installed.
- `python3 scripts/check_extension_onboarding.py` verifies popup onboarding
  controls, Chrome-extension origin allow-list snippet compatibility, and the
  health/voice-discovery service snapshot used by the popup.
- `python3 scripts/check_extension_reader_flow.py` verifies long-page reader
  wiring for `Speak Page`, progress, page-capture metadata, `Resume Page`, and
  previous/next section navigation, plus stop/restart recovery and popup
  reopen-state signals, then streams a generated thousand-word article through
  the local service WebSocket contract.
- `python3 scripts/check_local_service_bootstrap.py` creates an isolated
  first-run repo root, runs `setup-local`, starts the local service on loopback,
  runs the public-contract smoke, and shuts the service down.
- `python3 scripts/check_model_management_flow.py` creates a local
  model-artifact catalog, runs catalog-list, install, activate, service smoke
  with the installed voice, read-only model readiness diagnostics, and remove
  without external downloads.
- `python3 scripts/smoke_service.py --token-file config/token.txt
  --stream-text-repeat 200 --min-stream-text-chunks 2` verifies the public
  contract against a running service with separate page-scale WebSocket stream
  input.
- `python3 scripts/package_windows_bundle.py` builds the local reader handoff
  bundle with service/core source, Windows launchers, config example, docs,
  model manifest, extension source, and validated extension zip.
- `python3 scripts/check_windows_bundle_bootstrap.py` safely extracts a Windows
  local reader bundle, verifies that it does not contain local token/model
  artifacts, checks the embedded extension zip, and runs `setup-local` from the
  extracted source paths.
- `python3 scripts/check_windows_launchers.py` extracts a Windows local reader
  bundle and runs the bundled PowerShell/CMD launchers in setup-only mode when
  Windows launcher executables are available, verifying direct first-run
  config/token creation without starting a long-lived service process. On
  Windows, it also starts both launchers as foreground services on reserved
  loopback ports, runs public-contract smoke, and stops the process trees.
- `python3 scripts/check_windows_bundle_install.py` extracts a Windows local
  reader bundle, creates a temporary `.venv`, installs the extracted package,
  starts the installed `tts serve` entrypoint, runs public-contract smoke, and
  shuts the service down.

## Manual Gates

- Run the Windows launcher scripts directly on an operator machine for manual
  long-running service observation if desired. The extracted-bundle launcher
  setup-only path, foreground launcher smoke, venv install, and installed
  `tts serve` path are automated; extended operator comfort checks remain
  manual.
- Install and activate a real local voice with
  `tts model-install <model-id> --catalog ./models/catalog.json --activate`.
  The local artifact workflow is automated; real acoustic-output readiness
  still needs a real model artifact and runtime outside the default gate. Use
  `tts model-check <model-id>` to verify local manifest/backend assets and
  `sherpa_onnx` runtime availability before expecting real acoustic output.
- Run live smoke against the started service with
  `python3 scripts/release_check.py --live-smoke --token-file config/token.txt
  --stream-text-repeat 200 --min-stream-text-chunks 2`.
- Load `apps/chrome_extension` in Chrome, copy the extension origin into
  `security.allowed_origins`, restart the service, save the token in the popup,
  and confirm actual Chrome popup health plus voice discovery. The static
  popup/origin/service-snapshot contract is automated.
- On a long article page, verify `Speak Page`, progress display, truncation
  metadata, `Resume Page`, `Previous Section`, `Next Section`, stop/restart
  behavior, and popup state after reopening in actual Chrome. The reader-flow contract now
  automates the stop/recovery wiring and popup state fields, while actual
  Chrome playback remains manual.

## Product Choices

- Permanent Windows auto-start/service-manager installation remains undecided;
  do not silently choose NSSM, Task Scheduler, pywin32, or a startup-folder
  mechanism.
- Chrome Web Store signing/publishing remains out of scope for the local
  handoff package until explicitly chosen.
- A richer named reader-mode outline remains a future UX choice; current
  section navigation uses heading offsets and re-extracts active-tab text.

## Known Not Yet Automated

- There is no full automated Chrome MV3 browser harness in the repository; the
  automated onboarding gate does not replace manual Chrome loading/playback.
- JavaScript syntax validation in `scripts/check_extension.py` requires `node`
  to be installed.
- Real acoustic-output readiness requires a real local model install and live
  service smoke outside the default offline release gate.
- Extended foreground PowerShell/CMD launcher observation remains manual; the
  automated gates cover safe extraction, launcher setup-only execution,
  launcher foreground service smoke, `setup-local`, temporary venv
  installation, installed `tts serve`, loopback service startup, and
  stub-backed smoke.
