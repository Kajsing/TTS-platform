# Reader append measurement - 2026-11-01

- Added isolated public-HTTP M1/M2 append benchmark, controlled source-size versus
  history-count fixtures, exclusive/inclusive phase timers and SQL-parent/commit/
  close counters. No production append behavior or live service data changed.
- Stored synthetic-only detailed report under ignored
  `logs/reader-append-benchmark-20261101/detailed-results.json`; retained two earlier
  successful diagnostics rather than discarding evidence.
- Detailed run: 10 cases, five measured samples plus one warmup each; all 60 full
  readbacks/receipt counts pass. Timed/verification/seed request counts: 60/1392/534.
- At fixed five chapters/272 blocks, M1 block-insert self median grows from 1.558
  ms at 50k source characters to 14.942 ms at 880k; M2 follows the same pattern.
  Code shows whole-document FTS reconstruction on each block insert. These timings
  include all insertion/trigger work and do not isolate FTS or explain every
  observed slowdown. Commit/close and large outliers remain explicit.
- `docs/reader_append_benchmark.md` records methodology, environment, complete
  timing ranges, limits and the proposed next investigation. No optimization is
  selected or implemented by this evidence-only slice.
- Validation: benchmark tests 5 pass; scoped Ruff passes. Real TCP miniature test
  covers both delivery paths and exact full readback. Existing HTTP dependency
  deprecation warnings are reported. Root agent owns overall validation/commit.
