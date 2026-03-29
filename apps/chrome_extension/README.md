# Chrome Extension Prototype

This directory contains the first MV3 prototype client for the local TTS platform.

## What it can do

- speak the current selection from the active tab
- speak a trimmed version of the current page text
- stream audio through an offscreen document
- buffer PCM audio before playback starts
- store local service settings such as base URL, token, preferred voice, and page-text limits

## Before loading the extension

1. Start the local service.
2. Ensure the service token is available.
3. Add the extension origin to `security.allowed_origins` in the local service config.
4. Keep the service running on a localhost URL that the extension can reach.

The popup shows the extension origin so it can be copied into the service allow-list.

## Load in Chrome

1. Open `chrome://extensions`.
2. Enable Developer Mode.
3. Choose `Load unpacked`.
4. Select this `apps/chrome_extension` directory.

## Prototype flow

- `background.js` orchestrates text capture and offscreen playback.
- `content-script.js` reads selection or page text.
- `offscreen.js` connects to the local service and plays streamed PCM audio with a small prebuffer.
- `popup.html` and `popup.js` provide a basic control surface for configuration and playback actions.

## Notes

- Browser WebSocket clients cannot set custom `Authorization` headers, so the prototype sends the bearer token in the first `start` event for `WS /v1/tts/stream`.
- This token flow is intentionally limited to the localhost MVP shape and should be revisited if the browser client becomes more broadly distributed.
- The current playback buffer is a small jitter-buffer-style scheduler, not a final production playback engine.
