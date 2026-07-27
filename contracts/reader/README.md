# Reader contract fixtures

These JSON files freeze representative version-1 Reader HTTP payloads. They are
backend-agnostic and intentionally exclude document text from summaries and edit
history text from mutation responses.

Run `py -3 scripts\check_reader_contracts.py` on Windows to validate every
fixture against the service schemas. Contract changes must remain additive or
increment `contract_version` deliberately.

All `/v1/reader/*` routes require the service's existing bearer-token and origin
checks. `/v1/health` remains public and exposes only sanitized Reader readiness.
