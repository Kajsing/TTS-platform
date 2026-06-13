# Chrome Extension Prototype

This directory contains the first MV3 prototype client for the local TTS platform.

## What it can do

- speak the current selection from the active tab
- speak a bounded readable snapshot of the current page text
- stream audio through an offscreen document
- buffer PCM audio before playback starts
- show reader progress for streamed page playback
- resume page playback from the latest reader progress
- store local service settings such as base URL, token, preferred voice, and page-text limits
- discover available voices from the local service
- show service health and a ready-to-copy allow-list snippet for the extension origin
- recover more deliberately from playback underruns by rebuffering before audio resumes
- retry offscreen playback startup if the offscreen document has gone stale
- provide a troubleshooting guide and a lightweight repo-native validation script

## Before loading the extension

1. Start the local service.
2. Ensure the service token is available.
3. Add the extension origin to `security.allowed_origins` in the local service config.
4. Keep the service running on a localhost URL that the extension can reach.

The popup shows the extension origin so it can be copied into the service allow-list.
The popup can also refresh service health and voice discovery directly from the local service.

## Load in Chrome

1. Open `chrome://extensions`.
2. Enable Developer Mode.
3. Choose `Load unpacked`.
4. Select this `apps/chrome_extension` directory.

## Prototype flow

- `background.js` orchestrates text capture and offscreen playback.
- `content-script.js` reads selection or page text.
- `offscreen.js` connects to the local service and plays streamed PCM audio with a small prebuffer.
- `popup.html` and `popup.js` provide a basic control surface for configuration, playback actions, reader progress, and page resume.

## Suggested manual check

1. Start the local service.
2. Load the extension.
3. Open the popup and confirm that service status loads successfully.
4. Confirm that the voice list populates from `/v1/voices`.
5. Save the token and other settings.
6. Speak a text selection from a normal web page.
7. Stop playback once and start it again to confirm the offscreen flow recovers cleanly.
8. Reopen the popup during or after playback and confirm the state still looks sensible.
9. During long page playback, confirm the playback state includes reader progress.
10. Stop page playback and use `Resume Page` on the same page to restart from the latest text chunk.

## Notes

- Browser WebSocket clients cannot set custom `Authorization` headers, so the prototype sends the bearer token in the first `start` event for `WS /v1/tts/stream`.
- This token flow is intentionally limited to the localhost MVP shape and should be revisited if the browser client becomes more broadly distributed.
- The current playback buffer now includes simple rebuffering behavior, but it is still a lightweight jitter-buffer-style scheduler rather than a final production playback engine.
- Page text capture now prefers likely article/main content over a raw whole-body dump, but it still uses heuristic extraction rather than a full reader-mode pipeline.
- Page playback uses the service WebSocket stream path and defaults to a 24,000 character page capture limit. The local service default `tts.max_chars_per_stream` is 48,000 characters.
- The service stream reports progress by planned text chunk. The extension shows that progress in the popup playback state.
- `Resume Page` does not persist raw page text. It re-extracts readable text from the active tab and sends the latest planned text chunk index to the service.

## Validation

Run the lightweight extension validation script with:

```bash
python3 scripts/check_extension.py
```

This checks manifest references, linked popup/offscreen assets, and JavaScript syntax when `node` is available.

For common issues, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
