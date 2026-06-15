# Native SAPI Engine Placeholder

This directory is reserved for the future native SAPI 5 COM engine.

The current spike intentionally stops before implementing `ISpTTSEngine`.
First, the project needs to prove that TextAloud can see a custom SAPI voice
token and whether TextAloud requires x86, x64, or both registry/build targets.

Next native step after the dummy-token spike:

1. Add a C++ COM DLL project.
2. Implement `ISpObjectWithToken`.
3. Implement `ISpTTSEngine::Speak`.
4. Write generated PCM to `ISpTTSEngineSite`.
5. Register the COM class and voice token for the TextAloud-required bitness.

