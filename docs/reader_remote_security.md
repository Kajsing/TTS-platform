# Reader Remote Access Security

## Status

This document began as the Reader Upgrade U7 threat model and architecture
decision. The user approved the optional, owner-managed WireGuard direction and
started U8 on 2026-08-19. The U8 beta is now implemented but remains disabled by
default. The final acceptance step is a live create/status/remove pass for the
exact firewall rule on the owner's intended WireGuard interface.

The normal service remains plain HTTP on `127.0.0.1`. U8 does not widen that
listener. It adds a separate HTTPS/WSS gateway which can start only from an
explicit remote profile after its certificate identity, private bind address,
and exact Windows Firewall rule have all been revalidated.

## Decision summary

The first remote Reader will be a single-owner, private-network feature with
these boundaries:

1. Keep the existing localhost listener and its clients unchanged.
2. Keep Local as the default workspace. Its existing localhost service,
   library, models, and offline behavior do not depend on remote access.
3. Add a separate, disabled-by-default secure Reader gateway in U8.
4. Bind that gateway to one explicitly selected private or VPN interface
   address, never a wildcard address.
5. Accept only HTTPS and WSS on the gateway. Do not open or redirect a plain
   HTTP LAN port.
6. Give the gateway an ECDSA P-256 server identity and pin its SHA-256 Subject
   Public Key Info (SPKI) in each paired desktop profile.
7. Pair out of band with a short-lived invitation containing the endpoint,
   SPKI pin, and a high-entropy one-time secret.
8. Give every paired computer its own high-entropy, revocable credential.
9. Use the existing Reader API, stable IDs, content revisions, and row-version
   conflicts. Never copy or synchronize the live SQLite database.
10. Keep Local and Remote as separate workspaces in the first version. Switching
    profiles never migrates, replaces, or merges the local library.
11. Keep direct public Reader exposure unsupported. Remote internet use goes
    through owner-managed WireGuard. Reader does not depend on a hosted VPN
    account or control plane, and the transport remains replaceable.
12. Keep the Chrome extension outside the first remote slice.

The secure gateway is preferred over changing the existing listener because it
preserves the known localhost contract for the WPF Reader, Chrome extension,
SAPI bridge, CLI, and other local tools. It also provides one place to enforce
remote-only credentials, endpoint restrictions, and per-device limits before a
request reaches the local service.

## Product and trust boundary

### In scope for the first beta

- one owner and their explicitly paired Windows computers;
- the existing local Windows Reader as a complete, offline-capable default;
- an owner-controlled private network, with self-hosted WireGuard as the
  recommended internet transport and trusted LAN as an optional local path;
- online access to the server-owned library, folders, rules, bookmarks, queue,
  imports, exports, editing, and TTS playback;
- named local and remote desktop connection profiles;
- no offline remote replica;
- revocation of a lost or retired client computer.

### Out of scope

- forwarding the Reader HTTPS/WSS port, public Reader DNS/TLS hosting, or a
  third-party cloud relay required by Reader;
- installing or administering WireGuard from inside Reader;
- anonymous, guest, or multi-user accounts;
- collaborative editing or automatic conflict merging;
- synchronization of SQLite files;
- remote model installation, service control, local-token rotation, support
  bundles, or Privacy-lock recovery and configuration;
- Chrome-extension remote access;
- protection after the server's Windows account or an administrator is
  compromised;
- protection of exported files deliberately saved on a client computer.

## Assets

- article text, titles, folder names, source metadata, search terms, rules, and
  generated audio;
- Privacy-lock codes, recovery keys, and unlock sessions;
- the existing localhost bearer token;
- remote device credentials and pairing invitations;
- the server identity private key and its pinned public-key identity;
- revision history, bookmarks, queue state, and export files;
- service availability and TTS compute capacity.

## Attacker model

The design considers:

- a passive LAN observer;
- an active LAN attacker able to spoof DNS, ARP, or a server address;
- an unpaired computer on the same LAN or VPN;
- a malicious web page trying to reach a local or private service;
- a stolen remote computer or copied remote credential;
- an internet scanner reaching a mistakenly forwarded port;
- malformed, oversized, replayed, or high-rate requests from a paired device;
- simultaneous edits from two legitimate paired computers.

Same-user malware on the server can already read the local token, database, and
audio. U8 does not claim to protect against that stronger local compromise.

## Threats and controls

| Threat | Required control | Residual risk |
| --- | --- | --- |
| Private-network traffic is read or modified | WireGuard plus TLS 1.3 preferred, TLS 1.2 minimum; HTTPS/WSS only | Endpoint traffic remains visible to the two Windows machines themselves |
| Active man-in-the-middle during pairing | Invitation carries the SPKI pin before network contact; no certificate-warning bypass or trust-on-first-click | The invitation must be transferred through a channel the owner trusts |
| False server after pairing | Exact SPKI pin, hostname/SAN, expiry, and server-auth usage validation for both HTTP and WebSocket | Server-key compromise requires revocation and re-pairing |
| Stolen shared localhost token | Local token is never accepted by the gateway and never sent to a remote client | Same-user server malware remains out of scope |
| Lost client computer | Per-device credential stored with Windows protection; immediate server-side revocation | Data already displayed or explicitly exported on that client cannot be recalled |
| Pairing-code guessing | 256-bit random ticket secret, ten-minute expiry, single use, five failures per ticket/IP | Invitation disclosure during its short life permits pairing |
| Credential replay | TLS, protected client storage, device-specific credential, last-used visibility, revoke and rotate | A copied live bearer remains usable until revoked; request signing is deferred |
| Malicious web origin | Remote gateway rejects every request carrying an `Origin` header in the first beta; no CORS; no WebSocket token in a start message | A compromised native paired client retains its authorized access |
| DNS rebinding or forged proxy headers | Pin the server key; use the socket peer/local address; ignore and strip forwarded-IP headers | None beyond server/key compromise |
| Public Reader exposure by mistake | Disabled profile, exact private/VPN bind address, narrow firewall rule, prominent unsupported warning | NAT port forwarding cannot be detected reliably; the Reader gateway must never be forwarded |
| Request flooding | Pre-auth IP limit, post-auth device limit, one active speech stream per device, existing global TTS/export limits | A paired device can still consume some local compute until revoked |
| API privilege expansion | Positive remote endpoint allow-list; deny unknown and administrative paths before proxying | The allow-list must be reviewed whenever new routes are added |
| Private text in caches or logs | `Cache-Control: no-store`; existing low-sensitivity logging; gateway logs only IDs, counts, device ID, outcome, and timing | OS memory, screen capture, and explicit client exports remain outside this control |
| Concurrent overwrite | Existing integer row versions, content revisions, content leases, and typed conflicts; no last-write-wins fallback | The owner must choose how to resolve a real conflict |
| Gateway compromise reaches localhost | Gateway strips remote auth and adds the local token only on its internal loopback hop; strict route and header allow-lists | A compromised gateway process runs as the same Windows user and is a server compromise |

## Listener architecture

U8 should add a companion gateway rather than run a second copy of the TTS
application:

```text
Local WPF / Chrome / SAPI
        |
        | HTTP/WS + existing local token
        v
127.0.0.1:7777  Existing service and single Reader/TTS state
        ^
        | internal loopback proxy; remote credential stripped
        | existing local token attached only inside the server computer
        |
selected-private-IP:configured-port  Secure Reader gateway
        ^
        | HTTPS/WSS + pinned server key + per-device credential
        |
Paired remote WPF Reader
```

The gateway and local service run under the same Windows user. The gateway must
not duplicate model loading, export workers, or Reader application state. It
forwards bounded HTTP bodies and WebSocket frames to the one localhost service.
It must not trust `X-Forwarded-For`, `Forwarded`, a client-supplied Host header,
or an inbound Authorization header after device authentication.

Fail closed if the localhost service, credential store, certificate/key, or
selected interface is unavailable. The local service remains usable if the
gateway fails or is stopped.

## Server certificate and pinning

### Creation

- Generate one ECDSA P-256 identity key when the owner explicitly enables the
  remote profile.
- Store the private key under the current user's Reader remote-access directory
  with an ACL limited to that user and administrators. This is filesystem
  protection, not hardware-backed key storage or encryption at rest.
- Create a SHA-256 self-signed leaf certificate with server-auth extended key
  usage and SAN entries for the selected IP address and configured server name.
- Do not install a root CA into either computer's global trust store.
- Do not use a public CA merely to serve a private IP.

### Client validation

The pairing invitation installs a `sha256/<base64>` hash of the certificate's
Subject Public Key Info into the remote connection profile. Every `HttpClient`
and `ClientWebSocket` connection must require:

- HTTPS/WSS scheme;
- an exact configured host and port;
- a valid current certificate time range;
- server-auth extended key usage;
- no hostname/SAN mismatch;
- a constant-time match with the stored SPKI pin.

The self-signed chain error is the only normal chain exception. The UI must not
offer `Continue anyway` after a pin, name, usage, or expiry failure.

Certificate renewal reuses the identity key and therefore the pin. If the IP or
server name changes, issue a new certificate with the same key and updated SAN
before starting the gateway. Rotating or losing the identity key requires every
remote client to pair again. That is preferable to silently trusting a new key.

Mutual TLS is not selected for the first beta. It adds client-certificate
issuance, storage, renewal, and revocation complexity without removing the need
for a device list and product-level revocation. Pinned TLS plus a random
per-device credential provides the required single-owner control with a much
smaller recovery surface.

## One-time pairing

1. On the server computer, the owner chooses **Create pairing invitation**.
2. A local-only operation creates a random ticket ID and 256-bit secret, stores
   only the secret hash, and expires it after ten minutes.
3. The UI shows one copyable invitation containing contract version, exact
   HTTPS endpoint, SPKI pin, ticket ID, and secret. A QR rendering may be added
   later, but the encoded payload is the authoritative form.
4. The owner transfers the invitation to the second computer out of band.
5. The remote Reader validates the invitation shape, connects using the
   supplied pin, and only then sends the one-time secret with a user-chosen
   device name.
6. The server consumes the ticket and returns a 256-bit device credential once.
7. The client stores the device credential with Windows DPAPI or Credential
   Manager and persists only its connection metadata and SPKI pin in settings.
8. The server stores device ID, display name, credential hash, creation time,
   last-used time, generation, and revocation state. It never stores the
   plaintext credential.

Pairing is never available on plain HTTP. A consumed, expired, or throttled
ticket cannot be retried. Pairing invitations, device credentials, folder
codes, and recovery keys never enter ordinary logs.

## Device credential lifecycle

- Credential format: versioned opaque bearer containing a non-secret device ID
  and at least 256 random secret bits.
- Lookup by device ID, followed by constant-time comparison of the stored
  SHA-256 secret hash. A slow password hash is unnecessary for an unguessable
  random secret.
- Revocation is immediate for new HTTP requests and WebSocket handshakes. The
  gateway also closes active streams for that device.
- Rotation is two phase: an authenticated client requests a pending new secret;
  the old credential remains valid briefly; the client stores and confirms the
  new credential; confirmation activates the new generation and revokes the
  old. An unconfirmed rotation expires without locking out the client.
- The server UI lists device name, paired time, last-used time, current status,
  and Revoke/Rotate actions. It never displays a credential.
- Removing the remote profile revokes every device, deletes pending invitations,
  removes the exact firewall rule, and stops the gateway. Library data remains.

## Remote API policy

All data-plane requests, including health, require a valid device credential.
The pairing endpoint is the only pre-device exception and accepts only a valid
short-lived ticket over pinned TLS.

### Allowed in the first beta

- `/v1/health`, `/v1/voices`;
- Reader capabilities, library lists/search, documents, blocks, positions,
  bookmarks, queue, folders, moves, imports, exports/results, highlighter,
  rules, and Reader WebSocket playback;
- Privacy-lock unlock and relock;
- the bounded synchronous/streaming TTS endpoints needed for explicit remote
  clipboard playback.

Destructive Reader actions remain available because this is one owner's full
Reader client, but the desktop must retain its current confirmations and send
the current row version.

### Denied in the first beta

- auth-token rotation and every endpoint not on the positive allow-list;
- service start/stop, service installation, model install/remove/activate,
  configuration, diagnostics/support-bundle creation, and arbitrary filesystem
  paths;
- Privacy-lock setup, code change, removal, and recovery;
- browser capture, extension onboarding, and desktop-open handoff;
- credentials in query strings or WebSocket start messages;
- every request carrying a browser `Origin` header.

The gateway must have tests that enumerate the actual registered service routes
and fail when a newly added route has no explicit remote classification.

## Rate and resource policy

- Before authentication: five failed pairing/auth attempts per source IP in ten
  minutes, with bounded global state.
- After authentication: default 120 ordinary HTTP requests per minute per
  device, keyed by device ID rather than IP.
- One active Reader/raw-TTS WebSocket playback stream per device.
- One active import upload per device; existing file, archive, character, block,
  and parser limits remain authoritative.
- Export creation receives a separate low-frequency limit while existing
  service-wide export concurrency remains authoritative.
- Existing global TTS job and stream concurrency remains defense in depth.
- A 429 response identifies only the applicable limit and retry delay; it does
  not expose another device or a private value.

These values are safe beta defaults, not a public multi-tenant capacity claim.

## Simultaneous edits and state

Remote clients use the current Reader contracts unchanged:

- every mutation sends its expected integer row version;
- content revisions and stable block IDs remain the source of truth;
- an active playback stream keeps its content lease;
- stale updates return the existing typed conflict rather than overwriting;
- the desktop offers reload, retry after review, or duplicate-as-editable where
  appropriate;
- timestamps are display/audit information, never concurrency authority;
- no automatic merge or last-write-wins behavior is added in U8.

Two-client Windows smoke must prove that one client's stale edit cannot replace
the other's committed edit.

## Windows Firewall design

U7 does not change the firewall. U8 may offer an elevated, reviewable action
only after the owner selects a private interface and port.

The created rule must use:

- one stable internal name containing the Reader remote-profile ID;
- inbound TCP only;
- the exact selected local IP and configured port;
- `RemoteAddress LocalSubnet` for the optional LAN preset, or an explicitly
  selected WireGuard peer/subnet for the recommended VPN preset;
- Windows `Private` profile only for the LAN preset;
- for the WireGuard preset, the exact tunnel interface alias plus its exact
  current Windows network profile; never an unrestricted interface or `Any`
  profile;
- the exact packaged gateway executable/interpreter path;
- no edge traversal and no wildcard local address.

Conceptual PowerShell shape:

```powershell
New-NetFirewallRule `
  -Name "TTSPlatform.Reader.Remote.<profile-id>" `
  -DisplayName "TTS Platform Reader secure remote access" `
  -Group "TTS Platform Reader" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalAddress <selected-private-ip> `
  -LocalPort <selected-port> `
  -RemoteAddress LocalSubnet `
  -Profile Private `
  -Program <exact-gateway-program>
```

Setup first previews the rule, verifies the active interface and network
category, and asks for elevation. The LAN preset refuses Public networks. The
WireGuard preset may match a Public-classified tunnel only when the rule also
matches the exact tunnel interface alias, private local address, and explicit
peer/subnet. Both presets refuse `0.0.0.0`, `::`, `Any` profile, unrestricted
interfaces, and `Any` remote address. Re-running setup is idempotent only when
every property matches; a conflicting existing rule is reported rather than
broadened.

Disable/uninstall removes only the exact stored rule name:

```powershell
Remove-NetFirewallRule -Name "TTSPlatform.Reader.Remote.<profile-id>"
```

Status reads the rule and its address/application filters back and compares
them with the saved profile. A firewall rule is defense in depth; missing
authentication or TLS is never excused by a narrow rule.

## Internet access through owner-managed WireGuard

The first supported remote-internet path is an owner-managed WireGuard network.
WireGuard is not part of the Reader protocol: Reader will not install, update,
configure, or administer it. The operator supplies a working WireGuard address,
and the Reader gateway binds only to that exact private address. This keeps the
transport replaceable if another self-hosted VPN is selected later.

The WireGuard endpoint itself may require an owner-configured public UDP
endpoint, router forwarding, dynamic DNS, or equivalent reachability. That is
separate from the Reader gateway: the Reader HTTPS/WSS port is never forwarded
or bound to a public interface. The same TLS pin and device credential remain
mandatory because WireGuard is an additional network boundary rather than a
replacement for Reader authentication.

Reader never performs UPnP/NAT-PMP changes. Direct Reader port forwarding, a
public Reader reverse proxy, and public Reader HTTP(S) hosting are unsupported.
If public Reader hosting is ever proposed, it requires a new threat model
covering public certificates, account recovery, abuse response, patching,
Internet-scale rate limiting, and service isolation.

## U7 Windows feasibility spike

The committed spike is deliberately isolated from production settings:

```powershell
py -3 scripts\check_reader_secure_transport.py --require-windows
```

It:

- creates a temporary ECDSA P-256 certificate and private key with .NET;
- starts the actual Reader FastAPI application on `127.0.0.1` only with Uvicorn
  TLS;
- creates a temporary token, manifest, Reader home, and database;
- has a .NET client validate the SPKI pin for raw TLS, HTTPS, and WSS;
- proves a wrong pin is rejected;
- calls protected Reader capabilities and creates a temporary document over
  HTTPS;
- completes the Reader `started -> mark -> PCM -> done` protocol over WSS;
- proves plain HTTP is rejected on the TLS port;
- removes all temporary state and makes no firewall change.

Windows evidence from 2026-08-19:

- negotiated protocol: TLS 1.3;
- wrong SPKI pin: rejected;
- protected Reader HTTPS: passed;
- Reader WSS: 45 marked PCM messages, 84,768 audio bytes, completed;
- plain HTTP on the TLS listener: rejected;
- remote binding: disabled;
- firewall changes: none.

The spike proves transport and .NET pinning feasibility. It is not the U8
gateway, pairing store, device UI, or firewall implementation.

## U8 implementation gates

U8 is complete only when all of these pass:

- localhost behavior and existing clients remain unchanged;
- Local is the default workspace, works without WireGuard or internet access,
  and retains its own existing local library and models;
- Remote profiles are explicit, separate from Local, and cannot overwrite or
  silently migrate the local library;
- secure profile is absent/disabled by default and cannot bind a wildcard;
- non-loopback startup refuses missing TLS, missing device store, public IP,
  wrong SAN, or unsafe firewall state;
- TLS 1.0/1.1 and plain HTTP fail; TLS 1.2/1.3 work;
- correct and incorrect SPKI pins are tested for HTTP and WSS;
- pairing is pinned, single-use, expiring, throttled, and secret-free in logs;
- two devices receive different credentials; revoke and two-phase rotation are
  proven;
- remote route-classification tests fail closed for unknown routes;
- browser origins and WebSocket start-message credentials are rejected;
- per-IP, per-device, stream, upload, and global resource limits are tested;
- remote Privacy-lock unlock/relock works while administration/recovery is
  denied;
- two logical clients prove row-version conflicts and content leases;
- firewall create/status/remove is idempotent, exact, reversible, and tested on
  Windows without leaving a rule behind;
- disabling remote access closes the listener, revokes devices, clears pending
  pairing tickets, and leaves localhost Reader operation and data healthy;
- a scoped security review reports no unhandled high/critical findings.

## U8 implementation evidence

The beta implementation adds:

- a separate Uvicorn HTTPS/WSS gateway and a positive Reader route allow-list;
- a SQLite pairing/device store containing hashes rather than plaintext
  invitation or device secrets;
- ten-minute one-use invitations, per-device credentials, immediate revocation,
  and two-phase credential rotation;
- ECDSA P-256 identity generation plus start-time validation of the key pair,
  validity period, self-signature, server-auth usage, SAN, and persisted SPKI
  pin;
- exact private-address binding with no wildcard, loopback, link-local, public,
  or hostname bind;
- local-only native administration endpoints, per-IP and per-device throttles,
  one upload and one stream per device, request/frame limits, browser-Origin
  denial, and credential rejection in query strings or WebSocket messages;
- Local/Remote desktop profiles, pinned HTTP and WSS clients, DPAPI-protected
  device credentials, pairing, rotation, profile switching, device management,
  and local-only Privacy-lock administration controls;
- an elevated firewall helper limited to one profile UUID, exact address, port,
  program, Windows profile, interface (for WireGuard), and peer IP or subnet.
  IPv4 peer subnets must be `/24` or narrower and IPv6 peer subnets `/64` or
  narrower. Conflicting rules are never broadened or replaced;
- a disable flow that stops the gateway and revokes devices before attempting
  removal of only that exact firewall rule.

`scripts/check_reader_remote_gateway.py` is the isolated live security smoke. It
uses two logical devices and a temporary TLS gateway, does not modify Windows
Firewall, and proves pinned HTTPS/WSS, wrong-pin rejection, single-use pairing,
two-phase rotation, revocation, row-version conflict behavior, content leases,
Origin/admin denial, legacy-TLS/plain-HTTP rejection, and continued localhost
health after the gateway stops.

On 2026-08-19 that smoke negotiated TLS 1.3 and passed every assertion. Its
first device paired through the production .NET `RemotePairingClient`, including
the same certificate-pin validator used by the desktop. All 468 Python tests,
all 142 .NET Release tests, Ruff, .NET format, the complete Windows desktop
integration/package smoke, the transport smoke, and the security-default check
also passed. A scoped review found no unhandled high or critical issue within
this threat model.

The firewall helper separately passed read-only status inspection and rejected
an over-broad subnet before firewall inspection. This computer currently has no
WireGuard interface and its physical Ethernet profile is Public, so the final
elevated create/status/remove proof is deliberately not faked against the wrong
interface. No firewall rule was left behind.

## References

- [OWASP Transport Layer Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html)
- [Python `ssl` contexts and TLS version controls](https://docs.python.org/3.12/library/ssl.html)
- [Uvicorn HTTPS settings](https://www.uvicorn.org/settings/#https)
- [.NET `ClientWebSocketOptions.RemoteCertificateValidationCallback`](https://learn.microsoft.com/dotnet/api/system.net.websockets.clientwebsocketoptions.remotecertificatevalidationcallback)
- [.NET `SubjectAlternativeNameBuilder`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.x509certificates.subjectalternativenamebuilder)
- [Microsoft `New-NetFirewallRule`](https://learn.microsoft.com/powershell/module/netsecurity/new-netfirewallrule)
- [Microsoft Windows Firewall command-line management](https://learn.microsoft.com/windows/security/operating-system-security/network-security/windows-firewall/configure-with-command-line)
- [WireGuard project and protocol overview](https://www.wireguard.com/)
- [WireGuard platform installers](https://www.wireguard.com/install/)
