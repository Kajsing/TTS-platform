# Reader append benchmark

## Purpose and command

`scripts/benchmark_reader_append.py` measures actual M1 chapter delivery and M2
managed delivery through the public HTTP service contract. It uses only synthetic
text and owns temporary Reader storage, credentials, stub backend and a prebound
ephemeral loopback socket. It refuses port 7777. It does not open the live Reader
profile, modify service configuration or change production append behavior.

```powershell
py -3 scripts/benchmark_reader_append.py --output logs/reader-append-benchmark-20261101/detailed-results.json --repeats 5 --warmups 1
py -3 -m pytest -q packages/reader_core/tests/test_append_benchmark.py
py -3 -m ruff check scripts/benchmark_reader_append.py packages/reader_core/tests/test_append_benchmark.py
```

The report contains counts, hashes and timings; no text, SQL, credential or raw
server error bodies. Temporary databases contain synthetic fixtures and are
removed after the run. Results stay under ignored `logs/`.

## Controlled comparisons

- Source-size cases start at 50,000 / 400,000 / 880,000 normalized characters,
  each with five delivered chapters and 272 source blocks, including the fixed
  two-block wrapper. The near-limit case remains below the 900,000-character
  default after appending.
- History cases use 5 / 40 / 90 delivered chapters at exactly 400,000 characters
  and 272 blocks. The five-chapter baseline is the source-size medium case.
  Splitting the same number of paragraphs into different deliveries separates
  history/marker count from source length and block count. It does not isolate
  every effect of history layout or retained edit metadata.
- Every timed request appends the identical 4,000-code-point, two-paragraph
  payload, containing one non-BMP character. M1 calls `/articles/{id}/chapters`;
  M2 calls `/import-plans/{id}/chapters` for the last prepared chapter in the
  existing part. M2 final-part hash validation is therefore included explicitly;
  this does not measure first-part creation or rollover latency.
- Baselines are seeded and fully read back using public endpoints outside
  timing. After stopping that temporary service, its Reader directory is copied
  to a fresh temporary profile for every sample. Each replica starts a fresh app
  and warms its TCP/auth connection with one workspace request before timing.
  OS file caches are not flushed. Five measured samples and one separately
  retained warmup are used per case/path. Failed calls are retained without
  automatic retries; warmups alone are excluded from the summary.
- Every append is followed by complete revision-pinned public text readback,
  exact normalized comparison and chapter-receipt count verification. Verification
  requests are counted separately from the one timed mutation.

## Timing boundaries

Process-local wrappers instrument application dispatch, authorization, target
resolution, M1/M2 delivery, append, chapter-marker history, history insertion/
trimming, cursor revision updates, document counters and managed-part validation.
SQLite `execute`, `executemany`, commit, rollback and close are timed; SQL labels
contain only the enclosing allowlisted method name, never statements or values.
Connection setup uses the same flags/PRAGMAs as the ordinary repository.

Each span retains inclusive time and **exclusive self time**, subtracting timed
child spans. Exclusive times can be added without double-counting nested calls.
`sqlite_executemany:append` covers block insertion including SQLite triggers.
Cursor iteration/materialization is charged to its enclosing method, rather than
the initial `execute` call. `sqlite_close` includes normal connection teardown;
it is not a separately isolated checkpoint/disk measurement.

All timed calls are instrumented; profiler overhead is not subtracted. The
client wall-time remainder is labeled HTTP/framework/serialization/uninstrumented
work, not pure network latency. This is a diagnostic benchmark, not a production
latency SLA, memory benchmark, unprofiled throughput test or playback regression
test. Machine background activity and storage-cache state are not controlled.

## Observed Windows run: 2026-11-01

Authoritative detailed report:
`logs/reader-append-benchmark-20261101/detailed-results.json`.
Environment: Windows 11 build 26200, Python 3.12.10, SQLite 3.49.1, 24 logical CPUs.
Started at 15:08:34 UTC. All **60 samples** (50 measured + 10 warmups) passed full
readback and receipt verification: **60 timed requests**, **1,392 verification
requests**, and **534 baseline-seeding requests**. There were no failed samples.

Earlier successful diagnostic reports are retained as `initial.json` (one sample
per case) and `results.json` (five plus warmup, before adding finer SQL-parent and
connection-close timing). They are exploratory evidence, not replacements for
failed runs. The table below uses only `detailed-results.json`.

| Source before append | Seed chapters | M1 median ms | M1 observed min-max ms | M2 median ms | M2 observed min-max ms |
| --- | ---: | ---: | --- | ---: | --- |
| 50,000 | 5 | 29.156 | 20.835-29.773 | 32.469 | 23.001-34.727 |
| 400,000 | 5 | 35.550 | 28.484-37.574 | 31.565 | 30.755-39.957 |
| 880,000 | 5 | 42.898 | 39.893-415.226 | 54.073 | 44.451-180.399 |
| 400,000 | 40 | 38.554 | 28.303-353.918 | 41.355 | 33.933-42.047 |
| 400,000 | 90 | 39.667 | 33.646-358.683 | 37.132 | 33.903-188.956 |

The large outliers remain in the report and ranges. Five samples do not support
a tail-latency claim; the source of those outliers is not established.

At fixed chapter/block count, median exclusive block-insert time grows from
**1.558 to 6.525 to 14.942 ms** for M1, and **1.641 to 6.752 to 15.525 ms** for M2.
This is the clearest measured source-size-dependent component in these fixtures.
Source inspection of `_initialize_search_index` in `sqlite/repository.py` confirms
that every inserted block fires a trigger that deletes/reconstructs the document's
FTS content using all its blocks. Existing prose is therefore processed again.
The timer includes the entire insertion/trigger path; it does **not** isolate FTS
work from the remaining SQLite insertion costs or prove it explains every slowdown.

At fixed 400,000 characters/272 blocks, increasing history from five to 90
chapters changes M1 marker self time from **0.493 to 1.295 ms** and history-trim
self time from **0.206 to 1.209 ms**. The corresponding M2 values are **0.618 to
1.166 ms** and **0.229 to 1.046 ms**. Total latency is noisy and nonmonotonic;
these results do not establish history count as the dominant overall bottleneck.
M2 final-part validation ranges from **0.308 ms** at 50k to **1.526 ms** at 880k.
Commit and close costs are substantial and variable, so their measured categories
must remain visible in any follow-up comparison.

## Recommended follow-up, not implemented here

Investigate performing search-index maintenance once per logical append, or an
equivalent incremental update, while preserving transactional search correctness,
edits/Undo/Redo, privacy filtering and rollback behavior. Compare against this
controlled baseline before selecting an optimization. A dedicated trigger/index
ablation would be needed to isolate its causal share of runtime. No production
optimization, search contract change or rate-limit change is part of this benchmark.

Validation: five benchmark tests pass, including real TCP service delivery and
full readback for both paths, exact fixture counters, exclusive-time accounting,
privacy-safe instrumentation restoration and retained failed-sample metadata.
Ruff passes. The test runtime emits two existing uvicorn/websockets deprecation
warnings; they do not affect the HTTP-only checks.
