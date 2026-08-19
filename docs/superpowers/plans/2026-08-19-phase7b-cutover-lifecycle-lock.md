# Phase 7B Cutover Lifecycle Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the final Phase 7B cutover safety findings by binding the published backup authority, requiring approval before I/O, and serializing product startup and configuration cutover with one shared lifecycle lock.

**Architecture:** Extend the canonical preparation receipt with the backup basename and byte length, then verify the sibling backup through the existing single-open identity boundary. Add a small cross-platform lifecycle-lock service: Windows uses a zero-wait named mutex; POSIX uses a stable hash-named advisory-lock file. The backend holds the lock for its complete lifespan, while cutover releases it for browser smoke and reacquires it before success or rollback.

**Tech Stack:** Python 3.12, asyncio/FastAPI lifespan, Win32 named mutexes through `ctypes`, POSIX `fcntl.flock`, pytest, existing Phase 7B canonical receipt and backup services.

---

## File map

- Create `backend/services/product_database_lifecycle_lock.py`: shared lock contract, Windows/POSIX implementations, fixed safe lifecycle errors, and primary-before-cleanup handling.
- Create `backend/tests/unit/test_product_database_lifecycle_lock.py`: independent platform API fakes and real-process contention coverage.
- Modify `backend/domain/product_database_readiness.py`: bind `backup_filename` and `backup_byte_length` into `PreparationReceipt`.
- Modify `backend/services/product_database_readiness.py`: propagate the verified `BackupReceipt` authority into the final receipt.
- Modify `backend/services/product_database_backup.py`: reject a size mismatch from the opened handle before hashing.
- Modify `backend/scripts/prepare_product_database.py`: serialize/parse the two new closed receipt fields without weakening the existing one-megabyte receipt limit.
- Modify `backend/scripts/cutover_product_database.py`: approval-first CLI, receipt-derived safe backup verification, and lifecycle-lock cutover/recovery sequencing.
- Modify `backend/main.py`: acquire the lifecycle lock before database access and release it after complete shutdown.
- Modify the corresponding existing unit tests plus `backend/tests/unit/test_main_lifespan.py`.
- Modify this amendment plan's checkboxes and add its exact verification evidence only after all
  implementation gates pass. Do not create the final Phase 7B acceptance document before Stage B.

### Task 1: Bind exact backup authority into the preparation receipt

**Files:**
- Modify: `backend/domain/product_database_readiness.py`
- Modify: `backend/services/product_database_readiness.py`
- Modify: `backend/scripts/prepare_product_database.py`
- Test: `backend/tests/unit/test_product_database_readiness_domain.py`
- Test: `backend/tests/unit/test_product_database_readiness.py`
- Test: `backend/tests/unit/test_prepare_product_database_command.py`

- [ ] **Step 1: Write failing receipt-domain tests**

Add exact-construction and rejection cases proving the final receipt requires a safe basename and exact nonnegative built-in byte length:

```python
receipt = PreparationReceipt(
    state="awaiting_cutover_approval",
    previous_receipt_hash=HASH,
    legacy_database="novel_creator",
    new_database="novel_creator_v113",
    legacy_inventory_hash=HASH,
    new_inventory_hash=HASH,
    backup_filename="phase7b.sql",
    backup_sha256=HASH,
    backup_byte_length=123,
    style_count=10,
    experience_card_count=64,
    market_source_count=2,
    receipts=state_receipts,
)
assert receipt.backup_filename == "phase7b.sql"
assert receipt.backup_byte_length == 123
```

Parameterize rejection for path separators, `.`/`..`, Windows reserved names, trailing dot/space, NUL, wrong suffix, bool/int subclasses, negative length, and missing/extra JSON keys.

- [ ] **Step 2: Run the receipt RED tests**

Run:

```powershell
python -m pytest backend/tests/unit/test_product_database_readiness_domain.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_prepare_product_database_command.py -q --basetemp=.pytest-phase7b-lifecycle-task1-red
```

Expected: failures show `PreparationReceipt` does not accept or require `backup_filename` and `backup_byte_length`.

- [ ] **Step 3: Implement the closed receipt fields**

Add exact fields and validation to `PreparationReceipt`:

```python
def _require_backup_basename(value: object) -> str:
    if (
        type(value) is not str
        or not value.endswith(".sql")
        or value in {".", ".."}
        or Path(value).name != value
        or value[-1] in {".", " "}
        or "\x00" in value
        or value.partition(".")[0].upper()
        in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    ):
        _invalid()
    return value

backup_filename: str
backup_sha256: str
backup_byte_length: int

_require_backup_basename(self.backup_filename)
_require_hash(self.backup_sha256)
_require_nonnegative_int(self.backup_byte_length)
```

Construct them only from the already verified `BackupReceipt`:

```python
backup_filename=backup.backup_filename,
backup_sha256=backup.backup_sha256,
backup_byte_length=backup.backup_byte_length,
```

Keep `publish_readiness_receipt` canonical serialization and `load_preparation_receipt` exact-key parsing. Do not add compatibility defaults: a receipt lacking either field is invalid.

- [ ] **Step 4: Run Task 1 GREEN tests**

Run the Step 2 command. Expected: all three files pass and no test weakens the existing path, identity, one-megabyte, canonical-JSON, or secret-free error checks.

- [ ] **Step 5: Commit Task 1**

```powershell
git add backend/domain/product_database_readiness.py backend/services/product_database_readiness.py backend/scripts/prepare_product_database.py backend/tests/unit/test_product_database_readiness_domain.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_prepare_product_database_command.py
git commit -m "fix: bind readiness backup authority"
```

### Task 2: Verify backup size and digest through one owned handle

**Files:**
- Modify: `backend/services/product_database_backup.py`
- Modify: `backend/scripts/cutover_product_database.py`
- Test: `backend/tests/unit/test_product_database_backup.py`
- Test: `backend/tests/unit/test_cutover_product_database_command.py`

- [ ] **Step 1: Write failing backup-boundary tests**

Add tests that open a non-link regular file once and prove size is checked before the first read:

```python
with pytest.raises(ProductDatabaseBackupError, match="^backup verification failed$"):
    verify_backup_file(path, hashlib.sha256(b"ok").hexdigest(), 2)
assert opened.read_calls == 0
assert opened.close_calls == 1
```

Cover symlink/reparse components, path-to-handle identity mismatch, non-regular file, short/long size, digest mismatch, read/close failure precedence, and cleaned flow-control exceptions.

- [ ] **Step 2: Run the backup RED tests**

Run:

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py -q --basetemp=.pytest-phase7b-lifecycle-task2-backup-red
```

Expected: the pre-read size assertion fails because `_open_verified_backup` currently hashes before comparing length.

- [ ] **Step 3: Add the pre-read size binding**

After `fstat` and same-file validation, reject before `_hash_handle`:

```python
if opened.st_size != expected_length:
    raise OSError
digest, length = _hash_handle(handle)
if digest != expected_sha256 or length != expected_length:
    raise OSError
```

Retain the same handle for hashing and existing close/error normalization.

- [ ] **Step 4: Write failing cutover approval and sibling tests**

Prove wrong approval causes zero calls to receipt loader, verifier, config reader, inventory, smoke, or writer. For valid approval, require the backup path to be `receipt_path.parent / receipt.backup_filename` and verifier arguments to be the receipt SHA-256 and byte length. Reject a mismatched directory, unsafe receipt basename, verifier failure, or wrong type with fixed cutover evidence errors.

- [ ] **Step 5: Replace the cutover digest helper with safe verification**

Validate CLI mode and exact confirmations before receipt I/O. Replace `_backup_sha256_for_receipt` with an injected verifier matching:

```python
def _verify_receipt_backup(receipt_path: Path, receipt: PreparationReceipt) -> None:
    backup_path = receipt_path.parent / receipt.backup_filename
    verify_backup_file(
        backup_path,
        receipt.backup_sha256,
        receipt.backup_byte_length,
    )
```

Pass no separately observed digest into `cutover`; it trusts only a successfully verified exact `PreparationReceipt`. Keep recovery approval-first and receipt-free.

- [ ] **Step 6: Run Task 2 GREEN tests and commit**

Run:

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py backend/tests/unit/test_cutover_product_database_command.py -q --basetemp=.pytest-phase7b-lifecycle-task2-green
python -m py_compile backend/services/product_database_backup.py backend/scripts/cutover_product_database.py
git diff --check
```

Expected: all pass. Then commit only the four Task 2 files:

```powershell
git add backend/services/product_database_backup.py backend/scripts/cutover_product_database.py backend/tests/unit/test_product_database_backup.py backend/tests/unit/test_cutover_product_database_command.py
git commit -m "fix: verify cutover backup before access"
```

### Task 3: Add the shared lifecycle-lock service

**Files:**
- Create: `backend/services/product_database_lifecycle_lock.py`
- Create: `backend/tests/unit/test_product_database_lifecycle_lock.py`

- [ ] **Step 1: Write independent Windows/POSIX RED contracts**

Tests must import only the public lock factory/error and inject independent API fakes. Require:

```python
with product_database_lifecycle_lock(config_path, platform_name="nt", windows_api=api):
    assert api.events == ["create", "wait"]
assert api.events == ["create", "wait", "release", "close"]
```

Cover null create, timeout, wait failure, abandoned mutex, success, body ordinary/CancelledError/KeyboardInterrupt/SystemExit, release failure, close failure, primary-first groups, and exact safe leaves. POSIX covers stable opaque lock path, `LOCK_EX | LOCK_NB`, contention, unlock/close ordering, open/flock failures, and the same error matrix. Assert names contain neither repository path nor injected secret.

- [ ] **Step 2: Run the lifecycle-lock RED suite**

Run:

```powershell
python -m pytest backend/tests/unit/test_product_database_lifecycle_lock.py -q --basetemp=.pytest-phase7b-lifecycle-task3-red
```

Expected: collection fails because the module does not exist.

- [ ] **Step 3: Implement the minimal public contract**

Expose one synchronous context manager and one fixed exception:

```python
class ProductDatabaseLifecycleError(RuntimeError):
    pass

@contextmanager
def product_database_lifecycle_lock(
    config_path: Path,
    *,
    platform_name: str = os.name,
    windows_api: object | None = None,
    posix_api: object | None = None,
):
    selected = (
        _windows_lifecycle_lock(config_path, windows_api)
        if platform_name == "nt"
        else _posix_lifecycle_lock(config_path, posix_api)
    )
    with selected:
        yield
```

Use a distinct opaque prefix such as `Local\\NovelCreator.ProductDatabaseLifecycle.` plus SHA-256 of the normalized absolute config path on Windows. On POSIX use `tempfile.gettempdir() / ("novel-creator-product-lifecycle-" + digest + ".lock")`, open without following symlinks where supported, retain the descriptor for the full context, and never delete the stable empty lock file. Rebuild all public exceptions: ordinary failures become fixed `ProductDatabaseLifecycleError`; flow-control leaves retain only safe type/integer code; body primary precedes release/close cleanup.

- [ ] **Step 4: Add real contention probes**

On Windows, use a separate spawned process because mutex acquisition is recursive within one owner thread. On POSIX, use a separate process holding `flock`. Assert the contender fails immediately, executes no body, leaks no handle/process, and succeeds after the owner exits.

- [ ] **Step 5: Run Task 3 GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_product_database_lifecycle_lock.py -q --basetemp=.pytest-phase7b-lifecycle-task3-green
python -m py_compile backend/services/product_database_lifecycle_lock.py backend/tests/unit/test_product_database_lifecycle_lock.py
git diff --check
git add backend/services/product_database_lifecycle_lock.py backend/tests/unit/test_product_database_lifecycle_lock.py
git commit -m "feat: add product database lifecycle lock"
```

### Task 4: Hold the lifecycle lock for the complete backend lifespan

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/unit/test_main_lifespan.py`

- [ ] **Step 1: Write lifespan RED tests**

Inject a recording context manager and prove exact ordering:

```python
assert events.index("lock:enter") < events.index("database:verify")
assert events.index("pool:closed") < events.index("lock:exit")
```

Add second-instance contention, startup failure, shutdown failure, body flow-control, and lock release/close failure cases. The lock must be attempted before stale-root cleanup or any database/background-service action. Every acquired application resource must still be cleaned before lock release; application primary remains first when release fails.

- [ ] **Step 2: Run lifespan RED tests**

```powershell
python -m pytest backend/tests/unit/test_main_lifespan.py -q --basetemp=.pytest-phase7b-lifecycle-task4-red
```

Expected: ordering tests fail because `backend.main.lifespan` does not acquire the new lock.

- [ ] **Step 3: Wrap the existing lifespan without weakening cleanup**

Acquire at the outermost boundary:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    with product_database_lifecycle_lock(LOCAL_CONFIG_PATH):
        async with _application_lifespan(app):
            yield
```

Move the existing body unchanged into `_application_lifespan`; do not reorder its gateway, registry, scheduler, or pool cleanup. The outer lock context observes the final application/cleanup exception and can retain its own release/close failure after it.

- [ ] **Step 4: Run Task 4 GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_main_lifespan.py backend/tests/unit/test_product_database_lifecycle_lock.py -q --basetemp=.pytest-phase7b-lifecycle-task4-green
python -m py_compile backend/main.py
git diff --check
git add backend/main.py backend/tests/unit/test_main_lifespan.py
git commit -m "fix: lock the product backend lifespan"
```

### Task 5: Serialize cutover, smoke completion, rollback, and recovery

**Files:**
- Modify: `backend/scripts/cutover_product_database.py`
- Modify: `backend/tests/unit/test_cutover_product_database_command.py`

- [ ] **Step 1: Write the cutover sequencing RED matrix**

Replace process-scan expectations with a recording lifecycle factory. Require these event sequences:

```python
# success
["lock1:enter", "config:read", "inventory", "write:new", "lock1:exit",
 "smoke:start", "smoke:stop", "lock2:enter", "config:revalidate", "lock2:exit"]

# smoke failure with rollback
["lock1:enter", "write:new", "lock1:exit", "smoke:fail",
 "lock2:enter", "rollback:old", "lock2:exit"]
```

Add contention before initial read, contender winning before smoke, contender winning before final verification, contender winning before rollback, recovery contention, lock acquisition/release failure, and ordinary/flow primary precedence. Assert no write without an active lock and no process enumeration call.

- [ ] **Step 2: Run the sequencing RED tests**

```powershell
python -m pytest backend/tests/unit/test_cutover_product_database_command.py -q --basetemp=.pytest-phase7b-lifecycle-task5-red
```

Expected: lifecycle event assertions fail because cutover still uses the one-time process scan.

- [ ] **Step 3: Implement three bounded lock scopes**

Use an injected factory defaulting to the shared service:

```python
with lifecycle_lock(Path(config_path)):
    original_snapshot = capture_local_document_snapshot(Path(config_path))
    observed = await _invoke(inventory_reader, original)
    switched_snapshot = await _invoke(
        writer, Path(config_path), switched, acl_runner, original_snapshot
    )

try:
    await _invoke(smoke, switched)
except BaseException as smoke_error:
    with lifecycle_lock(Path(config_path)):
        await _invoke(
            writer, Path(config_path), original, acl_runner, switched_snapshot
        )
    raise_safe_smoke_or_rollback(smoke_error)
else:
    with lifecycle_lock(Path(config_path)):
        require_exact_snapshot(switched_snapshot)
```

Recovery uses one lock scope covering config read, inventory proof, and CAS write. Remove `assert_no_product_application_process` from the authoritative path and delete its injected `idle_guard` parameter/tests. Do not hold the lock while spawning smoke.

- [ ] **Step 4: Run Task 5 GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_cutover_product_database_command.py backend/tests/unit/test_main_lifespan.py backend/tests/unit/test_product_database_lifecycle_lock.py -q --basetemp=.pytest-phase7b-lifecycle-task5-green
python -m py_compile backend/scripts/cutover_product_database.py
git diff --check
git add backend/scripts/cutover_product_database.py backend/tests/unit/test_cutover_product_database_command.py
git commit -m "fix: serialize product database cutover"
```

### Task 6: Final regression gates and reviews

**Files:**
- Modify after success: `docs/superpowers/plans/2026-08-19-phase7b-cutover-lifecycle-lock.md`

- [ ] **Step 1: Run the complete Phase 7B focused Python gate**

Use a unique worktree-owned basetemp and include Tasks 1–7, the new lock suite, main lifespan, cutover, and browser-owner command tests. Expected: all pass, zero skips except explicitly platform-inapplicable lock implementation cases.

- [ ] **Step 2: Run repository unit and static gates once**

```powershell
npm test
npm run build
python -m py_compile backend/domain/product_database_readiness.py backend/services/product_database_readiness.py backend/services/product_database_backup.py backend/services/product_database_lifecycle_lock.py backend/scripts/prepare_product_database.py backend/scripts/cutover_product_database.py backend/main.py
node --check frontend/e2e/run-phase7b.mjs
node --check scripts/run-tests.mjs
git diff --check
```

Expected: Python, scripts Node, frontend Node, build, compilation, and diff checks all exit zero. Run sequentially; do not overlap runners that share `.codex-test-artifacts`.

- [ ] **Step 3: Run the existing real MySQL 8.4 focused gate once**

Set the already approved explicit `TEST_MYSQL_*` values for `127.0.0.1:3307` and exact 8.4 client paths, then run only `backend/tests/integration/test_product_database_readiness_mysql.py`. Expected: 7 passed, 0 skipped; disposable database ledger created equals cleaned and remaining is zero. Never enumerate, read, write, or drop an existing database.

- [ ] **Step 4: Obtain independent specification and quality reviews**

The specification review must trace every new design paragraph to code and non-fake tests. The quality review must actively probe approval-before-I/O, receipt length spoofing, relative-command backend contention, lock gap races, abandoned mutex/POSIX contention, and primary/cleanup flow ordering. Active Critical/Important/Minor findings must be `0/0/0` before proceeding.

- [ ] **Step 5: Update evidence only after all gates pass**

Record exact counts and resource ledgers in this amendment plan. Do not create the final acceptance
document or mark Stage A, Stage B, cutover, or legacy retirement complete; this implementation
performs no real backup, product-database write, browser formal, config write, Provider call, or
network action.

- [ ] **Step 6: Commit documentation closure**

```powershell
git add docs/superpowers/plans/2026-08-19-phase7b-cutover-lifecycle-lock.md
git commit -m "docs: record phase7b lifecycle verification"
```

Verify the final worktree is clean and report any externally owned test temp that policy prevented removing.
