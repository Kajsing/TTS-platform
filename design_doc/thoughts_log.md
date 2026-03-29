# Thoughts Log

This file captures implementation-time thoughts that are worth remembering but are not yet formal architecture decisions. It is intentionally lightweight and should be updated as the project evolves.

## Current State

- The platform now has working HTTP synthesis, async jobs, protected WebSocket streaming, a public-contract CLI, a benchmark script, structural audio regression tests, and a first Chrome MV3 prototype.
- The backend is still a deterministic development synthesizer behind the `sherpa-onnx` contract.
- Most observability is currently exposed through health snapshots and structured local logging, not an external metrics backend.
- Job observability is now visible in health snapshots, which reduces one of the bigger blind spots from the earlier phase 5 pass.
- The CLI now covers more lifecycle work, but it should stay disciplined about using only public endpoints.
- The browser prototype keeps playback in an offscreen document and leaves the localhost service browser-agnostic apart from one streaming-auth concession.
- The popup can now inspect local service health and voices directly, which makes the browser prototype less dependent on undocumented setup knowledge.
- Extension playback state is now mirrored into session storage so popup reopens and service-worker restarts have a better chance of showing useful state.
- Phase 6.2 added a repo-native extension checker so we have at least one repeatable validation step before a full browser automation story exists.

## Known Gaps

- Text chunk planning is still not a first-class domain component. Streaming and sync synthesis work, but they are not yet driven by a dedicated chunk plan with pause metadata.
- Observability is broader now, but still lacks a real export path for longer-running analysis.
- CLI ergonomics are better, but if we keep adding commands it may deserve a dedicated usage document separate from README.
- Benchmarking now covers sync HTTP and streaming, but it still does not benchmark async job flows directly.
- The extension playback buffer is intentionally lightweight. It is good enough for the prototype, but not yet a rich jitter buffer with recovery heuristics.
- The extension currently depends on manual Chrome loading and manual allow-list setup, which is acceptable for the prototype but should not be mistaken for a polished distribution flow.
- The popup now improves setup, but there is still no automated voice warmup/install flow from the browser side.
- Rebuffering is better now, but it is still heuristic and not driven by chunk-plan metadata from the domain layer.
- Text capture is better than a whole-body dump now, but it is still heuristic and page-dependent.

## Deferred Work

- Export metrics in a more production-friendly form instead of relying only on health snapshots.
- Add richer audio regression techniques if the backend becomes more realistic and waveform drift becomes more meaningful.
- Revisit cancellation once a true inference backend exists, especially for running jobs and active streams.
- Revisit browser auth hardening if the extension evolves beyond the current localhost prototype. The `auth_token` field on the first stream event is practical, but it should remain a deliberate compromise rather than spread casually.
- Consider a dedicated extension usage and troubleshooting guide if phase 6 grows beyond a prototype.
- If extension complexity keeps growing, consider splitting the popup state/service inspection code from playback-control code so the client remains readable.
- If a true extension test harness arrives later, the current `check_extension.py` script should probably stay as the fastest structural smoke check rather than being replaced entirely.

## Next Phase Notes

- Phase 6 should stay client-focused and avoid leaking browser-specific concerns back into the service core.
- The browser prototype confirmed that standard browser WebSockets cannot be treated like CLI clients for auth. Keep that constraint visible in future design choices.
- If CLI output grows much more, consider a dedicated usage guide so README stays readable.
- Phase 6.1 addressed popup voice discovery and basic rebuffering, so the next likely browser targets are better text extraction, stronger extension testability, and more resilient offscreen lifecycle recovery.
- Phase 6.2 improved all three of those areas partially, so the next browser-focused gaps are now richer MV3 automation, better reader-mode style extraction, and sharper recovery semantics when the service disappears mid-stream.

## Phase 7 Notes

- Phase 7 should start with backend bootstrap and readiness before trying to solve every runtime detail at once.
- A hidden manifest-side backend configuration block is a good compromise for real model asset mapping. It keeps `/v1/voices` backend-agnostic while still letting the service bind voices to real local assets.
- An explicit backend runtime mode such as `stub`, `auto`, and `real` helps the repo move from the deterministic development synthesizer toward real inference without breaking all current development flows immediately.
- `auto` should remain conservative: old manifests without backend asset metadata can still use the stub path, but voices that do declare backend assets should fail clearly if those assets or the runtime are not usable.
- Truthful readiness is more important than pretending the real backend is active. If a manifest opts into real assets, startup and health should surface model-path or runtime failures instead of silently masking them.
- A fake in-test `sherpa_onnx` module is a practical bridge for early Phase 7 work. It lets us verify config wiring, warmup, runtime construction, and WAV generation behavior without requiring heavyweight model downloads in the normal test suite.
- Exposing backend state in `/v1/health` is useful now that the service can run in multiple backend modes. A small additive backend snapshot is enough for local debugging without turning health into a backend-specific dump.
- The next valuable confidence step after sync runtime support is not immediately chunk planning. It is proving that the same real-runtime wiring survives async jobs and WebSocket streaming, since those are the platform contracts clients actually depend on.
- The current real-runtime streaming path still generates full PCM before chunk slicing. That is acceptable as an intermediate Phase 7 state, but it should stay visible as a temporary truth until chunk-planned or incremental backend streaming arrives.
- Benchmark coverage should follow contract shape, not private internals. Adding async job benchmarking at the public API level keeps the tooling aligned with the same design principle used earlier for the CLI.
- Chunk planning is now worth making real even before true incremental backend generation exists. A domain-level plan lets sync, jobs, and streaming share the same text-execution structure instead of each mode inventing its own splitting behavior.
- The first chunk-planning pass can stay intentionally simple: sentence-based grouping with pause hints is already a big improvement over hiding all chunk behavior inside backend implementation details.
- Even with a chunk plan, the current service may still synthesize one planned chunk at a time and then re-encode. That is not the final performance shape, but it is a clean transitional architecture because it makes plan boundaries explicit without changing public contracts.

## Next Session Starting Point

- The repo is in a good checkpoint state after the first large Phase 7 pass.
- Current validation status: `python3 -m pytest -q` passes with 61 tests, and `python3 -m ruff check .` passes.
- The service now has real-backend configuration, truthful readiness reporting, fake-runtime coverage for sync/jobs/streaming, async job benchmarking, and a first chunk planner.
- The highest-value next task is probably to improve chunk-plan quality and then tighten the streaming path so it can move toward true incremental backend generation rather than full planned-chunk synthesis followed by PCM frame slicing.
- If the next session needs a smaller starting slice, model/setup documentation is also a good target because the backend asset conventions now exist in code but are not yet explained clearly for humans.
