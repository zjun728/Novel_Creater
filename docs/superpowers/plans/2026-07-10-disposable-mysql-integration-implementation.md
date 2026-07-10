# Disposable MySQL Transaction Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the draft-pair service's atomicity, idempotency, collision handling, connection-outcome recovery, and migration containment against a newly generated disposable MySQL schema only.

**Architecture:** A test-only harness accepts one explicit loopback admin DSN without a database name, creates a cryptographically named schema, loads a dedicated three-table fixture plus the ledger migration, and injects a pool bound to that schema. The opt-in module is excluded from default discovery; cleanup revalidates the exact run token before dropping only its generated schema.

**Tech Stack:** Python 3.12 standard library, `unittest.IsolatedAsyncioTestCase`, aiomysql 0.2, MySQL 5.7-compatible DDL, npm opt-in script.

---

## File map

- Create `backend/tests/control_plane/fixtures/control_plane_minimal_schema.sql`: only projects, chapters, chapter_versions.
- Create `backend/tests/control_plane/mysql_harness.py`: DSN guards, schema lifecycle, fixed SQL loaders, pool injection.
- Create `backend/tests/control_plane/test_mysql_harness.py`: deterministic pure guard tests included in `npm test`.
- Create `backend/tests/control_plane/mysql_integration_test.py`: opt-in database cases excluded from `test_*.py` discovery.
- Reuse transaction files and migration created by the transaction-core plan.
- Do not modify or execute `backend/schema.sql`; do not import `backend.main`, `backend.config`, or `backend.database`.

## Execution dependency

This plan is not parallel with Transaction Core. Start it only after the Gateway and Core commits pass deterministic verification. Its worker owns only the four integration files listed above and does not stage or commit; the product-control thread performs final DB verification, exact staging, review, and commit.

### Task 1: Add the dedicated fixture and deterministic harness guards with TDD

**Files:**
- Create: `backend/tests/control_plane/fixtures/control_plane_minimal_schema.sql`
- Create: `backend/tests/control_plane/test_mysql_harness.py`
- Create: `backend/tests/control_plane/mysql_harness.py`

- [ ] **Step 1: Add the exact minimal fixture**

The file contains exactly these three unqualified tables, without `IF NOT EXISTS`, `CREATE DATABASE`, `DROP DATABASE`, or `USE`:

```sql
CREATE TABLE projects (
  id CHAR(36) PRIMARY KEY,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE chapters (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL DEFAULT 0,
  final_version_id CHAR(36) DEFAULT NULL,
  status VARCHAR(20) DEFAULT 'drafting',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_chapters_project (project_id),
  INDEX idx_chapters_num (project_id, chapter_num),
  INDEX idx_chapters_status (project_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE chapter_versions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL DEFAULT 0,
  title VARCHAR(200) DEFAULT '',
  content LONGTEXT DEFAULT NULL,
  version_type VARCHAR(30) DEFAULT 'ai_candidate',
  source_model_id CHAR(36) DEFAULT NULL,
  prompt_brief TEXT DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_versions_project (project_id),
  INDEX idx_versions_chapter (chapter_id),
  INDEX idx_versions_type (version_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

- [ ] **Step 2: Write pure red tests for DSN, token, schema, and fixture guards**

```python
class MySQLHarnessGuardTest(unittest.TestCase):
    def test_rejects_product_database_path_before_connect(self):
        with self.assertRaises(HarnessConfigurationError):
            parse_admin_dsn("mysql://root:secret@127.0.0.1:3306/novel_creator")

    def test_schema_name_is_exactly_bound_to_token(self):
        token = "a" * 24
        self.assertEqual(
            schema_name_for_token(token),
            "novel_creator_control_plane_disposable_" + token,
        )

    def test_fixture_has_only_three_allowed_tables(self):
        statements = load_and_validate_minimal_fixture()
        self.assertEqual(len(statements), 3)
        self.assertEqual(extract_created_tables(statements), {
            "projects", "chapters", "chapter_versions"
        })
```

Table-drive missing DSN, wrong scheme, remote host, credentials without username, path, query, fragment, socket form, invalid port, malformed token, bad schema prefix, and fixture forbidden keywords/schema-qualified names. Accept `localhost`, `127.0.0.1`, and `::1` without a path/query/fragment.

- [ ] **Step 3: Run the guard test red**

```powershell
python -m unittest discover -s backend/tests/control_plane -p "test_mysql_harness.py" -v
```

Expected: FAIL because `mysql_harness.py` does not exist.

- [ ] **Step 4: Implement pure guard helpers without importing product config**

Expose:

```python
@dataclass(frozen=True)
class AdminDSN:
    host: str
    port: int
    user: str
    password: str

class HarnessConfigurationError(RuntimeError):
    """The disposable database harness was not safely configured."""

def parse_admin_dsn(raw: str) -> AdminDSN:
    """Accept mysql:// loopback admin DSNs with no database/query/fragment."""

def new_run_token() -> str:
    return secrets.token_hex(12)

def schema_name_for_token(token: str) -> str:
    """Return and validate novel_creator_control_plane_disposable_<24-hex>."""

def validate_schema_identity(schema_name: str, token: str) -> None:
    """Require exact prefix-plus-token identity before identifier interpolation."""

def load_and_validate_minimal_fixture() -> list[str]:
    """Load only the fixed fixture constant path and return three safe statements."""
```

Never include the raw DSN/password in errors or logs. Do not provide a general `execute_sql_file(path)` API.

- [ ] **Step 5: Run deterministic guard tests green and prove no network**

Run the target test with `CONTROL_PLANE_DISPOSABLE_MYSQL_DSN` unset. Expected: PASS and no socket/database call. Then run default Python discovery and confirm `mysql_integration_test.py` is absent from the discovered tests.

### Task 2: Implement the disposable schema/pool lifecycle with TDD fakes

**Files:**
- Modify: `backend/tests/control_plane/mysql_harness.py`
- Modify: `backend/tests/control_plane/test_mysql_harness.py`

- [ ] **Step 1: Write fake-admin lifecycle tests**

Use injected `create_pool` and fake admin/data pools. Assert order:

1. query `information_schema.schemata` for exact name;
2. fail if present;
3. create database without `IF NOT EXISTS`;
4. open data pool with explicit `db=generated_schema`;
5. assert `SELECT DATABASE()` before/after fixture and migration;
6. close data pool;
7. revalidate token/schema;
8. drop exact generated database;
9. close admin pool.

Also assert successful creation prints `CONTROL_PLANE_DISPOSABLE_SCHEMA_CREATED=<exact-name>`, successful cleanup prints `CONTROL_PLANE_DISPOSABLE_SCHEMA_DROPPED=<exact-name>`, and cleanup failure prints `CONTROL_PLANE_DISPOSABLE_SCHEMA_ORPHAN=<exact-name>`. No output may contain the DSN or credentials.

- [ ] **Step 2: Implement a fixed-path async context manager**

```python
@dataclass
class DisposableMySQL:
    schema_name: str
    run_token: str
    pool: object

@asynccontextmanager
async def disposable_mysql(*, environ: Mapping[str, str],
                           create_pool: Callable[..., Awaitable[object]]):
    raw = environ.get("CONTROL_PLANE_DISPOSABLE_MYSQL_DSN")
    if raw is None:
        raise HarnessConfigurationError("CONTROL_PLANE_DISPOSABLE_MYSQL_DSN is required")
    dsn = parse_admin_dsn(raw)
    token = new_run_token()
    schema = schema_name_for_token(token)
    admin_pool = await create_admin_pool(create_pool, dsn)
    data_pool = None
    created = False
    try:
        await assert_schema_absent(admin_pool, schema)
        await create_exact_schema(admin_pool, schema, token)
        created = True
        print(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_CREATED={schema}")
        data_pool = await create_data_pool(create_pool, dsn, schema)
        await apply_fixed_fixture_and_migration(data_pool, schema)
        yield DisposableMySQL(schema_name=schema, run_token=token, pool=data_pool)
    finally:
        cleanup_error = None
        if data_pool is not None:
            try:
                data_pool.close()
                await data_pool.wait_closed()
            except Exception as error:
                cleanup_error = error
        if created:
            try:
                validate_schema_identity(schema, token)
                await drop_exact_schema(admin_pool, schema, token)
                print(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_DROPPED={schema}")
            except Exception as error:
                print(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_ORPHAN={schema}")
                cleanup_error = cleanup_error or error
        try:
            admin_pool.close()
            await admin_pool.wait_closed()
        except Exception as error:
            cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            raise cleanup_error
```

Use fixed constants for the fixture, apply migration, and rollback migration paths. Split SQL only after verifying forbidden tokens and table allowlists.

- [ ] **Step 3: Add the database identity assertion used at every phase**

```python
async def assert_selected_database(conn, expected_schema: str) -> None:
    async with conn.cursor() as cursor:
        await cursor.execute("SELECT DATABASE()")
        row = await cursor.fetchone()
    selected = row[0] if isinstance(row, (tuple, list)) else row.get("DATABASE()")
    if selected != expected_schema:
        raise HarnessConfigurationError("Disposable database identity mismatch")
```

Call before and after fixture, apply, rollback, and before yielding. Never parse/rewrite/read `backend/schema.sql`.

- [ ] **Step 4: Run all harness guard/lifecycle tests green**

Expected: PASS with fakes only and no real DB access.

### Task 3: Add opt-in atomicity and idempotency integration cases

**Files:**
- Create: `backend/tests/control_plane/mysql_integration_test.py`

- [ ] **Step 1: Create isolated async setup/cleanup and fixture seeding helpers**

Use `unittest.IsolatedAsyncioTestCase`. Each test enters its own `disposable_mysql()` context, inserts one project, two drafting chapters, and two source versions, then builds a `DraftWriteService` with the injected pool/schema/token. The helper returns a valid command whose two source/candidate hashes are computed from exact UTF-8 strings.

- [ ] **Step 2: Add success, rollback, replay, conflict, and drift tests**

Implement these exact methods and assertions:

```text
test_two_candidates_commit_together
  ledger=1; qa_draft_candidate=2; result IDs match request order; chapters unchanged

test_failure_after_first_candidate_rolls_back_ledger_and_candidates
  injected after_candidate_insert(1) raises; ledger=0; qa candidates=0

test_same_key_same_hash_replays_without_duplicates
  results equal; ledger=1; qa candidates=2

test_same_key_different_hash_conflicts_without_writes
  second code=idempotency_manifest_conflict; totals stay 1/2

test_source_preimage_drift_conflicts_without_writes
  update source after command creation; code=source_preimage_mismatch; totals 0/0
```

- [ ] **Step 3: Add both finalized-state and lock-order tests**

Add one test for `status='final'`, another for non-null `final_version_id`; both return `chapter_finalized` and leave 0/0. Send writes in reverse chapter order, assert success/result request order, and combine with the deterministic repository SQL test that proves lock order is stored `(chapter_num,id)`.

- [ ] **Step 4: Run only the opt-in module against an explicitly provided disposable server**

```powershell
$env:CONTROL_PLANE_DISPOSABLE_MYSQL_DSN='mysql://user:password@127.0.0.1:3306'
python -m unittest discover -s backend/tests/control_plane -p "mysql_integration_test.py" -v
```

Expected at this checkpoint: the implemented cases PASS; every printed created schema has a matching dropped line. If the environment variable or disposable server is unavailable, report the integration plan as blocked and do not substitute product `MYSQL_*` settings.

### Task 4: Add concurrency, migration containment, and commit-outcome recovery

**Files:**
- Modify: `backend/tests/control_plane/mysql_integration_test.py`
- Modify only if tests expose a narrow interface defect: files under `backend/control_plane/`.

- [ ] **Step 1: Add concurrent identical submission**

Run two separate service calls with the same key/hash via `asyncio.gather`. Assert both results equal, one ledger exists, and exactly two candidate rows exist.

- [ ] **Step 2: Add migration apply/rollback containment**

Assert ledger exists only in the selected generated schema after apply. Execute only the fixed rollback migration, assert ledger is gone while the three fixture tables remain, reapply for cleanup/test continuation, and assert `SELECT DATABASE()` at every phase.

- [ ] **Step 3: Add commit-landed outcome-unknown recovery**

Inject a test-only commit operation that awaits the real commit and then raises `ConnectionError`. First submit returns `commit_outcome_unknown`; direct counts are 1 ledger/2 candidates. Recreate a normal service and replay same key/hash; it returns the original result and counts remain 1/2.

- [ ] **Step 4: Add commit-not-landed outcome-unknown recovery**

Inject a commit operation that closes/invalidates the uncommitted connection and raises before commit. First submit returns `commit_outcome_unknown`; direct counts are 0/0. A normal same-key/hash replay then commits and counts become 1/2.

The injected hook/commit operation exists only as a constructor dependency in tests. No HTTP field, environment flag, module global, or product app exposes it.

- [ ] **Step 5: Run all 12 required integration cases fresh**

```powershell
npm run test:control-plane:db
```

Expected: 12 cases, no skip, `OK`; every created schema is dropped; no product database name, backend service, provider, or model call appears.

### Task 5: Negative guards, full audit, and isolated commit

**Files:** all files in this plan only, plus any test-driven narrow fix under `backend/control_plane/`.

- [ ] **Step 1: Prove unsafe configurations fail before connection**

Run the opt-in command with the environment variable absent, with `mysql://user:password@127.0.0.1:3306/novel_creator`, and with `mysql://user:password@example.com:3306`. Instrument or use the pure parser tests to prove the injected `create_pool` call count remains zero. Expected: non-zero command exit with fixed safe configuration text and no credentials.

- [ ] **Step 2: Run default deterministic tests separately**

```powershell
npm test
```

Expected: PASS and no execution of `mysql_integration_test.py`.

- [ ] **Step 3: Audit forbidden imports/files and cleanup evidence**

```powershell
git diff --check
rg -n "backend\.main|backend\.config|backend\.database|MYSQL_CONFIG|MYSQL_DB" backend/tests/control_plane
rg -n -F "backend/schema.sql" backend/tests/control_plane
git status --short
```

Expected: no product module imports or product schema execution. The literal `schema.sql` may appear only in a rejection assertion proving it is forbidden; review that occurrence.

- [ ] **Step 4: Stage only integration files and test-driven narrow fixes**

```powershell
git add backend/tests/control_plane/fixtures/control_plane_minimal_schema.sql `
  backend/tests/control_plane/mysql_harness.py `
  backend/tests/control_plane/test_mysql_harness.py `
  backend/tests/control_plane/mysql_integration_test.py
git diff --cached --check
git diff --cached --name-only
```

If a production transaction file required a narrow integration-driven correction, stage it explicitly and document the exact failing test that justified it.

- [ ] **Step 5: Commit**

```powershell
git commit -m "test(control-plane): add disposable mysql transaction coverage"
```

Expected: an independently reviewable integration commit. Only fresh opt-in output grants `DB Ready` for this service; it never grants AI Proxy or Live Ready.
