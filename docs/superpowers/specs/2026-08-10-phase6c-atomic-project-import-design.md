# Phase 6C Strict Preflight and Atomic Project Import Design

This document refines and supersedes section 5 of
`docs/superpowers/specs/2026-08-09-phase6-download-backup-import-design.md` where the two differ.

## 1. Decision

Phase 6C imports one exact Phase 6B package as one new active project. It has two public stages:

1. request-scoped, write-free package preflight;
2. command-owned staging followed by one final MySQL publication transaction.

The project row and all project authorities are inserted only in the final transaction. Until that
transaction commits, the destination project does not exist. This deliberately replaces the earlier
`projects.visibility=importing` proposal: adding a visibility column would require every project
read/list/lock path to change, while a single publication transaction already gives the required
application-level atomicity.

Phase 6C adds only a specialized import command table and immutable import provenance rows. It does
not add a generic job/workflow engine, a hidden project state, merge/overwrite, old-format conversion,
cloud storage, a preflight token, a cleanup scheduler, Provider matching, or a cancellation protocol.

## 2. Alternatives considered

### 2.1 Recommended: stage first, publish once

The server validates the package and stages corpus blobs before opening the publication transaction.
One transaction then writes the complete remapped project graph, reconstructed Projection, import
provenance, and the successful command result. A rollback leaves no project row.

This is the smallest design that provides complete recovery, deterministic identity, unknown-result
recovery, and zero partial visible project.

### 2.2 Rejected: hidden project plus two database transactions

Writing `visibility=importing` first and switching it later makes intermediate state explicit, but it
also requires a broad audit and modification of all current project queries. It creates more product
surface without improving the final guarantee.

### 2.3 Rejected: current-state-only restore

Restoring only the latest heads is faster, but discards immutable revisions and audit/recovery
evidence. It does not satisfy the Phase 6 backup-recovery boundary.

## 3. Product flow and API

Project Library exposes one secondary action: `导入项目备份`.

### 3.1 Preflight

`POST /api/project-imports/preflight` accepts one multipart `file` and no other field. The upload is
streamed into an exclusive request-owned quarantine with the Phase 6B archive limit enforced while
copying. The original filename is ignored.

A successful response contains only:

- `packageHash`, `manifestHash`, and package version;
- source title and a sanitized proposed new title;
- closed entity/asset/corpus/history counts;
- whether finalized chapters exist;
- Provider-history count and the fixed warning that all eight local task bindings will be unbound.

It never returns prose, prompts, paths, record payloads, database ids, Provider output, or secret
values. Success, validation failure, request cancellation, and response completion remove the
preflight quarantine. The response is not a capability and creates no token or server registry.

### 3.2 Import

`POST /api/project-imports` accepts the same package again plus exactly:

- `commandId`: UUID;
- `idempotencyKey`: 16–64 lowercase letters, digits, `_`, or `-`;
- `expectedPackageHash`: 64 lowercase hex;
- `newTitle`: trimmed 1–200 characters.

The server streams and hashes the package, requires the expected hash, and repeats the entire
preflight. Its request fingerprint is canonical SHA-256 of package hash, manifest hash, package
version, normalized title, command id, and idempotency key.

`GET /api/project-imports/{command_id}` is the only unknown-result status boundary. It returns the
closed command status/phase, a fixed public error when known, `retryRequired` only for an expired
same-fingerprint lease, and `targetProjectId` only after success. It never returns a staging path,
lease owner, SQL error, payload, or source content.

Same idempotency key plus same fingerprint returns or resumes the same command and target project.
The same key or command id with a different fingerprint is `409`. The client never generates a new
identifier merely because the response was lost.

There is no second confirmation after the preflight summary. The single `导入为新项目` click is the
publication decision. The UI shows no Cancel action.

## 4. Exact package preflight

Only `novel-creator-project` version `1` with `sha256` is accepted. Preflight has four closed layers.

### 4.1 Raw ZIP envelope

A narrow raw-envelope verifier checks EOCD and central/local headers before extraction:

- one non-spanned archive, no prefix/trailing bytes, and no ZIP64;
- archive and entry comments empty; extra fields empty;
- UTF-8/encryption/data-descriptor flags absent;
- `ZIP_STORED` only;
- central/local name, flags, method, CRC, compressed size, and uncompressed size agree;
- fixed Phase 6B timestamp and Unix regular-file `0600` metadata;
- exact ASCII forward-slash paths with no absolute, drive, UNC, dot segment, backslash, NUL,
  duplicate, case-fold collision, or overlength path;
- no symlink, reparse, device, directory, encrypted member, or undeclared member.

The verifier enforces archive, entry-count, total-uncompressed, per-structured-entry, per-blob, path,
and JSON-depth limits before allocation or extraction. CRC, actual streamed length, and SHA-256 are
checked while reading.

### 4.2 Manifest and canonical bytes

The importer requires the exact v1 top-level entry set and content-addressed blob prefix.
`manifest.sha256`, canonical `manifest.json`, entry declarations, actual sizes, payload hashes, counts,
and lexicographic order must agree. Re-encoding every structured JSON/JSONL item must reproduce its
exact source bytes including one LF. Duplicate JSON keys, non-finite values, unknown fields, and
noncanonical representations are rejected.

### 4.3 Record graph

The record registry is closed. Every `(entityType, logicalId)` is unique and every logical reference
resolves to the permitted target type. Revisions, heads, current authorities, content hashes, Canon
sequence, finalized-chapter pins, frozen asset references, corpus revision/chapter/fragment links,
operation terminal states, Provider provenance, and Projection validation counts/hashes are checked.

The importer maintains one static classification for every v1 record type:

- `formal`: restored into product authority tables;
- `reconstructed`: model bindings, content-addressed storage, and Projection;
- `provenance`: inert history that cannot safely satisfy current executable foreign keys;
- `invalid`: a record/state that package v1 must never contain.

An unclassified record type fails the schema contract test and runtime preflight.

### 4.4 Sensitive data

The same recursive sensitive-key classes as backup are rejected in structured records. Import
additionally rejects unsafe configuration aliases such as `includeApiKeys`, authorization headers,
DSNs, passwords, tokens, absolute values in fields declared as paths, Provider profile ids,
lease/owner tokens, and executable idempotency keys. Corpus bytes are verified as the declared frozen
content and are not searched heuristically for words or path-like fiction. Errors expose only a fixed
field class and never the value, record, entry path, or original text.

## 5. Deterministic identity and hash normalization

Every database-backed package identity maps to:

```text
UUIDv5(UUID(commandId), entityType + "/" + logicalId)
```

The target project id is the mapping for `project:1`. The canonical, sorted mapping has an
`idMapHash`; duplicate inputs, duplicate outputs, unknown types, or raw UUID-like values outside the
typed rewrite registry fail closed.

All strict JSON authorities are decoded with their existing production models and rewritten through
typed visitors. Prose bytes, Candidate content, frozen corpus bytes, and their content hashes remain
unchanged. JSON containing remapped ids is canonicalized and rehashed. Relational reference hashes
are then updated in dependency order; the importer never copies a stale package hash into a rewritten
authority.

Imported binding revisions retain their revision order but are reconstructed with all eight
`TASK_KEYS` in canonical order and `resolutionStatus=unbound`; provider id/name/model are null.
Their hashes are recomputed. CreationContract binding references and dependent contract-head/planning
reference hashes are rewritten to those unbound revisions. The imported current binding head is
therefore Not Ready until the author explicitly configures local Providers.

## 6. Formal authority versus inert provenance

### 6.1 Formal restore

The formal restore includes the new project; seed revisions/selection; story-engine authorities;
Contract, Style, Bible, Planning and Outline drafts/revisions/heads/confirmations; ChapterSessions;
current WorkingDraft; Candidates; provider-free quality findings; finalization change sets/revisions/
records; final chapters; Canon; and reference uses.

Internal idempotency keys that are required by product tables but intentionally absent from the
package are deterministically derived from command id plus package logical identity. They are never
reused as external command keys.

### 6.2 Reconstructed shared frozen data

Frozen style/experience revisions receive command-scoped deterministic stable keys and are inserted
without changing any global asset head. They are not automatically made current or recommended.

Frozen corpus source/revision/chapter/fragment metadata and exact content-addressed bytes are
restored without creating a corpus head or import run. A pre-existing blob is reused only after exact
length and SHA-256 verification.

Canon Projection rows are never restored from the package. They are rebuilt from imported Canon in
the publication transaction and compared with `validation/projections.json` before commit.

### 6.3 Provenance normalization

Provider history, market history, terminal operation evidence, operation events, provider-bound
attempts/reports, and operation-dependent recovery revisions that cannot satisfy current secret-free
foreign keys are stored as immutable import provenance records. No fake, disabled, or name-matched
Provider profile is created.

`project_import_provenance` stores one canonical record per source item, not one unbounded aggregate
JSON value. Each row has category, source entity type/logical id, canonical payload, content hash, and
stable order. A later backup emits these rows as closed `import-provenance` graph records so their
content round-trips unchanged without becoming executable history.

## 7. Specialized persistence

The create-only schema advances once and adds exactly two tables.

### 7.1 `project_package_import_commands`

One row owns command/idempotency/fingerprint, source package and manifest hashes/version, deterministic
target project id, normalized title, closed status/phase, bounded lease, canonical staging manifest,
fixed public error, and timestamps. Status is `reserved|running|succeeded|failed`; phase is
`uploaded|preflighted|staged|publishing|succeeded|failed`.

The staging manifest contains only relative owned object names, hashes, lengths, and whether the
target blob was newly created. It contains no absolute path or source body.

### 7.2 `project_import_provenance`

Rows are owned by the imported project and command and keyed by stable record order. They store a
closed provenance category, source type/logical id, canonical payload JSON, content hash, and creation
time. The table has no Provider, market-source, operation, lease, or executable-command foreign key.

No `projects.visibility`, compatibility table, preflight table, backup ledger, generic task table, or
event bus is added.

## 8. Staging, publication, and crash recovery

### 8.1 Owned files

Preflight uses a random exclusive private quarantine outside the managed corpus root and always
removes it with response ownership.

Import uses a command-owned private quarantine plus
`.project-import-staging/<commandId>` under the managed corpus root. The same POSIX/Windows ACL
postconditions as Phase 6B apply. The command staging manifest is written before promotion.

### 8.2 Blob promotion

Validated blob files are promoted to their content-addressed destinations before database
publication. `os.replace` is used only when the destination does not exist. Existing destinations
must match length and SHA-256. Promotion never overwrites mismatched bytes.

A crash may leave an unreferenced content-addressed blob. Recovery removes only a blob marked
`createdByCommand=true` when no `corpus_blobs` row references its hash. It never deletes a pre-existing
or shared blob.

### 8.3 One publication transaction

The final transaction:

1. locks and revalidates the command/fingerprint/lease;
2. proves the deterministic target project does not exist;
3. inserts shared frozen rows, the complete project authority graph, reconstructed unbound bindings,
   and provenance in explicit foreign-key order;
4. rebuilds Projection from imported Canon and verifies package projection counts/hashes;
5. marks the command `succeeded` with the target project id.

All five steps commit together. Any exception rolls them all back. A separate fixed-outcome update
may mark the already-reserved command failed after command-owned file cleanup, but it cannot publish a
project.

### 8.4 Unknown result

If the response is lost, the UI queries the command. `succeeded` returns the one project; `failed`
returns the fixed outcome; an unexpired `running` command remains blocking; an expired matching lease
returns `retryRequired`, after which the client reposts the same retained File and identifiers.

Startup performs only bounded Phase 6C recovery: inspect at most 32 expired command-owned roots,
reconcile them with command rows, and remove only terminal or provably unreferenced owned files. It is
not a scheduler and never resumes an import without the exact retained/reuploaded package.

## 9. UI behavior

The Project Library import panel has three visible states:

1. choose one `.zip` file and run `检查备份`;
2. review source title, counts, proposed editable new title, and the fixed Provider Not Ready warning;
3. click `导入为新项目` once, then show fixed upload/check/stage/publish/recover phases in the global
   blocking operation overlay.

Preflight failure keeps the file selector available and shows one fixed retryable error. Import
prevents double submission and navigation, installs the existing `beforeunload` fence, retains the
File and command identifiers for unknown-result recovery, and exposes no Cancel. Success navigates to
the new project overview, where normal lifecycle authority shows Provider Not Ready.

The frontend never parses package JSON, derives ids, reads file body for UI display, or trusts the
filename. It sends multipart bytes only through a dedicated API client path with listener/timer
cleanup and fixed error mapping.

## 10. Error boundary

Public outcomes are closed:

- `400/413/422`: upload, package, canonical, graph, sensitive-field, or size rejection;
- `404`: command unknown;
- `409`: idempotency/fingerprint conflict, active same command, target collision, or nonmatching
  existing blob;
- `500`: fixed integrity/publication failure;
- network/timeout: unknown result, immediately resolved through command status.

`CancelledError` remains cancellation. Logs and artifacts contain only phase, fixed code, counts,
hash class, and owned-resource ledger—never package payload, prose, secret values, DSNs, Provider
output, SQL, or absolute paths.

## 11. Verification and acceptance

Implementation uses focused TDD:

- raw ZIP and canonical rejection matrix;
- closed record registry, logical-reference graph, identity/hash rewrite, and restore/provenance
  classification;
- schema and Provider-bound normalization contract;
- disposable-MySQL success, every injected transaction boundary failure, idempotent replay,
  fingerprint conflict, Projection mismatch, and zero visible project after failure;
- blob stage/promote/reuse/crash cleanup matrix on POSIX and Windows permission boundaries;
- API/frontend preflight, one-click import, unknown-result recovery, operation fencing, and safe errors;
- one visible-browser scenario that chooses a real Phase 6B ZIP through the file input and proves one
  new project, matching current/finalized authorities, Provider Not Ready, and zero residue.

No test calls a Provider, reads a product database, uses a live website, or bypasses UI with
`page.request`, `page.route`, `fetch`, `axios`, or `page.evaluate`.

Phase 6 closes only after one fresh full Phase 6 Python/Node/MySQL/build/browser/resource matrix.
Acceptance states only that finalized download, deterministic backup, and strict atomic import work
with disposable local data. Real-provider quality, product-database readiness, live-site readiness,
and novel content quality remain unaccepted.
