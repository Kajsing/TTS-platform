# Reader Agent Access Plan

## Status and objective

Approved as the next project target on 2026-09-05. U8 remains parked and
incomplete; its resume conditions are preserved in `reader_upgrade_plan.md`.
M1 is the active app goal; implementation is pending. The user manually stopped
the previous U8 app goal on 2026-09-05, after which M1 registration succeeded.
The user explicitly asked to revisit U8 after this side quest. Stopping its app
goal does not mark the remaining U8 acceptance complete.

Build an optional local MCP integration through which an agent can maintain
articles in one owner-selected Reader folder. The motivating future workflow
is an agent following selected fiction sites and delivering new chapters into
the user's reading library. M1 provides the article tools and reliable chapter
delivery contract; website monitoring and cloud connectivity are later work.

## M1: Local MCP article workspace and chapter delivery

### Ownership and connection

- The Python service remains the sole owner of Reader persistence. MCP calls
  use protected service APIs and never open or synchronize the live database.
- Start with an optional local MCP stdio adapter and document how an MCP client
  starts it. It connects to the existing loopback service. Enabling agent access
  is explicit and does not change the default service bind address.
- Keep article operations independent of the MCP transport and of a particular
  agent vendor. Later remote access should reuse those operations, but requires
  its own reviewed transport and authentication integration.
- No paid service, hosted VPN control plane, or cloud account is required.
- Keep web retrieval in the external agent. Source URLs are provenance, not
  commands for the Reader service to fetch pages or execute content.

### Folder-scoped authorization

- Add `Options -> Agent access`: choose a folder, provision an access credential,
  inspect its status, revoke it, and obtain the local MCP connection instructions.
- The owner selects a normal non-Privacy-locked folder through Reader. Standard
  folder creation can be reused; the agent cannot choose a broader scope itself.
- A grant is bound to a stable folder ID and explicit allowed operations on the
  service side. Check authorization on every list, search, read, edit, and import,
  including idempotent retries and documents addressed directly by ID.
- Moving an article outside that folder removes agent access. Deleting the
  folder, revoking the grant, or enabling Privacy lock must not leave an alternate
  route to its content. No privacy-code or unlock bypass is introduced.
- Agent credentials cannot act as the existing unrestricted local token, manage
  models or the service, or use broader Reader endpoints to bypass their scope.
- Store credential hashes on the service side and protect the local credential
  using the existing Windows credential-storage conventions. Keep secrets out of
  tool results, normal logs, example config, and source control.
- Document the boundary honestly: MCP/API permissions do not sandbox an agent
  that separately has unrestricted filesystem access as the same Windows user.

### Agent tools

Expose bounded, well-described tools to:

1. Inspect the granted workspace and list or search its articles.
2. Read an article with its current revision and paginated content when needed.
3. Create an editable article in the granted folder.
4. Rename an article, append text, and apply explicit text edits.
5. Inspect imported chapter identities and deliver a chapter to a selected story
   article without adding it twice.

Do not make agents calculate internal block offsets to perform ordinary text
edits. Adapt the existing revisioned edit operations behind an explicit text
contract. Refuse ambiguous replacements and preserve Undo/Redo. Whole-article
replacement, if exposed, must be atomic and revision-checked rather than a
sequence of destructive partial operations.

Article/folder deletion, moving articles between folders, playback control, and
audio export tools are outside M1. The user retains normal Reader controls.

### Reliable chapter delivery

- Persist source URL, stable story/chapter identity, title, supplied ordering
  metadata, and import outcome in service-owned storage. History must survive
  restarts and agent-session changes.
- Use a durable uniqueness constraint for a chapter in its target story article,
  plus a retry identifier and payload fingerprint. Repeated and concurrent
  delivery of the same chapter must append text once and return the committed
  result on retry, including after a lost response.
- Append chapter content and record successful import in one transaction.
  Failed writes leave neither partial text nor a false success receipt.
- A changed payload for an already-imported chapter is an explicit conflict;
  routine polling must not overwrite the user's corrections. Existing imported
  text can be changed through the separate revision-checked edit tool.
- Preserve supplied chapter order and enough provenance to flag inconsistencies.
  Do not assume chapter numbering is always consecutive or that an order gap
  proves missing text; fiction sites may use interludes or nonnumeric labels.
- Define and test how Undo, Redo, article deletion, and user removal of imported
  text interact with chapter history. A later automatic retry must not silently
  restore content that the user deliberately removed.
- Return distinct outcomes for imported, already imported, conflict, busy,
  unauthorized, and service unavailable. A caller can retry a busy import later;
  M1 does not add a background scheduler or an unbounded retry queue.

### Coexistence with the desktop Reader

- Preserve expected row versions, content revisions, stable source mapping, and
  the content lease held by active playback. Agent writes must not stop playback
  or bypass its lease.
- Unsaved desktop changes remain intact if an agent saves another revision.
  Saving the stale edit produces the existing conflict behavior, not an overwrite.
- Reloading an externally changed article must not replace unsaved text or
  recreate the stale-cursor behavior fixed after clipboard append.
- Imported articles and chapters must be readable through the ordinary Reader
  interface without an agent-specific playback path.

## Acceptance and validation

M1 is complete only when:

- A real local MCP session initializes, lists tools, creates and reads an
  article, edits it, and appends chapters through the running service.
- Direct-ID access, search, pagination, moved articles, revoked credentials,
  locked/deleted folders, retries, and broader API routes cannot escape scope.
- Retry-after-timeout, restart, concurrent delivery, changed-payload conflicts,
  and failure during commit demonstrate the promised import semantics.
- Playback leases and stale desktop edits are covered by regression tests.
- Options can provision and revoke access; no grant exists by default.
- A documented Windows smoke uses isolated storage, demonstrates that the
  resulting article appears in Reader, and checks ordinary reading behavior.
- Relevant Python and .NET tests, Ruff, format checks, WPF build, scoped security
  review, and the end-to-end MCP smoke pass. Check new dependency licenses.
- The runtime-specific binary opened by the root Reader shortcut is published
  and verified when Reader can be updated without losing active or unsaved state.
  A running old binary is reported as pending deployment, not as completion.
- Documentation is current and the validated slice is committed and pushed.

Implement in this order: service authorization and storage, transactional chapter
operations, MCP tools, Options setup, end-to-end validation and deployment. Keep
each commit coherent and include the tests/docs for its behavior. This planning
commit is documentation-only; it does not satisfy M1 implementation acceptance.

## Later work, deliberately outside M1

- Choose fiction sources, polling cadence, login requirements, content extraction,
  and whether each story appends to one article or creates one article per chapter.
- Run an external agent on a schedule and report new chapters or retrieval errors.
- Verify ChatGPT Work/OpenClaw compatibility in the intended execution environment.
  Do not assume a cloud agent can use local stdio or join the owner's WireGuard
  network. A reachable authenticated MCP transport or an explicitly selected
  bridge needs a separate deployment/security decision.
- After M1, bring U8 back to the user and confirm the intended WireGuard
  environment before resuming its reversible elevated firewall acceptance test.

## Registered app goal scope

Implement Reader Agent Access M1: optional local MCP access to one user-selected
folder, service-enforced revocable permissions, article creation/reading/editing,
and transactional chapter delivery with durable duplicate protection and source
history. Preserve playback leases and revision conflicts. Include Options setup,
client configuration, tests, end-to-end Windows smoke, safe deployment to the
actual Reader shortcut target, documentation, commit, and push. Keep U8, website
monitoring, and cloud connectivity parked; require no paid dependency.
After M1, revisit U8 with the user before making network configuration changes.
