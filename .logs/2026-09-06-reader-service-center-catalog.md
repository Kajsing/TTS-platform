# T2 reviewed voice catalog and shared Kokoro runtime — 2026-09-06

## Implementation

- Expanded `models/catalog.json` from 1 to 3 packages: unchanged Lessac Medium
  plus separate Kokoro v1.0 FP32/INT8 bundles, each registering the upstream US
  speaker map 0–19. One download/assets directory per bundle, not per voice.
- Primary release API pins exact SHA-256 and sizes (349418188 / 131839838 bytes).
  Export workflow and official docs verify paths and speaker mappings. The
  package-license page separates Apache model/voices from GPL eSpeak data and
  other component notices. No claim that the entire archive is Apache-licensed.
- Deferred Danish Piper: CC0 dataset/fine-tuning provenance does not establish
  whole-model terms. Scope is the approved small compatible catalog, not every
  researched candidate. No project license/backend/security/networking change.
- Optional `install_note` reaches the C# helper contract and WPF package review.
  Full-bundle download even with old single-voice assets is visible before
  acceptance. Existing manifest IDs/asset directories are never overwritten or
  silently adopted. The review checkbox covers component as well as voice terms.
- Supporting local backend fix: identical fully resolved/validated Kokoro
  configs (excluding per-generation SID) share a native engine under the existing
  construction lock. Native generation is serialized per shared engine; no
  assumption of C++ thread safety. Different lexicon/model assets do not share.
  This prevents twenty model-weight copies after trying twenty speakers.
- Bootstrap guidance handles multiple choices with `tts model-list`, without
  silently picking a default. Source/extracted/installed bundle verifiers and
  their legacy readiness markers now validate the appropriate single/multiple
  behavior. The existing one-package test fixtures remain valid.

## Validation evidence

- Actual catalog tested with tiny synthetic tar.bz2 files, preserving its real
  internal layout and all 20 speaker IDs. Atomic registration, path validation,
  checksum checks, retained config/custom manifest fields and no overwrite pass.
- Concurrent 20-speaker runtime test proves one constructed engine, preserved
  per-request SID, serialized generation, and separate engine for another lexicon.
- Read-only production C# -> Python inventory: 5 existing voices, 3 packages;
  both new bundles available with 20 voices, correct sizes and visible download
  warning. Before/after manifest SHA-256 identical.
- Read-only native .venv probe reused existing weights in a separate short-lived
  process: SID 3/11 produced distinct mono PCM16 24-kHz WAVs with one shared engine
  per FP32/INT8 asset set. Sample lengths about 2.0–2.1 sec; startup+two syntheses
  about 4.0 sec FP32 / 7.3 sec INT8 on this run. Not a controlled speed ranking.
  No sound device was opened and no model/article/config file was changed.
- .NET 10.0.202 tests: 268 pass. Published exact win-x64 shortcut binary with no
  warnings/errors. Isolated WPF lifecycle and small-window install-note/scroll
  assertions pass, and screenshot reviewed. Initial IsVisible check ran before
  WPF layout; waiting for dispatcher idle fixed the test timing, not its assertion.
- Portable verifier passes with live_voice_preview=true, synthetic HTTP/paging/
  edit/playback checks and WPF lifecycle. Physical-audio/hotkey smoke not requested.
- Final full Python suite: 626 passed, 2 optional skips; Ruff passed. Scoped
  .NET format and diff whitespace checks passed.
  Earlier failures exposed single-catalog assumptions in bootstrap verifiers
  and their old source-marker checks; fixed with explicit multi-choice coverage.

Evidence retained under ignored `logs/service-center-catalog-20260906/`:
shortcut marker/PNGs and read-only native probe. Real helper probe is under
`logs/service-center-voices-20260906/bridge-probe/`.

## Preservation and handoff

No real download, model installation, license acceptance, default change,
production service lifecycle action, firewall/U8 change or startup enablement.
The pre-existing `models/MANIFEST.json` edit stays unstaged. T1/T2 acceptance is
complete. U8 remains parked: ask about the user's
actual WireGuard server environment before doing any network setup.
