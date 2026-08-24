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

The log does **not** contain article titles, article text, clipboard contents,
tokens, speech-rule text, or imported-file paths. It is still local diagnostic
metadata and should be treated as private when shared.

## When a playback problem happens

Note the local time and briefly record what happened and which control you used.
The Reader can keep running. When the problem is ready for investigation, keep
both JSONL files and share them together with the approximate time. Playback
behavior should be changed only after the trace has been reviewed.
