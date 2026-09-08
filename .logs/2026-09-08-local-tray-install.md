# Local Reader tray and service installation

User requested a compiled Reader, a root shortcut to its tray mode, and the
working local service. The user selected Kokoro English `af_heart`.

## Installed result

- SDK: .NET 10.0.400 x64 under `%LOCALAPPDATA%/TTSPlatform/dotnet`, installed
  with the Microsoft-signed [official installer script](https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-install-script).
  The pre-existing system installation had .NET 8 runtimes and no SDK.
- Reader: self-contained Release executable at
  `dist/windows/TTSPlatform.Reader/TtsPlatform.Reader.App.exe`.
- Root shortcut: `TTS Platform Tray.lnk`, target above, arguments `--background`,
  working directory `C:\home\TTS-platform`, embedded executable icon.
  The machine-specific shortcut is excluded through `.git/info/exclude`.
- Service: `.venv` with `.[dev,real]`; localhost `127.0.0.1:7777`, token auth,
  Kokoro `kokoro-en-v1_0-af-heart` as default, existing per-user Reader storage.
  Reader settings refer to the token file, never a copied token value.
- Started with the existing `LocalServiceCoordinator` and
  `LocalServiceProcessControl`, through a local helper under the ignored build
  logs. Launcher ownership was persisted and verified so tray Start/Stop works.
  The service and one tray process remain running. The shortcut starts the tray;
  after a reboot, use its **Start local service** menu. Windows logon autostart
  was not enabled.

## Build and validation

Used `py -3` instead of the Microsoft Store `python3` alias, then the explicit
virtual-environment Python executables. Build command after solution restore:

```powershell
& "$env:LOCALAPPDATA\TTSPlatform\dotnet\dotnet.exe" publish apps\desktop_reader\src\TtsPlatform.Reader.App\TtsPlatform.Reader.App.csproj -c Release -r win-x64 --self-contained true --nologo -p:PublishSingleFile=false -p:DebugType=None -p:DebugSymbols=false -o dist\windows\TTSPlatform.Reader
```

- Solution Release build: zero warnings/errors; 285 .NET tests passed.
- Python: 625 passed, 3 skipped, using `logs/build-tray-20260908/test-venv`
  with `.[dev]` and FastAPI 0.136.3. Ruff passed.
- `scripts/check_desktop_reader.py --require-dotnet --skip-build`: passed
  isolated HTTP Reader operations, temporary portable package and WPF checks.
- The delivered executable passed every existing isolated Service Center
  lifecycle marker, including background startup and article-switch safety.
- Actual root shortcut invoked twice: one executable instance, no main window.
- Live `scripts/smoke_service.py --token-file config/token.txt
  --voice kokoro-en-v1_0-af-heart`: HTTP, job and WebSocket synthesis passed.
- `logs/build-tray-20260908/kokoro-check.wav`: 4.59 seconds, mono PCM16,
  24,000 Hz, peak 12,125. Physical speaker playback was not tested.

## Environment findings and retained evidence

The first Python run had three failures: two tests assume that the real runtime
is absent; another enumerates flat FastAPI routes. A separate base test venv
and local FastAPI 0.136.3 resolved them. FastAPI 0.141.1 installed initially;
[upstream describes the changed router representation from 0.137](https://github.com/fastapi/fastapi/discussions/15791).
Both runtime and test environments use 0.136.3. Project dependency ranges and
test source were not changed. Dependency snapshots are in the ignored build
logs; general compatibility with newer FastAPI remains separate follow-up work.

The shipped Kokoro catalog correctly refused the replaced upstream archive.
The publisher's `tts-models` release asset metadata on 2026-09-08 reports
349,906,910 bytes and SHA-256
`c5f7e2d2caf082bc1d20fb70334a61d99d20b484500aad32e7cf84c128ea3298`.
Saved that metadata and an updated local catalog under
`logs/build-tray-20260908/`, then used the normal installer with checksum and
archive validation enabled. Model structure, runtime loading and synthesis
passed. The shared catalog was not repinned in this installation-only slice.

No model assets or generated machine configuration are committed. The installed
`models/MANIFEST.json` remains a local change required by this installation;
do not discard it as part of documentation cleanup. This build remains for
local use pending the existing repository license decision. U8 and chapter
implementation remain untouched.

## Follow-up: ordinary work-PC session

The user reported an unreachable service and missing local-owner authentication
after opening Reader from Explorer. The original setup and acceptance commands
had run elevated; those results were insufficient evidence for ordinary use.

Verified findings:

- The current service was stopped and port 7777 had no listener.
- A probe launched through the existing Explorer window verified
  `elevated=false`. It could read the configured repository token, but the
  Reader settings created by the elevated setup were absent in that session,
  despite the same logical `%LOCALAPPDATA%` path. This proves a context-dependent
  view; the exact Windows/profile-management mechanism was not established.
- Creating the settings in the ordinary session removed that setup gap.
  Capturing the normal service launch exposed `PermissionError: [WinError 5]`
  for the Kokoro `model.onnx` file.
- The installed package root had a protected DACL granting owner rights,
  SYSTEM and Administrators, and its owner was Administrators. Descendant model
  files inherited those entries. The ordinary user lacked access to the model.

Repair was limited to an inheritable Modify grant for the current user's SID
on `models/voices/kokoro-en-v1_0-af-heart`, preserving its existing permissions.
The root's previous SDDL is saved in the ignored `model-acl-repair.json`.
Used the existing .NET settings store and ownership-aware service controller
from a self-contained local helper launched by Explorer, with an explicit
refusal to run the setup wrapper elevated. No company policy, firewall,
autostart, application source or shared catalog changed.

Final ordinary-session evidence under `logs/build-tray-20260908`:

- `normal-user-diagnostic.json`: original missing-settings observation and
  readable token, with no token value recorded.
- `ordinary-launcher-error.log`: exact denied model-file access.
- `normal-bootstrap-result.json`: `elevated=false`, return code 0.
- `normal-service-start.log`: Ready, selected Kokoro voice, verified launcher
  ownership. The process is owned by the ordinary session.
- `normal-live-smoke.json`: successful authenticated HTTP, job and stream
  synthesis. The first run's default 50-ms job polling received HTTP 429 under
  the existing 30-requests/minute setting. Retried after the window expired with
  `--poll-interval-ms 1000`; the rate limit itself was preserved.
- `normal-verification.json`: smoke return code 0, 3.10-second PCM WAV,
  peak 11,971; physical speaker playback was not exercised.
- The user closed/reopened Reader and explicitly confirmed it now shows Ready.

Reader and service are left running in the ordinary session. Future local
installation validation must include that same context, rather than relying
only on a successful elevated launch. No code behavior changed, so the prior
unit-suite results were supplemented with these relevant live checks.
