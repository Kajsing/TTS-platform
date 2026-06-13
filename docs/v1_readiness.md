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
- `python3 scripts/check_local_service_bootstrap.py` creates an isolated
  first-run repo root, runs `setup-local`, starts the local service on loopback,
  runs the public-contract smoke, and shuts the service down.
- `python3 scripts/check_model_management_flow.py` creates a local
  model-artifact catalog, runs catalog-list, install, activate, service smoke
  with the installed voice, and remove without external downloads.
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

## Manual Gates

- Create a virtualenv in an extracted Windows local reader bundle, install the
  package, and start the service with `scripts/windows/run_service.ps1` or
  `tts serve` for manual Windows operator verification.
- Install and activate a real local voice with
  `tts model-install <model-id> --catalog ./models/catalog.json --activate`.
  The local artifact workflow is automated; real acoustic-output readiness
  still needs a real model artifact and runtime outside the default gate.
- Run live smoke against the started service with
  `python3 scripts/release_check.py --live-smoke --token-file config/token.txt
  --stream-text-repeat 200 --min-stream-text-chunks 2`.
- Load `apps/chrome_extension` in Chrome, copy the extension origin into
  `security.allowed_origins`, restart the service, save the token in the popup,
  and confirm actual Chrome popup health plus voice discovery. The static
  popup/origin/service-snapshot contract is automated.
- On a long article page, verify `Speak Page`, progress display, truncation
  metadata, `Resume Page`, `Next Section`, stop/restart behavior, and popup
  state after reopening.

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
- Full extracted-bundle virtualenv installation remains manual; the automated
  gates cover safe extraction, `setup-local`, loopback service startup, and
  stub-backed smoke from source paths.
