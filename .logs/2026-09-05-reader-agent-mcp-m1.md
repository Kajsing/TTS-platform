# Reader Agent Access M1 - MCP / Options slice

- Scope: optional local stdio adapter, one-folder Options grants, protected
  configuration, desktop coexistence guard and isolated Windows acceptance.
- Backend foundation is already committed as `8df6853`; this slice consumes its
  protected HTTP contract and keeps Python service-owned persistence.
- Added `apps/reader_agent`, SDK 2.1.1 optional extra, separate `.venv-agent`,
  bounded HTTP adapter and nine MCP tools. No remote transport, website fetch,
  scheduler, paid account, token in client config or direct DB access.
- Added Options pane, owner grant client methods, CurrentUser DPAPI local files,
  compensation on failed key save, revoke and sanitized runtime check.
- Guarded editor refresh after awaits and locked loading; coherent-page revision
  check prevents externally changed blocks from being used with a stale revision.
- Added real subprocess/HTTP restart/concurrent-retry smoke plus explicit WPF
  isolated settings/provision/read/revoke hook. No live profile/clipboard/audio
  device access. Uses stub PCM and checks ordinary source-mapped Reader streaming.
- A full-suite rerun exposed an existing completion/cancel race in the lease
  test, not the production stream. Split deterministic post-generation release
  from event-synchronized in-generation cancellation. Both preserve strict lease
  and metrics assertions; production streaming code is unchanged.
- Tests: final base Python 522 passed/2 optional skips; agent env 26 passed/no skips;
  pip check; Ruff; Python format; 20 contract fixtures; .NET 167 tests;
  solution format; WPF build; self-contained win-x64 publish; both development
  and root-shortcut exe passed isolated end-to-end smoke (98 audio packets and
  source spans). Visually inspected synthetic Options/article screenshots.
- User closed Reader for safe publication. Root `.lnk` target was read via
  WScript.Shell and tested exactly, not merely the development build.
- Live service is old (new grant route 404), idle (zero leases, only completed
  exports). Exact-process restart attempt was blocked by execution policy before
  execution; no workaround attempted. User restart + route readiness check is
  still required before final goal completion. No live grant/article was created.
- Dependency license review and SDK primary documentation are recorded in
  THIRD_PARTY_NOTICES.md and docs/reader_agent_mcp.md. No security or licensing
  direction change. Adapter isolation is not a same-user filesystem sandbox.
- Preserve/exclude user models/MANIFEST.json. Commit/push validated source/docs.
- U8 is still parked/incomplete; revisit with user after M1, never silently open
  ports, configure WireGuard or create firewall rules.
