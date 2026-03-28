# Thoughts Log

This file captures implementation-time thoughts that are worth remembering but are not yet formal architecture decisions. It is intentionally lightweight and should be updated as the project evolves.

## Current State

- The platform now has working HTTP synthesis, async jobs, protected WebSocket streaming, a public-contract CLI, a benchmark script, and structural audio regression tests.
- The backend is still a deterministic development synthesizer behind the `sherpa-onnx` contract.
- Most observability is currently exposed through health snapshots and structured local logging, not an external metrics backend.
- Job observability is now visible in health snapshots, which reduces one of the bigger blind spots from the earlier phase 5 pass.
- The CLI now covers more lifecycle work, but it should stay disciplined about using only public endpoints.

## Known Gaps

- Text chunk planning is still not a first-class domain component. Streaming and sync synthesis work, but they are not yet driven by a dedicated chunk plan with pause metadata.
- Observability is broader now, but still lacks a real export path for longer-running analysis.
- CLI ergonomics are better, but if we keep adding commands it may deserve a dedicated usage document separate from README.
- Benchmarking now covers sync HTTP and streaming, but it still does not benchmark async job flows directly.

## Deferred Work

- Export metrics in a more production-friendly form instead of relying only on health snapshots.
- Add richer audio regression techniques if the backend becomes more realistic and waveform drift becomes more meaningful.
- Revisit cancellation once a true inference backend exists, especially for running jobs and active streams.

## Next Phase Notes

- Phase 5.1 should tighten CLI usability, job observability, and benchmark coverage.
- Phase 6 should stay client-focused and avoid leaking browser-specific concerns back into the service core.
- If CLI output grows much more, consider a dedicated usage guide so README stays readable.
