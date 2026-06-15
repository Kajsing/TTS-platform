# Windows SAPI 5 Bridge Plan

This document records the post-v1 plan for making the local TTS platform
available to Windows SAPI 5 applications such as TextAloud.

## Goal

Expose the local TTS platform as an optional Windows SAPI 5 voice so legacy
desktop TTS applications can use the same localhost service and installed
models as the Chrome extension.

Target user flow:

```text
TextAloud -> SAPI 5 voice -> TTS Platform SAPI bridge -> localhost TTS service -> audio
```

Expected first real target:

- TextAloud 3.x sees a voice such as `TTS Platform Lessac High`.
- Selecting that voice in TextAloud reads short English text through
  `http://127.0.0.1:7777`.
- The bridge uses the existing local token and default voice, currently
  `vits-piper-en_US-lessac-high` on the development machine.
- No model files are committed to Git.

## Why SAPI 5

TextAloud and similar Windows desktop readers commonly enumerate SAPI voices.
Microsoft's SAPI 5 engine model allows third-party TTS engines to register as
COM objects. A TTS engine implements `ISpTTSEngine` for synthesis calls and
`ISpObjectWithToken` so SAPI can create and initialize the engine. During
`ISpTTSEngine::Speak`, the engine writes audio back through the SAPI engine
site.

Reference material:

- https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms717037(v=vs.85)
- https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms719558(v=vs.85)
- https://github.com/gexgd0419/NaturalVoiceSAPIAdapter

The GitHub project above is useful as prior art for a SAPI adapter, but any
reuse must be reviewed for licensing and architecture before copying code.

## Project Placement

Treat this as an optional Windows integration, not core service behavior.

Proposed layout:

```text
apps/
  sapi_bridge/
    README.md
    src/
      TtsPlatformSapiEngine.cpp
      TtsPlatformSapiEngine.h
      dllmain.cpp
      registry.rgs
    tests/
    TtsPlatformSapiBridge.vcxproj

scripts/
  windows/
    install_sapi_voice.ps1
    remove_sapi_voice.ps1
    check_sapi_voice.ps1

docs/
  sapi_bridge.md
```

The bridge should remain a client of the service, like the Chrome extension.
Do not move SAPI-specific logic into core API contracts unless a real shared
need appears.

## Security Model

The bridge should preserve the local-reader security shape:

- Connect only to `127.0.0.1:7777` by default.
- Use the existing bearer token from `config/token.txt` for MVP.
- Do not disable service token auth.
- Do not weaken Chrome origin allow-listing or browser security defaults.
- Do not require cloud or paid dependencies.

SAPI calls are native local COM calls and do not carry a browser `Origin`.
Origin allow-listing is therefore expected to be irrelevant for this bridge.
Token auth still applies.

Future hardening may store the token in Windows Credential Manager instead of
reading the repo-local token file.

## Implementation Phases

### Phase 1: Feasibility Spike

Build the smallest native SAPI voice that proves registration and TextAloud
visibility.

Scope:

- Create an isolated `apps/sapi_bridge/` skeleton.
- Register one SAPI 5 voice token.
- Implement enough COM/SAPI plumbing for TextAloud to enumerate the voice.
- In `Speak`, return dummy PCM or a simple generated tone.
- Add install/remove/check PowerShell scripts.

Expected result:

- TextAloud lists the custom voice.
- A minimal speak request does not crash TextAloud.
- We know whether TextAloud 3.x requires a 32-bit SAPI engine.

Stop condition:

- If TextAloud cannot see the voice, resolve COM registration and bitness
  before integrating the localhost service.

### Phase 2: Localhost TTS Integration

Connect the SAPI voice to the existing TTS service.

MVP approach:

- Collect plain text fragments from `ISpTTSEngine::Speak`.
- Send a synchronous request to `/v1/tts`.
- Decode/forward PCM/WAV audio to `ISpTTSEngineSite`.
- Use the configured default voice unless a bridge setting overrides it.

Expected result:

- TextAloud reads short text through `vits-piper-en_US-lessac-high`.
- TextAloud can use its existing output/save paths if they rely on normal SAPI
  audio output.

Use synchronous HTTP first. WebSocket streaming is useful later, but a sync path
is simpler and better suited to the first SAPI proof.

### Phase 3: Long Text Behavior

Make long TextAloud documents practical.

Add:

- Chunking for long input.
- Stop/abort handling.
- Timeouts and retry boundaries.
- Service rate-limit awareness.
- Basic progress/events if TextAloud reacts to them.

Expected result:

- Long articles do not freeze TextAloud indefinitely.
- Stop/cancel works at reasonable chunk boundaries.
- The service remains protected against runaway local clients.

### Phase 4: Voice Metadata And Settings

Make the bridge feel installable.

Add:

- Voice metadata such as name, language, age/gender fields when useful.
- One SAPI voice per selected installed model, or one generic `TTS Platform`
  voice that follows the service default.
- User-local config for base URL and token source.
- Clear install/remove scripts.

Expected result:

- TextAloud displays a sensible voice entry.
- Users can install/remove without manual registry editing.

### Phase 5: Hardening

Prepare the integration for normal local use.

Checks:

- Build x86 and/or x64 as required by TextAloud.
- Install/remove registry smoke.
- Service unavailable path.
- Bad token path.
- Long text path.
- Uninstall leaves no broken SAPI token.

## Main Risks

- Bitness: TextAloud 3.x may be 32-bit, which likely requires an x86 SAPI
  engine even on 64-bit Windows.
- COM registration: SAPI voice tokens and COM classes must be registered
  correctly, possibly with per-user vs machine-wide differences.
- Installer permissions: machine-wide registration may need admin. Prefer
  per-user registration if SAPI/TextAloud supports it reliably.
- Responsiveness: sync `/v1/tts` is simple but can block during long input.
  Chunking and abort support are required before calling this production-ready.
- Rate limiting: TextAloud may issue many requests during long documents.
  Bridge chunking must not fight the service's local safety defaults.

## Recommended First Slice

Start with Phase 1 only:

1. Add `apps/sapi_bridge/` skeleton and build notes.
2. Add install/remove/check scripts under `scripts/windows/`.
3. Register one dummy SAPI voice.
4. Verify TextAloud can see it.
5. Verify a dummy speak request returns audio or at least does not crash.

Do not integrate the localhost service until TextAloud visibility and bitness
are proven.

## Acceptance Criteria For The Spike

- `check_sapi_voice.ps1` reports the registered voice token.
- TextAloud lists the voice.
- TextAloud can trigger `Speak` without crashing.
- Install/remove scripts are reversible.
- Docs record whether the working build is x86, x64, or both.

## First-Run Findings

The first implementation pass found:

- `cl`, `msbuild`, and `vswhere` were not available on the development machine,
  so a native C++ COM DLL could not be built in this pass.
- A temporary `HKCU\SOFTWARE\Microsoft\Speech\Voices\Tokens` dummy token was
  not enumerated by `SAPI.SpVoice`.
- A temporary `HKCU\SOFTWARE\WOW6432Node\Microsoft\Speech\Voices\Tokens`
  dummy token was also not enumerated by 32-bit `SAPI.SpVoice`.
- Writing `HKLM` SAPI voice tokens requires elevated PowerShell.

Because of those findings, the first committed spike provides reversible
machine-scope install/remove/check scripts. The user should run the install
script from an elevated PowerShell prompt when ready to test whether TextAloud
lists `TTS Platform Dummy Voice`.

The second implementation pass added a native C++ SAPI engine skeleton:

- `apps/sapi_bridge/TtsPlatformSapiBridge.vcxproj`
- `apps/sapi_bridge/src/TtsPlatformSapiEngine.h`
- `apps/sapi_bridge/src/TtsPlatformSapiEngine.cpp`
- `apps/sapi_bridge/src/dllmain.cpp`
- `apps/sapi_bridge/src/TtsPlatformSapiBridge.def`

The skeleton is ATL-free, implements `ISpTTSEngine` and
`ISpObjectWithToken`, and returns a short generated PCM tone through
`ISpTTSEngineSite::Write`. It does not call `/v1/tts` yet.

`scripts/check_sapi_toolchain.py` now reports whether the current machine can
attempt a native MSVC build. It checks PATH, Visual Studio install locations,
`vswhere` when available, Windows SDK include roots, and `winget`
availability. The native skeleton is ATL-free and avoids `sphelper.h`, so the
required build inputs are `cl`, `msbuild`, `sapi.h`, `sapiddk.h`, and the
`.vcxproj`; install Visual Studio Build Tools 2022 with Desktop development
with C++ and the Windows SDK before building the DLL.

The current `winget` package id is `Microsoft.VisualStudio.2022.BuildTools`.
The repo guidance uses the C++ workload plus Windows 10 SDK component because
that is enough for the ATL-free SAPI bridge skeleton:

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --source winget --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.Windows10SDK.19041 --includeRecommended"
```

The build script still does not install global prerequisites automatically. It
only reports this command and exits cleanly in non-strict mode when MSBuild is
missing.

The native registration path now has a working X86 verification path:

- `scripts\windows\build_sapi_bridge.ps1` builds Win32 and/or x64 with MSBuild.
- `scripts\windows\install_sapi_native_voice.ps1` registers the built DLL as
  an `InprocServer32` COM class and installs a machine-scope
  `TTS Platform Native Dummy Voice` SAPI token.
- `scripts\windows\check_sapi_native_voice.ps1` checks the native token, CLSID,
  `InprocServer32`, and DLL path.
- `scripts\windows\remove_sapi_native_voice.ps1` removes the native token and
  COM class registration.

The install/remove scripts still require elevated PowerShell for HKLM writes.

Build verification on 2026-06-15 after installing Visual Studio Build Tools
2022:

- `scripts\windows\build_sapi_bridge.ps1 -Platform Both -Configuration Release -RequireBuildTools`
  built both `Win32` and `x64` DLLs with 0 warnings and 0 errors.
- Generated DLLs:
  - `apps\sapi_bridge\build\Win32\Release\TtsPlatformSapiBridge.dll`
  - `apps\sapi_bridge\build\x64\Release\TtsPlatformSapiBridge.dll`
- The first build attempt showed why the native skeleton should avoid
  `sphelper.h`: that header pulls in ATL (`atlbase.h`). The bridge now uses
  `sapiddk.h` for `ISpTTSEngine` and remains ATL-free.
- Codex could not install the native token itself because its shell was not
  elevated. Run the install/check scripts from an Administrator Developer
  PowerShell.
- Manual X86 registration from an Administrator Developer PowerShell succeeded:
  `check_sapi_native_voice.ps1 -Architecture X86` reported the token,
  CLSID, `InprocServer32`, and registered DLL path present and valid.
- X64 native registration was not installed during this test.

The native X86 registration command that matched the manual TextAloud test:

```powershell
cd C:\project\TTS-platform
.\scripts\windows\build_sapi_bridge.ps1 -Platform Both -Configuration Release -RequireBuildTools
.\scripts\windows\install_sapi_native_voice.ps1 -Architecture X86 -DllPath .\apps\sapi_bridge\build\Win32\Release\TtsPlatformSapiBridge.dll
.\scripts\windows\check_sapi_native_voice.ps1 -Architecture X86 -RequireInstalled
```

If TextAloud does not list or play the X86 native voice, repeat the install and
check commands with `-Architecture X64` and the x64 DLL path.

## Manual TextAloud Verification

Manual verification on 2026-06-15 confirmed:

- Running `scripts\windows\install_sapi_voice.ps1` from an elevated
  PowerShell prompt installed the dummy machine-scope voice token.
- TextAloud 3.0.117 displayed a `TTS Platform` provider node.
- Under that provider, TextAloud listed `TTS Platform Dummy Voice`.
- TextAloud playback produced Microsoft Zira audio through the dummy voice,
  which is expected because this spike aliases the existing Zira SAPI engine.

This satisfies the first feasibility question: TextAloud can see a custom
TTS Platform SAPI voice token when it is installed machine-wide. The next slice
can move from token visibility to a real native SAPI engine DLL.

Manual native verification on 2026-06-15 confirmed:

- Running `scripts\windows\install_sapi_native_voice.ps1 -Architecture X86`
  from an Administrator Developer PowerShell installed
  `TTS Platform Native Dummy Voice`.
- `scripts\windows\check_sapi_native_voice.ps1 -Architecture X86` reported:
  token exists, COM class exists, `InprocServer32` exists, and the registered
  DLL path points to
  `apps\sapi_bridge\build\Win32\Release\TtsPlatformSapiBridge.dll`.
- TextAloud 3.0.117 displayed `TTS Platform Native Dummy Voice` under the
  `TTS Platform` provider.
- TextAloud playback produced the native dummy tone, described by the user as a
  single "dut".

This satisfies the native Phase 1 acceptance criteria for X86: TextAloud can
enumerate the custom native voice, instantiate the COM engine, call `Speak`,
and receive dummy PCM audio without crashing. The evidence also strongly
suggests this TextAloud 3.x installation is using 32-bit SAPI. The next slice
can connect the X86 native engine to the localhost `/v1/tts` service.

## Commit Strategy

Keep this in small, reviewable commits:

1. `docs: plan sapi bridge integration`
2. `feat: add sapi bridge skeleton`
3. `feat: register dummy sapi voice`
4. `feat: connect sapi bridge to local service`
5. `test: add sapi bridge smoke checks`

Do not commit downloaded model assets or local machine registry exports.
