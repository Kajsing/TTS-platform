# Local Reader rate budget

The user reported `Playback: Rate limit exceeded.` after enabling clipboard
prompt mode and using the local Reader. This slice tunes the existing local
deployment limit; it does not change the shared security contract or defaults.

## Evidence and impact review

- `config/config.toml` had `limits.requests_per_minute = 30`.
- `security.RateLimiter` counts one sliding 60-second window per client host.
  Protected Reader HTTP, service status, TTS jobs and Reader/TTS WebSocket
  admission share the application container's limiter. Local clients share
  the loopback key.
- `Playback.cs` can persist an advanced heard position once per second.
  `ServiceDashboard` polls every five seconds with its panel open, and the
  Reader browser-handoff timer polls every ten seconds. These paths can need
  roughly 78 calls/minute before document browsing and new playback starts.
  Actual position-save frequency also depends on cursor advancement.
- A pre-restart live health snapshot counted 187 service-status calls and
  82 desktop-handoff calls over approximately 15 minutes. This supports the
  material background contribution, but does not identify which exact call
  exhausted the window shown in the screenshot.

Applied the change-impact-review workflow and selected the narrow local
configuration override: **30 to 120 requests/minute**. No endpoint exemption,
authentication/origin change, global default change or client code change.
Other HTTP/stream clients in this same local deployment share the new budget;
the separately limited remote gateway and agent access policies are unchanged.
Higher activity can still exhaust the bounded budget. Other installations
retain their own configured/default limit.

## Validation and activation

`logs/build-tray-20260908/check_reader_rate_budget.py` uses isolated temporary
Reader databases and the real HTTP/WebSocket routes with a stub backend. It
compresses one minute of position/status/handoff calls into a burst, then
starts Reader streaming:

- 30/minute: 30 HTTP requests accepted, 50 rejected, Reader stream rejected.
- 120/minute: all 80 HTTP requests accepted; Reader stream starts and delivers
  72 PCM packets. Further requests still receive HTTP 429 at the configured cap.
- Five existing API tests selected by `rate_limiter or auth or origin` passed.
- Parsed and compared TOML before/after: only `requests_per_minute` changed.
  Original bytes are backed up at
  `config/.config.toml.before-rate-limit-20260908`. The config remains local.

Activation requires a service restart. Requested the existing Service Center
Restart action so the open Reader handles its own playback/unsaved-state
guards. User confirmation and the post-restart check are pending.
