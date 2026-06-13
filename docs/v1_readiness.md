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
  boundaries, local install guidance/icons, and JavaScript syntax when `node`
  is installed.
- `python3 scripts/check_extension_onboarding.py` verifies popup onboarding
  controls, Chrome-extension origin allow-list snippet compatibility, and the
  copyable `tts extension-allow-origin` first-run helper before checking the
  health/voice-discovery service snapshot used by the popup.
- `python3 scripts/check_extension_reader_flow.py` verifies long-page reader
  wiring for `Speak Page`, progress, page-capture metadata, `Resume Page`, and
  `Continue Page`, popup long-page status, state-aware popup controls,
  previous/next section navigation, truncated-page continuation to the first
  known uncaptured section, truncated text-offset continuation without storing
  raw page text, automatic continuation after a truncated segment finishes,
  plus stop/restart recovery and popup reopen-state signals, then streams a
  generated thousand-word article through the local service WebSocket contract.
- `python3 scripts/check_chrome_extension_smoke.py` validates the extension
  static contract, then uses Chrome or Edge through DevTools Protocol when a
  browser is available. It loads the unpacked MV3 extension, starts an isolated
  loopback service with the generated extension origin allow-listed, opens a
  generated long article, verifies content-script page capture and background
  health fetch, starts `Speak Page`, and observes playback state. Without
  Chrome or Edge, or when the local browser/MV3 environment cannot run the
  smoke, it reports a skipped smoke unless `--require-browser` is set.
- `python3 scripts/check_local_service_bootstrap.py` creates an isolated
  first-run repo root, runs `setup-local`, starts the local service on loopback,
  verifies setup next-step guidance, runs the public-contract smoke, and shuts
  the service down. `setup-local` now also reports default catalog readiness and
  can point a development-stub default voice at the concrete default English
  install command before first playback.
- `python3 scripts/check_model_management_flow.py` creates a local loopback
  HTTP model-artifact catalog with a relative artifact URL, runs catalog-list,
  verifies the default `models/catalog.json` path behavior, lists installed
  manifest models offline, runs download/install, activate, service smoke with
  the installed voice, read-only model readiness diagnostics with catalog-aware
  next steps, and remove without external downloads. Model installs require
  `artifact_sha256` by default, with
  `--allow-missing-checksum` reserved for trusted local artifacts. The default
  catalog now includes the English
  `vits-piper-en_US-lessac-medium` sherpa-onnx model, and the installer supports
  the official `tar.bz2` release archive format. `model-check` now reads the
  default catalog and suggests the concrete default English model when the
  configured development stub is not real-backend ready.
- `python3 scripts/smoke_service.py --token-file config/token.txt
  --stream-text-repeat 200 --min-stream-text-chunks 2` verifies the public
  contract against a running service with separate page-scale WebSocket stream
  input.
- `python3 scripts/package_windows_bundle.py` builds the local reader handoff
  bundle with service/core source, Windows launchers, config example, docs,
  model manifest, default model catalog, model-readiness handoff guidance,
  extension source, extension install guide/icons, and validated extension zip.
- `scripts/windows/install_local.ps1` bootstraps an extracted bundle by
  creating `.venv`, installing the local package, and running `setup-local`
  without choosing a persistent service manager.
- `python3 scripts/check_windows_bundle_bootstrap.py` safely extracts a Windows
  local reader bundle, verifies that it does not contain local token/model
  artifacts, checks first-run/model-readiness guide markers, checks the
  embedded extension zip, and runs `setup-local` from the extracted source
  paths with first-run next-step guidance validation.
- `python3 scripts/check_windows_launchers.py` extracts a Windows local reader
  bundle and runs the bundled PowerShell/CMD launchers in setup-only mode when
  Windows launcher executables are available, verifying direct first-run
  config/token creation and setup next-step guidance without starting a
  long-lived service process. On
  Windows, it also starts both launchers as foreground services on reserved
  loopback ports, runs public-contract smoke, and stops the process trees.
- `python3 scripts/check_windows_bundle_install.py` extracts a Windows local
  reader bundle, creates a temporary `.venv`, installs the extracted package,
  validates installed setup next-step guidance, starts the installed
  `tts serve` entrypoint, runs public-contract smoke, and shuts the service
  down. When the bundled install script is present, the check uses it for the
  venv/package/setup stage.

## Manual Gates

- Run the Windows launcher scripts directly on an operator machine for manual
  long-running service observation if desired. The extracted-bundle launcher
  setup-only path, foreground launcher smoke, venv install, and installed
  `tts serve` path are automated; extended operator comfort checks remain
  manual.
- Install and activate the default English local voice with
  `tts model-install vits-piper-en_US-lessac-medium --activate`. For alternate
  catalogs, use
  `tts model-install <model-id> --catalog ./models/catalog.json --activate`.
  The local artifact workflow is automated; real acoustic-output readiness
  still needs a real model artifact and runtime outside the default gate. Use
  `tts setup-local` for catalog-aware first-run guidance, then
  `tts model-list` to inspect installed manifest voices and
  `tts model-check <model-id>` to verify local manifest/backend assets plus
  `sherpa_onnx` runtime availability before expecting real acoustic output.
- Run live smoke against the started service with
  `python3 scripts/release_check.py --live-smoke --token-file config/token.txt
  --stream-text-repeat 200 --min-stream-text-chunks 2`.
- Load `apps/chrome_extension` in Chrome, copy the allow-list command, run
  `tts extension-allow-origin <copied-origin>`, restart the service, save the
  token in the popup, and confirm actual Chrome popup health plus voice
  discovery. The static
  popup/origin/service-snapshot contract is automated, and
  `python3 scripts/check_chrome_extension_smoke.py --require-browser --headed`
  can provide strict local Chrome/MV3 browser smoke evidence on a machine with
  Chrome or Edge installed.
- On a long article page, verify `Speak Page`, progress display, truncation
  metadata, `Resume Page`, `Continue Page`, `Previous Section`,
  `Next Section`, stop/restart behavior, and popup state after reopening in
  actual Chrome if operator comfort evidence is desired. The reader-flow
  contract automates truncated-section continuation, manual and automatic
  truncated text-offset continuation, stop/recovery wiring, and popup state
  fields; the Chrome/MV3 smoke automates one real browser path when Chrome or
  Edge is available.

## Product Choices

- Permanent Windows auto-start/service-manager installation remains undecided;
  do not silently choose NSSM, Task Scheduler, pywin32, or a startup-folder
  mechanism.
- Chrome Web Store signing/publishing remains out of scope for the local
  handoff package until explicitly chosen.
- A richer named reader-mode outline remains a future UX choice; current
  section navigation uses heading offsets and re-extracts active-tab text.

## Known Not Yet Automated

- strict Chrome/MV3 smoke requires Chrome or Edge to be installed and able to
  load the unpacked MV3 extension. The default release gate can skip the
  browser smoke when the local browser environment cannot run it;
  run `python3 scripts/check_chrome_extension_smoke.py --require-browser` when
  a real browser must be present.
- JavaScript syntax validation in `scripts/check_extension.py` requires `node`
  to be installed.
- Real acoustic-output readiness requires a real local model install and live
  service smoke outside the default offline release gate.
- Extended foreground PowerShell/CMD launcher observation remains manual; the
  automated gates cover safe extraction, local install bootstrap, launcher
  setup-only execution, launcher foreground service smoke, `setup-local`,
  temporary venv installation, installed `tts serve`, loopback service startup,
  and stub-backed smoke.
