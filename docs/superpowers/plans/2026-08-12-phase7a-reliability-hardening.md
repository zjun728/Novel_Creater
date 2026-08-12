# Phase 7A Reliability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the nine reliability items explicitly deferred by Phase 6 without changing any public route, DTO, schema, UI state, Provider behavior, or accepted product boundary.

**Architecture:** Implement five narrow fixes in their existing owner modules: deadline-based corpus-claim waiting, backend cleanup precedence and safe warnings, frontend state/download cleanup, and Phase 6A runner-wide observation and cleanup assurance. Each slice has its own local seam and tests; no shared retry, logging, or reliability framework is introduced.

**Tech Stack:** Python 3.12, asyncio, pytest, aiomysql/disposable MySQL, JavaScript ES modules, Vue 3, Node test runner, Playwright, Vite, PowerShell-hosted npm scripts.

---

## Scope guard

- Implement only `docs/superpowers/specs/2026-08-12-phase7a-reliability-hardening-design.md`.
- Preserve every public HTTP route, request/response body, error code, UI label, blocking phase, navigation rule, schema table, and column.
- Add no shared retry/deadline/logging framework and no new production module.
- Keep Provider calls, outbound calls, and product-database reads/writes at zero. Tests may use disposable `novel_creator_test_%` databases, owned local files, the owned deny proxy, and owned local browsers.
- Stop on a newly discovered concern unless it is the direct first cause preventing one of the nine approved items from closing.
- Run focused tests in Tasks 1–5. Run the branch-wide matrix once, serially, in Task 6.

## File map

| Responsibility | Production files | Test files |
| --- | --- | --- |
| Digest-claim deadline | `backend/services/project_imports.py` | `backend/tests/unit/test_project_import_staging.py` |
| Snapshot connection finalization | `backend/repositories/project_packages.py` | `backend/tests/unit/test_project_package_repository.py` |
| Package temp cleanup and stale warnings | `backend/services/project_packages.py` | `backend/tests/unit/test_project_package_service.py`, `backend/tests/unit/test_project_package_temp_cleanup.py`, `backend/tests/unit/test_main_lifespan.py` |
| Frontend download hardening | `frontend/src/api/db/client.js`, `frontend/src/application/downloads/novelDownloadController.js`, `frontend/src/components/projects/ProjectBackupPanel.vue` | `frontend/tests/unit/projectBackupApi.test.mjs`, `frontend/tests/unit/novelDownloadController.test.mjs`, `frontend/tests/unit/projectBackupPanel.test.mjs` |
| Phase 6A runner assurance | `backend/scripts/prepare_phase6a_browser_db.py`, `frontend/e2e/run-phase6a.mjs`, `frontend/e2e/playwright.phase6a.config.mjs`, `frontend/e2e/phase6a/finalized-novel-download.spec.mjs`, `frontend/e2e/phase6a/runtime-observer.mjs` | `scripts/tests/phase6aBrowserContract.test.mjs`, `frontend/e2e/phase6a/runtime-observer.test.mjs` |
| Acceptance evidence | `docs/acceptance/2026-08-12-phase-7a-reliability-hardening.md` | existing full unit/integration/build/browser commands |

## Fixed safe event names

Use these exact constant log messages with no formatting arguments and never attach `exc_info`:

```text
project_package_repository_cleanup_failed
project_package_service_cleanup_failed
project_package_stale_candidate_cleanup_failed
project_package_stale_scan_failed
```

All backend package warnings use `logging.getLogger("backend.project_packages")` so the existing lifespan log boundary remains stable.

### Task 1: Replace import claim event-loop yields with a monotonic deadline

**Files:**
- Modify: `backend/services/project_imports.py:5-15,43-47,144-151,239-263`
- Test: `backend/tests/unit/test_project_import_staging.py:115-196`

- [ ] **Step 1: Add a fake-clock RED test for the exact backoff and deadline**

Add a deterministic seam fixture and test to `test_project_import_staging.py`:

```python
class _ClaimClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.delays: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.now += delay


@pytest.mark.asyncio
async def test_claim_wait_uses_capped_backoff_and_exact_monotonic_deadline(
    tmp_path: Path, monkeypatch,
) -> None:
    clock = _ClaimClock()
    staging = ProjectImportStaging(
        tmp_path, "10000000-0000-4000-8000-000000000001", tmp_path / "stage", (),
        _monotonic=clock.monotonic,
        _sleep=clock.sleep,
    )
    item = StagedBlob("7" * 64, 7, managed_corpus_storage_key("7" * 64), False)
    monkeypatch.setattr(project_imports.os, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(FileExistsError()))

    with pytest.raises(ProjectImportCommandStateConflict):
        await staging._acquire_claim(item)

    assert clock.now == pytest.approx(30.0)
    assert clock.delays[:6] == pytest.approx([0.01, 0.02, 0.04, 0.08, 0.16, 0.25])
    assert max(clock.delays) == pytest.approx(0.25)
    assert sum(clock.delays) == pytest.approx(30.0)
```

- [ ] **Step 2: Run the deadline test and confirm RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_project_import_staging.py::test_claim_wait_uses_capped_backoff_and_exact_monotonic_deadline -q --basetemp=.pytest-phase7a-claim-red
```

Expected: FAIL because `ProjectImportStaging` has no `_monotonic` or `_sleep` constructor fields and still uses `CLAIM_ATTEMPTS` plus `asyncio.sleep(0)`.

- [ ] **Step 3: Add delayed-winner and cancellation RED tests**

Extend the existing same-digest fixture so the first command blocks inside an async `persist_manifest`, the second command starts while the claim exists, then the first is released. Assert both `promote()` calls succeed, exactly one staging instance owns the installed digest, the destination bytes/hash are exact, and the claim directory is empty. Add this cancellation test:

```python
@pytest.mark.asyncio
async def test_claim_wait_propagates_cancellation_without_claim_ownership(
    tmp_path: Path, monkeypatch,
) -> None:
    async def cancel_sleep(_delay: float) -> None:
        raise asyncio.CancelledError

    staging = ProjectImportStaging(
        tmp_path, "10000000-0000-4000-8000-000000000002", tmp_path / "stage", (),
        _sleep=cancel_sleep,
    )
    item = StagedBlob("8" * 64, 8, managed_corpus_storage_key("8" * 64), False)
    monkeypatch.setattr(project_imports.os, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(FileExistsError()))

    with pytest.raises(asyncio.CancelledError):
        await staging._acquire_claim(item)
    assert not staging._installed_hashes
```

Run both new tests and expect the delayed-winner test to fail with `ProjectImportCommandStateConflict` and the cancellation test to expose the missing sleeper seam.

- [ ] **Step 4: Implement the local monotonic deadline**

In `backend/services/project_imports.py`, import `Awaitable`, replace `CLAIM_ATTEMPTS`, and add narrow dataclass seams:

```python
from collections.abc import Awaitable, Callable, Mapping

CLAIM_WAIT_SECONDS = 30.0
CLAIM_INITIAL_DELAY_SECONDS = 0.01
CLAIM_MAX_DELAY_SECONDS = 0.25

@dataclass(slots=True)
class ProjectImportStaging:
    managed_root: Path
    command_id: str
    root: Path
    blobs: tuple[StagedBlob, ...]
    _cleaned: bool = False
    _installed_hashes: set[str] = field(default_factory=set, init=False)
    _monotonic: Callable[[], float] = field(default=time.monotonic, repr=False)
    _sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep, repr=False)
```

Replace the bounded-attempt loop in `_acquire_claim` with:

```python
deadline = self._monotonic() + CLAIM_WAIT_SECONDS
delay = CLAIM_INITIAL_DELAY_SECONDS
while True:
    created = False
    try:
        descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            output.write(self.command_id)
        apply_private_permissions(claim, is_directory=False)
        return claim
    except FileExistsError:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise ProjectImportCommandStateConflict() from None
        await self._sleep(min(delay, remaining))
        delay = min(delay * 2, CLAIM_MAX_DELAY_SECONDS)
    except BaseException:
        if created:
            try:
                if claim.is_file() and not claim.is_symlink() and claim.read_text("ascii") == self.command_id:
                    claim.unlink()
            except BaseException:
                pass
        raise
```

Do not catch cancellation around `_sleep`, and do not alter `promote()` destination verification or ownership bookkeeping.

- [ ] **Step 5: Run focused claim tests GREEN**

Run:

```powershell
python -m pytest backend/tests/unit/test_project_import_staging.py -q --basetemp=.pytest-phase7a-claim-green
```

Expected: all tests pass; the delayed persistence case takes no wall-clock 30-second wait; all command roots and claim entries are removed by their existing cleanup assertions.

- [ ] **Step 6: Commit the claim slice**

```powershell
git add backend/services/project_imports.py backend/tests/unit/test_project_import_staging.py
git commit -m "fix: wait safely for import blob claims"
```

### Task 2: Preserve project-package repository primary errors and always release

**Files:**
- Modify: `backend/repositories/project_packages.py:1-20,1782-1805,2492-2500`
- Test: `backend/tests/unit/test_project_package_repository.py:624-670,670-696`

- [ ] **Step 1: Write the cleanup precedence matrix RED tests**

Add `_CleanupSession` and `_CleanupPool` test doubles that independently raise fixed sentinel exceptions from `rollback()` and `release()`. Cover these cases:

```python
@pytest.mark.parametrize("rollback_fails,release_fails", ((True, False), (False, True), (True, True)))
@pytest.mark.asyncio
async def test_snapshot_primary_error_survives_cleanup_failures_and_release_is_attempted(
    rollback_fails: bool, release_fails: bool, caplog,
) -> None:
    primary = asyncio.CancelledError()
    raw = _CleanupSession(rollback_fails=rollback_fails)
    pool = _CleanupPool(raw, release_fails=release_fails)
    with caplog.at_level("WARNING", logger="backend.project_packages"):
        with pytest.raises(asyncio.CancelledError) as captured:
            try:
                raise primary
            finally:
                await project_packages._finalize_snapshot_connection(
                    pool, raw, primary_active=True,
                )
    assert captured.value is primary
    assert pool.release_calls == 1
    assert caplog.messages == ["project_package_repository_cleanup_failed"]
```

Also test `primary_active=False`: rollback-only, release-only, and both failures each raise `ProjectPackageInvalid` with the existing fixed text/cause policy; successful cleanup returns normally. Assert the warning record has `args == ()` and does not contain either cleanup sentinel.

- [ ] **Step 2: Run the matrix and confirm RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_project_package_repository.py -q -k "cleanup_failures or cleanup_precedence" --basetemp=.pytest-phase7a-repository-red
```

Expected: FAIL because rollback currently prevents release and no cleanup-precedence helper exists.

- [ ] **Step 3: Implement nested finalization with fixed warning output**

Add `import logging` and `import sys`, define `_logger = logging.getLogger("backend.project_packages")`, and add this module-local helper immediately before `ProjectPackageRepository`:

```python
async def _finalize_snapshot_connection(pool, raw, *, primary_active: bool) -> None:
    cleanup_failed = False
    try:
        rollback = getattr(raw, "rollback", None)
        if rollback is not None:
            await rollback()
    except BaseException:
        cleanup_failed = True
    finally:
        try:
            pool.release(raw)
        except BaseException:
            cleanup_failed = True
    if cleanup_failed:
        if primary_active:
            _logger.warning("project_package_repository_cleanup_failed")
            return
        raise _invalid() from None
```

Replace the old `finally` block with:

```python
finally:
    await _finalize_snapshot_connection(
        self._pool,
        raw,
        primary_active=sys.exception() is not None,
    )
```

This intentionally treats a cleanup failure after a successful return as a fixed package error, but never replaces an active business exception or `CancelledError`.

- [ ] **Step 4: Run repository tests GREEN**

Run:

```powershell
python -m pytest backend/tests/unit/test_project_package_repository.py -q --basetemp=.pytest-phase7a-repository-green
```

Expected: all repository tests pass, every matrix case records one release attempt, and log checks expose only the fixed event.

- [ ] **Step 5: Commit the repository slice**

```powershell
git add backend/repositories/project_packages.py backend/tests/unit/test_project_package_repository.py
git commit -m "fix: preserve project package cleanup precedence"
```

### Task 3: Retry service-owned temp cleanup and make stale failures observable

**Files:**
- Modify: `backend/services/project_packages.py:1-15,44-50,138-172,351-404`
- Test: `backend/tests/unit/test_project_package_service.py:321-364`
- Test: `backend/tests/unit/test_project_package_temp_cleanup.py:39-76`
- Test: `backend/tests/unit/test_main_lifespan.py:201-281`

- [ ] **Step 1: Write service-failure cleanup RED tests**

Monkeypatch `ProjectPackageTempOwner.cleanup` so it fails once and then delegates to the real method. Cross this with a zip `RuntimeError` and `asyncio.CancelledError`; assert the original object is raised, cleanup is attempted twice, and no `TEMP_PREFIX` root remains. Add a permanent-failure case:

```python
@pytest.mark.asyncio
async def test_permanent_temp_cleanup_failure_keeps_primary_and_logs_one_fixed_warning(
    tmp_path: Path, monkeypatch, caplog,
) -> None:
    primary = RuntimeError("PRIMARY_SENTINEL")
    cleanup_secret = "CLEANUP_PATH_SECRET_SENTINEL"
    attempts = 0

    def fail_zip(*_args, **_kwargs):
        raise primary

    def fail_cleanup(_owner):
        nonlocal attempts
        attempts += 1
        raise RuntimeError(cleanup_secret)

    monkeypatch.setattr(ProjectPackageTempOwner, "cleanup", fail_cleanup)
    service = _service(tmp_path, _snapshot(), zip_writer=fail_zip)
    with caplog.at_level("WARNING", logger="backend.project_packages"):
        with pytest.raises(RuntimeError) as captured:
            await service.create_backup("project", 0)
    assert captured.value is primary
    assert attempts == 2
    assert caplog.messages == ["project_package_service_cleanup_failed"]
    assert cleanup_secret not in caplog.text
```

- [ ] **Step 2: Write stale scan warning RED tests**

Create three stale owned-prefix directories. Monkeypatch `shutil.rmtree` to fail for the first candidate and succeed for the next two. Assert `examined == 3`, the latter two are deleted, the first remains, and exactly one `project_package_stale_candidate_cleanup_failed` warning with `record.args == ()` is emitted. Separately monkeypatch `Path.iterdir` to raise a secret-bearing error and assert return `0`, one `project_package_stale_scan_failed` warning, and no secret/path text.

Keep the existing lifespan test that monkeypatches the helper itself to raise; it proves the outer startup boundary remains non-blocking and uses `project_package_stale_cleanup_failed`.

- [ ] **Step 3: Run new cleanup tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_project_package_service.py backend/tests/unit/test_project_package_temp_cleanup.py backend/tests/unit/test_main_lifespan.py -q -k "cleanup_failure or stale" --basetemp=.pytest-phase7a-package-cleanup-red
```

Expected: FAIL because service cleanup is one-shot and stale cleanup currently swallows both failure classes.

- [ ] **Step 4: Implement the local two-attempt failure-path helper**

Add `import logging`, `_logger = logging.getLogger("backend.project_packages")`, and:

```python
def _cleanup_owned_temp_after_failure(owner: ProjectPackageTempOwner) -> None:
    for attempt in range(2):
        try:
            owner.cleanup()
            return
        except BaseException:
            if attempt == 1:
                _logger.warning("project_package_service_cleanup_failed")
```

Change only the service-owned failure path:

```python
except BaseException:
    _cleanup_owned_temp_after_failure(owner)
    raise
```

Do not use this helper after response handoff; the router wrapper remains the sole owner there.

- [ ] **Step 5: Emit fixed stale candidate and scan warnings**

Change the two existing swallowed exception sites to:

```python
except (OSError, RuntimeError, ValueError):
    _logger.warning("project_package_stale_candidate_cleanup_failed")
    continue
```

and:

```python
except (OSError, RuntimeError, TypeError, ValueError):
    _logger.warning("project_package_stale_scan_failed")
    return 0
```

Do not pass the exception, path, candidate, or any formatting argument to either warning.

- [ ] **Step 6: Run the complete package cleanup/lifespan focus GREEN**

Run:

```powershell
python -m pytest backend/tests/unit/test_project_package_service.py backend/tests/unit/test_project_package_temp_cleanup.py backend/tests/unit/test_main_lifespan.py -q --basetemp=.pytest-phase7a-package-cleanup-green
```

Expected: all tests pass; first-attempt cleanup failures recover; permanent failures preserve the primary exception; candidate scanning stays capped at 32.

- [ ] **Step 7: Commit the service cleanup slice**

```powershell
git add backend/services/project_packages.py backend/tests/unit/test_project_package_service.py backend/tests/unit/test_project_package_temp_cleanup.py backend/tests/unit/test_main_lifespan.py
git commit -m "fix: harden project package temporary cleanup"
```

### Task 4: Harden frontend download state, timeout, and anchor cleanup

**Files:**
- Modify: `frontend/src/application/downloads/novelDownloadController.js:107-172`
- Modify: `frontend/src/api/db/client.js:1-15,2049-2061`
- Modify: `frontend/src/components/projects/ProjectBackupPanel.vue:16-25`
- Test: `frontend/tests/unit/novelDownloadController.test.mjs:114-180`
- Test: `frontend/tests/unit/projectBackupApi.test.mjs:111-179`
- Test: `frontend/tests/unit/projectBackupPanel.test.mjs:171-245`

- [ ] **Step 1: Write controller RED tests**

Add one test whose `operationStore.finish` throws only on its first invocation. The first download must reject with that exact store error, expose `下载失败，请重试。`, and end with `busy.value === false`; a second call must reach the API, proving `inFlight` was cleared. Extend the option-disposal test to assert `loading.value === false` immediately after `dispose()` and that the late promise changes neither `options` nor `error`.

- [ ] **Step 2: Write backup timeout and anchor RED tests**

Change the timeout spy expectation from `30_000` to `1_200_000` and retain assertions for fixed `request_timeout`, cleared timer, and removed external abort listener. In the panel test, make the created anchor's `click()` throw a sentinel; assert the action rejects, that exact anchor has `removed === true`, the controller's existing revoke spy receives the URL once, and the button becomes usable again.

- [ ] **Step 3: Run frontend focus and confirm RED**

Run:

```powershell
node --test frontend/tests/unit/novelDownloadController.test.mjs frontend/tests/unit/projectBackupApi.test.mjs frontend/tests/unit/projectBackupPanel.test.mjs
```

Expected: the finish-throw test leaves `busy` true, dispose leaves `loading` true, the timeout is 30,000ms, and a throwing click leaves the anchor attached.

- [ ] **Step 4: Implement controller-owned cleanup precedence**

Replace the inner download-finalization block with:

```javascript
} finally {
  try {
    if (objectUrl !== null) revokeObjectURL(objectUrl)
  } finally {
    try {
      operationStore.finish(operationId)
    } catch (failure) {
      if (active()) error.value = '下载失败，请重试。'
      throw failure
    } finally {
      if (inFlight?.token === token) {
        inFlight = null
        busyState.value = false
      }
    }
  }
}
```

In `dispose()` clear options loading immediately before aborting:

```javascript
disposed = true
loadGeneration += 1
loadingState.value = false
inFlight?.abortController.abort()
busyState.value = false
```

- [ ] **Step 5: Implement the backup-specific timeout and anchor `finally`**

Add beside the other request constants:

```javascript
const PROJECT_BACKUP_TIMEOUT = 1_200_000
```

Pass only this call's timeout:

```javascript
signal: options?.signal,
timeoutMs: PROJECT_BACKUP_TIMEOUT,
includePackageSha256: true,
```

Replace the anchor click/remove sequence with:

```javascript
document.body.append(link)
try {
  link.click()
} finally {
  link.remove()
}
```

Do not move URL revocation into the component.

- [ ] **Step 6: Run frontend focus GREEN and build the touched app**

Run:

```powershell
node --test frontend/tests/unit/novelDownloadController.test.mjs frontend/tests/unit/projectBackupApi.test.mjs frontend/tests/unit/projectBackupPanel.test.mjs
npm --prefix frontend run build
```

Expected: focused tests pass; Vite build exits 0; other API calls retain their existing default timeouts.

- [ ] **Step 7: Commit the frontend slice**

```powershell
git add frontend/src/api/db/client.js frontend/src/application/downloads/novelDownloadController.js frontend/src/components/projects/ProjectBackupPanel.vue frontend/tests/unit/projectBackupApi.test.mjs frontend/tests/unit/novelDownloadController.test.mjs frontend/tests/unit/projectBackupPanel.test.mjs
git commit -m "fix: harden project download cleanup and timeout"
```

### Task 5: Harden the Phase 6A runner boundary

**Files:**
- Modify: `backend/scripts/prepare_phase6a_browser_db.py:9-28,53-105`
- Modify: `frontend/e2e/run-phase6a.mjs:20-24,60-110,113-159`
- Modify: `frontend/e2e/playwright.phase6a.config.mjs:1-18`
- Modify: `frontend/e2e/phase6a/finalized-novel-download.spec.mjs:5-56,89-91`
- Modify: `frontend/e2e/phase6a/runtime-observer.mjs:1-29`
- Create: `frontend/e2e/phase6a/runtime-observer.test.mjs`
- Modify: `scripts/tests/phase6aBrowserContract.test.mjs:13-83`

- [ ] **Step 1: Add source-contract RED assertions for the full runner boundary**

Extend `phase6aBrowserContract.test.mjs` to require:

```javascript
const fixture = source('backend/scripts/prepare_phase6a_browser_db.py')
assert.doesNotMatch(fixture, /from backend\.tests|import backend\.tests/u)
assert.doesNotMatch(fixture, /from backend\.routers|finalization\._(?:service|atomic_service)/u)
assert.doesNotMatch(fixture, /hashlib|\bsha256\b|canonical_hash|build_projection_bundle/u)

const spec = source('frontend/e2e/phase6a/finalized-novel-download.spec.mjs')
assert.match(spec, /observeRuntime\(context,/u)
assert.ok(spec.indexOf('observeRuntime(context') < spec.indexOf('page.goto('))

const observer = source('frontend/e2e/phase6a/runtime-observer.mjs')
for (const marker of ['context.on(\'page\'', "page.on('pageerror'", "page.on('request'", "page.on('requestfinished'", 'pendingRequests', 'listenerCount']) {
  assert.equal(observer.includes(marker), true, marker)
}
```

Also assert the Playwright config retains one context-wide proxy and exact owned-origin bypass, and runner safe output contains fixed cleanup category counts rather than exception strings.

- [ ] **Step 2: Add runtime-observer unit RED tests**

Create `runtime-observer.test.mjs` with small EventEmitter-based fake context/page/request/response objects. Cover:

1. an initial page and a later popup both attach all listeners;
2. an unexpected origin increments `originViolations`;
3. console error, page error, failed request, and non-2xx response each increment only a fixed counter;
4. request then requestfinished returns pending count to zero;
5. `finish()` detaches every owned listener and returns `listenerCount: 0`;
6. `assertRuntimeEvidenceHealthy` rejects every nonzero unsafe counter and never includes the raw URL/error text.

Use this exact evidence shape:

```javascript
{
  consoleErrors: 0,
  pageErrors: 0,
  requestFailures: 0,
  non2xx: 0,
  originViolations: 0,
  pendingRequests: 0,
  listenerCount: 0,
}
```

- [ ] **Step 3: Run runner contracts and confirm RED**

Run:

```powershell
node --test scripts/tests/phase6aBrowserContract.test.mjs frontend/e2e/phase6a/runtime-observer.test.mjs
```

Expected: FAIL because observation is page-local, starts mid-scenario, stores raw URL/error strings, and the fixture imports test helpers/router-private services.

- [ ] **Step 4: Replace the observer with context-owned fixed counters**

Implement `observeRuntime(context, { allowedOrigins })`. Attach each existing page, subscribe to `context.on('page', onPage)`, and for every page attach `console`, `pageerror`, `request`, `requestfinished`, `requestfailed`, and `response`. Track pending request objects in a `Set`; check origins via `new URL(request.url()).origin`; retain only integer counters. `finish()` must remove the context listener and every per-page listener before returning the frozen evidence object above.

Implement the health assertion as fixed category checks:

```javascript
export function assertRuntimeEvidenceHealthy(evidence) {
  for (const key of [
    'consoleErrors', 'pageErrors', 'requestFailures', 'non2xx',
    'originViolations', 'pendingRequests', 'listenerCount',
  ]) {
    if (!Number.isInteger(evidence?.[key]) || evidence[key] !== 0) {
      throw new Error(`phase6a-runtime-${key}-count`)
    }
  }
}
```

In the spec, receive `context` from Playwright, call `observeRuntime(context, { allowedOrigins })` before the first `page.goto`, and retain the existing final `finish()` assertion after both downloads.

- [ ] **Step 5: Remove fixture test/private-router dependencies**

In `prepare_phase6a_browser_db.py`, replace `backend.tests.*` imports and `backend.routers.finalization` with public repositories, domain DTOs, and service constructors. Use `backend.database.transaction` directly for all product services. Construct finalization dependencies explicitly:

```python
finalization_service = FinalizationService(
    transaction_factory=transaction,
    repository=FinalizationRepository(),
    quality_provider=_Quality(),
    extraction_provider=_Extraction(),
    clock=lambda: int(time.time() * 1000),
)
canon_repository = CanonRepository()
atomic_finalization_service = AtomicFinalizationService(
    transaction_factory=transaction,
    repository=FinalizationRepository(),
    planning_repository=PlanningRepository(),
    canon_committer=CanonService(
        canon_repository,
        transaction_factory=transaction,
        clock=lambda: int(time.time() * 1000),
    ),
    clock=lambda: int(time.time() * 1000),
)
```

Change `_finalize` to accept these two services and invoke only `prepare`, `confirm`, and `commit`. Build the confirmed contract/planning/outline/session authority through `ContractService`, `PlanningService`, `ChapterOutlineService`, and `ChapterSessionService`; keep fixture payloads as Pydantic/domain inputs, not copied hash or state-transition functions. Preserve the existing fixed project id, two finalized chapters, one non-final chapter, and postcondition SQL. The source contract must reject any direct `backend.tests`, `backend.routers`, private service, or hash-builder dependency.

- [ ] **Step 6: Add bounded cleanup fault injection and safe counts to the runner**

Export `cleanupRoot` with an optional tools object containing `waitForPortReleaseImpl` and `removeOwnedRootImpl`. Wrap each operation in a local two-attempt helper. A first-attempt injected failure increments one of the fixed counters `portReleaseRetries`, `rootAuditRetries`, or `rootRemovalRetries`; a second failure is wrapped with `phase6aCleanupCategory` set to the corresponding fixed category. Never put the cause text/path/port in the summary.

Extend `safeCliFailureSummary` to return only:

```javascript
{
  firstStage: 'root-cleanup',
  errorCount: 1,
  browserCause: null,
  cleanupCategoryCounts: { portRelease: 0, rootAudit: 0, rootRemoval: 1 },
}
```

The exact values vary by injected category, but the keys are closed and integer-only. Contract tests must inject one first-attempt failure followed by success and assert the owned root is removed; inject a permanent failure and assert the fixed category appears without the sentinel error/path.

- [ ] **Step 7: Run the runner contract, syntax, and fixture focus GREEN**

Run:

```powershell
node --test scripts/tests/phase6aBrowserContract.test.mjs frontend/e2e/phase6a/runtime-observer.test.mjs
node --check frontend/e2e/run-phase6a.mjs
node --check frontend/e2e/playwright.phase6a.config.mjs
node --check frontend/e2e/phase6a/finalized-novel-download.spec.mjs
node --check frontend/e2e/phase6a/runtime-observer.mjs
python -m py_compile backend/scripts/prepare_phase6a_browser_db.py
```

Expected: all Node contract tests pass and all five syntax/compile commands exit 0.

- [ ] **Step 8: Run the formal Phase 6A browser gate once**

Run:

```powershell
npm run test:browser:phase6a
```

Expected: `1/1 scenarios passed`; full-window counters are zero; disposable DB, process, ports, temp, downloads, artifacts, Vite, Provider, and outbound residue are zero. If it fails, stop, preserve the first fixed stage/category, use `systematic-debugging`, and do not blindly rerun.

- [ ] **Step 9: Commit the runner slice**

```powershell
git add backend/scripts/prepare_phase6a_browser_db.py frontend/e2e/run-phase6a.mjs frontend/e2e/playwright.phase6a.config.mjs frontend/e2e/phase6a/finalized-novel-download.spec.mjs frontend/e2e/phase6a/runtime-observer.mjs frontend/e2e/phase6a/runtime-observer.test.mjs scripts/tests/phase6aBrowserContract.test.mjs
git commit -m "test: harden phase6a browser lifecycle"
```

### Task 6: Verify, review, document, and prepare integration

**Files:**
- Create: `docs/acceptance/2026-08-12-phase-7a-reliability-hardening.md`
- Verify: every file changed by Tasks 1–5

- [ ] **Step 1: Run the focused Phase 7A gate**

Run serially with unique worktree-owned pytest roots:

```powershell
python -m pytest backend/tests/unit/test_project_import_staging.py backend/tests/unit/test_project_package_repository.py backend/tests/unit/test_project_package_service.py backend/tests/unit/test_project_package_temp_cleanup.py backend/tests/unit/test_main_lifespan.py -q --basetemp=.pytest-phase7a-focused
node --test frontend/tests/unit/novelDownloadController.test.mjs frontend/tests/unit/projectBackupApi.test.mjs frontend/tests/unit/projectBackupPanel.test.mjs scripts/tests/phase6aBrowserContract.test.mjs frontend/e2e/phase6a/runtime-observer.test.mjs
python -m py_compile backend/services/project_imports.py backend/repositories/project_packages.py backend/services/project_packages.py backend/scripts/prepare_phase6a_browser_db.py
git diff --check
```

Expected: all tests pass, compile exits 0, and diff check reports no whitespace errors. Remove only the exact `.pytest-phase7a-focused` directory after resolving and verifying it is inside this worktree.

- [ ] **Step 2: Run the full unit and integration gates once**

Run serially and do not impose a wrapper timeout shorter than the previously observed integration duration:

```powershell
npm test
npm run test:integration
```

Expected: both commands exit 0 with terminal summaries; disposable database ledger reports created equals cleaned and remaining zero. On the first observed failure, stop the matrix and diagnose that first cause before any rerun.

- [ ] **Step 3: Run build and the three accepted browser gates once each**

```powershell
npm run build
npm run test:browser:phase6a
npm run test:browser:phase6b
npm run test:browser:phase6c
```

Expected: build exits 0; each browser suite reports `1/1`; owned DB/process/port/temp/quarantine/staging/download/artifact/Vite residue is zero; Provider/outbound is zero; product DB reads/writes are `0/0`.

- [ ] **Step 4: Perform the required self-review and code review gates**

Review the final diff against every item in the design inventory. Confirm:

```text
claim deadline/backoff/cancellation: covered
repository rollback/release precedence: covered
service cleanup retry/primary preservation: covered
stale warning boundary: covered
controller finish/dispose state: covered
backup 20-minute timeout: covered
anchor finally cleanup: covered
context-wide Phase6A observation: covered
fixture public-boundary rule: covered
runner cleanup fault injection/residue: covered
public API/schema/UI change: none
```

Run a specification review and a quality review. Active Critical/Important findings must be `0/0` before continuing; deferred Minor findings must be recorded without widening Phase 7A.

- [ ] **Step 5: Write the acceptance record**

Create `docs/acceptance/2026-08-12-phase-7a-reliability-hardening.md` with:

```markdown
# Phase 7A Reliability Hardening Acceptance

## Accepted boundary

Phase 7A closes the nine reliability items deferred by Phase 6 while preserving all public routes,
DTOs, schema, UI states, Provider behavior, atomicity, idempotency, cancellation, and security bounds.

## Evidence

- Focused Python/Node/runner-contract suites: PASS with exact terminal counts recorded from this run.
- Full `npm test`: PASS with exact terminal counts recorded from this run.
- Full `npm run test:integration`: PASS with exact terminal counts and disposable DB ledger recorded from this run.
- Frontend build: PASS.
- Phase 6A/6B/6C browser gates: PASS, one scenario each.
- Provider/outbound calls: 0/0.
- Product DB reads/writes: 0/0.
- Owned DB/process/port/temp/quarantine/staging/download/artifact/Vite residue: 0.
- Specification review active Critical/Important: 0/0.
- Quality review active Critical/Important: 0/0.

## Deferred boundary

Product-database readiness remains Phase 7B; real Provider quality/budget/privacy/content evaluation
remains Phase 7C; deployment, live-site security operations, and monitoring remain Phase 7D.
```

Replace each “exact terminal counts recorded from this run” phrase with the actual observed counts before committing. Do not estimate or recover truncated counts.

- [ ] **Step 6: Verify the final tree and commit acceptance**

```powershell
git status --short
git diff --check
git log --oneline --decorate -8
git add docs/acceptance/2026-08-12-phase-7a-reliability-hardening.md
git commit -m "docs: accept phase7a reliability hardening"
git status --short
```

Expected: diff check exits 0; the acceptance commit succeeds; final status is clean. Do not merge or push until the user explicitly requests integration.

## Plan self-review

- **Specification coverage:** Tasks 1–5 map to all nine deferred items; Task 6 enforces the approved acceptance and residue boundaries.
- **No-placeholder check:** every implementation step names exact files, code shape, test command, and expected outcome; acceptance counts must be copied from observed terminal output rather than guessed.
- **Type consistency:** `_monotonic` is `Callable[[], float]`, `_sleep` is `Callable[[float], Awaitable[None]]`; observer evidence is an integer-only closed object; cleanup event/category names are fixed across implementation and tests.
- **YAGNI check:** no schema, route, UI state, metrics platform, shared framework, Provider call, or product-database operation is added.
