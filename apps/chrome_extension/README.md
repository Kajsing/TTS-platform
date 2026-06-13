# Chrome Extension Prototype

This directory contains the first MV3 prototype client for the local TTS platform.

## What it can do

- speak the current selection from the active tab
- speak a bounded readable snapshot of the current page text
- stream audio through an offscreen document
- buffer PCM audio before playback starts
- show reader progress for streamed page playback
- resume page playback from the latest reader progress
- show page-capture metadata for long pages, including captured characters,
  readable block count, extraction source, and truncation at the configured limit
- preserve short article headings in page playback and show heading/body/list
  structure counts in playback state
- jump to the previous or next page section by re-extracting the active tab
  from a heading index or the first known uncaptured section after truncation
- continue a truncated page from the next known text character offset when
  no later heading-backed section is available
- automatically continue from that text offset when a truncated page segment
  finishes normally
- stop playback and keep popup state truthful if playback is interrupted while
  the offscreen document is unavailable
- store local service settings such as base URL, token, preferred voice, and page-text limits
- discover available voices from the local service
- show service health and a ready-to-copy allow-list snippet for the extension origin
- show a setup checklist for service reachability, saved token, origin snippet, voice discovery, and health
- include `INSTALL.md` and manifest/action icons in local handoff packages
- recover more deliberately from playback underruns by rebuffering before audio resumes
- retry offscreen playback startup if the offscreen document has gone stale
- provide a troubleshooting guide, a lightweight repo-native validation script,
  and an optional Chrome/MV3 browser smoke script

## Before loading the extension

1. Run `tts setup-local` or `scripts\windows\run_service.ps1 -SetupOnly`.
2. Ensure the service token is available.
3. Copy the extension origin from the popup.
4. Run `tts extension-allow-origin <copied-origin>`.
5. Start or restart the service on a localhost URL that the extension can reach.

The popup shows the extension origin so it can be copied into the service allow-list.
The popup can also refresh service health and voice discovery directly from the local service.
The setup checklist in the popup summarizes the first-run state after each
refresh or settings save.

## Load in Chrome

1. Open `chrome://extensions`.
2. Enable Developer Mode.
3. Choose `Load unpacked`.
4. Select this `apps/chrome_extension` directory.

## Package Locally

Build a zip with the extension manifest at the archive root:

```bash
python3 scripts/package_extension.py
```

The package script runs `scripts/check_extension.py` first and writes the zip to
`dist/chrome_extension/tts-platform-prototype.zip` by default. The zip is for
local testing and handoff; it is not Chrome Web Store signing or publishing.
It includes `INSTALL.md` and the icon set referenced by the manifest and toolbar
action.

## Prototype flow

- `background.js` orchestrates text capture and offscreen playback.
- `content-script.js` reads selection or page text.
- `offscreen.js` connects to the local service and plays streamed PCM audio with a small prebuffer.
- `popup.html` and `popup.js` provide a basic control surface for configuration, playback actions, reader progress, and page resume.

## Suggested manual check

1. Start the local service.
2. Load the extension.
3. Open the popup and confirm that service status loads successfully.
4. Confirm the setup checklist reports service reachability, saved token,
   origin snippet readiness, voice discovery, and health.
5. Confirm that the voice list populates from `/v1/voices`.
6. Save the token and other settings.
7. Speak a text selection from a normal web page.
8. Stop playback once and start it again to confirm the offscreen flow recovers cleanly.
9. Reopen the popup during or after playback and confirm the state still looks sensible.
10. During long page playback, confirm the playback state includes reader progress.
11. Confirm the playback state includes page-capture metadata and reports
    truncation when the readable page text reaches `Max Page Characters`.
12. Confirm short article headings are included in page playback and that
    `Page Capture` reports heading/body/list structure counts.
13. Use `Previous Section` and `Next Section` during page playback and confirm
    they restart from heading-backed sections when available.
14. On a truncated long page without later headings, confirm normal playback
    starts the next segment automatically after the current segment finishes.
15. Use `Continue Page` and
    confirm it restarts from the next captured text character offset.
16. Stop page playback and use `Resume Page` on the same page to restart from the latest text chunk.

## Notes

- Browser WebSocket clients cannot set custom `Authorization` headers, so the prototype sends the bearer token in the first `start` event for `WS /v1/tts/stream`.
- This token flow is intentionally limited to the localhost MVP shape and should be revisited if the browser client becomes more broadly distributed.
- The current playback buffer now includes simple rebuffering behavior, but it is still a lightweight jitter-buffer-style scheduler rather than a final production playback engine.
- Page text capture now prefers likely article/main content over a raw whole-body dump, but it still uses heuristic extraction rather than a full reader-mode pipeline.
- Page playback uses the service WebSocket stream path and defaults to a 24,000 character page capture limit. The local service default `tts.max_chars_per_stream` is 48,000 characters.
- The service stream reports progress by planned text chunk. The extension shows that progress in the popup playback state.
- The extension stores only page-capture metadata in session playback state, not
  raw page text.
- Page-capture structure metadata stores counts only; it does not store heading
  text or other raw page text.
- `Previous Section` and `Next Section` use heading offsets and section indexes
  from the latest page capture metadata, then re-extract page text from the
  active tab. When a capture is truncated, `Next Section` can also use the
  first known uncaptured section index without storing its heading text.
- `Continue Page` uses a non-textual character offset from the latest truncated
  page capture metadata, then re-extracts the active tab from that offset. It
  does not persist raw page text.
- When a page playback segment finishes normally and that metadata still points
  at later text, the background worker starts the next segment automatically
  from the same offset.
- `Resume Page` does not persist raw page text. It re-extracts readable text from the active tab and sends the latest planned text chunk index to the service.
- Manifest host permissions are limited to the localhost service origins. The
  declared content script handles page access, and the validation script checks
  that network playback stays in the background/offscreen path.

## Validation

Run the lightweight extension validation script with:

```bash
python3 scripts/check_extension.py
```

This checks manifest references, linked popup/offscreen assets, manifest policy,
local install assets, extension privacy/layering boundaries, and JavaScript
syntax when `node` is available.

Run the onboarding contract check with:

```bash
python3 scripts/check_extension_onboarding.py
```

This starts a temporary local service, verifies the popup setup controls,
checks that the extension-origin allow-list snippet is accepted by service
config, and confirms the health/voice-discovery snapshot shape used by the
popup.

Run the long-page reader-flow contract check with:

```bash
python3 scripts/check_extension_reader_flow.py
```

This verifies the `Speak Page`, reader progress, page-capture metadata,
`Resume Page`, `Continue Page`, previous/next section navigation,
truncated-section continuation, manual and automatic truncated text-offset
continuation, stop/restart recovery, and popup reopen-state wiring, then
streams a generated thousand-word article through the local WebSocket service
path.

Run the optional Chrome/MV3 browser smoke with:

```bash
python3 scripts/check_chrome_extension_smoke.py
```

The smoke uses Chrome or Edge through DevTools Protocol when a browser is
available, loads this unpacked extension, starts an isolated local service,
opens a generated long article, verifies page capture, starts page playback,
and observes playback state. It skips truthfully when the local browser/MV3
environment cannot run the smoke; add `--require-browser --headed` when strict
local browser evidence is needed.

For common issues, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
