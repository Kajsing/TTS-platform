# Local Reader MCP integration (M1)

An optional **local stdio MCP adapter** lets an external agent maintain articles
in one folder chosen by the owner. Reader's service still owns the database,
authorization, revisions, playback leases and chapter receipts. The adapter
has no database, file-import, website-fetch, deletion, service-control or audio
tools. Normal Reader use does not require the adapter or an agent account.

## First-time Windows setup

From the project root, install a separate environment. Do not upgrade the
working TTS/voice environment just to install MCP:

```powershell
py -3 -m venv .venv-agent
.venv-agent\Scripts\python.exe -m pip install -e ".[agent]"
```

This pins the official Python MCP SDK to 2.1.1. Its dependencies are optional;
no paid service or cloud account is required. The resolved environment was
tested with Python 3.12. The SDK and dependency licenses are recorded in
`THIRD_PARTY_NOTICES.md`. Re-run validation after dependency upgrades.

1. Start/restart the updated local service and Reader. Keep the Local workspace
   selected. A service process started before M1 must be restarted; a new Reader
   binary cannot add routes to an already-running old Python process.
2. Create a normal folder using **Library -> Folders** if necessary. Do not use
   a Privacy-locked folder. No grant is created automatically.
3. Open **Options -> Agent access**. Choose the folder and access name, then
   **Enable for selected folder**. Confirm its limited read/create/edit scope.
4. Select the new grant. Under **Connect your agent**, choose
   `.venv-agent\Scripts\python.exe` if Reader did not locate it automatically.
   Scroll down or enlarge Options to see this section on a small display.
5. Use **Test MCP connection** to check the optional environment, protected key
   and service access. Copy the selectable configuration into your local MCP
   client's configuration. The test does not install or configure that client.

Enable and revoke take effect immediately, independently of **Save options** or
**Cancel**. Revocation removes the now-unusable local key/configuration files,
but keeps articles and chapter history. A failed local key setup attempts to
revoke the just-created grant; if the service cannot confirm this, refresh the
grant list and revoke the new grant before trying again.

The shown configuration is conventional `mcpServers` JSON, for example:

```json
{
  "mcpServers": {
    "tts-platform-reader": {
      "command": "C:\\project\\TTS-platform\\.venv-agent\\Scripts\\python.exe",
      "args": [
        "-m", "reader_agent.server", "--config",
        "C:\\Users\\YOUR_NAME\\AppData\\Local\\TTSPlatform\\Reader\\agent-connections\\GRANT_ID.json"
      ]
    }
  }
}
```

Use the actual values shown by Options, not these placeholders. A client using
another configuration format needs the same executable and separate arguments;
no shell command, owner token or environment secret is required. The client
must support launching local stdio servers as the Windows user who enabled
access. Cloud ChatGPT Work/OpenClaw deployment compatibility is **not** claimed
by this local milestone; select/review its intended transport in later work.

## Tools and results

| Tool | Purpose |
|---|---|
| `reader_workspace` | Granted folder, permissions and limits |
| `reader_list_articles` | Folder-scoped search/list; follow `next_cursor` |
| `reader_read_article` | Text and `article.row_version`; follow `next_offset` |
| `reader_create_article` | Create a normal editable article |
| `reader_rename_article` | Rename using the current expected row version |
| `reader_append_text` | Normal undoable append, revision checked |
| `reader_replace_text` | Replace a unique passage within one paragraph |
| `reader_list_chapters` | Durable delivery identities and provenance |
| `reader_deliver_chapter` | Retry-safe atomic chapter append and receipt |

Results include structured JSON and matching text content. Errors set MCP
`isError` and return `outcome`, an allowlisted `code`, and `retryable`, without
raw upstream messages. Outcomes distinguish conflict, busy, unauthorized,
invalid request and service unavailable. Reads are bounded to 20,000 Unicode
code points and writes to 200,000 characters. Subsequent text pages pass the
first page's `article.row_version` as `expected_row_version`.

For chapter delivery, reuse stable story/chapter/retry keys and the same payload
after an uncertain response. `already_imported` means a prior delivery committed,
even if the owner later removed its text or used Undo. It never restores removed
text. Changed content for the same identity conflicts. Use a separate explicit
revision-checked replacement for corrections. Include a spoken chapter heading
in `text` if desired; `title` is provenance metadata, not spoken automatically.

**Do not blindly retry create, append or edits after a timeout.** They may have
committed; inspect the current article/library first. Only chapter delivery has
durable retry identities. Busy playback is a reason to try later, not to stop
the user's reading. No scheduler or background website monitoring is installed.

See `reader_agent_api.md` for exact HTTP fields, conflict semantics, provenance,
order warnings and the authorization contract.

## Credentials and security review

- Options saves a configuration JSON and a sibling encrypted `.bin` under
  `%LOCALAPPDATA%\TTSPlatform\Reader\agent-connections`. JSON contains only a
  version, loopback service URL and grant ID. The key uses CurrentUser Windows
  DPAPI, with no plaintext fallback; C# creation/Python decryption is smoke-tested.
- Do not copy the `.bin` into source control, paste it into agent instructions,
  or use the unrestricted service token as an agent credential. Re-provision
  under the correct Windows account if the key cannot be unlocked.
- The adapter reloads the key per call, accepts only fixed agent API routes and
  canonical UUIDs, pins `localhost` to numeric loopback, refuses redirects, uses
  no proxy environment, and bounds response bodies and network timeouts. It
  exposes stdio only, not HTTP/SSE listening modes. Source URLs are never fetched.
- Service scope and revocation apply on every request and in the same database
  transaction as the operation. The remote gateway denies both agent route
  groups. Folder lock, deletion, moves and retries cannot bypass scope.
- MCP tool descriptions mark read-only, destructive edit and retry-safe tools
  appropriately. Article content and source URLs are explicitly untrusted data.
  SDK/HTTP logging is disabled in the adapter; normal service logs omit text,
  credential bodies, source URLs and raw client-controlled request paths.
- No telemetry exporter is configured. The SDK's telemetry API dependency does
  not add a Reader telemetry destination. No firewall/VPN/model configuration is
  changed by agent setup.
- This is a service permission boundary, **not a sandbox for unrestricted local
  agents**. A process separately granted all of this Windows user's filesystem
  permissions may also read their files or use their DPAPI identity. Do not give
  such an agent broad filesystem access if folder-only isolation is required.

## Validation and isolated Windows smoke

```powershell
py -3 -m pytest -q
py -3 -m ruff check .
py -3 scripts/check_reader_contracts.py
.venv-agent\Scripts\python.exe -m pip install -e ".[agent,dev]"
.venv-agent\Scripts\python.exe -m pytest -q apps/reader_agent/tests
.venv-agent\Scripts\python.exe -m pip check
& "$env:LOCALAPPDATA\TTSPlatform\dotnet\dotnet.exe" test apps/desktop_reader/TtsPlatform.Reader.sln -c Release
& "$env:LOCALAPPDATA\TTSPlatform\dotnet\dotnet.exe" format apps/desktop_reader/TtsPlatform.Reader.sln --verify-no-changes --no-restore
```

When Reader has been closed with edits saved, publish the actual shortcut target:

```powershell
& "$env:LOCALAPPDATA\TTSPlatform\dotnet\dotnet.exe" publish apps/desktop_reader/src/TtsPlatform.Reader.App/TtsPlatform.Reader.App.csproj -c Release -r win-x64 --self-contained true
.venv-agent\Scripts\python.exe scripts/check_reader_agent.py --reader-exe apps/desktop_reader/src/TtsPlatform.Reader.App/bin/Release/net10.0-windows/win-x64/TtsPlatform.Reader.App.exe --artifacts apps/desktop_reader/artifacts/reader-agent-m1
```

The script uses a temporary Reader database, generated owner token, protected
agent keys and a non-default loopback port. It starts real stdio MCP subprocesses
and shows temporary Reader/Options windows without clipboard listeners, hotkeys
or audible playback. It exercises the production Options provisioning/revocation
methods, validates cross-language DPAPI, all article operations, pagination,
concurrent duplicate delivery, changed-payload conflict, service/MCP restart,
broader-route denial and revoked access. The generated article is loaded into
the ordinary WPF library/editor and read through the normal source-mapped PCM
WebSocket path using a deterministic stub voice. It is not a real-voice quality
or audio-device test. Temporary data is removed; only nonsecret result JSON and
two synthetic-content screenshots are optionally retained.

The service/repository regression suite additionally tests playback leases,
stale desktop saves, privacy/move/delete scope, failed commit rollback, lost
responses, and Undo/Redo/manual-removal behavior. Windows unit tests verify
protected files and client configuration. This is a scoped review and regression
suite, not a claim of an independent penetration test or cloud compatibility.

## Troubleshooting

- **404 / Not Found:** restart the old service process after saving/finishing
  current work; then Refresh the Agent access tab.
- **Environment unavailable:** install `.[agent]` in the separate environment
  and choose its real Python executable. A normal service Python without the
  SDK cannot host the optional adapter.
- **Cannot unlock key:** use the original Windows user, or revoke and provision
  again. There is no plaintext recovery fallback.
- **Unauthorized:** check grant status, folder privacy and whether the article
  was moved. Removing a Privacy lock does not reactivate revoked credentials.
- **Conflict:** retain the local edit, read the current version, and reconcile
  deliberately. Reader refuses to reload over edits made during playback's
  version check and locks input while loading. A revision change during document
  pagination is refused; select the article again to get a coherent version.

U8 remains parked/incomplete. After M1, confirm the owner's intended WireGuard
environment before resuming its real firewall acceptance; do not silently expose
this adapter or the existing Reader service to the internet.
