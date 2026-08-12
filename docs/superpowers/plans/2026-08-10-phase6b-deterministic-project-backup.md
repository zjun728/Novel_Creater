# Phase 6B Deterministic Project Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one deterministic, secret-free ZIP backup download for an active or archived project without adding import, schema, background jobs, Provider calls, or product-database access.

**Architecture:** A closed domain module defines package-local records, canonical JSON/JSONL, entry paths, limits, sensitive-key rejection, and deterministic ZIP metadata. One repository reads an explicit project-owned graph in a single repeatable-read consistent snapshot and returns immutable DTOs plus frozen corpus descriptors; one service verifies external blobs, scans exact referenced secrets in private memory, writes a bounded `ZIP_STORED` archive under a runner-owned Phase6B temp root, and transfers cleanup ownership to the response. A single POST route and a compact project-center action reuse the existing operation overlay and binary client.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, aiomysql, `zipfile`, SHA-256, canonical JSON, Vue 3, Pinia, Node test runner, pytest, Playwright, disposable MySQL.

## Execution status

Accepted on 2026-08-10. Tasks 1–7 are complete; final specification and quality reviews reported
`Critical/Important/Minor = 0/0/0` new findings. Exact evidence and the zero-residue ledger are recorded in
`docs/acceptance/2026-08-10-phase-6b-deterministic-project-backup.md`.

---

## Scope guard

- Implement only section 4 of `docs/superpowers/specs/2026-08-09-phase6-download-backup-import-design.md`.
- Do not add a table, schema version, migration, backup ledger, command ledger, scheduler, generic job/workflow, cancellation protocol, cloud destination, encryption, incremental backup, compatibility conversion, or import code.
- Never export Provider profile ids, API keys, Base URLs, settings, prompts, raw Provider output, streamed deltas, owner/lease tokens, executable idempotency keys, global asset heads, corpus heads/import runs, or Projection rows as authority.
- Do not call a Provider, read a product database, or use a real corpus path in automated tests. Use only `novel_creator_test_%` and owned temporary roots.
- Run focused tests per task. Do not run branch-wide Python/Node/MySQL/build/browser gates until Phase 6C closes.

## Package v1 contract locked by this plan

- Required top-level entries: `manifest.json`, `manifest.sha256`, `project/graph.jsonl`, `history/operations.jsonl`, `history/providers.jsonl`, `assets/frozen.jsonl`, `corpus/revisions.jsonl`, `validation/projections.json`; zero or more `corpus/blobs/sha256/<64-lower-hex>` entries.
- `manifest.json.entries` lists every payload entry except `manifest.json` and `manifest.sha256`, in ASCII path order, with `path`, `byteLength`, and `sha256`. `manifest.sha256` is the lowercase SHA-256 of the exact canonical `manifest.json` bytes followed by one LF. This avoids self-reference.
- JSON uses `backend/domain/json_contracts.py`: UTF-8, sorted keys, compact separators, `allow_nan=False`. JSONL is one canonical object plus LF per record, sorted by `(entityType, logicalId, revision/order)` defined by each record type.
- ZIP entries are lexicographic, `ZIP_STORED`, timestamp `1980-01-01T00:00:00`, Unix regular-file mode `0600`, no comment, no extra field, no data descriptor, and ASCII forward-slash paths only.
- Limits: archive `2 GiB`, entries `20,000`, total uncompressed entry bytes `4 GiB`, structured entry `128 MiB`, corpus blob `1 GiB`, path `240` ASCII bytes, JSON nesting `64`.

## Task 1: Closed package domain, canonical records, limits, and secret rejection

**Files:**

- Create: `backend/domain/project_packages.py`
- Create: `backend/security/project_package_paths.py`
- Create: `backend/tests/unit/test_project_package_domain.py`
- Create: `backend/tests/unit/test_project_package_security.py`

- [ ] **Step 1: Write RED tests for exact paths and deterministic canonical bytes.**

```python
def test_payload_entries_are_exact_ascii_and_sorted():
    entries = build_structured_entries(snapshot_fixture(reverse=True))
    assert [entry.path for entry in entries] == [
        "assets/frozen.jsonl",
        "corpus/revisions.jsonl",
        "history/operations.jsonl",
        "history/providers.jsonl",
        "project/graph.jsonl",
        "validation/projections.json",
    ]
    assert all(entry.data.endswith(b"\n") for entry in entries)

def test_manifest_has_no_self_reference():
    manifest = build_manifest(payload_entries(), counts={"project": 1})
    assert [item.path for item in manifest.entries] == sorted(PAYLOAD_PATHS)
    assert "manifest.json" not in {item.path for item in manifest.entries}
    assert "manifest.sha256" not in {item.path for item in manifest.entries}
```

- [ ] **Step 2: Run the domain RED.**

Run: `python -m pytest -q backend/tests/unit/test_project_package_domain.py`

Expected: fail with `ModuleNotFoundError: backend.domain.project_packages`.

- [ ] **Step 3: Implement immutable package values and canonical helpers.**

```python
PACKAGE_FORMAT = "novel-creator-project"
PACKAGE_VERSION = 1
HASH_ALGORITHM = "sha256"

@dataclass(frozen=True, slots=True)
class PackageEntry:
    path: str
    data: bytes

@dataclass(frozen=True, slots=True)
class ManifestEntry:
    path: str
    byte_length: int
    sha256: str

def canonical_line(value: Mapping[str, object]) -> bytes:
    validate_json_depth(value, maximum=64)
    return canonical_json_bytes(value) + b"\n"

def canonical_jsonl(records: Iterable[PackageRecord]) -> bytes:
    return b"".join(canonical_line(record.to_public_dict()) for record in sorted(records, key=record_sort_key))
```

All public record models use `ConfigDict(extra="forbid", frozen=True)` or frozen dataclasses. Raw database ids are accepted only by private repository DTOs and converted to typed logical ids before serialization.

- [ ] **Step 4: Write RED security and limit tests.**

Cover absolute paths, `..`, backslashes, NUL, non-ASCII, duplicate/case-colliding paths, path length, entry count, structured bytes, blob bytes, total bytes, archive bytes, nesting depth, `NaN`, and recursive keys matching `apiKey`, `api_key`, `baseURL`, `base_url`, `Authorization`, `token`, `password`, `dsn`, `lease`, or `ownerToken`.

```python
@pytest.mark.parametrize("key", ["apiKey", "base_url", "Authorization", "ownerToken"])
def test_sensitive_key_is_rejected_without_value_or_path(key):
    sentinel = "SECRET_MUST_NOT_APPEAR"
    with pytest.raises(ProjectPackageSensitiveData, match="sensitive field class") as raised:
        reject_sensitive_keys({"nested": {key: sentinel}})
    assert sentinel not in str(raised.value)
    assert "nested" not in str(raised.value)
```

- [ ] **Step 5: Implement path and limit guards.**

```python
ALLOWED_FIXED_PATHS = frozenset({...})
CORPUS_BLOB_RE = re.compile(r"^corpus/blobs/sha256/[0-9a-f]{64}$")

def validate_entry_path(value: str) -> str:
    encoded = value.encode("ascii", "strict")
    if len(encoded) > 240 or "\\" in value or value.startswith("/") or ".." in value.split("/"):
        raise ProjectPackageInvalid("invalid package entry path")
    if value not in ALLOWED_FIXED_PATHS and not CORPUS_BLOB_RE.fullmatch(value):
        raise ProjectPackageInvalid("invalid package entry path")
    return value
```

Errors are fixed classes: `ProjectPackageNotFound`, `ProjectPackageConflict`, `ProjectPackageTooLarge`, `ProjectPackageInvalid`, `ProjectPackageIntegrity`, and `ProjectPackageSensitiveData`; never include rejected values.

- [ ] **Step 6: Run focused tests and commit.**

Run: `python -m pytest -q backend/tests/unit/test_project_package_domain.py backend/tests/unit/test_project_package_security.py`

Expected: all pass.

Commit: `feat: define deterministic project package contract`

## Task 2: Explicit consistent-snapshot repository and complete ownership inventory

**Files:**

- Create: `backend/repositories/project_packages.py`
- Create: `backend/tests/unit/test_project_package_repository.py`
- Create: `backend/tests/integration/test_project_package_snapshot_mysql.py`

- [ ] **Step 1: Freeze the ownership inventory in a failing repository test.**

The test must parse the create-only schema inventory and compare it to explicit constants; adding a future project-owned table must fail until classified. The repository allowlist covers project, seed/revision/selection, binding revisions/items/heads, project market/seed-inspiration/asset-recommendation/style-trial evidence, story engine, contract/bible/planning/outline revisions/drafts/confirmations, chapter sessions, working draft/revisions, draft attempts/events/candidates/freeze, quality/finalization/final chapters, Canon entities/aliases/revisions/events, and reference uses.

```python
assert PROJECT_OWNED_TABLES | SHARED_EXCLUDED_TABLES | INTERNAL_NON_PACKAGE_TABLES == schema_tables
assert PROJECT_OWNED_TABLES.isdisjoint(SHARED_EXCLUDED_TABLES)
```

Shared exclusions include `provider_profiles`, provider mutations, `application_settings`, global style/experience heads, corpus heads/import/deletion, and global market source/policy/refresh state.

- [ ] **Step 2: Write repository RED tests.**

Assert explicit columns and parameterized project predicates; forbid `SELECT *`. Assert active and archived lifecycle revision match; missing project is distinct from busy/conflict. Assert any active draft/market lease or finalization in `preparing|awaiting_author|committing` blocks before payload publication. Assert terminal/interrupted operation rows are normalized and contain no prompt, request JSON, raw output, deltas, owner token, lease, or replayable idempotency key.

- [ ] **Step 3: Define the repository boundary.**

```python
@dataclass(frozen=True, slots=True)
class ProjectPackageSnapshot:
    source_project_logical_id: str
    lifecycle_revision: int
    graph_records: tuple[PackageRecord, ...]
    operation_records: tuple[PackageRecord, ...]
    provider_history_records: tuple[PackageRecord, ...]
    frozen_asset_records: tuple[PackageRecord, ...]
    corpus_revision_records: tuple[PackageRecord, ...]
    corpus_blobs: tuple[FrozenCorpusBlob, ...]
    projection_validation: Mapping[str, object]
    referenced_secret_values: tuple[bytes, ...]
    counts: Mapping[str, int]

class ProjectPackageRepository:
    async def read_snapshot(self, project_id: str, expected_lifecycle_revision: int) -> ProjectPackageSnapshot: ...
```

- [ ] **Step 4: Implement one read-only consistent transaction.**

Use one acquired MySQL connection:

```sql
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION READ ONLY, WITH CONSISTENT SNAPSHOT;
```

Read every database DTO before rollback/close. Do not perform filesystem reads inside the transaction. Use explicit query blocks and deterministic `ORDER BY`; never infer project ownership by table name alone.

- [ ] **Step 5: Normalize Provider, market, operation, and projection evidence.**

- Provider history: package-local `historyProviderId`, public provider/model name snapshots, task/binding revision/hash and inert operation refs only.
- Market history: minimal public snapshot label/hash/time-range evidence needed by project-local records; never a live source id or refresh command.
- Operations: terminal/interrupted status, result hash, safe request fingerprint and record refs; active attempts block.
- Projections: recompute deterministic count/hash sets from Canon-derived projection rows for later import validation, but never serialize projection rows as restore authority.

- [ ] **Step 6: Add disposable-MySQL concurrency coverage.**

Pause the repository after its first authority read, commit a concurrent allowed change, resume, and prove every returned row belongs to one snapshot. Add busy-state cases and lifecycle revision conflict. Ledger must report `created=cleaned`, `remaining=0`.

- [ ] **Step 7: Run focused tests and commit.**

Run:

```text
python -m pytest -q backend/tests/unit/test_project_package_repository.py
python -m pytest -q backend/tests/integration/test_project_package_snapshot_mysql.py
```

Commit: `feat: read project package consistent snapshot`

## Task 3: Deterministic ZIP service, corpus verification, and owned temp lifecycle

**Files:**

- Create: `backend/services/project_packages.py`
- Create: `backend/tests/unit/test_project_package_zip.py`
- Create: `backend/tests/unit/test_project_package_service.py`
- Create: `backend/tests/unit/test_project_package_temp_cleanup.py`

- [ ] **Step 1: Write deterministic ZIP RED tests.**

Build the same snapshot twice with reversed input record order and different wall clocks; assert exact archive bytes and package SHA-256 match. Inspect every `ZipInfo` for fixed timestamp, `ZIP_STORED`, `extra == b""`, `comment == b""`, ASCII path, lexicographic order, and mode `0600`.

- [ ] **Step 2: Implement the ZIP writer.**

```python
def zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(validate_entry_path(path), (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.extra = b""
    info.comment = b""
    return info
```

Build or spool the bounded payload entries first, compute the canonical manifest and its LF-terminated
hash entry, then write the complete entry set in one final lexicographic pass. Use known sizes on the
seekable owned archive file. Track actual archive bytes during writes and fail before returning when
a limit is crossed.

- [ ] **Step 3: Write corpus and exact-secret RED tests.**

For each frozen corpus descriptor verify storage path through `backend/security/paths.py`, regular-file status, expected byte length, SHA-256, and exact raw bytes. Test missing file, changed length/hash, symlink/path escape, oversized blob, and one referenced API-key/Base-URL sentinel embedded in structured or raw corpus bytes. Error text and traceback-visible public cause must not contain the sentinel.

- [ ] **Step 4: Implement service and private secret scan.**

```python
@dataclass(frozen=True, slots=True)
class ProjectPackageFile:
    path: Path
    package_sha256: str
    download_name: str
    cleanup: Callable[[], None]

class ProjectPackageService:
    async def create_backup(self, project_id: str, expected_lifecycle_revision: int) -> ProjectPackageFile: ...
```

Load referenced secret/Base URL values only into private byte arrays, skip empty values, scan all structured entry bytes and corpus bytes by exact value, then release references. Do not log the values, match ordinary words such as `password`, or serialize `hasApiKey`/`enabled` hints.

- [ ] **Step 5: Implement the Phase6B temp owner.**

Create one exclusive random directory outside the managed corpus root with prefix `novel-creator-phase6b-`, mode `0700`, and archive mode `0600`. Cleanup is idempotent and validates the resolved target remains an owned prefix before recursive removal. Startup cleanup only scans that exact prefix under the configured temp parent, removes roots older than 24 hours, and examines at most 32 entries; no scheduler.

- [ ] **Step 6: Test every cleanup exit.**

Cover success handoff, repository failure, corpus failure, ZIP failure, sensitive-value failure, client generator cancellation, response background cleanup, duplicate cleanup, and startup stale-root cleanup. Each test asserts owned roots/files `0` afterward.

- [ ] **Step 7: Run focused tests and commit.**

Run:

```text
python -m pytest -q backend/tests/unit/test_project_package_zip.py backend/tests/unit/test_project_package_service.py backend/tests/unit/test_project_package_temp_cleanup.py
python -m py_compile backend/domain/project_packages.py backend/repositories/project_packages.py backend/services/project_packages.py
```

Commit: `feat: build deterministic secret-free project package`

## Task 4: One POST route and response-owned cleanup

**Files:**

- Create: `backend/routers/project_packages.py`
- Create: `backend/tests/api/test_project_package_routes.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/api/test_route_inventory.py`

- [ ] **Step 1: Write route RED tests.**

Exact request:

```http
POST /api/projects/{projectId}/backup
Content-Type: application/json

{"expectedLifecycleRevision": 7}
```

Reject unknown body fields and invalid revisions with 422. Map missing project to 404, lifecycle/busy state to 409, size to 413, integrity/sensitive data to fixed 422, and unexpected internal failure to fixed 500. No response contains paths, ids beyond the public project id, secret values, DSNs, corpus bytes, or exception causes.

- [ ] **Step 2: Test exact success response and disconnect cleanup.**

Assert `application/zip`, `Content-Disposition` safe fallback plus UTF-8 name, `X-Package-SHA256`, `Cache-Control: private, no-store`, and `X-Content-Type-Options: nosniff`. Test normal streaming, generator cancellation, and response background callback each invoke the same idempotent cleanup.

- [ ] **Step 3: Implement the route and DI boundary.**

```python
class BackupProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_lifecycle_revision: int = Field(alias="expectedLifecycleRevision", ge=0)

@router.post("/projects/{project_id}/backup")
async def backup_project(project_id: str, body: BackupProjectBody) -> Response: ...
```

Use `FileResponse` or a bounded chunk generator plus `BackgroundTask(package.cleanup)`. The generator `finally` also calls cleanup so response close and disconnect have two idempotent cleanup paths.

- [ ] **Step 4: Register only the router and bounded startup cleanup.**

Call the narrow stale-root cleanup from the existing application lifespan before serving requests. Failure logs only a fixed safe code and must not prevent normal DB pool cleanup. Do not create a repeating task.

- [ ] **Step 5: Run focused tests and commit.**

Run: `python -m pytest -q backend/tests/api/test_project_package_routes.py backend/tests/api/test_route_inventory.py backend/tests/unit/test_main_lifespan.py`

Commit: `feat: expose project backup download`

## Task 5: Frontend binary API, controller, and project-center action

**Files:**

- Modify: `frontend/src/api/db/client.js`
- Create: `frontend/src/application/project/projectBackupController.js`
- Create: `frontend/src/components/projects/ProjectBackupPanel.vue`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Modify: `frontend/src/views/ArchivedProjectStatusView.vue`
- Create: `frontend/tests/unit/projectBackupApi.test.mjs`
- Create: `frontend/tests/unit/projectBackupController.test.mjs`
- Create: `frontend/tests/unit/projectBackupPanel.test.mjs`
- Modify: `frontend/tests/unit/projectPreparationOverview.test.mjs`

- [ ] **Step 1: Write API and controller RED tests.**

The API sends only `{ expectedLifecycleRevision }` and returns `{ blob, contentDisposition, packageSha256 }`. Reuse the independent binary request path; do not parse the ZIP body as JSON or a filename.

Controller contract:

```javascript
createProjectBackupController({
  api,
  operationStore,
  flushCurrentDraft,
  createObjectURL,
  revokeObjectURL,
  saveBlob,
  abortControllerFactory,
})
```

Active backup awaits `flushCurrentDraft()` before starting the request; false/rejection produces fixed `保存当前正文失败，未创建备份。` and exactly zero backup requests. Archived backup skips flush. Single-flight, operation start/update/finish, object URL revoke, dispose abort, safe filename fallback `project-backup.zip`, and fixed public errors are mandatory. There is no Cancel button.

- [ ] **Step 2: Keep the UI placement lean.**

Add one compact secondary `ProjectBackupPanel` after the existing finalized download panel on active Overview and archived read-only status. It receives `projectId`, `title`, `lifecycleRevision`, and `archived`. Backup is not exposed from Writer routes; existing Writer `onBeforeRouteLeave -> controller.canNavigate()` flushes debounce before the user reaches Overview, so the active backup action cannot coexist with an unflushed Writer editor.

- [ ] **Step 3: Implement safe phase updates.**

Use the existing `operationStore.update(id, { label, detail })` only for these fixed phases:

1. `正在核对项目状态`
2. `正在建立一致快照`
3. `正在写入备份包`
4. `正在准备下载`

The overlay remains blocking; no percent, path, body, Provider text, history, persistence, or cancel control.

- [ ] **Step 4: Test active/archived behavior and DOM save.**

Tests must observe anchor `href`, `.zip` download name, append, click, remove, and `URL.revokeObjectURL`; verify flush failure sends zero requests; verify archived skips flush; verify lifecycle revision is exact; verify one primary creative next action still precedes both download/backup secondary panels.

- [ ] **Step 5: Run focused tests and build once.**

Run:

```text
node --test frontend/tests/unit/projectBackupApi.test.mjs frontend/tests/unit/projectBackupController.test.mjs frontend/tests/unit/projectBackupPanel.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs frontend/tests/unit/appFeedback.test.mjs
npm --prefix frontend run build
```

Commit: `feat: add deterministic project backup action`

## Task 6: Disposable-MySQL package acceptance and one visible-browser path

**Files:**

- Create: `backend/scripts/prepare_phase6b_browser_db.py`
- Create: `frontend/e2e/run-phase6b.mjs`
- Create: `frontend/e2e/playwright.phase6b.config.mjs`
- Create: `frontend/e2e/phase6b/project-backup.spec.mjs`
- Create: `scripts/tests/phase6bBrowserContract.test.mjs`
- Modify: `scripts/run-tests.mjs`
- Modify: `package.json`
- Modify: `frontend/package.json`

- [ ] **Step 1: Add a runner-contract RED.**

Require one disposable DB, unique API/deny-proxy/Vite ports, owned temp/download/artifact/corpus roots, no Provider configuration, exact one formal scenario, fixed package paths, actual ZIP parsing, and forbidden `page.request`, `page.route`, `fetch`, `axios`, and `page.evaluate`.

- [ ] **Step 2: Seed the smallest complete fixture.**

Use real services/repositories to create one project containing the immutable creative chain, one finalized chapter, one non-final WorkingDraft/Candidate sentinel, one frozen style/experience revision, and one frozen corpus revision with owned content-addressed bytes. Add inert terminal Provider/operation evidence with secret/Base-URL sentinels in the disposable Provider row so exact-value scanning is exercised while the package remains secret-free.

- [ ] **Step 3: Exercise the visible UI only.**

From active Overview click `创建项目备份`, wait for the blocking overlay, prove a visible navigation attempt is fenced, receive the Playwright download event, save to the owned download root, and inspect the ZIP with a runner-owned verifier process. Archive through the product UI and prove archived backup also succeeds.

- [ ] **Step 4: Verify actual package bytes.**

The verifier asserts exact entry set/order/metadata, manifest and package hashes, one complete corpus blob, creative records present, projection validation present, Provider history inert, and zero occurrences of API-key/Base-URL/WorkingDraft body in logs or artifacts. The WorkingDraft itself is included in `project/graph.jsonl` by design; only logs/artifacts must not expose it outside the downloaded package.

- [ ] **Step 5: Verify success and failure cleanup.**

Inject one owned client disconnect/failure case at the response consumer without changing product output. Both success and failure must report database, API, proxy, Vite, browser, ports, package temp, owned corpus fixture, downloads, artifacts, and Vite `deps_temp` residue `0`; outbound/Provider `0`; product DB reads/writes `0/0`.

- [ ] **Step 6: Run only the focused browser gate and commit.**

Run:

```text
node --test scripts/tests/phase6bBrowserContract.test.mjs
npm run test:browser:phase6b
```

Commit: `test: accept phase6b deterministic project backup`

## Task 7: Serial reviews, acceptance record, and Phase 6C handoff

**Files:**

- Create: `docs/acceptance/2026-08-10-phase-6b-deterministic-project-backup.md`
- Modify: this plan's execution status after acceptance

- [x] **Step 1: Run the combined Phase 6B focused suite once fresh.**

Run domain/security/repository/service/API/frontend/runner-contract tests from Tasks 1–6, one disposable-MySQL snapshot test, `py_compile`, frontend build, and `git diff --check`. Do not run branch-wide Phase 6 gates.

- [x] **Step 2: Run one specification review.**

Require `Critical/Important/Minor = 0/0/0` for new findings. Only Critical/Important active-path data corruption, security, deterministic-package, or guaranteed cleanup defects may return to implementation; record extreme non-blockers for Phase 7 hardening.

- [x] **Step 3: Run one serial quality review after spec passes.**

Use the same stop rule. Do not start a second review loop for new non-blocking scope.

- [x] **Step 4: Record exact evidence and resource ledger.**

The acceptance document records commands, exit/counts, first-cause history, review counts, package format/version/hash, and DB/process/port/temp/corpus/download/artifact/Vite residue. It must not contain body text, secret values, DSNs, Provider output, or local absolute corpus paths.

- [x] **Step 5: Commit and proceed directly to 6C.**

Commit: `docs: accept phase6b deterministic project backup`

State only: deterministic secret-free project backup is accepted with disposable local data. Do not claim import, complete Phase 6, real-provider quality, or product-database readiness. Create the separate Phase 6C execution plan and continue without user confirmation.

## Self-review result

- Spec coverage: API/lifecycle, consistent snapshot, exact package entries, ownership/exclusions, Provider/market normalization, secret scanning, fixed limits, temp ownership, active/archived UI, browser bytes, and residue are each mapped to a task.
- Placeholder scan: no placeholder marker or unspecified error-handling step remains.
- Type consistency: `ProjectPackageSnapshot`, `ProjectPackageFile`, `expectedLifecycleRevision`, package entry names, limit values, and response headers are identical across repository, service, API, frontend, and browser tasks.
- Lean boundary: Phase 6B adds no persistence and no generic orchestration; Phase 6C remains the only import/schema slice.
