# Chrome Extension Troubleshooting

## Popup cannot reach the service

- Confirm the local service is running.
- Confirm the popup `Base URL` matches the service host and port.
- Confirm the service is listening on a localhost URL that Chrome can reach.
- Confirm the popup `Base URL` is an HTTP localhost origin such as
  `http://127.0.0.1:7777` or `http://localhost:7777`; paths, query strings,
  credentials, and external hosts are rejected when settings are saved.
- Use the popup `Refresh` button and read the `Service Status` panel.
- Use the popup `Setup Checklist` panel to see whether service reachability,
  token setup, voice discovery, backend readiness, default voice loading, and
  health are passing.

## Setup checklist shows todo items

- `Service reachable`: start the service with `tts serve` or the Windows
  launcher and confirm the popup `Base URL`.
- `Token saved`: paste the local bearer token from `config/token.txt` into the
  popup and save settings.
- `Origin snippet ready`: copy the allow-list snippet from the popup into
  `config/config.toml`.
- `Voice available`: run `tts list-voices` or install and activate a voice with
  `tts model-install <model-id> --activate` when the catalog is saved as
  `models/catalog.json`; otherwise pass `--catalog <path-or-url>`.
- `Backend ready`: confirm the configured backend mode can start locally. For
  real local playback, install the selected model and the `sherpa_onnx`
  runtime package.
- `Default voice loaded`: install and activate a real voice, then restart the
  service so `/v1/health` can load the configured default voice.
- `Health ok`: refresh after setup changes or inspect `/v1/health` for the
  degraded check.

## Playback fails immediately

- Confirm a token has been saved in the popup.
- Confirm the extension origin shown in the popup is allow-listed in the service config.
- Confirm the selected or page text is not empty.
- For page playback, confirm `Max Page Characters` does not exceed the service
  `tts.max_chars_per_stream` setting.
- If the service was restarted recently, refresh the popup and try again.

## Voice list is empty

- Confirm `/v1/voices` works from the local service.
- Confirm the model manifest or backend fallback exposes at least one voice.
- Use the service status panel to confirm the service is reachable before assuming the voice registry is empty.

## Playback stops mid-stream

- Reopen the popup and inspect the `Playback State` panel.
- If reader progress is available, use `Resume Page` on the same page to restart
  from the latest planned text chunk.
- If the offscreen document became unavailable, stop playback once and start a new request.
- If underruns are frequent, increase `Prebuffer (ms)` and `High Watermark (ms)`.

## Resume Page does not continue where expected

- Confirm the active tab is the same tab you were listening to. Manual page
  resume, continue, and section actions refuse to use stored page progress from
  another active tab.
- Check `Source Tab` in the popup `Playback State`; it reports whether the
  original page tab is active and explains disabled manual page actions.
- Use `Focus Page` to return Chrome to the original tab when it is still open.
- Resume re-extracts readable page text and uses the last planned text chunk
  index; if the page content changed, the resumed position may shift.
- Resume intentionally repeats the latest known text chunk instead of skipping
  ahead, because stream progress can be reported before that chunk has fully
  played.

## Page playback stops before the whole article

- Check `Page Capture` in the popup playback state.
- If the captured text includes hidden UI or modal text, inspect whether the
  page marks those regions with `aria-hidden`, `hidden`, or `inert`; the
  extension deliberately skips those subtrees.
- If it says `truncated`, the extension reached `Max Page Characters` before
  the readable page text ended.
- Use `Continue Page` to re-extract the active tab from the next known text
  character offset when the page has no later heading-backed section.
- If the prior page segment finished normally, the extension should try this
  continuation automatically before manual action is needed.
- Increase `Max Page Characters` up to the local service stream limit, then save
  settings and start page playback again.
- The popup stores capture counts and extraction metadata only; it does not
  store raw page text.

## Page playback misses section breaks

- Check whether `Page Capture` reports heading counts.
- Short `h1` to `h4` headings are preserved even when they are shorter than the
  normal body-text block threshold.
- Pages without semantic headings can still sound flatter because the extension
  has only body/list/quote block structure to work with.
- Structure metadata stores counts only, not heading text.

## Previous/Next Section is unavailable

- Start page playback first so the popup has current page-capture metadata.
- `Previous Section` needs an earlier heading-backed section than the current
  reader position. It will be unavailable near the start of the captured text.
- `Next Section` needs a later captured heading offset than the current reader
  progress, or a known uncaptured section index from a truncated page capture.
  It will be unavailable near the end only when neither signal exists.
- Pages without semantic `h1` to `h4` headings may not expose usable sections.
- Switch back to the original page tab before using section navigation from
  stored page progress.
- The popup disables section navigation when the active tab does not match the
  stored page-progress source tab.
- Use `Focus Page` when the popup says the original page tab is not active.
- If the page is truncated but has no later heading-backed section, use
  `Continue Page` instead. Normal page playback also tries this automatically
  when a truncated segment finishes.
- The actions re-extract the active tab from a section index; if the page
  content changed, the new section position may shift.

## Selection playback does not read the expected text

- The content script prefers selected text first, then readable page content.
- Inputs and textareas use the current text selection inside the control.
- Page playback intentionally bounds and normalizes text, so exact visual parity
  with the page is not guaranteed.
