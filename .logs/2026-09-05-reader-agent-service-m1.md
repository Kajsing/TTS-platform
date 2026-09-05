# Reader Agent Access M1: service foundation

- Added schema 10 for revocable folder grants, chapter receipts and retry aliases.
- Added a scoped transaction facade that reuses ordinary Reader editing/history.
- Added native-loopback agent APIs and distinct owner-authenticated grant setup.
- Preserved active content leases, optimistic desktop edits, privacy locks,
  local binding and the remote gateway deny boundary.
- Tests use isolated temporary databases and fake synthesis; the user's Reader,
  service, live library, credentials and models were not changed or restarted.
- Added API/decision/security-review documentation. No dependency introduced.
- Validation: 497 Python tests passed, Ruff clean, 20 Reader contract fixtures
  passed. All tests used temporary storage. Desktop validation belongs to the
  subsequent Options/MCP slice.
- M1 remains active and incomplete. MCP, Options, DPAPI handoff, Windows smoke
  and exact shortcut deployment are still required. U8 remains parked.
