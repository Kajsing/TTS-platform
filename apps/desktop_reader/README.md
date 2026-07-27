# TTS Platform Reader Desktop

This directory is reserved for the Windows-native Reader Workstation client.
The selected stack is C#, XAML, WPF, and `net10.0-windows`.

The desktop layer owns presentation, view models, Windows integration, local
PCM playback, focus and accessibility behavior, and client-local settings. It
consumes the protected localhost Reader and TTS contracts.

It must not own the canonical Reader database, document parsing, speech-rule
semantics, SQL, or TTS backend inference. Those responsibilities remain in the
Python service and domain packages.

Milestone 0 contains no desktop feature code or runtime dependencies.
