# T2 fixed-text voice preview — 2026-09-06

## Completed slice

- Native-owner, loopback/no-Origin POST `/v1/service/voice-preview` accepts only
  a selected voice and an idle reservation. English/Danish samples are fixed on
  the server. Remote route inventory explicitly denies it. Reuses synthesis;
  no model, default, Reader preference or article mutations.
- Rendering consumes the maintenance reservation until the actual synchronous
  native worker exits. Client cancellation/expiry/release cannot free a live
  worker. WAV response is bounded and non-cacheable.
- Desktop validates mono PCM16 WAV <=2 MiB and <=10 seconds; acquires a new idle
  reservation after rendering. Conservative deadline includes request latency
  and a safety margin. Stop/dispose precedes release, including cancellation.
- Tray-owned preview serializes library/lifecycle actions and guards existing
  active, paused or transitioning Reader speech, dialogs and calls/alarms.
  Disabled Reader commands and post-await playback rechecks prevent late starts.
  Stop preview or closing the panel cancels; unlike installation, preview audio
  does not continue behind a closed panel. Draft/editor state is preserved.

## Files

- Python `service_control.py`, router wiring in `main.py`, explicit deny in
  `remote_gateway.py`, `test_service_control.py`.
- Client preview contract/bounded delivery; application `VoicePreviewRunner`
  and read-only playback transition flag; Windows `VoicePreviewAudio` decoder/
  output adapter; dedicated client/application/Windows tests.
- WPF `DesktopServiceCenterHost.Preview.cs`, host/voice tab wiring, Reader guards,
  `App.ServiceCenterPreviewSmoke.cs` and lifecycle integration.
- Compiled Client.Smoke exercises live HTTP WAV preview; the verifier requires
  its explicit result and preview/voice lifecycle assertions.
- API, voices, plan and live Documentation updated. User MANIFEST excluded.

## Validation and findings

- `py -3 -m pytest -q`: 621 passed, 2 optional skips (Windows py launcher used).
- `py -3 -m ruff check .`: pass. Changed preview Python files format-check pass.
  Repository-wide format check reports existing unrelated formatting drift;
  no bulk rewrite was made.
- .NET 10.0.202 Release tests: Client 51, Application 126, Windows 91 = 268 pass.
  An initial existing Playback_complete_restarts_from_first_cursor_on_next_play
  timed out waiting for its second stream; isolated rerun and two full later
  Application runs passed. No unproven buffering/replay fix was introduced.
- New tests caught missing InvalidDataException translation and missing explicit
  remote-route classification. Both fixed; full relevant regressions pass.
- Published win-x64 self-contained to the actual root shortcut executable;
  zero build warnings/errors. No live Reader or port-7777 listener was present.
- Published exact shortcut with isolated lifecycle settings/activation scope:
  every assertion true, including selected voice, Stop, panel close, audio
  disposal before release, guarded host/Reader close and preserved dirty edit.
  Evidence: `logs/service-center-preview-20260906/shortcut.json` and PNGs;
  installed/playing preview screenshots visually inspected.
- Compiled updated Client.Smoke (the initial --skip-build run still used its old
  DLL), then reran `check_desktop_reader.py --require-dotnet --dotnet <local SDK>
  --skip-build`: explicit live_voice_preview=true; isolated HTTP, paging,
  UTF-16 edits, playback/resume, portable package and WPF lifecycle pass.
- Synthetic audio output only: no subjective voice quality/physical-device
  assertion. No production Reader/service/data/config/model/startup mutation.

## Boundaries and resume

No plan/security/licensing/backend change. The additive owner-only route is
needed because ordinary synthesis correctly refuses maintenance reservations.
Preview protects this host's Reader and global in-flight service work; it cannot
detect already-buffered audio in unrelated clients on other computers. A hung
native backend remains busy and is not silently killed. The ordinary 15-second
idle reservation still expires if its owner disappears.

Remaining T2: expand reviewed compatible packages, with exact upstream hashes,
layout and voice/component licensing; preserve installed FP32/INT8 assets and
the machine-local manifest. Overall goal stays active; U8 stays parked.
