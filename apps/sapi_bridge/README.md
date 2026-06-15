# TTS Platform SAPI Bridge

This is the post-v1 Windows SAPI 5/TextAloud integration area.

The first slice is a feasibility spike. It does not implement the final
localhost TTS engine yet. Instead, it installs a reversible dummy SAPI voice
token that aliases an existing Windows SAPI voice. This proves whether
TextAloud can enumerate a custom TTS Platform voice token, and whether the
working path needs 64-bit, 32-bit, or both registry views.

## Current Spike

The dummy voice is:

```text
TTS Platform Dummy Voice
```

It copies the engine token values from `TTS_MS_EN-US_ZIRA_11.0`, so speaking
through the dummy voice still uses Microsoft's Zira engine. That is deliberate:
the first question is SAPI registration and TextAloud visibility, not localhost
audio integration.

## Scripts

Check current state:

```powershell
.\scripts\windows\check_sapi_voice.ps1
```

Install the dummy token:

```powershell
.\scripts\windows\install_sapi_voice.ps1
```

Remove the dummy token:

```powershell
.\scripts\windows\remove_sapi_voice.ps1
```

The install/remove scripts write under `HKLM\SOFTWARE\Microsoft\Speech` and
`HKLM\SOFTWARE\WOW6432Node\Microsoft\Speech`, so they must be run from an
elevated PowerShell prompt. The check script does not require elevation.

## Expected First-Run Result

After install:

- `check_sapi_voice.ps1 -RequireInstalled` reports the token in registry.
- The current PowerShell bitness can enumerate `TTS Platform Dummy Voice` via
  `SAPI.SpVoice`.
- If 32-bit PowerShell exists, the check also reports whether 32-bit SAPI can
  enumerate the token.
- TextAloud should list `TTS Platform Dummy Voice` if its bitness matches one
  of the installed registry views.

If TextAloud sees the dummy voice, the next slice is a native SAPI engine DLL
under `apps/sapi_bridge/src/` that implements `ISpTTSEngine` and forwards text
to the localhost service.

## Native Skeleton

`src/` now contains an ATL-free C++ COM DLL skeleton:

- `TtsPlatformSapiEngine.h`
- `TtsPlatformSapiEngine.cpp`
- `dllmain.cpp`
- `TtsPlatformSapiBridge.def`
- `../TtsPlatformSapiBridge.vcxproj`

The skeleton implements `ISpTTSEngine` and `ISpObjectWithToken` enough to
return a short generated PCM tone through `ISpTTSEngineSite::Write`. It does
not call the localhost service yet.

Check whether the current machine can build it:

```powershell
py -3 scripts\check_sapi_toolchain.py
```

To require a complete native build environment:

```powershell
py -3 scripts\check_sapi_toolchain.py --require-build-tools
```

## Known Limits

- This dummy token is not the final bridge.
- It does not call `http://127.0.0.1:7777`.
- It does not use `config/token.txt`.
- It does not prove audio streaming behavior.
- It may require admin rights because SAPI voice enumeration did not see
  per-user `HKCU` voice tokens on the development machine.
