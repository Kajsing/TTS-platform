# Reader Milestone 5 Windows Manual Checklist

Use this checklist on an idle Windows desktop after the automated Milestone 5
gate passes. The application-selection checks are intentionally manual because
foreground automation can steal keystrokes from an active user session.

The unattended gate never reads or writes the current clipboard:

```powershell
py -3 scripts\check_desktop_reader.py --require-windows-integration
```

## Preparation

1. Start the local service and open TTS Platform Reader with a valid token file.
2. Confirm the header says `Clipboard prompt: Off · Privacy` on a new profile.
3. Open an editable plain-text or clipboard document and note its final
   paragraph.
4. In settings, leave Privacy mode enabled, enable Copy Selection and Read, and
   save. Enable Clipboard prompt mode only for the prompt-specific checks.
5. Use harmless, unique sample text. Do not use a password field, secret, or
   other sensitive content.

## Application matrix

Record Windows and application versions plus Pass, Fail, or Not available.

| Application | Selection check | Expected result | Result |
|---|---|---|---|
| Notepad | Select a sentence and invoke Copy Selection and Read | Audio begins within the bounded capture window; the compact controller contains no copied text | Pending |
| Chrome or Edge | Select only a useful paragraph on a forum/article and invoke Copy Selection and Read | Only the selection is read; surrounding navigation and filler are absent | Pending |
| Microsoft Word, when installed | Select a paragraph and invoke Copy Selection and Read | The selected paragraph is read and Word remains responsive | Pending |
| Unsupported/no selection | Focus a window or control with no selectable text and invoke Copy Selection and Read | A quiet `No selectable text...within one second` status appears; no retry loop or audio starts | Pending |

For each successful application check, verify that a safely serializable prior
clipboard value is restored. If the prior formats cannot be serialized safely,
best-effort restoration is skipped; this must not crash or retry.

## Prompt and append workflow

1. With Clipboard prompt mode Off, copy text in another application. No prompt
   should appear.
2. Invoke Read Clipboard. Audio should start even though monitoring remains Off,
   and no Reader document should be created.
3. Turn Clipboard prompt mode On and press `Ctrl+C` on a harmless selection. The
   prompt must offer Read now, Append to open document, Create new document,
   Save to Inbox, Ignore, and Always ignore this app.
4. Choose Append to open document three times with three different selections.
   Each selection must be a separate paragraph.
5. Press Undo once in Reader. Exactly the third selection must disappear; the
   first two must remain. Redo should restore only the third selection.
6. Start playback of the open document, copy another selection, and choose
   Append. The app must tell the user to pause or stop playback and must not
   change the document.
7. Exercise Create new document and Save to Inbox once. The former opens the
   editable document; the latter saves without replacing the open document.
8. Choose Always ignore this app, copy there again, and confirm no prompt opens.
   Remove the executable from the block list afterward if desired.

## Controls, privacy, and shutdown

1. Confirm invalid or occupied hotkeys are reported in settings without closing
   the app; working controls and other registered hotkeys must remain usable.
2. Confirm Play/Pause and Stop work from the main window, configured global
   hotkeys, tray menu, and compact controller.
3. With Privacy mode enabled, confirm copied text is absent from the prompt
   preview, tray tooltip, compact controller, taskbar, and application logs.
4. Toggle Clipboard prompt mode from the tray and confirm the header updates.
5. If Minimize to tray on close is disabled, close the main window during
   playback and confirm the desktop process exits cleanly. If enabled, closing
   hides the main window and tray Exit still stops playback and exits.
6. Confirm the shared local TTS service remains running after tray Exit.

## Verification record

The code and unattended integration portions passed on 2026-07-27. A visible
application-matrix attempt was safely aborted when another running application
took foreground focus; no manual application result is claimed from that
attempt. Complete the Result column during an idle desktop session before a
public alpha/release candidate.
