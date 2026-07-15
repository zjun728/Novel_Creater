# Atomic Draft Transaction Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dormant, disposable-pool-only backend service that atomically creates exactly two QA draft candidates with RFC 8785 manifest integrity, binary idempotency, confirmed rollback behavior, and deterministic unit tests.

**Architecture:** A new `backend.control_plane` package owns restricted JCS, closed request/domain models, errors, an injected-pool transaction boundary, repository SQL, and the orchestration service. A router factory is test-app-only and is never imported by `backend/main.py`; the ledger is introduced through one explicit migration that does not alter product tables.

**Tech Stack:** Python 3.12, FastAPI 0.115, Pydantic 2.13 strict models, aiomysql-compatible protocols, standard `unittest`, MySQL 5.7 SQL contracts.

---

## File map

- Create `backend/control_plane/__init__.py`: package boundary.
- Create `backend/control_plane/restricted_jcs.py`: duplicate-rejecting parser and restricted RFC 8785 canonicalizer.
- Create `backend/control_plane/draft_write_models.py`: closed request models and immutable commands/results.
- Create `backend/control_plane/draft_write_errors.py`: safe domain/HTTP error mapping.
- Create `backend/control_plane/draft_write_transaction.py`: injected-pool connection lifecycle.
- Create `backend/control_plane/draft_write_repository.py`: all SQL with an explicit connection.
- Create `backend/control_plane/draft_write_service.py`: atomic two-candidate orchestration and replay.
- Create `backend/routers/control_plane_draft_writes.py`: dormant router factory.
- Create `backend/migrations/20260710_control_plane_draft_write_batches.sql` and rollback.
- Create `tools/control-plane-qa/restricted-jcs.mjs`: Node implementation of the same restricted JCS profile.
- Create `tools/control-plane-qa/tests/restricted-jcs.test.mjs`: shared-vector Node verification.
- Create deterministic tests under `backend/tests/control_plane/` plus shared JCS vectors under `tools/control-plane-qa/fixtures/`.
- Do not modify `backend/main.py`, `backend/database.py`, `backend/config.py`, `backend/schema.sql`, or `backend/requirements.txt`.

## Parallel execution ownership

Transaction Core Tasks 1-5 may be developed in parallel with Gateway Tasks 1-4 because the plans own distinct files. Core workers use direct `python -m unittest ...` and explicit `node --test <file>` commands during the parallel wave; they do not invoke npm scripts, stage, or commit. After both workers finish, the product-control thread verifies and commits Gateway first, then runs Core's complete npm verification, stages Core's exact files, and commits Core. Disposable Integration remains sequential after Core.

### Task 1: Implement restricted RFC 8785 and closed domain models with TDD

**Files:**
- Create: `tools/control-plane-qa/fixtures/rfc8785-restricted-vectors.json`
- Create: `backend/control_plane/__init__.py`
- Create: `backend/control_plane/restricted_jcs.py`
- Create: `backend/control_plane/draft_write_models.py`
- Create: `backend/control_plane/draft_write_errors.py`
- Create: `backend/tests/control_plane/test_restricted_jcs.py`
- Create: `backend/tests/control_plane/test_draft_write_models.py`
- Create: `tools/control-plane-qa/restricted-jcs.mjs`
- Create: `tools/control-plane-qa/tests/restricted-jcs.test.mjs`

- [ ] **Step 1: Write shared canonicalization vectors and red tests**

Create vectors for UTF-16 key order, `é` versus `e\u0301`, quotes/backslashes/control characters, a non-BMP key/value, arrays, and safe integer bounds. The JSON shape is fixed:

```json
{
  "valid": [
    { "name": "object order", "value": { "b": 1, "a": 2 }, "canonical": "{\"a\":2,\"b\":1}" },
    { "name": "no unicode normalization", "value": { "é": "é" }, "canonical": "{\"é\":\"é\"}" }
  ],
  "invalidRaw": [
    { "name": "duplicate key", "raw": "{\"a\":1,\"a\":2}" }
  ]
}
```

Test signatures:

```python
from backend.control_plane.restricted_jcs import (
    JCSCanonicalizationError,
    canonical_sha256,
    canonicalize,
    loads_rejecting_duplicates,
)

class RestrictedJCSTest(unittest.TestCase):
    def test_checked_in_valid_vectors(self):
        for case in load_vectors()["valid"]:
            self.assertEqual(canonicalize(case["value"]).decode("utf-8"), case["canonical"])

    def test_duplicate_key_is_rejected(self):
        with self.assertRaises(JCSCanonicalizationError):
            loads_rejecting_duplicates(b'{"a":1,"a":2}')
```

Add explicit rejects for floats, null, bool, out-of-range integers, invalid UTF-8, and unpaired surrogates.

- [ ] **Step 2: Run the JCS tests red**

```powershell
python -m unittest discover -s backend/tests/control_plane -p "test_restricted_jcs.py" -v
```

Expected: FAIL because `backend.control_plane.restricted_jcs` does not exist.

- [ ] **Step 3: Implement the restricted canonicalizer**

Expose exactly:

```python
class JCSCanonicalizationError(ValueError):
    """The value cannot be represented by this schema-restricted JCS profile."""

def loads_rejecting_duplicates(raw: bytes) -> object:
    """Decode strict UTF-8 JSON and reject duplicate keys at every object depth."""

def canonicalize(value: object) -> bytes:
    """Return RFC 8785-compatible UTF-8 bytes for dict/list/str/strict-int values."""

def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonicalize(value)).hexdigest()
```

Implementation rules are exact: sort object keys by `key.encode('utf-16-be')`; reject surrogate code points; handle bool before int; allow integers only in `[-(2**53)+1, (2**53)-1]`; use ECMAScript short escapes for `\b`, `\t`, `\n`, `\f`, `\r`, lower-case `\u00xx` for remaining controls; never normalize Unicode or escape `/`.

- [ ] **Step 4: Write and run the Node shared-vector tests red**

```js
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { canonicalize, canonicalSha256 } from '../restricted-jcs.mjs'

test('matches every valid restricted RFC 8785 vector', async () => {
  const raw = await readFile(new URL('../fixtures/rfc8785-restricted-vectors.json', import.meta.url), 'utf8')
  const vectors = JSON.parse(raw)
  for (const item of vectors.valid) {
    assert.equal(canonicalize(item.value), item.canonical, item.name)
    assert.match(canonicalSha256(item.value), /^[0-9a-f]{64}$/)
  }
})
```

Run:

```powershell
node --test tools/control-plane-qa/tests/restricted-jcs.test.mjs
```

Expected: FAIL because `restricted-jcs.mjs` does not exist.

- [ ] **Step 5: Implement the Node restricted canonicalizer**

Expose `canonicalize(value): string` and `canonicalSha256(value): string`. Recursively allow only plain objects, arrays, strings, and safe integers; reject null, bool, float, non-plain objects, and unpaired surrogates. Use JavaScript's default UTF-16 key sort after validating string keys, and `JSON.stringify()` only for already validated strings. Hash `new TextEncoder().encode(canonicalize(value))` with `node:crypto` SHA-256.

- [ ] **Step 6: Write closed-model red tests**

Test exact root/write keys, strict `manifestVersion == 1`, fixed purpose, two distinct chapters, strict positive integer chapter numbers, mandatory IDs/preimage hashes, lower-case 64-hex hashes, title 1-200, prompt 1-500, non-empty content, visible-ASCII idempotency key, and body/route project identity.

```python
def test_rejects_unknown_write_field(self):
    payload = valid_payload()
    payload["writes"][0]["model"] = "forbidden"
    with self.assertRaises(DraftWriteError) as caught:
        parse_manifest_value(payload)
    self.assertEqual(caught.exception.code, "unknown_field")

def test_candidate_hash_mismatch_is_422(self):
    payload = valid_payload()
    payload["writes"][0]["contentSha256"] = "0" * 64
    with self.assertRaises(DraftWriteError) as caught:
        to_command(
            route_project_id=payload["projectId"],
            request=parse_manifest_value(payload),
            idempotency_key="Key-1",
            manifest_sha256=canonical_sha256(payload),
        )
    self.assertEqual(caught.exception.http_status, 422)
```

- [ ] **Step 7: Implement strict models and immutable domain types**

Use Pydantic `ConfigDict(extra='forbid', strict=True)` and explicit validation functions. Public types and functions:

```python
class DraftCandidateWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chapterId: str
    chapterNum: int
    sourceVersionId: str
    expectedSourceContentSha256: str
    title: str
    content: str
    contentSha256: str
    promptBrief: str

class DraftWriteBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    manifestVersion: int
    purpose: str
    projectId: str
    writes: list[DraftCandidateWriteRequest]

def parse_manifest_bytes(raw: bytes) -> tuple[DraftWriteBatchRequest, dict[str, object]]:
    value = loads_rejecting_duplicates(raw)
    return parse_manifest_value(value), value

def parse_manifest_value(value: object) -> DraftWriteBatchRequest:
    """Validate exact manifest keys and strict field types, mapping failures to safe 400 errors."""

def to_command(*, route_project_id: str, request: DraftWriteBatchRequest,
               idempotency_key: str, manifest_sha256: str) -> DraftWriteCommand:
    """Validate headers, body/route identity and candidate hashes, then freeze the command."""
```

Define frozen dataclasses `DraftCandidateWrite`, `DraftWriteCommand`, and `DraftWriteResult`; `DraftWriteResult.to_wire()` returns only `batchId`, `projectId`, `manifestSha256`, ordered `candidateVersionIds`, and `committedAt`.

- [ ] **Step 8: Implement safe errors and run Python and Node suites green**

```python
@dataclass(frozen=True)
class DraftWriteError(Exception):
    code: str
    http_status: int
    message: str
    retryable: bool = False

def mysql_error_number(error: BaseException) -> int | None:
    args = getattr(error, "args", ())
    return args[0] if args and isinstance(args[0], int) else None
```

Add named constructors/classes for commit/transaction unknown and unsafe disposable DB. The 400 codes are `invalid_manifest`, `duplicate_json_key`, `unknown_field`, `invalid_write_count`, `duplicate_chapter_id`, `invalid_hash`, `invalid_manifest_hash`, and `invalid_idempotency_key`; 404 codes are `feature_disabled`, `project_not_found`, `chapter_not_found`, and `source_version_not_found`; 409 codes include all identity/finalized/preimage/idempotency cases plus `source_content_unavailable`; 422 is only `candidate_content_hash_mismatch`; 503 codes are the two outcome-unknown cases. Messages are fixed and never include request content or SQL errors.

Run:

```powershell
python -m unittest discover -s backend/tests/control_plane -p "test_restricted_jcs.py" -v
python -m unittest discover -s backend/tests/control_plane -p "test_draft_write_models.py" -v
node --test tools/control-plane-qa/tests/restricted-jcs.test.mjs
```

Expected: both suites PASS, 0 failures.

### Task 2: Add the ledger migration through static red/green tests

**Files:**
- Create: `backend/migrations/20260710_control_plane_draft_write_batches.sql`
- Create: `backend/migrations/20260710_control_plane_draft_write_batches_rollback.sql`
- Create: `backend/tests/control_plane/test_draft_write_migration.py`

- [ ] **Step 1: Write static migration tests first**

Assert apply SQL contains exactly one `CREATE TABLE draft_write_batches`, baseline columns, `VARBINARY(120)`, `ascii_bin`, and unique `(project_id, idempotency_key)`; reject `IF NOT EXISTS`, `CREATE DATABASE`, `USE`, other table names, and product-table alterations. Assert rollback normalizes exactly to `DROP TABLE draft_write_batches;`. Assert `backend/schema.sql`, `backend/database.py`, and `backend/main.py` do not contain the new table/router identifiers.

- [ ] **Step 2: Run migration tests red**

```powershell
python -m unittest discover -s backend/tests/control_plane -p "test_draft_write_migration.py" -v
```

Expected: FAIL because the migration files do not exist.

- [ ] **Step 3: Add exact apply and rollback SQL**

```sql
CREATE TABLE draft_write_batches (
  id CHAR(36) NOT NULL,
  project_id CHAR(36) NOT NULL,
  idempotency_key VARBINARY(120) NOT NULL,
  manifest_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  result_json JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  committed_at BIGINT DEFAULT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_draft_write_batches_project_key (project_id, idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

Rollback:

```sql
DROP TABLE draft_write_batches;
```

- [ ] **Step 4: Run migration tests green**

Expected: PASS, without connecting to MySQL.

### Task 3: Implement the injected-pool transaction boundary with TDD

**Files:**
- Create: `backend/control_plane/draft_write_transaction.py`
- Create: `backend/tests/control_plane/fakes.py`
- Create: `backend/tests/control_plane/test_draft_write_transaction.py`

- [ ] **Step 1: Build scripted fake pool/connection/cursor classes**

The fakes record acquire/release, SQL, begin/commit/rollback, autocommit changes, closed state, and injected commit/rollback/restore failures. They must implement only the methods used by the transaction/repository and must never import aiomysql or open a socket.

- [ ] **Step 2: Write red connection-lifecycle tests**

Cover exact schema validation before begin, `READ COMMITTED`, same connection throughout, success commit once/no rollback, domain error rollback once/no commit, transport-loss commit error without rollback, known 1205/1213 commit errors with confirmed rollback, other known MySQL commit errors with confirmed rollback, rollback error, and autocommit-restore failure. Assert only unknown-outcome connections are closed without rollback and never reusable.

```python
async def test_commit_failure_discards_connection_without_rollback(self):
    conn = FakeConnection(database_name=SCHEMA, commit_error=ConnectionError("lost"))
    pool = FakePool([conn])
    with self.assertRaises(CommitOutcomeUnknown):
        async with read_committed_transaction(pool=pool, expected_schema=SCHEMA):
            pass
    self.assertEqual(conn.rollback_calls, 0)
    self.assertTrue(conn.closed)
    self.assertFalse(pool.was_returned_reusable(conn))
```

- [ ] **Step 3: Run transaction tests red**

```powershell
python -m unittest discover -s backend/tests/control_plane -p "test_draft_write_transaction.py" -v
```

Expected: FAIL because the transaction module does not exist.

- [ ] **Step 4: Implement explicit transaction lifecycle**

Expose `PoolLike`, `ConnectionLike`, and:

```python
@asynccontextmanager
async def read_committed_transaction(*, pool: PoolLike,
                                     expected_schema: str,
                                     commit_operation: Callable[[ConnectionLike], Awaitable[None]] | None = None
                                     ) -> AsyncIterator[ConnectionLike]:
    """Validate the injected schema and yield one READ COMMITTED connection."""
```

Order: acquire; save original autocommit; `SELECT DATABASE()`; exact schema match; set autocommit false; set READ COMMITTED; begin; yield; commit once through `commit_operation(conn)` or `conn.commit()` when the dependency is absent. Pre-commit exceptions rollback once. A transport/connection-loss commit error with unknown server outcome becomes `commit_outcome_unknown` and is never rolled back; a known MySQL commit error attempts a confirmed rollback and then propagates for normal 1205/1213/internal mapping. Rollback failure becomes `transaction_outcome_unknown`. Confirmed endings restore original autocommit; restoration failure invalidates. Closed connections go through pool bookkeeping but never the reusable queue. `commit_operation` is constructor/test dependency only and is never sourced from HTTP, environment, or a module global.

Implement `is_commit_outcome_unknown(error)` to return true only for `ConnectionError`, connection-level `OSError`, or MySQL transport codes 2006, 2013, and 2055. Codes 1205 and 1213 are known retryable conflicts; other explicit MySQL errors are known failures. Tests cover all three categories.

- [ ] **Step 5: Run transaction tests green**

Expected: PASS, 0 sockets and 0 database access.

### Task 4: Implement repository SQL and service orchestration with TDD

**Files:**
- Create: `backend/control_plane/draft_write_repository.py`
- Create: `backend/control_plane/draft_write_service.py`
- Create: `backend/tests/control_plane/test_draft_write_service.py`

- [ ] **Step 1: Write service-order and domain-error tests**

Use one scripted connection and assert SQL order: project lock; ledger insert; chapters lock ordered by stored `chapter_num,id`; source locks ordered by ID; candidate insert 1; candidate insert 2; ledger completion. Add separate cases for missing/cross-project identity, number mismatch, both finalized conditions, source identity, SQL NULL source, preimage drift, candidate hash mismatch, injected first-insert failure, 1062 replay/conflict, 1205, and 1213.

- [ ] **Step 2: Run service tests red**

```powershell
python -m unittest discover -s backend/tests/control_plane -p "test_draft_write_service.py" -v
```

Expected: FAIL for missing repository/service modules.

- [ ] **Step 3: Implement repository methods with explicit connection first**

Expose `lock_project`, `insert_pending_batch`, `read_batch`, `lock_chapters`, `lock_source_versions`, `insert_candidate_version`, and `complete_batch`. Every signature starts with `conn`; the module must not import `database`, `config`, or `MYSQL_CONFIG`. Use the exact SQL and lock ordering from the design. Candidate inserts use only baseline columns, `qa_draft_candidate`, NULL model, and `[control-plane:<batch-id>]` prompt prefix.

- [ ] **Step 4: Implement `DraftWriteService.submit()`**

```python
class DraftWriteService:
    def __init__(self, *, pool: PoolLike, expected_schema: str, run_token: str,
                 uuid_factory: Callable[[], str], clock_ms: Callable[[], int],
                 after_candidate_insert: Callable[[int], Awaitable[None]] | None = None,
                 commit_operation: Callable[[ConnectionLike], Awaitable[None]] | None = None):
        """Accept only an explicitly injected disposable pool and deterministic dependencies."""

    async def submit(self, command: DraftWriteCommand) -> DraftWriteResult:
        """Create both candidate rows and the committed ledger result atomically."""
```

Validate `expected_schema == 'novel_creator_control_plane_disposable_' + run_token`. Pass `commit_operation` only to the transaction boundary. Keep request order for candidate/result IDs and database order for locks. Map 1062 by rolling back and opening a fresh current-read transaction; same hash + complete result replays, different hash conflicts, absent/incomplete row is retryable in-progress. Map 1205/1213 after confirmed rollback without automatic retry.

- [ ] **Step 5: Run service plus deterministic suites**

```powershell
python -m unittest discover -s backend/tests/control_plane -p "test_draft_write_service.py" -v
python -m unittest discover -s backend/tests/control_plane -p "test_*.py" -v
```

Expected: PASS. The integration module is not discovered.

### Task 5: Add the dormant router/test-app contract with TDD

**Files:**
- Create: `backend/routers/control_plane_draft_writes.py`
- Create: `backend/tests/control_plane/test_app.py`
- Create: `backend/tests/control_plane/test_draft_write_router.py`

- [ ] **Step 1: Write route-off, raw-parse, hash, and safe-error tests**

Use FastAPI's test client or `httpx.ASGITransport` against only the minimal test app. Flag absent/false/`1`/case variants produce normal 404. Exact `true` mounts the route. Invalid JSON, duplicate keys, unknown fields, invalid headers, and manifest mismatch must leave fake-pool acquire count at zero. Safe errors include only `code`, fixed `message`, and `retryable`.

- [ ] **Step 2: Run router tests red**

```powershell
python -m unittest discover -s backend/tests/control_plane -p "test_draft_write_router.py" -v
```

Expected: FAIL because router/test-app factories do not exist.

- [ ] **Step 3: Implement the dormant router factory**

```python
def create_router(*, service: DraftWriteService) -> APIRouter:
    router = APIRouter(tags=["control-plane-draft-writes"])

    @router.post("/projects/{project_id}/draft-write-batches")
    async def create_draft_write_batch(project_id: str, request: Request) -> dict[str, object]:
        raw = await request.body()
        parsed, manifest_value = parse_manifest_bytes(raw)
        supplied_hash = require_single_header(request, "X-Manifest-SHA256")
        if canonical_sha256(manifest_value) != supplied_hash:
            raise to_http_exception(DraftWriteError(
                code="invalid_manifest_hash",
                http_status=400,
                message="Manifest hash does not match the request body.",
            ))
        command = to_command(
            route_project_id=project_id,
            request=parsed,
            idempotency_key=require_single_header(request, "Idempotency-Key"),
            manifest_sha256=supplied_hash,
        )
        return (await service.submit(command)).to_wire()

    return router
```

Define `require_single_header(request, name)` to reject missing, duplicate, or invalid header values with safe 400 errors. Define `to_http_exception(error)` to emit only `detail.code`, fixed `detail.message`, and `detail.retryable`. Catch only `DraftWriteError`; never include raw body or underlying exception text.

- [ ] **Step 4: Implement a test-only app factory**

`create_disposable_test_app()` receives pool, schema name, run token, a passed-in environment mapping, deterministic UUID/clock, optional insert hook, and optional commit operation. It mounts only when `CONTROL_PLANE_DRAFT_WRITES_ENABLED` is exactly `true`. It never imports `backend.main`, global DB/config helpers, or reads MySQL environment variables. Neither test dependency is accepted through the HTTP request or process environment.

- [ ] **Step 5: Run router and full deterministic tests green**

```powershell
python -m unittest discover -s backend/tests/control_plane -p "test_draft_write_router.py" -v
npm run test:control-plane
```

Expected: all tests PASS; no DB integration, socket, service, provider, model, finalization, or live call.

### Task 6: Audit and commit the transaction-core slice

**Files:** all files in this plan only.

- [ ] **Step 1: Run scope and forbidden dependency checks**

```powershell
git diff --check
rg -n "MYSQL_CONFIG|get_pool|from database|import database" backend/control_plane backend/routers/control_plane_draft_writes.py
rg -n "control_plane_draft_writes|draft_write_batches" backend/main.py backend/schema.sql backend/database.py
git status --short
```

Expected: no whitespace errors; both forbidden scans return no production matches; no unrelated files.

- [ ] **Step 2: Run fresh deterministic verification**

```powershell
python -m unittest discover -s backend/tests/control_plane -p "test_*.py" -v
npm test
```

Expected: all deterministic Node/Python tests PASS. Do not run `npm run test:control-plane:db` in this plan.

- [ ] **Step 3: Stage the exact slice**

```powershell
git add backend/control_plane/__init__.py `
  backend/control_plane/restricted_jcs.py `
  backend/control_plane/draft_write_models.py `
  backend/control_plane/draft_write_errors.py `
  backend/control_plane/draft_write_transaction.py `
  backend/control_plane/draft_write_repository.py `
  backend/control_plane/draft_write_service.py `
  backend/routers/control_plane_draft_writes.py `
  backend/migrations/20260710_control_plane_draft_write_batches.sql `
  backend/migrations/20260710_control_plane_draft_write_batches_rollback.sql `
  backend/tests/control_plane/fakes.py `
  backend/tests/control_plane/test_app.py `
  backend/tests/control_plane/test_restricted_jcs.py `
  backend/tests/control_plane/test_draft_write_models.py `
  backend/tests/control_plane/test_draft_write_transaction.py `
  backend/tests/control_plane/test_draft_write_service.py `
  backend/tests/control_plane/test_draft_write_router.py `
  backend/tests/control_plane/test_draft_write_migration.py `
  tools/control-plane-qa/fixtures/rfc8785-restricted-vectors.json `
  tools/control-plane-qa/restricted-jcs.mjs `
  tools/control-plane-qa/tests/restricted-jcs.test.mjs
git diff --cached --check
git diff --cached --name-only
```

Expected: only transaction-core, deterministic tests, migration, and shared vector files are staged; no integration harness/fixture.

- [ ] **Step 4: Commit**

```powershell
git commit -m "feat(control-plane): add atomic draft write transaction"
```

Expected: one independently reviewable commit. Passing evidence grants `Transaction Unit Ready` only, never DB or Live Ready.
