# Phase 7B Locked Runtime Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure backend import performs no local-configuration I/O and every backend lifespan loads one immutable configuration snapshot only after acquiring the shared product-database lifecycle lock.

**Architecture:** `backend.config` keeps pure parsers and explicit administrative loaders, and adds one frozen runtime snapshot plus a single active-snapshot registry. `backend.main.lifespan` acquires the existing lifecycle lock, loads and installs the snapshot, passes or resolves that exact authority in every backend consumer, clears it after complete synchronous or deferred shutdown, and releases the lock last. No launcher, route, DTO, schema, Provider, or cutover public contract changes.

**Tech Stack:** Python 3.12, FastAPI lifespan, `asyncio`, `aiomysql`, pytest, Windows named-mutex/POSIX advisory-lock lifecycle service.

---

## File map

- Modify `backend/config.py`: import-time-I/O-free parsers, frozen `RuntimeConfiguration`, exact install/current/clear registry.
- Modify `backend/database.py`: construct the pool only from the installed snapshot.
- Modify `backend/main.py`: lock-before-load/install and clear-before-physical-release, including deferred shutdown transfer.
- Modify `backend/runtime/market_scheduler.py`: accept the installed scheduler flag instead of an imported constant.
- Modify `backend/domain/routers/application_settings.py`: resolve managed-root readiness from the installed snapshot.
- Modify `backend/services/creative_assets.py`: construct request services from the installed corpus roots.
- Modify `backend/scripts/verify_corpus_import.py`: replace the removed imported snapshot with an explicit command-time load.
- Modify focused tests under `backend/tests/unit/` for configuration, database, scheduler, application settings, creative assets, lifespan, and the verification script.
- Modify `backend/tests/unit/test_prepare_product_database_command.py`: locally close only the pytest-asyncio clean loop displaced by synchronous `main()` tests.
- Modify `backend/tests/unit/test_cutover_product_database_command.py`: apply the same local loop-ownership boundary to synchronous cutover `main()` tests.

### Task 1: Add the closed runtime-configuration authority

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/tests/unit/test_config.py`

- [ ] **Step 1: Write import and authority RED tests**

Add tests that start a clean Python subprocess, replace `Path.read_text` with a forbidden callback,
and import `backend.config`; the import must perform zero reads. Add exact-type tests for a frozen
snapshot containing MySQL items, both optional roots, and scheduler state. Add registry tests for:
no active snapshot, first install, duplicate install rejection, identity-exact clear, wrong-snapshot
clear rejection, access after clear, and ordinary/flow-control metadata safety.

```python
def test_runtime_configuration_registry_is_identity_bound(runtime_configuration):
    config.install_runtime_configuration(runtime_configuration)
    assert config.current_runtime_configuration() is runtime_configuration
    with pytest.raises(config.RuntimeConfigurationError):
        config.clear_runtime_configuration(dataclasses.replace(runtime_configuration))
    assert config.current_runtime_configuration() is runtime_configuration
    config.clear_runtime_configuration(runtime_configuration)
```

- [ ] **Step 2: Run the RED tests**

Run:

```powershell
python -m pytest backend/tests/unit/test_config.py -q -p no:cacheprovider --basetemp=tmp/pytest-phase7b-runtime-config-red
```

Expected: failures show import-time reads and missing runtime snapshot APIs.

- [ ] **Step 3: Implement the frozen snapshot and I/O-free import**

Use exact built-in containers so callers cannot mutate captured authority:

```python
@dataclass(frozen=True)
class RuntimeConfiguration:
    mysql_items: tuple[tuple[str, object], ...]
    corpus_root: Path | None
    managed_corpus_root: Path | None
    market_scheduler_enabled: bool

    def mysql_pool_options(self) -> dict[str, object]:
        return dict(self.mysql_items)


_active_runtime_configuration: RuntimeConfiguration | None = None


def load_runtime_configuration(
    *, environment: Mapping[str, str] | None = None,
    config_path: Path = LOCAL_CONFIG_PATH,
) -> RuntimeConfiguration:
    document = _read_local_document(Path(config_path))
    return _runtime_configuration_from_document(
        document=document,
        environment=os.environ if environment is None else environment,
    )


def install_runtime_configuration(snapshot: RuntimeConfiguration) -> None:
    global _active_runtime_configuration
    if type(snapshot) is not RuntimeConfiguration or _active_runtime_configuration is not None:
        raise RuntimeConfigurationError("runtime configuration installation failed") from None
    _active_runtime_configuration = snapshot


def current_runtime_configuration() -> RuntimeConfiguration:
    if _active_runtime_configuration is None:
        raise RuntimeConfigurationError("runtime configuration is unavailable") from None
    return _active_runtime_configuration


def clear_runtime_configuration(snapshot: RuntimeConfiguration) -> None:
    global _active_runtime_configuration
    if _active_runtime_configuration is not snapshot:
        raise RuntimeConfigurationError("runtime configuration cleanup failed") from None
    _active_runtime_configuration = None
```

Refactor `load_mysql_config`, `load_corpus_root`, and `load_managed_corpus_root` to share private
document-to-value helpers. `load_runtime_configuration` calls `_read_local_document` once. Remove
all four eager bottom-of-module assignments. Explicit command helpers load when invoked, never at
import.

- [ ] **Step 4: Run GREEN and compatibility tests**

Run the Task 1 command again, then:

```powershell
python -m pytest backend/tests/unit/test_initialize_database.py backend/tests/unit/test_database_transaction.py -q -p no:cacheprovider --basetemp=tmp/pytest-phase7b-runtime-config-compat
```

Expected: all pass; subprocess import reports zero reads.

- [ ] **Step 5: Commit Task 1**

```powershell
git add backend/config.py backend/tests/unit/test_config.py backend/tests/unit/test_initialize_database.py backend/tests/unit/test_database_transaction.py
git commit -m "refactor: add locked runtime configuration authority"
```

Only add test files if they required compatibility changes.

### Task 2: Migrate every backend consumer to the installed snapshot

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/runtime/market_scheduler.py`
- Modify: `backend/domain/routers/application_settings.py`
- Modify: `backend/services/creative_assets.py`
- Modify: `backend/scripts/verify_corpus_import.py`
- Modify: corresponding focused unit tests

- [ ] **Step 1: Write consumer RED tests**

Prohibit the removed configuration constants and assert each consumer sees the same installed
snapshot. The database test must mutate the file/environment after installation and prove
`aiomysql.create_pool` still receives only `snapshot.mysql_pool_options()`. Scheduler construction
must receive the snapshot boolean explicitly. Corpus readiness and creative-asset factories must use
the snapshot roots. The standalone verification command must call `load_mysql_config` at command
execution, not import.

```python
async def test_pool_uses_installed_snapshot_not_later_environment(monkeypatch, runtime_configuration):
    config.install_runtime_configuration(runtime_configuration)
    monkeypatch.setenv("MYSQL_DB", "later-value-must-not-win")
    await database.get_pool()
    assert create_pool_calls == [runtime_configuration.mysql_pool_options()]
```

- [ ] **Step 2: Run the RED consumer set**

Run:

```powershell
python -m pytest backend/tests/unit/test_database_transaction.py backend/tests/unit/test_market_scheduler.py backend/tests/api/test_application_settings_routes.py backend/tests/api/test_asset_routes.py backend/tests/unit/test_verify_corpus_import.py -q -p no:cacheprovider --basetemp=tmp/pytest-phase7b-runtime-consumers-red
```

Expected: failures identify imported globals or absent explicit runtime authority.

- [ ] **Step 3: Implement explicit snapshot consumption**

Use these boundaries:

```diff
# backend/database.py
snapshot = current_runtime_configuration()
_pool = await aiomysql.create_pool(**snapshot.mysql_pool_options())

# backend/runtime/market_scheduler.py exact replacements
-def build_market_scheduler_runtime() -> MarketSchedulerRuntime:
+def build_market_scheduler_runtime(*, enabled: bool) -> MarketSchedulerRuntime:
-        enabled=MARKET_SCHEDULER_ENABLED,
+        enabled=enabled,

# backend/domain/routers/application_settings.py
def _corpus_store_ready() -> bool:
    root = current_runtime_configuration().managed_corpus_root
    return root is not None and root.exists() and root.is_dir()

# backend/services/creative_assets.py
snapshot = current_runtime_configuration()
corpus_root = snapshot.corpus_root
managed_root = snapshot.managed_corpus_root

# Replace the existing constructor arguments exactly:
# corpus_root=CORPUS_ROOT       -> corpus_root=corpus_root
# managed_root=MANAGED_CORPUS_ROOT -> managed_root=managed_root
```

Do not add a lazy proxy, per-request file read, launcher override, or fallback to a removed global.

- [ ] **Step 4: Run GREEN and literal-boundary checks**

Run the Task 2 command again, including project-import, project-package, and corpus route tests. The
isolated Task 2 commit may explicitly deselect only tests that import the still-unmigrated
`backend.main`; Task 3 must rerun the complete consumer command with zero deselection. Then search
production Python files and require zero imports of `MYSQL_CONFIG`, `CORPUS_ROOT`,
`MANAGED_CORPUS_ROOT`, or `MARKET_SCHEDULER_ENABLED` as values.

- [ ] **Step 5: Commit Task 2**

```powershell
git add backend/database.py backend/runtime/market_scheduler.py backend/domain/routers/application_settings.py backend/services/creative_assets.py backend/scripts/verify_corpus_import.py backend/tests/unit/test_database_transaction.py backend/tests/unit/test_market_scheduler.py backend/tests/unit/test_verify_corpus_import.py backend/tests/api/test_application_settings_routes.py backend/tests/api/test_asset_routes.py backend/tests/api/test_corpus_routes.py
git commit -m "refactor: consume one backend configuration snapshot"
```

Before committing, inspect `git diff --cached --name-only` and unstage every unrelated test file.

### Task 3: Bind snapshot lifetime to the backend lifecycle lock

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/unit/test_main_lifespan.py`

- [ ] **Step 1: Write lifecycle and race RED tests**

Add exact event-ledger tests for:

```text
lock:enter, config:load, config:install, database:start, application:stop,
database:close, config:clear, lock:release, lock:close
```

Cover startup failure, body failure, direct shutdown, draft-only transfer, market-only transfer,
combined transfer, transfer failure, external completion cancellation, load failure, install failure,
clear ordinary/CancelledError/KeyboardInterrupt/SystemExit, and release/close failures. Every active
snapshot must clear exactly once before physical release. No application action may occur if load or
install fails.

Add a deterministic import/cutover race: module import executes while a fake cutover owns the lock
and records zero configuration reads; after the cutover publishes and releases, lifespan acquisition
loads only the new database name.

- [ ] **Step 2: Run the RED lifespan set**

```powershell
python -m pytest backend/tests/unit/test_main_lifespan.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-runtime-lifespan-red
```

Expected: load occurs before lock or no snapshot lifetime API is called.

- [ ] **Step 3: Implement lock-owned snapshot lifetime**

Immediately after `lock_context.__enter__()`:

```python
runtime_configuration = load_runtime_configuration(config_path=LOCAL_CONFIG_PATH)
install_runtime_configuration(runtime_configuration)
runtime_configuration_owned = True
```

Pass `runtime_configuration` into `_application_lifespan` for startup-only decisions. For direct
shutdown, call `clear_runtime_configuration(runtime_configuration)` before `lock_context.__exit__`.
For a deferred draft/market transfer, create one private exact `asyncio.Task` that awaits the trusted
transfer and clears the snapshot in `finally`; pass that task to `lock_lease.defer_until`. Publish
only the lease completion already required by the lifecycle design, never the private clearing task.

```python
async def _complete_runtime_configuration(transfer, snapshot):
    try:
        return await asyncio.shield(transfer)
    finally:
        clear_runtime_configuration(snapshot)
```

Immediately after creating the private task, call `lock_lease.defer_until(runtime_transfer)`
synchronously, before any `await` or externally cancellable handshake. Once deferral succeeds, lock
and snapshot ownership have transferred to that private task. Failure to publish the returned public
completion into `app.state` must not cancel or await the private task and must not clear the snapshot:
the immediate publication error is reported while the already-registered deferral continues to wait
for the real shutdown transfer, then clears the snapshot and physically releases the lock exactly
once. Only a failure before successful deferral remains eligible for synchronous snapshot cleanup.
Preserve application-primary-before-config-clear-before-lock-cleanup ordering. Never read
`error.__traceback__`, dynamic `__class__`, or arbitrary group descriptors.

- [ ] **Step 4: Run GREEN and downstream lifecycle tests**

```powershell
python -m pytest backend/tests/unit/test_main_lifespan.py backend/tests/unit/test_product_database_lifecycle_lock.py backend/tests/unit/test_cutover_product_database_command.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-runtime-lifespan-green
```

Expected: all pass, one host-only POSIX symlink test may skip on Windows, no warnings.

- [ ] **Step 5: Commit Task 3**

```powershell
git add backend/main.py backend/tests/unit/test_main_lifespan.py
git commit -m "fix: load backend configuration under lifecycle lock"
```

### Task 4: Close the pytest-asyncio displaced-loop warning locally

**Files:**
- Modify: `backend/tests/unit/test_prepare_product_database_command.py`
- Modify: `backend/tests/unit/test_cutover_product_database_command.py`

- [ ] **Step 1: Preserve the two-test RED reproducer**

Run the exact async flow-matrix case immediately before
`test_main_prints_only_fixed_failure`, with a call-phase `gc.collect()` plugin and `-W error`.
Expected before the fix: one `PytestUnraisableExceptionWarning` whose tracemalloc allocation points
to `pytest_asyncio.plugin._provide_clean_event_loop`.

- [ ] **Step 2: Add a local ownership fixture**

Apply it only to synchronous tests that call either command's `main()`:

```python
@contextmanager
def _owned_sync_main_event_loop():
    policy = asyncio.get_event_loop_policy()
    local = getattr(policy, "_local")
    borrowed = getattr(local, "_loop", None)
    owned = policy.new_event_loop()
    policy.set_event_loop(owned)
    try:
        yield
    finally:
        if not owned.is_closed():
            owned.close()
        policy.set_event_loop(
            borrowed if borrowed is not None and not borrowed.is_closed() else None
        )
```

The helper borrows any loop that was already installed without acquiring close authority, creates
and installs its own loop for the synchronous `main()` call, closes only that owned loop after
`asyncio.run` displaces it, and restores the still-open borrowed identity or exact no-loop state.
Fresh-policy normal and exceptional exits, an unrelated borrowed loop, and explicit no-loop state
must all be regression tested. Do not change production `main`, install an autouse/global fixture,
or close a loop used by an async test.

- [ ] **Step 3: Run the minimal reproducer and focused command suite**

Expected: the reproducer passes with no ResourceWarning; both complete command-test files pass with
`-W error`; the combined main-lifespan, lifecycle-lock, and cutover command gate has no unraisable
socket warning.

- [ ] **Step 4: Commit Task 4**

```powershell
git add backend/tests/unit/test_prepare_product_database_command.py backend/tests/unit/test_cutover_product_database_command.py
git commit -m "test: close displaced pytest event loop"
```

### Task 5: Final verification and review closure

**Files:**
- Modify only if a fresh review identifies a concrete defect in the approved scope.

- [ ] **Step 1: Run the focused Python and Node gates**

Run one sequential Python invocation covering the eight Phase 7B lifecycle files with `-W error`,
then `node --check` for both Phase 7B runner files and the 39-test Node contract. Expected: zero
failures/errors/warnings; only the documented host-only POSIX skip is allowed.

- [ ] **Step 2: Run the full unit/API gate and build**

Run `npm test` and `npm run build` sequentially. Record Python, scripts Node, frontend Node, skipped,
module, warning, and exit counts exactly. Do not run the formal browser yet.

- [ ] **Step 3: Run the disposable MySQL 8.4 gate**

Use only the already verified client paths under `D:\Software\MySQL Server 8.4\bin` and explicit
`TEST_MYSQL_*` authority for `127.0.0.1:3307`. Run the seven-test Phase 7B disposable suite once.
Require created/cleaned equality and remaining zero. Never enumerate, read, write, or drop an
existing database.

- [ ] **Step 4: Review and resource ledger**

Run independent spec and quality reviews. Require active Critical/Important/Minor `0/0/0`. Classify
the exact known `tmp/` test roots by owner and delete only exact validated task-owned roots when the
execution policy permits; otherwise report them without bypassing policy. Require tracked/index
clean and disclose any remaining untracked resources.

- [ ] **Step 5: Update the parent Phase 7B plan evidence**

Mark only gates actually proven by the final tree. Do not claim the formal browser, Stage A real
preparation, Stage B config write, Provider call, or old-database retirement unless separately
authorized and executed.
