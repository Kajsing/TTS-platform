# V1 Readiness Audit

This file tracks readiness for the local reader v1 goal: a Windows-friendly
localhost TTS service, local model-management flow, and Chrome extension reader
for long web-page text.

## Automated Gates

- `python3 scripts/release_check.py` runs ruff, pytest, security-default
  verification, local service bootstrap smoke, extension validation, extension
  packaging, and Windows bundle packaging. Use
  `--node-executable <path-to-node> --require-js-syntax` when the release gate
  must fail instead of skipping extension JavaScript syntax checks.
- `python3 scripts/check_security_defaults.py` verifies fail-closed local
  service defaults and ignored local artifacts.
- `python3 scripts/check_extension.py` verifies manifest references,
  popup/offscreen assets, extension wiring, manifest policy, privacy/layering
  boundaries, local install/troubleshooting guidance and icons, and JavaScript
  syntax when `node` is installed.
- `python3 scripts/check_extension_onboarding.py` verifies popup onboarding
  controls, Chrome-extension origin allow-list snippet compatibility, and the
  copyable `tts extension-allow-origin` first-run helper before checking the
  health, backend-readiness, default-voice, and voice-discovery service
  snapshot used by the popup.
- `python3 scripts/check_extension_reader_flow.py` verifies long-page reader
  wiring for `Speak Page`, progress, page-capture metadata, `Resume Page`, and
  `Continue Page`, popup long-page status, state-aware popup controls,
  previous/next section navigation, best-root selection for pages with multiple
  reader candidates, truncated-page continuation to the first known uncaptured
  section, truncated text-offset continuation without storing raw page text,
  automatic continuation after a truncated segment finishes, filtered fallback
  capture for flat pages, plus stop/restart recovery and popup reopen-state
  signals, then streams a generated thousand-word article through the local
  service WebSocket contract.
- `python3 scripts/check_chrome_extension_smoke.py` validates the extension
  static contract, then uses Chrome or Edge through DevTools Protocol when a
  browser is available. It loads the unpacked MV3 extension, discovers the
  registered extension id from the temporary Chrome profile, opens the
  extension popup as the CDP execution context, starts an isolated loopback
  service with the generated extension origin allow-listed, opens a generated
  long article, verifies content-script page capture and background health
  fetch, starts `Speak Page`, and observes playback state. Without Chrome or
  Edge, or when the local browser/MV3 environment cannot run the smoke, it
  reports a skipped smoke unless `--require-browser` is set;
  extension-registration skips include a short observed profile-extension id
  diagnostic.
- `python3 scripts/check_local_service_bootstrap.py` creates an isolated
  first-run repo root, runs `setup-local`, starts the local service on loopback,
  verifies setup next-step guidance, runs the public-contract smoke, and shuts
  the service down. `setup-local` now also reports default catalog readiness and
  can point a development-stub default voice at the concrete default English
  install command before first playback.
- `python3 scripts/check_model_management_flow.py` creates a local loopback
  HTTP model-artifact catalog with a relative artifact URL, runs catalog-list,
  verifies operator-facing catalog summary metadata and the default
  `models/catalog.json` path behavior, lists installed manifest models offline,
  runs download/install with artifact-size result metadata, activate, service
  smoke with the installed voice, read-only model readiness diagnostics with
  catalog-aware next steps, pre-download overwrite refusal, and remove without
  external downloads. Model installs require
  `artifact_sha256` by default, with
  `--allow-missing-checksum` reserved for trusted local artifacts. The default
  catalog now includes the English
  `vits-piper-en_US-lessac-medium` sherpa-onnx model, and the installer supports
  the official `tar.bz2` release archive format. `model-check` now reads the
  default catalog and suggests the concrete default English model when the
  configured development stub is not real-backend ready.
- `tts setup-local` and `tts model-list` expose `sherpa_onnx` runtime status
  plus `numpy` callback dependency status, and include the matching
  `python -m pip install ...` guidance when real local playback is relevant but
  a runtime package needed by real async/stream paths is missing.
- `python3 scripts/smoke_service.py --token-file config/token.txt
  --stream-text-repeat 200 --min-stream-text-chunks 2` verifies the public
  contract against a running service with separate page-scale WebSocket stream
  input.
- `python3 scripts/package_windows_bundle.py` builds the local reader handoff
  bundle with service/core source, Windows launchers, config example, docs,
  model manifest, default model catalog, model-readiness handoff guidance,
  extension source, extension install/troubleshooting guides, icons, and a
  validated extension zip.
  Pass `--node-executable <path-to-node> --require-js-syntax` to package scripts
  when standalone package builds must fail instead of skipping extension
  JavaScript syntax validation.
- `scripts/windows/install_local.ps1` bootstraps an extracted bundle by
  creating `.venv`, installing the local package plus its base dependencies,
  and running `setup-local` without choosing a persistent service manager.
  `-InstallRealRuntime` is an explicit opt-in path for installing the optional
  `.[real]` runtime dependencies into that `.venv` during the same bootstrap;
  `-NoDependencies` is reserved for already provisioned environments.
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
  venv/package/setup stage and expects base dependencies to be installed by
  default. `--install-real-runtime` exercises the optional `.[real]` install
  path only when a test machine should take that heavier dependency step;
  `--no-dependencies` is reserved for pre-provisioned test environments.

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
  `sherpa_onnx` and `numpy` runtime availability before expecting real
  acoustic output.
  When prompted, install the runtime in the active environment with
  `python -m pip install -e ".[real]"` when both runtime packages are missing;
  targeted single-package guidance (`python -m pip install sherpa-onnx` or
  `python -m pip install numpy`) is still reported when only one dependency is
  absent. In extracted Windows bundles, the operator can also run
  `.\scripts\windows\install_local.ps1 -InstallRealRuntime` during first-run
  bootstrap.
- Run `python3 scripts/demo_real_voice.py --python-executable
  .venv/Scripts/python.exe` to reproduce the real English voice demo in ignored
  `dist/real-demo`; it installs the default catalog model there, starts a
  temporary service, runs public-contract smoke with `--token-file`, writes a
  WAV, and stops the service. Install `.[real]` in the active environment first
  with `python -m pip install -e ".[real]"` when the runtime packages are not
  present, or pass `--install-real-runtime` to let the demo install that extra
  before setup/model checks. Use
  `python3 scripts/release_check.py --real-voice-demo --install-real-runtime`
  when the same demo should be included as an explicit opt-in release gate.
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
  a compatible Chrome, Chrome for Testing, Chromium, or Edge build.
- On a long article page, verify `Speak Page`, progress display, truncation
  metadata, `Resume Page`, `Continue Page`, `Previous Section`,
  `Next Section`, stop/restart behavior, and popup state after reopening in
  actual Chrome if operator comfort evidence is desired. The reader-flow
  contract automates truncated-section continuation, manual and automatic
  truncated text-offset continuation, best-root selection, filtered fallback
  capture, stop/recovery wiring, and popup state fields; the Chrome/MV3 smoke
  automates one real browser path when a compatible browser build is available.

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
  load the unpacked MV3 extension from automation. The default release gate can
  skip the browser smoke when the local browser environment cannot run it; run
  `python3 scripts/check_chrome_extension_smoke.py --require-browser` when a
  real browser must be present. Branded Chrome 137+ may ignore
  `--load-extension`; for strict automated evidence, pass Chrome for Testing or
  Chromium with `--browser-executable`. Missing extension-registration skips
  include observed profile-extension ids to separate unloaded unpacked
  extensions from generic CDP startup failures.
- JavaScript syntax validation in `scripts/check_extension.py` runs when
  `node` is available on `PATH`, or when `--node-executable`/`TTS_PLATFORM_NODE`
  points at Node.js. Use `--require-js-syntax` when missing Node.js should fail
  the gate instead of reporting a skip.
- Real acoustic-output readiness remains outside the default offline release
  gate because it can install runtime dependencies and download a real model.
  Use the explicit `--real-voice-demo` release-check flag when a machine should
  provide that evidence.
- Extended foreground PowerShell/CMD launcher observation remains manual; the
  automated gates cover safe extraction, local install bootstrap, launcher
  setup-only execution, launcher foreground service smoke, `setup-local`,
  temporary venv installation, installed `tts serve`, loopback service startup,
  and stub-backed smoke.
