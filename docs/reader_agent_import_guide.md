# Verified chapter imports through Reader MCP

This is an agent-side operating guide, not a new Reader feature or website
monitor. Use the existing [MCP setup](reader_agent_mcp.md) and
[API contract](reader_agent_api.md). Service, playback and network settings stay
unchanged. A local Codex skill, `reader-chapter-import`, accompanies this guide.
The skill lives in the owner's Codex skills directory; it is not a shipped
Reader component. Its human-readable workflow and offline checker are in this
repository so other agents do not need that particular Codex installation.

## What went wrong in the first field import

The 2026-09-05 run exposed orchestration errors, not a demonstrated MCP storage
failure:

| Observation | Cause / lesson |
|---|---|
| Direct HTTP returned 403 | The public page worked through ordinary browser navigation. Do not equate one retrieval failure with unavailable content or bypass access controls. |
| Two receipts held URLs instead of chapter text | Browser-session clipboard writes did not change the Windows clipboard read by the importer. Inspect the actual payload before the first write. |
| An advertised browser export failed | The in-app browser did not implement `tab.content.export`. Verify capabilities once, then use a supported transfer. |
| A chapter-body lookup returned null | Navigation had not finished replacing the DOM. Wait for the body and verify chapter identity. |
| Author notes appeared before the story | The first paragraph was not necessarily a title. Preserve notes and derive a heading from the page/menu. |
| A successful tool response was mistaken for a successful import | MCP correctly persisted the supplied payload. Count/hash/source and complete readback checks belong in the importing workflow. |

Initial folder/grant setup and recovery also took time. There is no precise
per-step timing trace, so do not attribute the whole elapsed time to the model
or synthesis performance. The failed task-created draft was soft-deleted only
after its exact content and unchanged row version were checked. The corrected
article was verified through all 23 MCP text pages: 11 ordered receipts and exact
equality with the normalized source text. No private article text, credentials,
local grant IDs or production database contents are included in this guide.

## Preferred workflow

1. Confirm the requested story and observed chapter count/order. Confirm or reuse
   explicitly approved folder access; pass only the nonsecret scoped connection
   file to the import agent. Verify `reader_workspace` and search the destination
   with pagination before creating anything.
2. Fetch every requested body before starting a new article. Use normal HTTP or
   supported browser access. Keep prose, paragraph breaks and author notes;
   remove page navigation/reviews/ads. Preserve source attribution and headings.
3. Transfer to a UTF-8 file in a task-specific ignored directory. Prefer a working
   file export/download. Browser and Windows clipboards must not be assumed to
   share state. If necessary, use a temporary loopback-only staging form, with a
   random route, exact Host/Origin checks, bounded body/file destination and
   lifetime, no Reader credentials, no CORS relaxation and verified shutdown.
4. Validate the staged package below before **any** article creation. Compare it
   to independently observed page identities, lengths and boundaries. A valid
   hash of the wrong text is still wrong. Investigate short/repeated chapters
   without imposing a universal minimum length on legitimate short chapters.
5. Use actual MCP tools, directly or through the installed optional SDK stdio
   client. Create the intro once and checkpoint the returned ID immediately.
   Deliver each chapter with stable story/chapter/retry keys, observed URL,
   spoken heading in `text`, order and expected row version. Checkpoint each
   receipt before proceeding. One chapter is atomic; the entire book is not.
6. Use `result_row_version` from a new delivery receipt for the next mutation.
   On conflict, inspect rather than overwrite. On an uncertain create, inspect
   the library/checkpoint before retrying. Only chapter delivery has durable
   retry identities. After `already_imported`, fetch the current article version
   instead of assuming an old receipt's version is current.
7. Read all receipts and **all text pages** through MCP, fixing
   `expected_row_version` to the first page's `article.row_version`. Verify
   chapter IDs, order, source URLs and count, then compare the concatenated text
   exactly with the normalized package. A matching snippet or first page is
   insufficient. Leave playback, unrelated articles and the service alone.

An inexpensive model can run this constrained workflow, but delegate only when
authorized. Prefer giving it already-validated input over asking it to invent a
browser/clipboard/MCP pipeline while also writing to the live library.

## Offline package check

The helper has no network, database, clipboard or credential access. It does not
import articles. It validates structure and accidental transport/capture errors;
it cannot prove a website was fully captured or the user granted access.

The JSON package has `story_key`, `intro` (title/author/source introduction), and
`chapters`. Each chapter has:

- `number`: contiguous delivery order starting at 1, independent of site numbering;
- `chapter_key`: stable source identity, not a new UUID on each attempt;
- `source_url`: observed HTTP(S) chapter URL without embedded credentials;
- `title`: the spoken heading;
- `text`: heading, blank line, then the complete captured chapter body;
- `sha256`: lowercase SHA-256 of the exact UTF-8 `text`, before Reader normalization.

Extra provenance fields such as observed source lengths may be retained. Supply
the expected count/story key from the source observation, not merely by copying
the package's own assertions. Repeated bodies or URLs require review; a warning
must not be bypassed by editing keys until the underlying source is understood.

```powershell
py -3 scripts/check_reader_chapter_bundle.py PATH_TO_BUNDLE --expected-count COUNT --story-key STORY_KEY
```

After a complete MCP readback has been saved locally as UTF-8 text:

```powershell
py -3 scripts/check_reader_chapter_bundle.py PATH_TO_BUNDLE --expected-count COUNT --story-key STORY_KEY --article-text PATH_TO_FULL_READBACK
```

Exit 0 reports counts/hash and whether full readback matched. Exit 1 reports a
bounded failure reason without printing chapter text. Reads through MCP are
bounded to 20,000 Unicode code points, writes to 200,000 characters. These are
contract-1 limits; check the current workspace before a later import. Do not
truncate oversized chapters; resolve an explicit delivery/splitting strategy.

Normalization matches Reader: CRLF/CR to LF, trim paragraph/outer whitespace,
join paragraphs with two newlines. Do not collapse all whitespace or rewrite
punctuation to force a comparison to pass.

## Recovery and retention

Stop on a bad committed payload. An `imported` receipt proves the operation
committed, not that its content is right. Retrying the same identity with changed
text conflicts. Undo does not remove durable receipts. Inspect the article and
get the appropriate authority before corrections; do not invent random keys,
delete existing articles or use the owner token as an agent workaround.

Keep source bundles/checkpoints/readback in a task-specific ignored staging
location for reconciliation, not normal application telemetry. Tell the owner
what is retained; do not commit or upload reading history, story text, tokens or
connection blobs. This guide does not authorize periodic monitoring or future
imports. U8/WireGuard remains separate and parked.
