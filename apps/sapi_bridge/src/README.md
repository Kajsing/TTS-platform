# Native SAPI Engine Placeholder

This directory contains the native SAPI 5 COM DLL engine skeleton.

The current skeleton implements `ISpTTSEngine` and `ISpObjectWithToken` enough
to return a short generated PCM tone. It is not wired to
`http://127.0.0.1:7777` yet.

Next native steps:

1. Install/locate Visual Studio Build Tools with Desktop development with C++.
2. Ensure the Windows SDK SAPI headers (`sapi.h`, `sphelper.h`) are present.
3. Build `TtsPlatformSapiBridge.vcxproj` for the TextAloud-required bitness.
4. Register the COM class and voice token for that bitness.
5. Replace dummy PCM with synchronous `/v1/tts` audio once TextAloud can call
   `Speak` on this COM class.
