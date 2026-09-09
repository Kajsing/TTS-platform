# Durable Reader capture outbox - approved Sep 9, 2026

The user approved an encrypted, per-Windows-user local staging queue that
survives Reader/computer restarts. This is local-to-service capture delivery,
not full offline library replication or synchronization of SQLite files.

## Current slice

- Persist only explicitly accepted Create/Inbox/Append actions. Never silently
  persist arbitrary clipboard changes. Preserve queued text until an explicit
  server receipt or user discard. Bound item/total sizes and handle disk errors.
- Bind each action to its original workspace, target article/folder, operation
  ID and chapter choice. Support appends following a queued new article.
- Serialize delivery and use transactional service receipts so a lost response,
  process restart or retry cannot duplicate an accepted action. A committed
  write followed by a failed library reload is still a successful delivery.
- Show queued/sending/waiting/attention status and a Retry/Discard interface;
  no modal window that freezes playback. Do not promise to cancel a write the
  service may already have committed. Save-to-disk failures remain visible.
- Respect server Retry-After and reduce competing requests while throttled.
  Retain authentication, privacy locks and content leases. Do not raise/disable
  the security budget merely to hide a request storm.
- Test 150k-character captures, disconnected/restarted service, lost replies,
  concurrent retry, wrong-workspace guards, queue recovery and UI responsiveness.
- Preserve the active user's Reader/service and voice manifest. Deployment
  requires a safe close and coordinated service restart after validation.

Playback faults remain a separate evidence-driven follow-up; collecting a queue
does not prove a fix for every audio interruption. U8 remains parked.

## Implemented behavior and limits

Accepted Create/Inbox/Append actions first enter `%LOCALAPPDATA%\TTSPlatform\Reader\capture-outbox`.
Each file is an atomic, flushed DPAPI CurrentUser envelope: no plaintext index,
article text in logs, or token in the envelope. Maximum 50 items, 1,000,000 UTF-16
characters per item, 8,000,000 in total. The queue is bound to the normalized
service endpoint plus a hash of its credential. Changing accounts/endpoints
does not redirect old captures. Keep Reader open for delivery; closing just the
queue window continues delivery, while closing Reader retains files for its
next launch. This is not a backup or full offline editing/sync system.

The connection panel contains **Capture queue…**, item/character counts and
queued/sending/waiting/attention status. The queue provides Retry, explicit
Allow duplicate after duplicate rejection, Discard selected and Recover text.
Recover text can save an explicitly chosen **unencrypted** text file. A local
save failure instead opens a recovery window with the original text; it is not
reported as successfully captured. Unsaved edits and active playback on the
append target defer synchronization; save/revert and pause to continue.

Clipboard changes received while another prompt is open wait in bounded RAM
only (same 50-item/8M-character bounds), still requiring individual acceptance.
They do not survive exit. Ignore/snooze remain privacy decisions, not accepted
captures. At capacity the UI explicitly reports that the new copy was not saved.

### Delivery contract

`POST /v1/reader/captures/{operation_id}` uses an immutable UUID and a JSON body:

```json
{"action":"append","text":"Next chapter.","document_id":"article-id","new_chapter":true}
```

Create uses `action: create`, `text`, optional `title`, `folder_id` and
`allow_duplicate`. Append requires exactly one `document_id` or
`target_operation_id` (the UUID of an earlier create), preserving intent even
before the new article has its service ID. No caller-provided stale text offset
or row version is applied: append resolves the current end/version inside the
write transaction. Existing privacy checks and active-reading leases still
apply. Legacy direct editing endpoints retain optimistic concurrency.

The response contains `operation_id`, `document_id` and `outcome` (`delivered`
or `already_delivered`). Migration 011 adds minimal SHA-256 payload receipts,
committed in the same SQLite transaction as the article/append. Reusing an ID
with different content returns `reader_capture_conflict` (409). Receipts survive
Undo and soft deletion; retries never resurrect explicitly undone/deleted text.
Only a matching success receipt removes the protected local copy. A failed
library refresh retries reads independently and cannot repeat the write.

HTTP 429 includes a rounded-up `Retry-After` and `retry_after_seconds`. Reader
and Service Center share an endpoint cooldown; manual Retry respects it.
Disconnected deliveries wait 15 seconds; active leases wait 5 seconds. Other
errors require attention without dropping the capture. Existing authentication,
origin checks, rate budget and remote transport policy remain in force.

Diagnostics add `capture_queued`, `capture_delivered` and state-change-only
`capture_waiting` events to the existing bounded playback JSONL log, using
operation IDs and outcomes, never clipboard text or credentials.

### Validation and activation (Sep 9)

- 654 Python tests passed, 2 optional skips; 313 .NET tests passed.
- Ruff, scoped .NET formatting/build, portable self-contained package and actual
  Windows silent-audio reopen passed. Global clipboard/hotkey integration was
  not activated by tests; real interactive clipboard use remains a field check.
- Live isolated HTTP client/service roundtrip verifies a >150k capture and a
  dependent chapter, replay receipts and complete text readback.
- Isolated real-WPF probes verify a 150k durable capture, accepting an append
  while delivery waits, 429 retention and refresh-only retry. The actual root
  shortcut EXE passes the same probe and its rendered queue was inspected.
- User confirmed Reader/tray closed. Before service restart, SQLite backup at
  `%LOCALAPPDATA%\TTSPlatform\Reader\backups\2026-09-09-before-capture-outbox.db`
  passed integrity validation. Restart used the existing verified-owner and
  maintenance-reservation controls. New service reports schema 11 and 25 voices;
  live articles, blocks and playback positions exactly match that backup.

No production article was added/deleted, and no local model manifest or rate
configuration was edited. Playback timing/position-budget tuning is not claimed
fixed by this slice; capture resilience now has its own regression coverage.

## Much later: local SAPI fallback reader

Explicit user request Sep 9: keep an optional local SAPI reader as a future
backup when the normal service/voice is unavailable. This is NOT the existing
TextAloud-facing SAPI bridge, and is NOT in the current capture-outbox work.
Later decisions: explicit versus automatic fallback, compatible installed voices,
source position/highlighting, avoiding two concurrent readers, and truthful
feature limitations. No implementation, engine change or dependency now.
