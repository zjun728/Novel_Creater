# Phase 6 Lean Download, Backup, and Import Design

## 1. Decision

Phase 6 is three sequential vertical slices:

1. **6A Novel download** — finalized prose only, synchronous and read-only.
2. **6B Project backup** — one deterministic, secret-free project package.
3. **6C Project import** — strict preflight followed by recoverable atomic publication as a new
   project.

This decomposition is the recommended balance between product value and safety. A single combined
export/import framework would recreate the over-designed delivery pattern that the lean strategy
removed. Download-only would be fast but would not deliver project recovery.

Phase 6 does not add a generic workflow engine, generic job runner, cloud sync, scheduled or
incremental backup, multi-project/database dump, password-protected packages, PDF/EPUB/DOCX,
merge/overwrite import, old backup compatibility, real Provider use, or product-database access.

## 2. Shared product rules

- Download and backup live in the project center as secondary actions. They never replace the one
  current creative next action.
- Project import lives in the project-library header and always creates a new active project.
- All three actions reuse the current global operation overlay. The overlay names the operation and
  current phase, blocks duplicate submission and unsafe navigation, and never displays body text,
  paths, Provider output, secrets, or DSNs.
- An action shows Cancel only when the backend has a proven cancellation protocol. Phase 6A and 6B
  do not show Cancel. Phase 6C cannot be cancelled after atomic publication begins.
- Archived projects remain readable and can be downloaded or backed up. Import never creates an
  archived project.
- No Phase 6 path calls a Provider. Automatic tests use only disposable MySQL and owned temporary
  roots.

The existing operation overlay gains only two narrow capabilities: update the phase/detail for one
owned operation, and install a `beforeunload` fence while a blocking operation is active. It does not
become a persistent job store.

## 3. Phase 6A — finalized novel download

### 3.1 Public API

Two project-scoped GET routes form the complete boundary:

- `GET /api/projects/{project_id}/novel-download/options`
- `GET /api/projects/{project_id}/novel-download`

The file route accepts the closed query:

- `scope=book|volume|chapter`;
- `format=txt|markdown`;
- `volumeId` only for `scope=volume`;
- positive `chapterNumber` only for `scope=chapter`.

Unknown, missing, extra, or contradictory selectors fail before any body is read. Options return
only availability, stable volume ids/titles, chapter numbers/titles, formats, and a fixed unavailable
reason. Options never return prose, hashes, internal revision ids, or database ids that the author
does not need.

### 3.2 Authority and ordering

Download reads only `final_chapters`. It never falls back to WorkingDraft, Candidate, operation
partial output, or `[暂无内容]`.

Each final chapter already pins its ChapterSession, ChapterOutline revision, and Planning revision.
The repository uses that pinned historical chain to recover the chapter's volume:

`final_chapters -> chapter_sessions -> chapter_outline_revisions -> planning_revisions`

It must not consult the current Planning head. The strict domain decoders verify chapter number,
story-block/volume reference, revision/hash pins, and the final prose SHA-256. Any missing or corrupt
link fails the entire download; it cannot silently omit or move a chapter.

Book output is ordered by global chapter number. Volume output includes only chapters whose pinned
Outline points to that volume. Chapter output includes exactly one final chapter.

### 3.3 File bytes

Both formats are UTF-8 without BOM, use LF, and end with one newline. Body text is not rewritten;
only line endings are normalized.

TXT structure:

```text
书名

===== 第 1 卷 · 卷名 =====

----- 第 1 章 · 章名 -----

正文
```

Markdown uses `#` for the book, `##` for a volume, and `###` for a chapter. Heading text is flattened
and escaped; prose is kept verbatim apart from line endings. The server cleans the attachment name
and sends both an ASCII fallback and RFC 5987 `filename*`.

Responses use the exact text media type, `Content-Disposition: attachment`,
`Cache-Control: private, no-store`, and `X-Content-Type-Options: nosniff`.

### 3.4 UI and errors

A shared compact download panel appears on active Project Overview and archived-project read-only
status. It defaults to whole-book TXT, supports book/volume/chapter and TXT/Markdown, disables the
button with a reason when no final chapter exists, does not confirm, and prevents double clicks.

Public outcomes are closed:

- `404` project or requested finalized scope missing;
- `409` project exists but contains no finalized chapter;
- `422` invalid query;
- fixed `500` integrity failure without prose, SQL, or internal ids.

Phase 6A adds no table, temp file, task, or cancellation protocol.

## 4. Phase 6B — deterministic project backup

### 4.1 Public API and lifecycle

`POST /api/projects/{project_id}/backup` accepts only the expected project lifecycle revision and
returns `application/zip` plus `X-Package-SHA256`.

The active-project UI stops debounce and flushes the current WorkingDraft before the request. Flush
failure sends no backup request. Archived projects need no flush. The backend rejects backup while
the project has an active AI lease/slot or finalization in preparing, awaiting-author, or committing
state.

The backend opens one `REPEATABLE READ WITH CONSISTENT SNAPSHOT`, verifies project ownership and
lifecycle, reads an explicit allowlisted DTO graph into a bounded spool, and closes the transaction.
It then verifies frozen corpus bytes and constructs the ZIP. No file I/O or Provider call occurs
inside a write transaction.

Backup is a retryable read. It has no command ledger and no generic background job.

### 4.2 Package v1

The package is a deterministic ZIP with ASCII entry paths, lexicographic entry order, fixed
timestamps/permissions, no comments/extra fields, and `ZIP_STORED`. The same authoritative snapshot
must produce identical entry bytes and hashes.

The exact top-level entries are:

- `manifest.json` — package/schema version, hash algorithm, package-local project id, ordered entry
  path/byteLength/SHA-256 list, and entity counts;
- `manifest.sha256` — SHA-256 of canonical `manifest.json`;
- `project/graph.jsonl` — allowlisted project-owned authorities, immutable revisions, heads, drafts,
  Candidates, finalization, final chapters, Canon, and reference uses using typed package-local
  logical ids;
- `history/operations.jsonl` — safe inert operation evidence only;
- `history/providers.jsonl` — public Provider/model name snapshots only;
- `assets/frozen.jsonl` — only style and experience-card revisions frozen by this project;
- `corpus/revisions.jsonl` and `corpus/blobs/sha256/<hash>` — only exact corpus revisions frozen by
  the project, including their complete raw content-addressed bytes;
- `validation/projections.json` — expected Canon-derived Projection hashes/counts, never projection
  rows as an authority.

Every JSON or JSONL record is strict canonical UTF-8 JSON with duplicate and unknown fields rejected.
Package ids are logical and immutable; raw database ids are not public package identity.

### 4.3 Included and excluded data

The project graph includes the complete project-owned creative chain: Seed selection and revisions;
model-binding history; story engine; Contract/Bible/Planning/Outline drafts, revisions and
confirmations; ChapterSessions; WorkingDraft and immutable recovery history; Candidates; quality and
finalization records; final chapters; Canon; safe reference evidence; and inert historical command
fingerprints needed to audit results.

Provider profiles, API keys, Base URLs, application settings, global asset heads, unfrozen global
assets, market scheduler state, source policies, corpus heads/import runs, active leases, owner
tokens, prompts, raw Provider responses, streamed deltas, and executable idempotency keys are not
included.

Project-local market/seed-generation evidence that depends on a shared market snapshot is exported
as an inert normalized history record with the minimum public snapshot metadata and hashes. It is not
restored as a live global market source, refresh job, or executable generation attempt.

Provider history contains only a package-local history id, public name/model snapshot, task, and
inert record reference. It cannot configure or select a Provider after import.

Interrupted attempts may be exported only as inert evidence. A currently active attempt blocks the
backup and cannot be relabeled terminal.

### 4.4 Security and resource ownership

All DTOs use field allowlists plus recursive sensitive-key rejection. The exporter loads only the
project-referenced Provider secret/Base URL values into private memory to scan exact-value leakage;
it never writes or reports those values. Raw corpus bytes use exact-secret scanning, not generic word
matching that would reject ordinary fiction.

Package v1 has fixed implementation limits: archive bytes `2 GiB`, entries `20,000`, total entry
bytes `4 GiB`, one structured entry `128 MiB`, one corpus blob `1 GiB`, entry path `240` ASCII bytes,
and JSON nesting depth `64`. Limit failures are fixed `413`/`422` errors.

The server creates one exclusive, least-privilege, random Phase6B temp root outside the managed
corpus store. Success, error, client disconnect, and response close all attempt cleanup. Startup may
clean only provably owned Phase6B roots under an age/count bound; it does not add a scheduler.

## 5. Phase 6C — preflight and atomic import

### 5.1 Public flow

Project Library exposes one `导入项目备份` action.

1. `POST /api/project-imports/preflight` uploads the package into an owned quarantine and performs
   all validation without writing product entities.
2. A successful response shows source title, proposed new title, entity/asset counts, package hash,
   and Provider history that will require explicit reconfiguration.
3. `POST /api/project-imports` accepts one author click, the same exact package, `commandId`,
   idempotency key, expected package hash, and new title. It repeats the full preflight server-side.
4. `GET /api/project-imports/{command_id}` is the only unknown-result recovery path.

There is no second confirmation. Import never accepts a destination project id and never overwrites,
merges, or silently reuses a project.

Preflight quarantine is request-scoped and is removed when the response completes or fails. The
browser retains the selected `File`; import uploads the same exact bytes again and the server repeats
preflight. No preflight token, temp registry, or cleanup scheduler is introduced.

### 5.2 Closed preflight

Only exact package v1 is accepted. Preflight rejects before publication:

- archive/package/manifest/version/hash/count mismatch;
- absolute, drive, UNC, `.`, `..`, backslash-confused, NUL, overlong, duplicate, Unicode-normalized,
  or case-fold-colliding paths;
- symlink, reparse, device, encrypted, nested-archive, unknown compression, unknown entry, or
  undeclared entry;
- declared/actual size mismatch or any package limit violation;
- duplicate JSON keys, unknown JSON fields, excessive depth, non-finite values, broken logical ids,
  dangling references, invalid revisions/heads, or authority/hash disagreement;
- recursively normalized sensitive keys including API key, Base URL, Authorization, token,
  password, DSN, and `includeApiKeys`.

Sensitive-field errors name only the rejected field class, never its value or original path.
Current or historical unsafe backup formats are rejected; Phase 6 does not strip secrets or attempt
compatibility conversion.

### 5.3 Identity and imported authority

Every package reference is `(entityType, logicalId)`. The backend deterministically maps it to
`UUIDv5(commandId, entityType/logicalId)`. Retrying the same command produces the same mapping.

Content-byte hashes for prose, Candidate content, corpus blobs, and Canon JSON remain stable. Values
containing remapped ids are rewritten and rehashed. Import records `sourcePackageHash`,
`sourceManifestHash`, and `idMapHash`.

Imported operational history is evidence, not an executable command graph. It cannot restore leases,
active slots, owner tokens, old operation ids, or old idempotency keys. Provider and model snapshots
are retained only in import provenance. The importer never name-matches, creates, enables, or binds a
local Provider.

The imported project receives a new current binding revision with all eight task keys `unbound`.
Provider readiness remains false until the author explicitly selects a local Provider later.

Current safe project authorities are restored into their formal tables. Historical attempt/report
rows that cannot satisfy the secret-free Provider boundary are normalized into immutable import
provenance instead of creating fake Provider profiles. Quality findings may be restored with no live
Provider reference; their public Provider/model history remains in provenance. A later backup must
round-trip this provenance unchanged.

The same rule applies to history that requires a shared market source or snapshot: retain its public
inert evidence in provenance, do not recreate or bind a global live object.

### 5.4 Minimal specialized persistence

Phase 6C advances the create-only Schema once and adds only:

- `projects.visibility` with closed values `visible|importing`; every normal project read/list/lock
  excludes `importing`;
- `project_package_import_commands` — command/idempotency/fingerprint, package/manifest hashes and
  version, target project id, closed status/phase, lease, owned staging manifest, fixed result/error,
  and timestamps;
- `project_import_provenance` — project, command, source hashes, id-map hash, Provider public history,
  inert operation/history manifest, and canonical content hash.

No generic job, workflow, event bus, compatibility table, or backup ledger is introduced. Before 6C
implementation, a focused Schema contract enumerates every Provider-bound historical field and the
exact normalization rule; implementation cannot use disabled or hidden `provider_profiles` as a
shortcut.

### 5.5 Atomic publication and recovery

The import command owns one quarantine/staging root. Validated corpus bytes are written under
`.project-import-staging/<commandId>` using existing content-addressed path rules.

One MySQL transaction writes the complete remapped project graph with `visibility=importing`, the
command, and provenance. No regular API can observe this project. The service rebuilds Projection
from imported Canon and compares the package validation hashes.

Validated new blobs are then atomically promoted with `os.replace`; pre-existing blobs must match
both length and SHA-256. A final transaction rechecks the command and graph, changes the project to
`visible`, and commits `succeeded + targetProjectId` together.

This provides atomic application visibility, not fictional cross-filesystem/MySQL 2PC. A crash after
blob promotion but before MySQL success may leave an unreferenced content-addressed blob. The command
records exactly which blobs it created; resume/cleanup removes only command-owned blobs proven to
have no `corpus_blobs` reference and never deletes pre-existing or shared bytes.

An expired import lease is resumed only under the same command/fingerprint and deterministic id map.
Same idempotency key plus same fingerprint returns the same project; same key plus different
fingerprint is `409`. If the client loses the response, it queries the command. A missing/uncommitted
result can be retried with the same identifiers; generating a fresh key is not a recovery path.

After publication begins, the UI has no Cancel action. Failure before visibility deletes the hidden
project graph, quarantine, and staging files while retaining only the fixed command outcome needed
for safe retry/audit.

## 6. Delivery and verification strategy

Each slice uses TDD and affected evidence only:

- 6A: renderer/domain, repository/API, narrow MySQL, frontend controller/panel, build, one browser
  scenario;
- 6B: package domain/ZIP/security, snapshot repository, temp lifecycle, API/frontend, narrow MySQL,
  one browser scenario;
- 6C: archive preflight rejection matrix, Schema/ownership, id remap, import/recovery fault matrix,
  frontend preflight/unknown result, narrow MySQL, one browser scenario.

The Phase 6 full Python/Node/MySQL/build/browser/resource matrix runs once at Phase close. Slice
reviews do not widen scope for noncritical theoretical findings.

Formal browser tests use visible UI, a disposable database, owned temp roots, and downloaded files.
They do not use page request/route/evaluate to bypass product behavior. They assert no real Provider
calls, no product-database reads/writes, no live website access, and no secrets, DSNs, Provider raw
text, or prose bodies in logs/artifacts.

## 7. Acceptance boundary

Phase 6 is accepted only when:

- book/volume/chapter TXT and Markdown contain exactly finalized prose in pinned historical order;
- an active or archived project produces one deterministic, secret-free, complete v1 package after
  a successful flush and consistent snapshot;
- that package preflights and imports as one new visible project with remapped ids, rebuilt matching
  Projection, complete current creative authorities, frozen asset bytes, inert historical evidence,
  and all current Provider bindings unbound;
- every injected file/database/network failure exposes no partial visible project and leaves only
  recoverable command-owned staging;
- same-command unknown-result recovery returns at most one imported project;
- full fresh gates and DB/process/port/temp/cache/artifact residue are zero.

Phase 6 does not grant real-provider quality, product-database readiness, live-site readiness, or
novel content-quality acceptance. After Phase 6 close, work proceeds directly to Phase 7: controlled
product-database readiness, explicitly authorized real-Provider testing, complete real product-flow
experience, and author review of the first 30 chapters.
