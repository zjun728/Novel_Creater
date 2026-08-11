# Phase 6C Atomic Project Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strictly preflight one Phase 6B package and atomically publish it as one new project with deterministic identities, unbound Providers, rebuilt Projection, recoverable idempotency, and zero partial visibility.

**Architecture:** A closed archive reader validates raw ZIP structure and canonical package bytes; a pure import planner classifies every package record, deterministically remaps ids, rewrites typed authority, and emits an immutable publication plan. Two specialized tables retain command recovery and inert provenance. Corpus bytes are staged before one final MySQL transaction writes the complete project, Projection, provenance, and successful command result together.

**Tech Stack:** Python 3.12, FastAPI multipart streaming, Pydantic v2, `zipfile` plus raw ZIP header validation, UUIDv5, SHA-256 canonical JSON, aiomysql/InnoDB, Vue 3, Pinia, Node test runner, pytest, Playwright, disposable MySQL.

---

## Scope guard

- Implement only `docs/superpowers/specs/2026-08-10-phase6c-atomic-project-import-design.md`.
- Add exactly `project_package_import_commands` and `project_import_provenance`; do not add `projects.visibility`, a generic job/workflow, preflight registry, compatibility table, backup ledger, event bus, scheduler, or Provider placeholder.
- Import always creates one new active project. It never accepts a destination project id, merge, overwrite, archive, Provider selection, or old package conversion.
- Automated tests use only `novel_creator_test_%`, owned quarantine/staging roots, local files, and deny-proxy boundaries. They never call a real Provider, product DB, or live website.
- Keep tests lean per task. Run the branch-wide Python/Node/MySQL/build/browser Phase 6 matrix once only in Task 10.

## Locked public types

```python
@dataclass(frozen=True, slots=True)
class ProjectImportSummary:
    package_hash: str
    manifest_hash: str
    package_version: int
    source_title: str
    proposed_title: str
    counts: Mapping[str, int]
    has_finalized_chapters: bool
    provider_history_count: int

@dataclass(frozen=True, slots=True)
class ProjectImportCommandView:
    command_id: str
    status: Literal["reserved", "running", "succeeded", "failed"]
    phase: Literal["uploaded", "preflighted", "staged", "publishing", "succeeded", "failed"]
    retry_required: bool
    target_project_id: str | None
    public_error_code: str | None
```

The exact endpoints are:

```text
POST /api/project-imports/preflight
POST /api/project-imports
GET  /api/project-imports/{command_id}
```

## Task 1: Raw ZIP envelope and owned upload quarantine

**Status:** Complete at `d5098b0`; specification review `0/0/0`, quality review `0/0/2` approved.

**Files:**

- Create: `backend/security/project_import_archives.py`
- Create: `backend/security/private_files.py`
- Create: `backend/domain/project_imports.py`
- Modify: `backend/services/project_packages.py`
- Create: `backend/tests/unit/test_project_import_archive_security.py`
- Create: `backend/tests/unit/test_project_import_domain.py`
- Modify: `backend/tests/unit/test_project_package_temp_cleanup.py`

- [x] **Step 1: Write the raw-envelope RED matrix.**

Construct byte-level fixtures for one valid Phase 6B archive and mutate EOCD/local/central fields.
Require fixed `ProjectImportInvalid` for prefix/trailing bytes, ZIP64, multi-disk, flag bits, encryption,
data descriptor, compression, comments, extra fields, timestamp, mode/type, central/local mismatch,
CRC/size mismatch, non-ASCII/backslash/dot/absolute/drive/duplicate/case-fold path, undeclared entry,
and every v1 limit. Assert exception cause is `None` and no rejected path/value appears in the message.

- [x] **Step 2: Run the RED.**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_project_import_archive_security.py backend/tests/unit/test_project_import_domain.py
```

Expected: collection fails because `backend.security.project_import_archives` and
`backend.domain.project_imports` do not exist.

- [x] **Step 3: Implement the closed archive types and verifier.**

Implement:

The locked interface consists of `ProjectImportInvalid`, `ProjectImportTooLarge`,
`ProjectImportSensitiveData`, immutable `VerifiedArchiveEntry(path, byte_length, crc32, sha256,
offset)`, and `verify_raw_zip_envelope(path: Path) -> tuple[VerifiedArchiveEntry, ...]`.

Parse EOCD, central headers, and local headers with `struct`; reject ZIP64 and all non-v1 metadata
before constructing `ZipFile`. Stream each member through one bounded reader that verifies CRC,
length, SHA-256, and declared limits.

- [x] **Step 4: Implement request-owned quarantine.**

First move the existing Phase 6B private-file permission implementation, without behavior changes,
from `backend/services/project_packages.py` to `backend/security/private_files.py`; keep the existing
backup permission regression green. Add `OwnedImportQuarantine` to `backend/domain/project_imports.py`.
It must create an exclusive random directory/file, use the shared helper to enforce POSIX `0700/0600`
or the Windows exact-SID DACL, stream at most `MAX_ARCHIVE_BYTES`, and expose idempotent retryable
cleanup. Do not store the upload filename.

- [x] **Step 5: Run GREEN and static checks.**

Run the Task 1 tests, `py_compile`, and `git diff --check`. Expected: all pass and every owned root is
cleaned after success, invalid input, cancellation, and injected cleanup retry.

- [x] **Step 6: Commit.**

```powershell
git add backend/security/project_import_archives.py backend/security/private_files.py backend/domain/project_imports.py backend/services/project_packages.py backend/tests/unit/test_project_import_archive_security.py backend/tests/unit/test_project_import_domain.py backend/tests/unit/test_project_package_temp_cleanup.py
git commit -m "feat: validate phase6 project import archives"
```

## Task 2: Canonical package reader, graph closure, and preflight summary

**Files:**

- Create: `backend/domain/project_import_plans.py`
- Create: `backend/tests/unit/test_project_import_package_reader.py`
- Create: `backend/tests/unit/test_project_import_graph.py`
- Modify: `backend/domain/project_imports.py`

- [x] **Step 1: Write canonical package RED tests.**

Use a real `build_archive()` package and mutations. Require exact manifest/version/hash/count/entry
agreement, canonical JSON re-encoding, one LF, duplicate-key rejection, closed record fields,
deterministic order, unique `(entityType, logicalId)`, valid typed logical references, revision/head/
Canon/finalized pins, corpus graph closure, and Projection validation closure.

- [x] **Step 2: Freeze complete record classification in RED.**

Define the expected classification test:

```python
groups = (
    set(FORMAL_ENTITY_TYPES), set(RECONSTRUCTED_ENTITY_TYPES),
    set(PROVENANCE_ENTITY_TYPES), set(INVALID_ENTITY_TYPES),
)
assert set().union(*groups) == all_v1_record_types()
for index, group in enumerate(groups):
    assert all(group.isdisjoint(other) for other in groups[index + 1:])
```

The formal set covers safe creative authority. Reconstructed covers bindings, assets/corpus storage,
and Projection. Provenance covers Provider/market/operation evidence and operation-dependent recovery.
Active/non-v1 states are invalid. Zero type may remain unclassified.

- [x] **Step 3: Implement strict streaming readers.**

Implement immutable `VerifiedProjectPackage(archive_path, package_hash, manifest_hash, manifest,
graph_index, entry_index, summary)` and
`read_verified_project_package(path: Path) -> VerifiedProjectPackage`.

Use duplicate-key rejecting JSON loads, existing package dataclasses/allowlists, and exact canonical
byte comparison. Parse JSONL line-by-line; never `extractall` and never trust a member path.

- [x] **Step 4: Implement graph validation and safe summary.**

Build type-specific reference rules and validate every record before returning the source/proposed
title and counts. `proposedTitle` is source title plus a fixed `（导入）` suffix, trimmed to 200 chars.
No content payload is returned by the summary.

- [x] **Step 5: Run GREEN, fuzzed mutations, and commit.**

Acceptance evidence (2026-08-11): Task 2 focused tests passed 28/28; the complete Task 1–2
import unit slice passed 94/94. Fresh `py_compile` and `git diff --check` passed, owned test
temporary roots were removed, and no database, Provider, network, API, UI, or product data was used.

Run Task 1–2 focused tests, `py_compile`, and `git diff --check`, then commit:

```powershell
git add backend/domain/project_imports.py backend/domain/project_import_plans.py backend/tests/unit/test_project_import_package_reader.py backend/tests/unit/test_project_import_graph.py
git commit -m "feat: preflight deterministic project packages"
```

## Task 3: Specialized schema and command/provenance repository

**Files:**

- Create: `backend/schema/80_project_imports.sql`
- Modify: `backend/schema_version.py`
- Create: `backend/repositories/project_imports.py`
- Create: `backend/tests/unit/test_project_import_schema.py`
- Create: `backend/tests/unit/test_project_import_repository.py`
- Create: `backend/tests/integration/test_project_import_commands_mysql.py`

- [x] **Step 1: Write the schema RED.**

Assert the schema adds exactly the two tables from the design, no `projects.visibility`, and advances
`EXPECTED_SCHEMA_VERSION` from `writer-core-v1.12.0` to `writer-core-v1.13.0`. Assert closed status/
phase/category checks, unique command/idempotency/target identities, project/command provenance
ownership, JSON validity, positive record order, and no Provider/market/operation foreign key.

- [x] **Step 2: Write command idempotency RED tests.**

Cover reserve same key+fingerprint, key conflict, command conflict, lease acquire/renew/expiry, fixed
failure, success result, and safe public view. Repository SQL must be explicit and parameterized.

- [x] **Step 3: Implement schema and repository.**

Expose `ProjectImportRepository.reserve_command`, `acquire_lease`, `mark_failed`, and `read_command`
with the exact request/result types locked in the design. Every state transition uses one explicit
conditional update followed by one exact read.

Store only relative staging manifest entries. Fixed exceptions must use `from None` and never include
ids, fingerprints, SQL, title, or path.

- [x] **Step 4: Run disposable MySQL GREEN.**

Run the schema unit tests plus `test_project_import_commands_mysql.py`. Expected ledger:
created count equal to cleaned count, `remaining=0`, and no product DB access.

- [x] **Step 5: Commit.**

Acceptance evidence (2026-08-11): the complete Task 3 unit and disposable-MySQL slice passed
96/96. Disposable databases reported `created=4 cleaned=4 remaining=0`; fresh `py_compile` and
`git diff --check` passed. Spec and quality reviews both closed at C/I/M 0/0/0. No Provider,
product database, live site, API, UI, or product data was used.

```powershell
git add backend/schema/80_project_imports.sql backend/schema_version.py backend/repositories/project_imports.py backend/tests/unit/test_project_import_schema.py backend/tests/unit/test_project_import_repository.py backend/tests/integration/test_project_import_commands_mysql.py
git commit -m "feat: persist recoverable project import commands"
```

## Task 4: Deterministic id map, typed authority rewrite, and publication plan

**Files:**

- Modify: `backend/domain/project_import_plans.py`
- Create: `backend/tests/unit/test_project_import_identity.py`
- Create: `backend/tests/unit/test_project_import_authority_rewrite.py`

- [ ] **Step 1: Write UUIDv5 and collision RED tests.**

Require `UUIDv5(UUID(commandId), entityType + "/" + logicalId)` for every database-backed record,
stable target project id, sorted canonical `idMapHash`, same-command equality, different-command
difference, and fail-closed duplicate input/output/unknown identity.

- [ ] **Step 2: Write full typed-authority RED fixtures.**

Use nonempty production Seed, StoryEngine, CreationContract, Bible, Planning, Outline,
FinalizationChangeSet, QualityFinding, receipt, Canon, and Projection fixtures. Assert every raw
package logical id is rewritten through the typed registry, all JSON hashes and dependent relational
hashes are recalculated in topological order, and prose/Candidate/corpus byte hashes stay unchanged.

- [ ] **Step 3: Reconstruct all binding revisions unbound.**

For each imported binding revision, emit exactly `TASK_KEYS` in canonical order with null Provider
fields and recalculated item/revision hashes. Rewrite CreationContract model-binding refs and every
dependent contract/planning reference hash. The imported head remains Not Ready.

- [ ] **Step 4: Emit an immutable publication plan.**

Implement immutable `ImportInsertBatch(table, columns, rows)`,
`ProjectPublicationPlan(command_id, target_project_id, id_map_hash, batches, provenance, blobs,
expected_projection)`, and
`build_publication_plan(package, command_id: str, new_title: str) -> ProjectPublicationPlan`.

Batch tables/columns are selected only from static allowlists. Values are immutable JSON primitives;
no SQL string or table name comes from the package.

- [ ] **Step 5: Add dangling/type/extra/hash failure matrix and commit.**

Run Task 2 and Task 4 focused tests; assert all fixed failures have no cause/value echo. Commit:

```powershell
git add backend/domain/project_import_plans.py backend/tests/unit/test_project_import_identity.py backend/tests/unit/test_project_import_authority_rewrite.py
git commit -m "feat: plan deterministic project import publication"
```

## Task 5: Provenance round-trip and atomic MySQL publication

**Files:**

- Modify: `backend/repositories/project_imports.py`
- Modify: `backend/domain/project_packages.py`
- Modify: `backend/repositories/project_packages.py`
- Modify: `backend/tests/unit/test_project_package_domain.py`
- Modify: `backend/tests/unit/test_project_package_repository.py`
- Create: `backend/tests/integration/test_project_import_publication_mysql.py`

- [ ] **Step 1: Write atomic publication RED tests.**

On disposable MySQL, inject failure before every insert batch, Projection rebuild, Projection compare,
command success update, and commit. Each failure must leave zero target project rows and a fixed
command outcome. Success must publish exactly one project and one succeeded command in the same
commit. Same command replay must not duplicate any row.

- [ ] **Step 2: Implement explicit foreign-key-ordered writer.**

Add:

```python
async def publish_project(self, session, plan: ProjectPublicationPlan, *, now: int) -> str:
    await self._lock_matching_command(session, plan.command_id)
    await self._assert_target_absent(session, plan.target_project_id)
    for batch in plan.batches:
        await self._insert_static_batch(session, batch)
    await self._rebuild_and_verify_projection(session, plan)
    await self._mark_succeeded(session, plan, now)
    return plan.target_project_id
```

The transaction factory owns commit/rollback. `_insert_static_batch` resolves SQL only from a frozen
code-owned table-plan registry.

- [ ] **Step 3: Normalize and persist inert provenance.**

Insert one `project_import_provenance` row per safe Provider/market/operation/unsupported-history
record. Quality findings may remain formal with Provider fields null. Never insert fake Provider
profiles or executable old idempotency/lease values.

- [ ] **Step 4: Extend Phase 6B backup round-trip.**

Add a closed `import-provenance` package record. Backup reads only provenance owned by the project and
emits category/source type/source logical id/payload/content hash in stable order. A backup→import→
backup unit fixture must retain each provenance payload/content hash unchanged.

- [ ] **Step 5: Run integration GREEN and commit.**

Run package focused tests plus `test_project_import_publication_mysql.py`; require DB ledger zero,
`py_compile`, `SELECT *` scan zero, and `git diff --check`. Commit:

```powershell
git add backend/repositories/project_imports.py backend/domain/project_packages.py backend/repositories/project_packages.py backend/tests/unit/test_project_package_domain.py backend/tests/unit/test_project_package_repository.py backend/tests/integration/test_project_import_publication_mysql.py
git commit -m "feat: atomically publish imported project authority"
```

## Task 6: Blob staging, promotion, cleanup, and import orchestration

**Files:**

- Create: `backend/services/project_imports.py`
- Create: `backend/tests/unit/test_project_import_staging.py`
- Create: `backend/tests/unit/test_project_import_service.py`
- Create: `backend/tests/integration/test_project_import_recovery_mysql.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/unit/test_main_lifespan.py`

- [ ] **Step 1: Write file fault RED matrix.**

Cover missing/short/hash-mismatched source blob, stage write failure, ACL failure, existing matching
target reuse, existing mismatched target conflict, `os.replace` failure, cancellation, disconnect,
quarantine cleanup retry, stage cleanup retry, and command-created unreferenced blob cleanup. Never
delete a pre-existing/shared/referenced blob.

- [ ] **Step 2: Implement command-owned staging.**

Use a private command quarantine and `.project-import-staging/<commandId>`. Write the canonical
relative staging manifest before promotion. Reuse the existing managed corpus content-addressed path
functions and Phase 6B ACL postcondition helpers.

- [ ] **Step 3: Implement the orchestration service.**

Expose `ProjectImportService.preflight(upload) -> ProjectImportSummary`,
`import_project(upload, request: ImportProjectRequest) -> ProjectImportCommandView`, and
`get_command(command_id: str) -> ProjectImportCommandView`.

`import_project` re-preflights exact bytes, reserves/acquires the same command, builds the plan,
stages/promotes blobs, then invokes one publication transaction. `CancelledError` remains primary.

- [ ] **Step 4: Implement bounded startup reconciliation.**

Inspect at most 32 expired Phase 6C roots. Delete only terminal roots or command-created blobs proven
unreferenced by `corpus_blobs`. Never resume without exact package bytes and never scan unrelated temp
or corpus files.

- [ ] **Step 5: Run service/recovery GREEN and commit.**

Run Task 6 unit/integration/lifespan tests with owned roots; require DB/file/temp residue zero. Commit:

```powershell
git add backend/services/project_imports.py backend/tests/unit/test_project_import_staging.py backend/tests/unit/test_project_import_service.py backend/tests/integration/test_project_import_recovery_mysql.py backend/main.py backend/tests/unit/test_main_lifespan.py
git commit -m "feat: stage and recover atomic project imports"
```

## Task 7: Closed API and fixed public errors

**Files:**

- Create: `backend/routers/project_imports.py`
- Modify: `backend/main.py`
- Create: `backend/tests/api/test_project_import_routes.py`
- Modify: `backend/tests/api/test_route_inventory.py`

- [ ] **Step 1: Write route inventory and multipart RED tests.**

Require exactly the three routes, one file, exact form fields, strict UUID/key/hash/title validation,
bounded upload, DI override, and zero service call for malformed requests.

- [ ] **Step 2: Write fixed result/error tests.**

Map invalid/too-large/sensitive/conflict/not-found/integrity to closed public responses. Test
`CancelledError`, disconnect cleanup, same-command success/replay, running/retryRequired/failed GET,
and no package/body/path/id leakage.

- [ ] **Step 3: Implement router and register it.**

The router streams multipart upload through the service; it never calls `await upload.read()` without
a size-bound chunk loop. Responses use `private, no-store` and `nosniff`.

- [ ] **Step 4: Run API focused GREEN and commit.**

```powershell
python -m pytest -q backend/tests/api/test_project_import_routes.py backend/tests/api/test_route_inventory.py backend/tests/unit/test_main_lifespan.py
git add backend/routers/project_imports.py backend/main.py backend/tests/api/test_project_import_routes.py backend/tests/api/test_route_inventory.py
git commit -m "feat: expose strict project import API"
```

## Task 8: Frontend import controller and Project Library UI

**Files:**

- Modify: `frontend/src/api/db/client.js`
- Create: `frontend/src/application/project/projectImportController.js`
- Create: `frontend/src/components/projects/ProjectImportPanel.vue`
- Modify: `frontend/src/views/ProjectLibraryView.vue`
- Create: `frontend/tests/unit/projectImportApi.test.mjs`
- Create: `frontend/tests/unit/projectImportController.test.mjs`
- Create: `frontend/tests/unit/projectImportPanel.test.mjs`
- Modify: `frontend/tests/unit/projectLibraryViews.test.mjs`

- [ ] **Step 1: Write binary/multipart API RED tests.**

Assert preflight sends only File; import sends File plus exact command/idempotency/hash/title; GET is
the only recovery call. Abort/listener/timer cleanup and fixed `ApiError` mapping must match existing
binary boundaries without reading file body for display.

- [ ] **Step 2: Write controller RED tests.**

Cover select→preflight summary→editable title→single import, double-click fence, fixed five phases,
same File/identifiers on retry, network unknown→GET, running poll, retryRequired repost, failed outcome,
success navigation, dispose/abort generation fence, and no Cancel.

- [ ] **Step 3: Implement the controller.**

The controller owns one selected File and one command identity until selection changes or succeeds.
It uses the existing operation store/beforeunload boundary and never parses the ZIP client-side.

- [ ] **Step 4: Implement the compact Project Library panel.**

Place `导入项目备份` in the library header. Show only file name, safe summary/counts, proposed title,
Provider Not Ready warning, fixed error, and the one import action. No destination selector, merge,
overwrite, archive toggle, Provider selector, payload preview, second confirmation, or cancel action.

- [ ] **Step 5: Run focused Node tests and build, then commit.**

```powershell
node --test frontend/tests/unit/projectImportApi.test.mjs frontend/tests/unit/projectImportController.test.mjs frontend/tests/unit/projectImportPanel.test.mjs frontend/tests/unit/projectLibraryViews.test.mjs frontend/tests/unit/appFeedback.test.mjs
npm --prefix frontend run build
git add frontend/src/api/db/client.js frontend/src/application/project/projectImportController.js frontend/src/components/projects/ProjectImportPanel.vue frontend/src/views/ProjectLibraryView.vue frontend/tests/unit/projectImportApi.test.mjs frontend/tests/unit/projectImportController.test.mjs frontend/tests/unit/projectImportPanel.test.mjs frontend/tests/unit/projectLibraryViews.test.mjs
git commit -m "feat: add project backup import flow"
```

## Task 9: Disposable browser acceptance

**Files:**

- Create: `backend/scripts/prepare_phase6c_browser_db.py`
- Create: `frontend/e2e/run-phase6c.mjs`
- Create: `frontend/e2e/playwright.phase6c.config.mjs`
- Create: `frontend/e2e/phase6c/project-import.spec.mjs`
- Create: `frontend/e2e/phase6c/runtime-observer.mjs`
- Create: `scripts/tests/phase6cBrowserContract.test.mjs`
- Modify: `scripts/run-tests.mjs`
- Modify: `package.json`
- Modify: `frontend/package.json`

- [ ] **Step 1: Write runner-contract RED.**

Require disposable DB, owned quarantine/staging/download/artifact roots, deny proxy, runtime observer,
visible UI file input, real preflight/import/download, one consumer-failure cleanup, exact ZIP/package
verifier reuse, and no `page.request`, `page.route`, `fetch`, `axios`, or `page.evaluate`.

- [ ] **Step 2: Seed one complete real authority fixture.**

Use real service paths to create one active project with confirmed Contract/Bible/Planning/Outline,
WorkingDraft, Candidate, final chapter/Canon, frozen asset/corpus, terminal operation history, and
private Provider configuration that must not run or leak.

- [ ] **Step 3: Exercise the complete visible Phase 6 flow.**

Through visible UI only: create the Phase 6B backup, navigate to Project Library, choose that actual
download with the file input, preflight, edit title, import once, open the new project, prove Provider
Not Ready, and download finalized TXT from the imported project. Verify current authority/final bytes
and that the original project remains unchanged.

- [ ] **Step 4: Inject unknown-result and cleanup boundaries.**

Hold/close one import response after publication and require GET recovery to return the same project.
Assert only one target project and zero quarantine/staging/temp/download/artifact/process/port/DB
residue after success and injected consumer failure.

- [ ] **Step 5: Run the focused browser gate once and commit.**

```powershell
node --test scripts/tests/phase6cBrowserContract.test.mjs
npm run test:browser:phase6c
git add backend/scripts/prepare_phase6c_browser_db.py frontend/e2e/run-phase6c.mjs frontend/e2e/playwright.phase6c.config.mjs frontend/e2e/phase6c scripts/tests/phase6cBrowserContract.test.mjs scripts/run-tests.mjs package.json frontend/package.json
git commit -m "test: accept phase6c atomic project import"
```

## Task 10: Reviews, full Phase 6 gates, and acceptance

**Files:**

- Create: `docs/acceptance/2026-08-10-phase-6c-atomic-project-import.md`
- Modify: this plan's execution status after acceptance

- [ ] **Step 1: Run one fresh combined Phase 6C focused suite.**

Run Tasks 1–9 domain/security/schema/repository/service/API/frontend/runner tests, one disposable-MySQL
publication/recovery suite, `py_compile`, build, and `git diff --check`.

- [ ] **Step 2: Run one specification review, then one serial quality review.**

Require `Critical/Important/Minor = 0/0/0` for new findings. Only active Critical/Important data
corruption, security, atomic-publication, idempotency, secret, or guaranteed cleanup defects may
return. Record nonblocking extremes for Phase 7; do not start an unbounded review loop.

- [ ] **Step 3: Run the full Phase 6 matrix once.**

Run serially and diagnose first cause before any rerun:

```powershell
npm test
npm run test:integration
npm run build
npm run test:browser:phase6c
```

The Phase 6C browser scenario itself covers finalized download, deterministic backup, and atomic
import. Require DB/process/port/temp/cache/quarantine/staging/download/artifact residue zero.

- [ ] **Step 4: Write acceptance and commit.**

Record exact exit/counts, review counts, first causes, schema version, package version/hash, Provider
Not Ready, atomic visibility, idempotent recovery, and resource ledger. Do not record body text,
secrets, DSNs, Provider output, SQL, or absolute paths.

```powershell
git add docs/acceptance/2026-08-10-phase-6c-atomic-project-import.md docs/superpowers/plans/2026-08-10-phase6c-atomic-project-import.md
git commit -m "docs: accept phase6c atomic project import"
```

- [ ] **Step 5: State the exact boundary and proceed to Phase 7.**

Use only:

> Phase 6 finalized download, deterministic secret-free backup, and strict atomic import are accepted with disposable local data. Real-provider quality, product-database readiness, live-site readiness, and novel content quality remain unaccepted.

## Self-review result

- Spec coverage: raw ZIP, canonical package, graph closure, identity/hash rewrite, Provider-unbound
  normalization, schema, command recovery, blob staging, one-transaction publication, Projection,
  provenance round-trip, API/UI, browser, full Phase 6 gates, and residue each map to one task.
- Placeholder scan: no `TBD`, `TODO`, generic error-handling placeholder, or unspecified test remains.
- Type consistency: endpoint names, command status/phase, package version/hash, UUIDv5 mapping,
  `ProjectPublicationPlan`, two schema tables, and frontend recovery semantics match the design.
- Lean boundary: no hidden project visibility state, generic workflow, merge/overwrite, compatibility
  conversion, Provider placeholder, preflight registry, or repeated branch-wide gate was introduced.
