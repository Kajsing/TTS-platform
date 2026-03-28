# Security

Security baselines for this repository:

- The service is expected to bind to `127.0.0.1` by default.
- Token-based write protection remains a required design constraint.
- Configuration validation must reject obviously unsafe or broken values.
- Raw input text should not be logged by default.
- Future browser integration must use explicit origin allow-lists rather than wildcard CORS.

Phase 1 establishes defaults and documentation only. Enforcement will start in later phases together with API endpoints.
