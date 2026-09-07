# Playback diagnostics

The Windows Reader records privacy-safe playback diagnostics automatically. The
log is intended for reproducing intermittent delays, jumps, unexpected stops,
and other playback-control failures without storing the article being read.

## Open the logs

1. Expand **Connection and keyboard settings** in TTS Platform Reader.
2. Choose **Open playback logs**.
3. Keep using the Reader normally. No diagnostic mode needs to be enabled.

The folder is:

```text
%LOCALAPPDATA%\TTSPlatform\Reader\logs
```

It contains the current `playback-performance.jsonl` and, after rotation,
`playback-performance.previous.jsonl`. Each file is limited to approximately
4 MiB. The Reader rotates while it is running, so a long session cannot grow
the files indefinitely.

Older oversized version-1 logs are reduced to a bounded tail when the updated
Reader first starts. Copy those older files before restarting if they must be
preserved in full.

## What is recorded

- a random desktop-session ID and playback-run ID;
- UTC timestamps and the Reader build version;
- Play, Pause, Stop, completion, cancellation, and fault transitions;
- the non-text document ID and cursor ordinals/offsets;
- stream-window startup timing and audio format;
- sampled audio-packet timing plus slow-gap, slow-submit, and underrun events;
- a summary for every stream window, including packet count, PCM byte count,
  time to first audio, buffer range, maximum gap, and underrun change;
- stable error categories, status codes, and request IDs when available.

### Input and focus trace (2026-09-06)

The updated desktop also writes `playback_ui` records with a versioned,
typed `interaction` object. `Command` identifies the actual entry point:
`MainButton`, `CompactButton`, `TrayMenu`, `GlobalHotkey`, `LocalSpace`,
`LocalEscape`, `AudioInterruption`, `AutomaticResume`, `ClipboardReading`,
`DocumentLoad`, `ReaderClose`, `ServiceOperation`, or `PrivacySessionEnded`.
These are command **requests**, not proof the command succeeded; correlate
them with the subsequent `playback_interrupt_requested` and `state_change`.

Reader and compact-window activation/deactivation, keyboard-focus categories,
and routed mouse down/up events are recorded without consuming those events.
Context includes active/visible/minimized state, whether the pointer is over
that window, the category of any captured control, and the fixed Teams/Windows
alarm/Windows alert interruption category. Recent local input and activation
ages use a monotonic clock. An older mouse event is context, not proof it
caused a later command. Global hotkeys are identified by command, not a record
of the keys the user pressed in another application.

Only this app's windows are observed. There is no global mouse hook, mouse
movement/coordinate recording, foreign window/process identification, arbitrary
key recording, control text or clipboard capture. Only Space/Enter on playback
buttons and the existing handled Space/Escape shortcuts have input labels.
Noisy editor/library pointer and focus observations are sampled at up to ten
per second; playback controls, commands and activation edges are not sampled.
The existing two-file 4 MiB rotation remains in force, with immediate flushing.
Windows can report an old file `LastWriteTime` while the writer is open:
inspect the timestamps **inside** the JSONL, rather than assuming no new logs.

`playback_operation_failed` with `operation: save_position` identifies failure
of the reading-position HTTP write, including a 429 and its request ID, before
the existing playback fault handling runs. This is diagnostic only: no retry,
rate-limit, buffering, shortcut or pause behavior was changed in this slice.

After updating, restart Reader/Service Center once to load the new logging code.
Normal use needs no diagnostic switch. When a problem occurs, note the local
time, whether highlighting continues, and whether you clicked Stop afterward.
Leave the app open if convenient; the files can be read while it is running.

The log does **not** contain article titles, article text, clipboard contents,
tokens, speech-rule text, or imported-file paths. It is still local diagnostic
metadata and should be treated as private when shared.

## When a playback problem happens

### Document navigation and deletion (2026-09-07)

`document_operation_completed` and `document_operation_failed` identify bounded
`load_document` / `delete_document` outcomes using document ID, exception category
and HTTP status only. No article title/text or server exception message is logged.

Navigation, Reader close, service lifecycle preparation and privacy-session end
preserve the last heard cursor and detach the old playback document. The explicit
Stop button/hotkey still rewinds. A `DocumentLoad` command labelled `Stop` is now
followed by `playback_interrupt_requested` with `restart_from_beginning: false`.

After a failed load the previous complete editor remains intact and its matching
library selection is restored (or unselected when outside the current filter).
Late/superseded loads cannot publish their content. A confirmed deletion is removed
locally even if the following library refresh fails, including late list responses.

### Reporting a new incident

Note the local time and briefly record what happened and which control you used.
The Reader can keep running. When the problem is ready for investigation, keep
both JSONL files and share them together with the approximate time. Playback
behavior should be changed only after the trace has been reviewed.
