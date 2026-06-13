# V1 Readiness Audit

This file tracks readiness for the local reader v1 goal: a Windows-friendly
localhost TTS service, local model-management flow, and Chrome extension reader
for long web-page text.

## Automated Gates

- `python3 scripts/release_check.py` runs ruff, pytest, security-default
  verification, extension validation, extension packaging, and Windows bundle
  packaging.
- `python3 scripts/check_security_defaults.py` verifies fail-closed local
  service defaults and ignored local artifacts.
- `python3 scripts/check_extension.py` verifies manifest references,
  popup/offscreen assets, extension wiring, manifest policy, privacy/layering
  boundaries, and JavaScript syntax when `node` is installed.
- `python3 scripts/smoke_service.py --token-file config/token.txt
  --stream-text-repeat 200 --min-stream-text-chunks 2` verifies the public
  contract against a running service with separate page-scale WebSocket stream
  input.
- `python3 scripts/package_windows_bundle.py` builds the local reader handoff
  bundle with service/core source, Windows launchers, config example, docs,
  model manifest, extension source, and validated extension zip.

## Manual Gates

- Extract the Windows local reader bundle, create a virtualenv, install the
  package, and start the service with `scripts/windows/run_service.ps1` or
  `tts serve`.
- Install and activate a real local voice with
  `tts model-install <model-id> --catalog ./models/catalog.json --activate`.
- Run live smoke against the started service with
  `python3 scripts/release_check.py --live-smoke --token-file config/token.txt
  --stream-text-repeat 200 --min-stream-text-chunks 2`.
- Load `apps/chrome_extension` in Chrome, copy the extension origin into
  `security.allowed_origins`, restart the service, save the token in the popup,
  and confirm service health plus voice discovery.
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

- There is no full automated Chrome MV3 browser harness in the repository.
- JavaScript syntax validation in `scripts/check_extension.py` requires `node`
  to be installed.
- Real acoustic-output readiness requires a real local model install and live
  service smoke outside the default offline release gate.
