# Reader request-budget isolation

User activated the existing-Reader rate-limit todo after explicitly stopping
the exact Reader/tray and service processes. Base main was 64b7544. The local
installed-voice MANIFEST is excluded (SHA-256
C0556F885B9AE3D881DDCB8A131B852263DCFC1045872F50F451CDAEC0C95DE8).

Implemented separate per-host background/playback sliding windows; existing
agent admission stays independent. Method/route allow-list selects playback,
never caller headers. Existing background cap remains 30 by default; the new
independent playback default is 120. Both are configurable and enforced.
429 errors add budget identity to header/details; Reader/TTS WS uses playback.
The .NET HTTP client shares scoped deadlines and 2-active/16-total request
admission per budget, handles cancellation and suppresses queued calls after
429 without retrying writes. Reader WS retains Retry-After/budget metadata.
Legacy/unknown tags keep conservative global cooldown.

Validation exposed an existing Completed-before-cleanup replay race. The first
full .NET run had one failure in Playback_complete_restarts_from_first_cursor
on_next_play. A new delayed-session-disposal regression failed deterministically
before the fix (restart returned immediately without opening a second stream).
Play now awaits terminal-run cleanup before starting again; full 350-test suite
passes. This is a small supporting reliability fix, not audio-buffer tuning.
The first new Python saturation test hit the native-loopback status guard with
TestClient's default non-loopback address; test transport was corrected to
127.0.0.1 and the guard was preserved. Initial Ruff long lines were formatted.

Passed: 689 Python tests, 2 optional skips; 350 .NET tests; Ruff; zero-warning
Release solution build; 20 contract fixtures; Chrome extension/JS checks.
The synthetic test uses >2M characters, 30 accepted/50 rejected background
requests, bounded two-block content, 60 position saves and two PCM stream
windows, followed by enforced playback rejection. Concurrent fake-clock tests
prove exactly bounded admission and retry-deadline recovery. Shared 30-case
route fixtures are read by both languages. .NET tests verify independent/shared
legacy cooldowns, bounded cancellable queues and no post-429 request storm.
The compiled live .NET smoke uses isolated 8/20 service limits, receives 68,640
PCM bytes / 36 source spans while background is saturated, roundtrips heard
position and immediate WAV synthesis, then verifies playback's own cap.
The desktop checker also passed live edits/import/rules/chapters/capture,
schema-11 SQLite preview integrity, portable packaging and WPF lifecycle.
Audio endpoint/global clipboard/hotkeys and real listening were not requested
by the automatic smoke. No production data/network/startup settings changed.

Remaining: bounded load/coalescing, page-based chapters, configurable part
limits, metadata preflight and measured append scaling. No memory/per-call
latency benchmark is claimed. PWA, U8 and audiobook production stay inactive.
Exact-shortcut publication and final Git delivery are recorded below.

Final deployment: root `TTS Platform Reader.lnk` still points to
`apps/desktop_reader/src/TtsPlatform.Reader.App/bin/Release/net10.0-windows/win-x64/TtsPlatform.Reader.App.exe`.
Published that exact directory after the replay fix, then verified isolated
folder/edit-preservation and single-tray/lifecycle probes. Evidence is under
ignored `logs/request-budgets-20261030/shortcut/`. The first PowerShell GUI launch
returned before process exit and its wrapper treated an unset LASTEXITCODE as a
failure; the process itself produced a passing marker. Explicit hidden
Start-Process -Wait/-PassThru confirmed exit code 0 and both probes passed.
Scoped .NET whitespace verification, security-default checks and the v1
completion gate pass. Production Reader/service remain stopped for normal
relaunch. MANIFEST hash remains identical. No live configuration was rewritten.
