# Local Reader Agent API (contract 1)

This is the service contract for Reader Agent Access M1. The optional stdio
adapter and Windows Options setup are documented in `reader_agent_mcp.md`.
An already-running pre-M1 service must be restarted to load these routes.

## Security boundary

The default library has no grants. A native loopback owner client using the
ordinary Reader bearer token explicitly provisions one grant for one existing
non-Privacy-locked folder. The grant stores a stable folder ID and an explicit
operation allowlist. The credential has 256 random bits and is SHA-256 hashed
in SQLite. Only its one-time owner provisioning response contains the secret;
status, article results and diagnostics do not. Options protects the credential
with CurrentUser Windows DPAPI; the MCP client configuration contains no secret.
Do not put the provisioning response into source control.

Agent requests require that separate bearer credential, native loopback origin,
and enabled owner authentication. Browser Origin headers (including empty or
`null`) are rejected. Agent credentials do not authenticate broader Reader/TTS
or owner-administration routes. The remote gateway explicitly denies both new
route groups. No new bind address, firewall rule or remote transport is added.

Each data operation authorizes inside the same SQLite transaction as its
read/write. Moving or soft-deleting an article removes access. Deleting the
folder cascades its grants. Enabling Privacy lock permanently revokes existing
grants; removing the lock does not reactivate them. Out-of-scope and nonexistent
document IDs return the same denial. Every retry repeats authorization.

These API permissions do not sandbox an agent separately granted unrestricted
filesystem access as the same Windows user. Disabling owner token authentication
disables the new agent interface; unauthenticated legacy service configurations
are not a secure agent deployment.

## Owner setup

Prefix: `/v1/reader/agent-access`. All operations require the ordinary owner token.

| Method and path | Request | Result |
|---|---|---|
| `GET /grants` | None | `grants`, no secrets |
| `POST /grants` | `folder_id`, optional `name` (80 chars) | `grant`, one-time `credential` |
| `DELETE /grants/{grant_id}` | None | `revoked: true`; repeated revoke is safe |

Grant fields: `id`, `folder_id`, `name`, `operations`, `created_at`, `revoked_at`.
Revoking credentials does not delete articles or chapter receipts.

## Agent operations

Prefix: `/v1/reader/agent`. Use the grant credential, never the owner token.
JSON bodies reject extra fields and require actual integer revisions.

| Method and path | Request | Result |
|---|---|---|
| `GET /workspace` | None | Contract version, folder, operations and limits |
| `GET /articles` | Optional `query`, `limit` 1-100, opaque `cursor` | `items`, `next_cursor` |
| `POST /articles` | `title`, `text` | New editable article metadata |
| `GET /articles/{id}` | `offset`, `limit`, optional `expected_row_version` | `article`, `text`, `offset`, `next_offset`, `text_length` |
| `PATCH /articles/{id}` | `title`, `expected_row_version` | Article metadata |
| `POST /articles/{id}/append` | `text`, `expected_row_version` | Article metadata |
| `PATCH /articles/{id}/text` | `old_text`, `new_text`, `expected_row_version` | Article metadata |
| `GET /articles/{id}/chapters` | `offset`, `limit` 1-100 | Receipt `items`, `next_offset` |
| `POST /articles/{id}/chapters` | Chapter payload below | Durable receipt |

Article metadata deliberately projects only `id`, `title`, `folder_id`,
`row_version`, `content_revision`, `state`, `total_characters`, `updated_at`.
It does not reveal original local file paths or internal importer metadata.

Text writes accept at most 200,000 characters per call; titles at most 500.
Article reads return at most 20,000 Unicode code points. Text offsets use Unicode
code points, not UTF-16 offsets. The logical text joins paragraphs with two
newlines. Continuation pages pass the first page's `article.row_version` as
`expected_row_version`;
a changed article returns a conflict rather than mixing revisions. Search uses
the existing folder-filtered FTS/fallback implementation. Unknown cursors cannot
broaden scope. Chapter history uses append-only offset pagination.

Replacement requires exactly one match **within one paragraph**, counting
overlapping matches too. Empty replacement deletes the matching text. A missing,
cross-paragraph or ambiguous match is refused; no whole-article replacement or
multi-operation partial replacement is exposed. Append creates one normal
undoable Reader operation, with paragraph boundaries. All content edits reuse
normal Reader history and source-cursor revision handling.

Agent HTTP traffic has its own 120-request/minute budget so it cannot consume
the desktop Reader's budget. Bodies are authenticated before JSON parsing and
capped at 2 MiB, including streamed bodies. Request diagnostics use generated
request IDs and route templates, not caller paths, queries, article text or URLs.

## Chapter delivery and retry rules

Required: `expected_row_version`, `story_key`, `chapter_key`, `retry_key`,
`source_url`, `title`, `text`. Optional: `order_label`, `order_index` (JSON-safe
integer). Identity/retry/order labels are bounded to 200 characters, source URL
to 2,048. URLs must be HTTP(S) without embedded credentials. The service stores
the supplied URL as provenance and **does not fetch it**. The supplied `text` is
appended as-is through Reader's plain-text normalization; the title is metadata,
not automatically prepended to spoken content.

Uniqueness is per target article plus `(story_key, chapter_key)`, independently
of grant lifetime. A retry key is also unique per target article. The fingerprint
covers the exact payload except its retry key and expected revision. Reusing
either identity with different text or metadata is a conflict. A new retry key
for the same unchanged chapter is recorded as an alias of the original receipt.

Text append, ordinary edit history, cursor revision advancement, chapter receipt
and retry identity commit in **one transaction**. An interrupted request whose
commit succeeded can be retried with the same payload and old expected revision:
it returns `already_imported` and the original committed receipt. A genuinely
new chapter still requires the current expected row version. Concurrent delivery
of the same chapter appends once. A failure before/during commit rolls back all
effects. Clients must reuse a stable retry key on uncertain outcomes.

Receipts contain `id`, `document_id`, source/identity/title/order fields,
`order_warning`, `imported_at`, `result_row_version`, `result_content_revision`,
and `outcome` (`imported` or `already_imported`). Repeated/nonincreasing numeric
order is flagged as `order_not_after_previous_delivery`; gaps are not guessed
to indicate missing content. Supplied labels and order are never rewritten.

Receipts intentionally survive normal Undo/Redo, edit-history trimming, manual
text removal, soft deletion and restore. A retry acknowledges prior delivery;
it never restores owner-removed text. A soft-deleted article remains inaccessible
until restored into the granted folder. Permanent physical article deletion
cascades its receipts; M1 does not expose that operation. Importing deliberately
different content must use a new chapter identity or an explicit revisioned edit,
not a routine retry that overwrites the user's corrections.

## Coexistence and failures

Agent mutations use the existing playback content lease; they never cancel
playback. A held lease returns `reader_document_locked` (409). The normal desktop
save retains its optimistic revision check: unsaved local text is not written
over a newer agent revision. Desktop playback refresh checks for local edits
after waiting for the server and again before loading; edits made during that
wait are kept. Loading locks input and refuses pages if the revision changed.

Errors retain the normal `{error: {type, message, param, details}}` envelope:

- `reader_agent_unauthorized` (403): missing/revoked/wrong scope/operation.
- `reader_agent_local_only` (403): browser or non-loopback request.
- `reader_agent_conflict` (409): identity/payload mismatch or ambiguous text.
- `reader_revision_conflict` (409): expected version changed; read again.
- `reader_document_locked` (409): active playback; retry later.
- `reader_database_busy` (503): storage contention; retry later.
- `reader_agent_unavailable` / `reader_database_unavailable` (503): service or
  storage unavailable. The MCP adapter maps connection failures to a sanitized
  `service_unavailable` result without retrying writes automatically.
- Existing validation/rate-limit errors (400/429); oversized bodies return
  `reader_agent_request_too_large` (413).

There is no server-side polling scheduler or unbounded background retry queue.

## Implementation review and validation

The private transaction-bound repository facade reuses existing create, append,
replace, search and metadata methods without changing ordinary Reader method
semantics. Nested calls neither reopen the DB nor commit independently. The
facade never escapes the scoped operation. Reads also take a short SQLite writer
reservation to serialize scope changes; returned pages and request budgets are
bounded. This is a local implementation detail, not a new persistence owner.

The scoped security review covered direct-ID scope, search/pagination, every
mutation, retry authorization, privacy-lock lifetime, broad-token separation,
native-only access, remote-gateway route classification, pre-body auth/limits,
low-sensitivity logs and playback lock order. Tests cover lost-response retry,
restart, concurrent delivery, failure after append and at commit, Undo/Redo,
manual removal, soft-delete/restore and stale desktop revisions. The MCP/client
security review and real stdio/Windows acceptance are in `reader_agent_mcp.md`;
deployment status and any remaining activation step are in
`docs/codex/Documentation.md`.
