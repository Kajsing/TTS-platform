# Thoughts Log

This file captures implementation-time thoughts that are worth remembering but are not yet formal architecture decisions. It is intentionally lightweight and should be updated as the project evolves.

## Current State

- The platform now has working HTTP synthesis, async jobs, protected WebSocket streaming, a public-contract CLI, a benchmark script, structural audio regression tests, and a first Chrome MV3 prototype.
- The backend is still a deterministic development synthesizer behind the `sherpa-onnx` contract.
- Most observability is currently exposed through health snapshots and structured local logging, not an external metrics backend.
- Job observability is now visible in health snapshots, which reduces one of the bigger blind spots from the earlier phase 5 pass.
- The CLI now covers more lifecycle work, but it should stay disciplined about using only public endpoints.
- The browser prototype keeps playback in an offscreen document and leaves the localhost service browser-agnostic apart from one streaming-auth concession.

## Known Gaps

- Text chunk planning is still not a first-class domain component. Streaming and sync synthesis work, but they are not yet driven by a dedicated chunk plan with pause metadata.
- Observability is broader now, but still lacks a real export path for longer-running analysis.
- CLI ergonomics are better, but if we keep adding commands it may deserve a dedicated usage document separate from README.
- Benchmarking now covers sync HTTP and streaming, but it still does not benchmark async job flows directly.
- The extension playback buffer is intentionally lightweight. It is good enough for the prototype, but not yet a rich jitter buffer with recovery heuristics.
- The extension currently depends on manual Chrome loading and manual allow-list setup, which is acceptable for the prototype but should not be mistaken for a polished distribution flow.

## Deferred Work

- Export metrics in a more production-friendly form instead of relying only on health snapshots.
- Add richer audio regression techniques if the backend becomes more realistic and waveform drift becomes more meaningful.
- Revisit cancellation once a true inference backend exists, especially for running jobs and active streams.
- Revisit browser auth hardening if the extension evolves beyond the current localhost prototype. The `auth_token` field on the first stream event is practical, but it should remain a deliberate compromise rather than spread casually.
- Consider a dedicated extension usage and troubleshooting guide if phase 6 grows beyond a prototype.

## Next Phase Notes

- Phase 6 should stay client-focused and avoid leaking browser-specific concerns back into the service core.
- The browser prototype confirmed that standard browser WebSockets cannot be treated like CLI clients for auth. Keep that constraint visible in future design choices.
- If CLI output grows much more, consider a dedicated usage guide so README stays readable.
- If phase 6 gets a polishing pass, likely targets are richer playback state UX, voice discovery inside the popup, and more deliberate buffering heuristics.
