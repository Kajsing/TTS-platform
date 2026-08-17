# Stable playback highlight

## Completed

- Kept the continuous editable TextBox visible while speech is active.
- Mapped played Reader source spans back to TextBox UTF-16 selection offsets.
- Used the existing highlight color as the selection background.
- Removed bold and underline from the paged reading-view highlight.
- Preserved read-only locking during playback and cursor restoration on Pause,
  Stop, completion, and playback failure.

## Scope

- Editable documents within the continuous-editor bounds use the stable text
  surface.
- Structured and oversized documents remain page-bounded and virtualized.
- No service, storage, model, voice, dependency, security, licensing, or
  deployment contract changed.

## Validation

- 419 Python tests passed.
- 100 .NET Release tests passed.
- The standalone Release WPF application build passed without warnings.
- Ruff, .NET formatting, and `git diff --check` passed.
- The complete Windows desktop integration check passed, including real Reader
  streaming, WASAPI, Windows integration, packaging, and packaged WPF render.
- A privacy-safe live UI check confirmed that the continuous editor remained
  visible before, during, and after Play, the virtualized reading control stayed
  hidden, and a non-empty source selection advanced during speech.
