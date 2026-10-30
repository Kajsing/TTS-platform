# PWA Reader & EU KVM Hosting Roadmap

**Status:** PROPOSED / NOT STARTED (2026-10-30)  
**Purpose:** Turn the existing local TTS Platform into a usable, installable, single-owner web Reader on Windows, Android phones/tablets, and other supported browsers, while keeping the original Windows Reader and optional offline operation intact.  
**Execution:** Planning only. This document does not authorize provisioning a VPS, deploying a service, opening network access, migrating data, or starting a Codex implementation goal. Activate one milestone explicitly.

## Product goal and non-goals

The everyday product is a lightweight personal Reader: open a document or article, choose a voice, listen, pause, seek, resume on another device, and optionally download generated audio. An installable **Progressive Web App (PWA)** provides one web codebase rather than separate desktop and mobile apps.

**In scope:** an EU-hosted, general-purpose KVM VPS; CPU-friendly TTS (Piper/VITS and, after measurement, Kokoro via sherpa-onnx); a browser client; a server-owned library; secure private remote access; resilient playback; optional later agent integrations.

**Not in the first release:** Qwen3-TTS audiobook rendering, GPU inference on the VPS, public multi-tenant hosting, voice cloning, public anonymous registrations, native Android Auto integration, simultaneous offline edits, or replacing the Windows WPF Reader.

Qwen3-TTS belongs to the separate, parked offline audiobook-production epic in [reader_audiobook_production_plan.md](reader_audiobook_production_plan.md). A future GPU worker can be on the owner's Windows PC or a separately provisioned GPU host. Do not make normal Play depend on Qwen3, an LLM, or the owner's home PC.

## Existing implementation to preserve

- Python service, shared TTS domain contracts, protected HTTP endpoints, jobs, WebSocket PCM streaming and real sherpa-onnx support already exist.
- The default voice catalog includes Piper; optional Kokoro voice catalogs are documented. Treat performance on virtual CPUs as **unmeasured**, not as guaranteed real-time playback.
- The Windows WPF Reader, service-center controls, Chrome MV3 extension, Reader library and existing local integrations remain supported. A PWA is an additional client, not a replacement.
- The current local service is loopback-first. The optional Windows Remote Reader beta in [reader_remote_security.md](reader_remote_security.md) has a **separate private-network HTTPS/WSS gateway**, Windows-specific setup and explicit pairing constraints; it is **not** approval to publish the local service on the public internet.
- Reader data and document revisions belong to the service. Never copy/synchronize the live SQLite file across devices.
- Local, folder-scoped MCP agent grants exist, but they are not a safe general-purpose public cloud authorization mechanism. See [reader_agent_access_plan.md](reader_agent_access_plan.md).
- [codex/Plan.md](codex/Plan.md) remains the execution-order source of truth until this track is explicitly activated. No existing parked milestone becomes active by adding this roadmap.

## Proposed topology

1. **Client:** installable web Reader (HTML/CSS/TypeScript, manifest, service worker, Media Session API). Same-origin HTTPS in an ordinary browser or installed PWA.
2. **Edge:** HTTPS reverse proxy with strict headers and rate limits. For a private-first pilot, permit access over owner-controlled WireGuard/Tailscale; public exposure, if ever selected, requires a **separate explicit security review**.
3. **Web session / API adapter:** a distinct, least-privilege web-facing component. It authenticates the owner, validates sessions and scopes, and offers only bounded Reader/TTS actions; it never hands the unrestricted localhost bearer token to browser JavaScript.
4. **Service:** existing Python TTS/Reader service on a private socket/loopback. The backend remains the single writer of the Reader library and the only owner of voice operations.
5. **Storage and models:** persistent server volume for SQLite, documents, model assets and generated/cached audio; independently verified backups and an export/recovery procedure.
6. **Optional agents:** OpenClaw or Hermes in separate containers/users with independent credentials and explicit, revocable scopes. No Docker socket, root access or broad Reader filesystem/SQLite mounts. Agent hosting is a separate experiment after the Reader is stable.
7. **Future audiobook worker:** optional offline GPU production connected by an authenticated job exchange/private network; never on the critical path for everyday streaming.

This is a **target design**, not a claim that the current server or clients already implement it.

## Design decisions / safety gates

- **Cloud hosting vs existing U8:** do not reuse or silently weaken the Windows U8 private-gateway trust model. Design the PWA's browser-origin auth, route allow-list and deployment as a separate reviewed boundary.
- **Network default:** a private/VPN-only pilot first. Do not expose port 7777, the SQLite database, local MCP/agent endpoints, Docker, the current U8 gateway or a privileged token publicly.
- **Auth:** first define a single-owner identity and explicit device/session revoke flow. If public browser access is later approved, use a vetted auth flow (for example OIDC/passkeys), server-side HttpOnly/Secure/SameSite cookies, CSRF protections and short-lived sessions. Browser JS must not persist the current all-powerful service token.
- **Privacy:** article text, credentials and raw audio are sensitive. No document text in access logs, telemetry, error trackers or agent prompts without explicit consent. Service-worker cache only static assets by default; user content offline cache must be opt-in, bounded, clearable, and visibly marked.
- **Data:** server-owned revisions, stable IDs and conflict responses. No blind last-write-wins or SQLite file synchronization. Ensure backup encryption/access control, restore testing, retention and explicit deletion.
- **Playback strategy:** prototype both existing WebSocket PCM streaming and an HTTP-served, browser-native playable format for reliable media controls, seeking and background playback. Do not promise uninterrupted mobile background playback until tested on real devices.
- **Compute:** initial planning envelope is an EU KVM host with approximately 4 vCPU, 8 GB RAM and SSD storage. This is a **benchmark candidate**, not certified capacity. Start with one CPU voice and one active stream; size up only after measuring CPU, RAM, synthesis real-time factor, queue latency and agent contention. Avoid overcommitting sherpa-onnx threads to virtual CPUs.
- **Commercial:** prefer monthly billing or no more than 12 months committed, explicit EU data-center selection, backups, and transparent renewal/IPv4/VAT costs. Keep hosting vendor-replaceable. No purchase is part of this roadmap.
- **Platform:** PWA installation varies by browser and OS; test Chromium desktop/Android first. Do not claim installability, Media Session support or offline behavior is identical on iOS/iPadOS, Samsung Internet or all browsers.

## Milestones and acceptance gates

### P0 — Inventory, proof of concept and architecture decision

- Inventory existing Reader APIs, auth, playback/resume contracts, exports, storage, extension constraints and relevant tests.
- Document the exact PWA MVP flows and how local and remote workspaces coexist.
- Record a short ADR selecting client framework/build tooling, media playback path, and private-network access model. Prefer minimal dependencies; do not couple the domain layer to browser code.
- Benchmark Piper and one Kokoro configuration on a representative 2-vCPU and/or 4-vCPU CPU-only environment; measure cold start, first audio latency, real-time factor, RAM, concurrency and recovery. Measure concurrent agent use separately.

**Done when:** baseline tests pass, architecture and security diagrams are approved, and VPS sizing uses measured results rather than assumptions. No public port is opened.

### P1 — Least-privilege browser gateway and service contracts

- Specify/add browser-safe auth/session handling, narrowly scoped Reader/TTS endpoints and device revocation. Maintain current local and U8 security semantics.
- Add stable playback progress APIs, versioned document metadata and bounded audio delivery/status where missing; avoid unnecessary API breakage.
- Add contract, negative-auth, session-expiry, CORS/CSRF, route-allow-list, rate-limit and restart/reconnect tests.
- Keep privileged local tokens and secrets server-side.

**Done when:** an untrusted browser cannot reach administrative endpoints, model installation, unrestricted Reader data, agent grants or raw SQLite, and a revoked session is denied.

### P2 — First responsive web Reader (online MVP)

- Add a separate web app (proposed location: apps/web_reader) for desktop, phone and tablet layouts.
- Implement owner login, service health, voice selection, open/import/select an existing article, Play/Pause/Stop, progress display, seek/resume and useful error states.
- Use existing document revision semantics. Start with one user, one active device and one CPU voice; do not require offline playback or background audio yet.
- Ensure keyboard, screen-reader labels, high-contrast and touch targets from the first vertical slice.

**Done when:** on a desktop and Android browser, the owner can sign in, play a real installed voice, resume the article and recover cleanly from a temporary network failure. Existing WPF/extension tests remain green.

### P3 — Installable PWA and robust playback

- Add a web app manifest, icons, install guidance, versioned service worker and a static-shell offline fallback.
- Integrate Media Session where supported; test headphones/Bluetooth controls, lock screen and app switching on real devices.
- Choose a tested audio buffering/delivery path that supports stable pause, seek, cancel and reconnection; retain the server's authoritative read position.
- Keep initial offline scope to static app shell and an honest “connection required for new speech” state. Cache or download user audio only through explicit later opt-in.

**Done when:** install works on tested Windows Chromium and Android Chromium browsers, updates do not corrupt sessions, and the client never claims offline TTS when the server is unavailable.

### P4 — Library, bookmarks and multi-device continuation

- Add library browsing, folders/search/queue, bookmarks and last-heard position with revision-aware updates.
- Handle cross-device position changes and concurrent edits explicitly; do not silently overwrite newer remote state.
- Support long documents through bounded pagination/chunks and existing Reader import/progress semantics.
- Keep Windows Local and remote cloud library clearly separate until the owner explicitly chooses an import/migration flow.

**Done when:** listening on Windows and continuing on Android/tablet preserves the intended article/position, conflicting edits do not destroy text, and a long article never needs to be loaded in full.

### P5 — EU KVM pilot deployment and operations

- Provision only after explicit approval and performance/security gates. Prefer a portable Ubuntu LTS deployment with separated service, edge, web adapter and optional model-worker containers/processes.
- Select an EU region; configure SSH keys, automatic security updates, host firewall, VPN access, resource limits, secrets, restart policy, non-root users and monitoring.
- Set up encrypted/off-site backups of DB and important assets, documented restores, storage alerts and predictable model/cache cleanup.
- Test host restart, disk full, failed model initialization, version rollback, expired/revoked client, and simulated VPS loss.
- Run CPU-only Piper/Kokoro benchmarks under real web-client and agent workloads before choosing a larger host.

**Done when:** a private owner-only pilot survives restart/reconnect, a backup is actually restored, and metrics prove acceptable single-user TTS performance without starving other services. No assumption that 2 shared vCPU support comfortable parallel synthesis.

### P6 — Mobile reliability and optional offline content

- Test actual Samsung Android phone/tablet behavior: sleep, lock screen, background media, Bluetooth, weak mobile connectivity and battery optimization.
- Add optional downloaded/previously rendered audio (not offline synthesis), storage quotas, expiry, user-initiated cleanup and transparent offline state.
- Consider PWA share-target and “open with” flows only when supported and reviewed for document privacy.
- Evaluate iOS/iPadOS later as a compatibility target, not a blocker for the Android-first release. Android Auto must be separately feasibility-tested; PWA installation alone does not create a native Android Auto app.

**Done when:** documented device-specific behavior matches actual tests, including failure/recovery; no promise of universal background audio.

### P7 — Optional private agents and automation (separate opt-in)

- Once the PWA/Reader is stable, isolate OpenClaw/Hermes from the TTS service; give agents a bounded voice/speech-generation or document-delivery tool instead of a privileged local token.
- Enable optional scheduling and delivery of text/audio summaries only with explicit source access, approval scopes, budgets and auditability.
- Keep agent failures from impairing speech latency; test CPU/RAM contention and rate-limit independent workloads.
- No background website monitoring, credential delegation, public connector, or autonomous writes by default.

**Done when:** an agent can perform only a separately approved action, loss/compromise of its credential cannot administer the host or read unrelated documents, and disabling it leaves the Reader functional.

## Proposed release slices

1. **Private alpha:** P0 + P1 + P2 on a controlled test machine; one real voice, one Android browser and one desktop browser.
2. **Usable private PWA:** P3 + P4; installability, progress sync and stable playback.
3. **Hosted personal beta:** P5; EU KVM, private/VPN-only access, tested backup/restore and CPU sizing.
4. **Comfort and expansion:** P6, then selectively P7; downloads and agents stay opt-in.

## Validation matrix

| Area | Minimum test |
| --- | --- |
| API/auth | Anonymous/expired/revoked users denied; browser cannot access privileged local APIs |
| Security | Origin/CSRF/session attacks, input bounds, safe logs, no public loopback/MCP/SQLite exposure |
| Audio | Piper + measured Kokoro, first-audio latency, real-time factor, pause/seek/cancel, long-text pacing |
| Resilience | Offline/network toggle, host restart, stream drop, interrupted download, client update |
| Data | Revision conflicts, two-device resume, import correctness, full backup/restore |
| Devices | Windows Chrome/Edge, Android Chrome on phone and Samsung tablet; optional Linux/iOS later |
| Operations | EU region, monthly costs, snapshots, updates, disk pressure, metrics, documented rollback |
| Regression | Python unit/integration/release checks, browser smoke, relevant .NET and Chrome MV3 tests |

## Open decisions before starting P0

1. Private VPN-only access for the first hosted version (recommended) versus a later public HTTPS login.
2. A separate cloud library versus a future explicitly approved import of selected local articles (recommend separate first).
3. Which audio delivery form gives the best supported background playback and seek/resume on Android.
4. Which actual EU KVM provider and region wins a **monthly-priced** pilot after CPU benchmarks and VAT/backup comparisons.
5. Whether agents share the same VPS after measured capacity or run on their own isolated instance.

## Start / handoff instructions

- This is a **roadmap, not an implementation request**. Do not provision hosting or change the current Reader deployment on the strength of this document alone.
- When the owner explicitly activates the track, add only **P0** to [codex/Plan.md](codex/Plan.md) as the next authorized bounded goal, with the usual validation/evidence recorded in [codex/Documentation.md](codex/Documentation.md).
- Work in small reversible slices. Update this roadmap with measured results and milestone status rather than marking later features completed by inference.
