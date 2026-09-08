# Reader pause viewport and sleep-safe audio output

## Scope and evidence

The user approved this reliability run after finishing their article and later
confirmed Reader/tray were closed. Chapters are explicitly a separate next run;
U8 stays parked. No goal was created, no live article was edited/deleted, and no
production service, voice manifest, clipboard, security/rate limit or network
configuration was changed.

The Sep 8 field trace previously inspected in this task showed normal PCM
arrival after wake (522–749 ms to first packet) followed by three attempts
stopping at 2000 ms buffered, without continuing consumption. Sleep/wake events
were 14:31:56/15:52:04 local time. This strongly suggests a stale output, not
stalled synthesis. The exact Windows driver failure remains unproven.

## Changes and decisions

- MainWindow keeps the audible adorner/structured marker on pause, completion
  and faults. Removed the state-change caret assignment and ScrollToLine.
  Audible highlighting no longer selects text or changes Start-at-cursor intent.
  Stop clears the marker without repositioning the viewport. Existing edit/load
  invalidation clears stale marks. Continuous Follow-off honors manual scroll.
  Stale coordinator/run/revision callbacks are rejected.
- WasapiAudioOutput now releases device ownership on Stop/Dispose; ordinary
  pause cancels playback and calls Stop, so the next Play creates the current
  Windows endpoint. Completion also releases it. Existing target/hard buffer
  limits and the NAudio 2.3 stack are unchanged.
- Device callbacks capture per-device health without taking the output lock,
  avoiding callback/join deadlocks and late failures poisoning a new device.
  Both write backpressure and drain detect three seconds without consumption.
  Progress freezes on device failure. A backend-neutral AudioOutputException
  presents only a fixed safe message. Reader faults, saves confirmed progress,
  and retries from that cursor on an explicit Play; it does not silently skip
  buffered speech or start talking by itself after sleep.
- Cancellation leaves checkpoint teardown to the owning coordinator/Stop path,
  which acknowledges heard audio before resetting the generation. The managed
  write gate is not disposed while cancelled writers may still release it.
- Fault diagnostics add heard location and buffer duration to existing bounded
  logs and distinguish audio_output_stalled/audio_output_unavailable. No private
  text, titles, clipboard data, token, path or native driver message is added.
- Clipboard playback and Service Center preview catch the new safe error;
  ephemeral completion/failure releases its output as well.

No architecture/product/security deviation. Recreating an idle output rather
than subscribing a new global sleep handler is a local implementation choice:
there is no device to become stale while paused, and an active dead output
fails safely without an unrequested automatic restart.

## Validation

- Used `py -3` on Windows and the bundled .NET 10.0.202 SDK (not PATH SDK 8).
- `dotnet build ... -c Release --no-restore`: zero warnings/errors.
- `dotnet test ... -c Release --no-build --no-restore`: 51 client + 143
  application + 102 Windows tests = 296 passed. New tests cover device reuse
  boundaries, write/drain stalls, failed initialization, asynchronous device
  loss, discarded buffers, cleanup failures, stale callbacks, cancellation,
  continuing consumption, sanitized diagnostics and retry from heard progress.
- `py -3 -m pytest -q`: 626 passed, 2 optional skips.
- `py -3 -m ruff check .`, scoped `dotnet format --verify-no-changes`, and
  `git diff --check`: passed.
- `check_desktop_reader.py --require-dotnet --dotnet <local-sdk> --skip-build
  --require-windows-audio`: isolated service/DB/live HTTP, portable WPF and
  physical default-endpoint silent PCM drain/Stop/reopen passed. Global
  clipboard/hotkey integration was intentionally not requested. The source gate
  was updated from the removed scrolling helper to ApplyPlaybackPresentation.
- New real WPF synthetic test covers wrapped text in the middle and at the end
  of a long document: pause/completion/fault retain scroll, selection, caret,
  marker, font/line geometry and editability. It also checks Follow-off, Stop,
  edits, structured view and document-clear behavior. No live articles/audio.
- Published `-c Release -r win-x64 --self-contained true` after verifying no
  Reader process. The root shortcut still targets the runtime-specific EXE,
  without arguments, with repository working directory. That exact executable
  passed the isolated lifecycle suite, including playback_pause_viewport and
  document_switch_safety. Inspected the synthetic paused render.
- Evidence: ignored `logs/pause-sleep-20260908/development.json`, `shortcut.json`
  and `paused-viewport.png`. Deployed App DLL SHA256:
  `003A56E06B53D773F7693CC36681E4259FE4EEEDD50501F52F8044F587948997`.

## Remaining field check

Publication initially met a non-fast-forward push: another installation had
added three documentation-only commits (`7f32c42`, `43124ea`, `748b2d1`). Merged
both sets of status notes, explicitly distinguishing the work-PC configuration
from this checkout. No source or published binary changed during that merge;
the user's installed-voice manifest remains uncommitted and untouched.

Use the root shortcut normally. Test manual pause, automatic call/alarm pause,
and completion while partway/down the end of an article; the visible mark and
viewport should stay put. Then try the ordinary pause -> sleep -> wake -> Play
workflow. This run did not put the user's machine to sleep or claim a physical
sleep/wake reproduction. A driver loss during active speech should present the
retryable audio error; Play reconnects from confirmed progress. The separate
Service Center 429 and chapter implementation remain outside this slice.
