# Security

Security baselines for this repository:

- The service is expected to bind to `127.0.0.1` by default.
- Token-based write protection is enforced for synthesis and job endpoints.
- Token rotation is available through a protected local endpoint.
- Configuration validation must reject obviously unsafe or broken values.
- Raw input text should not be logged by default.
- Requests with an `Origin` header are checked against an explicit allow-list.
- Protected endpoints use in-memory rate limiting as a baseline safeguard.

The current implementation uses a local token file and in-memory guards. This is sufficient for the current localhost MVP stages, but later phases should revisit persistence, rotation workflows, and browser-facing hardening details.
