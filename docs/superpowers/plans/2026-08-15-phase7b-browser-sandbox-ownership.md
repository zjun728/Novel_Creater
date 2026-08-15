# Phase 7B Browser Sandbox Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unsafe Node-owned Phase 7B browser root with one Python-owned leased sandbox and emit the canonical browser result only after truthful process, port, artifact, and root cleanup.

**Architecture:** Python is the sole sandbox owner and finalizer. It creates and leases the Windows directory, starts the Node lifecycle runner, consumes a private fixed-schema evidence marker, performs cleanup, and only then emits the public `PHASE7B_BROWSER_SMOKE_SUMMARY=` marker. Node receives a borrowed root and nonce, owns only child lifecycle work inside that root, and never recursively deletes the root or claims a final zero-resource ledger.

**Tech Stack:** Python 3.13, Win32 directory handles and Job Objects, Node.js ES modules, Playwright, pytest, Node test runner.

---

## File map

- Create `backend/scripts/run_phase7b_browser.py`: standalone Python owner/finalizer entry point used by the formal `browser-phase7b` target.
- Create `backend/tests/unit/test_run_phase7b_browser_command.py`: owner acquisition, private-evidence parsing, cleanup ledger, failure precedence, and CLI-output contracts.
- Modify `backend/scripts/prepare_product_database.py`: expose and reuse one owned-browser execution function for Stage A; retain existing Windows lease and Job implementation as the single ownership authority.
- Modify `backend/tests/unit/test_prepare_product_database_command.py`: prove Stage A consumes private Node evidence and validates only the post-cleanup canonical summary.
- Modify `frontend/e2e/run-phase7b.mjs`: remove Node root ownership/deletion, consume a borrowed sandbox, emit private evidence, and register each started server before later setup can fail.
- Modify `scripts/tests/phase7bBrowserContract.test.mjs`: dynamically exercise the borrowed-root lifecycle and every acquired process cleanup boundary.
- Modify `scripts/run-tests.mjs`: route formal `browser-phase7b` through the Python owner wrapper while retaining the exact formal spec inventory.

### Task 1: Python owner and final summary boundary

**Files:**
- Create: `backend/scripts/run_phase7b_browser.py`
- Create: `backend/tests/unit/test_run_phase7b_browser_command.py`
- Modify: `backend/scripts/prepare_product_database.py`
- Modify: `backend/tests/unit/test_prepare_product_database_command.py`

- [ ] **Step 1: Write RED tests for the owner/finalizer API**

Add tests that call the wished-for shared API:

```python
result = run_owned_phase7b_browser(
    node_command=(NODE_EXE, "frontend/e2e/run-phase7b.mjs"),
    cwd=REPOSITORY_ROOT,
    environment=clean_environment(),
    timeout_seconds=300,
    runner=fake_runner(private_evidence()),
    root_factory=fake_root_factory(),
)
assert result == {
    "firstStage": None,
    "firstCause": None,
    "scenarioCount": 1,
    "providerCalls": 0,
    "outboundRequests": 0,
    "processCount": 0,
    "portCount": 0,
    "rootCount": 0,
    "artifactCount": 0,
}
```

Cover these exact failures:

- malformed, duplicate, missing, or non-canonical private evidence;
- child start/timeout/nonzero exit;
- process-tree cleanup, port audit, artifact cleanup, root delete, and lease-close failure;
- ordinary primary plus cleanup failures, with primary first;
- `CancelledError`, `KeyboardInterrupt`, and `SystemExit` with sanitized arguments;
- root acquisition failure before child start;
- cleanup failure produces no public success marker and reports a fixed nonzero/failure category.

- [ ] **Step 2: Run the owner tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_run_phase7b_browser_command.py backend/tests/unit/test_prepare_product_database_command.py -q --basetemp=.pytest-phase7b-browser-owner-red
```

Expected: failure because `run_phase7b_browser` and `run_owned_phase7b_browser` do not exist and Stage A still expects the Node public marker.

- [ ] **Step 3: Implement the shared Python owner**

In `prepare_product_database.py`, expose a shared function with this boundary:

```python
def run_owned_phase7b_browser(
    *,
    node_command: tuple[str, ...],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
    runner: Callable[..., object],
    root_factory: Callable[..., object],
) -> dict[str, object]:
    """Own the sandbox and process tree; return only post-cleanup safe evidence."""
```

The function must:

1. create the private root and no-share-delete lease before starting Node;
2. pass only `PHASE7B_BROWSER_TASK_ROOT` and a fresh `PHASE7B_BROWSER_TASK_NONCE` to Node;
3. accept exactly one canonical `PHASE7B_BROWSER_INTERNAL_EVIDENCE=` line containing only fixed stage/cause, scenario, Provider/outbound, process, port, and artifact counters;
4. stop the Job/process tree before artifact and root cleanup;
5. delete the exact leased root and close the lease;
6. construct the public summary from observed post-cleanup facts, never from Node's root claim;
7. preserve operation-primary-before-cleanup ordering and sanitize every public exception tree.

Update Stage A `_default_smoke` to call this function directly with `node frontend/e2e/run-phase7b.mjs`; it must no longer ask Node to emit `PHASE7B_BROWSER_SMOKE_SUMMARY=`.

- [ ] **Step 4: Implement the standalone wrapper**

`backend/scripts/run_phase7b_browser.py` must be a thin CLI:

```python
def main() -> int:
    summary = run_owned_phase7b_browser(...production dependencies...)
    print("PHASE7B_BROWSER_SMOKE_SUMMARY=" + canonical_json(summary))
    return 0
```

On failure it prints only one fixed safe failure line to stderr, emits no success marker, and returns nonzero. It accepts no database name, credential, DDL, seed, or cleanup target argument.

- [ ] **Step 5: Run Python GREEN verification**

Run:

```powershell
python -m pytest backend/tests/unit/test_run_phase7b_browser_command.py backend/tests/unit/test_prepare_product_database_command.py -q --basetemp=.pytest-phase7b-browser-owner-green
python -m py_compile backend/scripts/run_phase7b_browser.py backend/scripts/prepare_product_database.py backend/tests/unit/test_run_phase7b_browser_command.py backend/tests/unit/test_prepare_product_database_command.py
```

Expected: all tests pass and no task root/process/handle remains.

- [ ] **Step 6: Commit the owner boundary**

```powershell
git add backend/scripts/run_phase7b_browser.py backend/tests/unit/test_run_phase7b_browser_command.py backend/scripts/prepare_product_database.py backend/tests/unit/test_prepare_product_database_command.py
git commit -m "fix: own phase7b browser sandbox externally"
```

### Task 2: Borrowed Node lifecycle runner

**Files:**
- Modify: `frontend/e2e/run-phase7b.mjs`
- Modify: `scripts/tests/phase7bBrowserContract.test.mjs`

- [ ] **Step 1: Write RED lifecycle tests**

Add dynamic tests that invoke `runPhase7B` with a validated borrowed root and nonce. Assert:

```javascript
assert.deepEqual(events, [
  'ports:reserve',
  'backend:start',
  'runtime:observe',
  'vite:start',
  'playwright:run',
  'vite:stop',
  'backend:stop',
  'ports:audit',
  'artifacts:audit',
])
```

Add a `runtime:observe` failure test that requires `backend:stop`. Add one failure at every acquisition/body/cleanup boundary and assert all previously acquired servers stop, ports audit, artifacts are counted truthfully, operation primary stays first, and flow-control types remain sanitized. Assert that deleting any `servers.push` immediately after a successful start fails the test.

- [ ] **Step 2: Verify Node RED**

Run:

```powershell
node --test scripts/tests/phase7bBrowserContract.test.mjs
```

Expected: failures because Node still creates/deletes a nested root, emits the public summary, and registers backend after observer creation.

- [ ] **Step 3: Implement the borrowed-root runner**

Remove `createFilesystemRootOwner`, `createRunnerRoot`, and recursive root deletion from Node production flow. Validate the supplied root and nonce syntax without claiming deletion authority. Create only fixed direct children for Playwright output/download/artifacts.

Change the marker to:

```javascript
const INTERNAL_EVIDENCE_MARKER = 'PHASE7B_BROWSER_INTERNAL_EVIDENCE='
```

The private record may report scenario/runtime/process/port/artifact observations but must not report `rootCount` as final authority. Immediately after each successful server start, push the server into the cleanup list before runtime observer or later setup:

```javascript
const backend = await atStage('backend:start', () => deps.startOwnedServer(...))
servers.push(backend)
const runtime = await atStage('runtime:observe', () => deps.createRuntimeAudit(backend))
```

- [ ] **Step 4: Run Node GREEN verification**

Run:

```powershell
node --test scripts/tests/phase7bBrowserContract.test.mjs
node --check frontend/e2e/run-phase7b.mjs
```

Expected: all contract tests pass; no test starts a real browser, backend, database, Provider, or network connection.

- [ ] **Step 5: Commit the Node borrower**

```powershell
git add frontend/e2e/run-phase7b.mjs scripts/tests/phase7bBrowserContract.test.mjs
git commit -m "fix: borrow phase7b browser sandbox"
```

### Task 3: Formal target routing and combined contracts

**Files:**
- Modify: `scripts/run-tests.mjs`
- Modify: `scripts/tests/phase7bBrowserContract.test.mjs`
- Test: `backend/tests/unit/test_run_phase7b_browser_command.py`

- [ ] **Step 1: Write RED routing contracts**

Assert that formal mode `browser-phase7b` launches exactly:

```text
<configured Python> -m backend.scripts.run_phase7b_browser
```

and never launches `frontend/e2e/run-phase7b.mjs` without the Python owner. Assert the Python owner launches the Node file directly, preventing wrapper recursion. Preserve the exact one-spec formal inventory.

- [ ] **Step 2: Verify routing RED**

Run:

```powershell
node --test scripts/tests/phase7bBrowserContract.test.mjs
```

Expected: failure because `scripts/run-tests.mjs` still maps the formal target directly to Node.

- [ ] **Step 3: Implement the formal routing**

Change only the `browser-phase7b` command mapping to the Python module wrapper. Keep the root and frontend package scripts unchanged: they still call `scripts/run-tests.mjs browser-phase7b`.

- [ ] **Step 4: Run the complete non-formal gate**

```powershell
node --test scripts/tests/phase7bBrowserContract.test.mjs
node --check frontend/e2e/run-phase7b.mjs
node --check frontend/e2e/playwright.phase7b.config.mjs
node --check frontend/e2e/phase7b-product-database-readiness.spec.mjs
node --check scripts/run-tests.mjs
python -m pytest backend/tests/unit/test_run_phase7b_browser_command.py backend/tests/unit/test_prepare_product_database_command.py -q --basetemp=.pytest-phase7b-browser-owner-final
python -m py_compile backend/scripts/run_phase7b_browser.py backend/scripts/prepare_product_database.py
git diff --check
```

Expected: all commands exit `0`; no formal browser run occurs; unit-test temporary roots are cleaned;
no process, port, root, artifact, or handle residue remains; and no database, Provider, or external
network resource is used.

- [ ] **Step 5: Commit and request two-stage review**

```powershell
git add scripts/run-tests.mjs scripts/tests/phase7bBrowserContract.test.mjs backend/tests/unit/test_run_phase7b_browser_command.py
git commit -m "test: route phase7b browser through owner"
```

Request a read-only specification review first. After all Critical/Important findings are closed, request a separate quality review. Do not run the formal browser gate before the approved Stage A gate.
