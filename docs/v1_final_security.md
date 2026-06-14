# V1 Final Security Pass

Final security-focused pass for the local reader v1 goal.

| Field | Value |
| --- | --- |
| Scan id | `a1645b6_20260614T200121` |
| Scan target | Repository-wide final v1 security pass |
| Open reportable findings: 0 | Current working tree has no open reportable findings from this pass |
| Candidates fixed during scan | 5 |
| Primary report | `C:\tmp\codex-security-scans\TTS-platform\a1645b6_20260614T200121\report.html` |
| Markdown report | `C:\tmp\codex-security-scans\TTS-platform\a1645b6_20260614T200121\report.md` |

## Fixed Candidates

| Candidate | Surface | Fix summary | Validation |
| --- | --- | --- | --- |
| `CAND-SERVICE-API-001` | WebSocket streaming start frame | First WebSocket frame is capped before JSON parsing and must be text JSON object data. | Focused `test_streaming.py` WebSocket regression passed. |
| `CAND-MODEL-CORE-001` | Remote model artifact fetch | Remote artifacts require `artifact_sha256` before fetch, missing-checksum override is local-only, redirects are rechecked, and connected private/local peers are rejected when transport peer info is available. | Focused model-install checksum, hostname, and connected-peer private-network rejection tests passed. |
| `CAND-MODEL-CORE-002` | Model archive extraction | Zip member-count hints are checked before metadata load, and tar members stream through path/type/quota checks before writes. | Focused archive quota and streaming-tar tests passed. |
| `CE-COV009-AUDIO-QUEUE-DOS-001` | Chrome offscreen playback | Queued audio now has byte, chunk-count, and duration caps with a buffer-limit failure state. | Extension structural check and bundled Node syntax validation passed. |
| `CE-COV009-DOM-EXTRACTION-DOS-001` | Chrome content-script capture | Page capture now uses budgeted DOM traversal, text-node, heading, and readable-block limits. | Extension reader-flow and extension structural checks passed. |

## Validation Commands

Focused commands run during the final security pass:

```bash
python3 -m pytest apps/tts_service/tests/test_streaming.py::test_websocket_stream_rejects_oversized_start_event_before_auth apps/tts_service/tests/test_streaming.py::test_websocket_stream_accepts_auth_token_in_start_event apps/tts_service/tests/test_streaming.py::test_websocket_stream_rejects_invalid_first_event -q
python3 -m pytest apps/tts_service/tests/test_cli_models.py::test_model_install_rejects_remote_artifact_connected_private_peer apps/tts_service/tests/test_cli_models.py::test_model_install_rejects_remote_artifact_hostname_resolving_private apps/tts_service/tests/test_cli_models.py::test_model_install_rejects_missing_remote_checksum_before_artifact_fetch apps/tts_service/tests/test_cli_models.py::test_model_install_rejects_missing_remote_checksum_even_with_override -q
python3 -m pytest apps/tts_service/tests/test_streaming.py apps/tts_service/tests/test_cli_models.py apps/tts_service/tests/test_check_extension.py -q
python3 -m pytest apps/tts_service/tests/test_model_management_flow_check.py apps/tts_service/tests/test_extension_reader_flow_check.py apps/tts_service/tests/test_chrome_extension_smoke_check.py -q
python3 scripts/check_extension.py --node-executable <bundled-node> --require-js-syntax
python3 <codex-security-plugin>/scripts/validate_report_format.py --report-md C:\tmp\codex-security-scans\TTS-platform\a1645b6_20260614T200121\report.md
python3 <codex-security-plugin>/scripts/render_report_html.py --template <codex-security-plugin>/assets/report_template_inlined.html --report-md C:\tmp\codex-security-scans\TTS-platform\a1645b6_20260614T200121\report.md --report-html C:\tmp\codex-security-scans\TTS-platform\a1645b6_20260614T200121\report.html --title "TTS-platform Codex Security Scan"
```

The final completion gate is:

```bash
python3 scripts/check_v1_completion.py --require-complete
```

On Windows, use `py -3` when `python3` is unavailable.

## Follow-Up Boundaries

- If the service is intentionally exposed beyond loopback in a future milestone,
  run a new scoped security pass for origin, token, rate-limit, and WebSocket
  controls under that changed deployment model.
- If third-party remote catalogs become a supported end-user feature instead of
  an operator-controlled escape hatch, add signed catalog or pinned-host policy
  work before treating that channel as trusted.
