# Formal Test Runner Pytest Temp Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every formal pytest stage use a deterministic runner-owned basetemp so `npm run test:milestone2` is reproducible on Windows and always cleans its temporary files.

**Architecture:** `scripts/run-tests.mjs` assigns one fixed relative basetemp to each Python stage and owns a small prepare/cleanup lifecycle around every child spawn. Paths are closed constants under `.codex-test-artifacts/pytest`; cleanup never recursively removes the parent `.codex-test-artifacts` namespace. Existing suite order, inventory, MySQL authority, child environment, and `shell:false` behavior remain unchanged.

**Tech Stack:** Node.js ESM, `node:fs`, `node:path`, `node:test`, Python pytest CLI

---

### Task 1: Freeze the pytest basetemp command and lifecycle contract

**Files:**
- Modify: `scripts/tests/run-tests.test.mjs`
- Test: `scripts/tests/run-tests.test.mjs`

- [ ] **Step 1: Add RED assertions for deterministic stage paths**

Add a helper that extracts the single value after `--basetemp`, then extend the Milestone 2 composition test:

```js
function pytestBasetemp(call) {
  const index = call.args.indexOf('--basetemp')
  if (index === -1 || index + 1 >= call.args.length) return null
  assert.equal(call.args.indexOf('--basetemp', index + 1), -1)
  return call.args[index + 1]
}

const pythonCalls = milestone2.filter(call => call.args.slice(0, 2).join(' ') === '-m pytest')
assert.deepEqual(pythonCalls.map(pytestBasetemp), [
  path.join('.codex-test-artifacts', 'pytest', 'm1-regression'),
  path.join('.codex-test-artifacts', 'pytest', 'unit-api'),
  path.join('.codex-test-artifacts', 'pytest', 'integration'),
])
```

- [ ] **Step 2: Add RED lifecycle tests with injected collaborators**

Call `runSuites()` with injected `preparePytestTempImpl` and `cleanupPytestTempImpl`. Record events and assert:

```js
assert.deepEqual(events, [
  'prepare:m1-regression',
  'spawn:m1-regression',
  'cleanup:m1-regression',
  'cleanup-all',
])
```

Cover these cases separately:

```js
// preparation failure: no spawn, cleanup-all still runs, result is non-zero
// child non-zero: stage cleanup and cleanup-all run, child status is preserved
// spawn error: stage cleanup and cleanup-all run, result is non-zero
// stage cleanup failure: cleanup-all still runs and result is non-zero
// unrelated `.codex-test-artifacts/keep-me` is never passed to either collaborator
```

Add one filesystem-backed test using a disposable fake repository root. Create
`.codex-test-artifacts/keep-me/evidence.txt`, invoke the default lifecycle with a
mocked successful child, then assert the evidence file still exists and
`.codex-test-artifacts/pytest` does not. This proves the production cleanup helper,
not only the injected test double.

- [ ] **Step 3: Run the RED tests**

Run:

```powershell
node --test scripts/tests/run-tests.test.mjs
```

Expected: the new tests fail because pytest commands have no `--basetemp` and `runSuites()` has no temp lifecycle collaborators.

- [ ] **Step 4: Commit the verified RED contract**

```powershell
git add scripts/tests/run-tests.test.mjs
git commit -m "test: require isolated pytest temp roots"
```

### Task 2: Implement the closed pytest temp lifecycle

**Files:**
- Modify: `scripts/run-tests.mjs`
- Modify: `scripts/tests/run-tests.test.mjs`

- [ ] **Step 1: Add fixed stage constants and pytest argument construction**

Define only these paths:

```js
const pytestTempNamespace = path.join('.codex-test-artifacts', 'pytest')
const pytestTempStages = Object.freeze({
  m1Regression: path.join(pytestTempNamespace, 'm1-regression'),
  unitApi: path.join(pytestTempNamespace, 'unit-api'),
  integration: path.join(pytestTempNamespace, 'integration'),
})

function pytestCommand(python, stage, args) {
  return [python, ['-m', 'pytest', ...args, '--basetemp', stage]]
}
```

Use `pytestCommand()` for the retained M1, unit/API, and integration command arrays. Do not change their test files, markers, order, or `-q` flags.

- [ ] **Step 2: Implement safe default preparation and cleanup**

Import `mkdirSync`, `rmSync`, and `rmdirSync` from `node:fs`. Resolve only constant stage paths under the repository root and reject anything outside the exact namespace:

```js
function resolveApprovedPytestTemp(rootDirectory, stage) {
  if (!Object.values(pytestTempStages).includes(stage)) {
    throw new Error('Unapproved pytest temp stage')
  }
  const namespace = path.resolve(rootDirectory, pytestTempNamespace)
  const target = path.resolve(rootDirectory, stage)
  if (path.dirname(target) !== namespace) throw new Error('Unsafe pytest temp stage')
  return { namespace, target }
}

function preparePytestTemp(rootDirectory, stage) {
  const { namespace, target } = resolveApprovedPytestTemp(rootDirectory, stage)
  mkdirSync(namespace, { recursive: true })
  rmSync(target, { recursive: true, force: true })
}

function cleanupPytestTemp(rootDirectory, stage) {
  const { namespace, target } = resolveApprovedPytestTemp(rootDirectory, stage)
  rmSync(target, { recursive: true, force: true })
  try { rmdirSync(namespace) } catch (error) {
    if (!['ENOENT', 'ENOTEMPTY'].includes(error?.code)) throw error
  }
}
```

The aggregate cleanup calls `cleanupPytestTemp()` for all three approved stages. It may use non-recursive `rmdirSync()` on an empty `.codex-test-artifacts` parent, but must never recursively delete that parent.

- [ ] **Step 3: Wrap every pytest spawn in prepare/cleanup**

Extend `runSuites()` options with the two injectable collaborators. Detect the basetemp argument from the closed command array, then use this control flow:

```js
let exitCode = 0
try {
  preparePytestTempImpl(rootDirectory, stage)
  const result = spawnSyncImpl(command, args, childOptions)
  exitCode = result.error ? (result.status ?? 1) : (result.status ?? 1)
} catch (error) {
  stderr.write(`Formal pytest temp setup failed for ${path.basename(stage)}\n`)
  exitCode = 1
} finally {
  try { cleanupPytestTempImpl(rootDirectory, stage) } catch {
    stderr.write(`Formal pytest temp cleanup failed for ${path.basename(stage)}\n`)
    if (exitCode === 0) exitCode = 1
  }
}
```

Preserve the existing detailed spawn error message and child status. An outer `finally` invokes cleanup for all three approved stages so earlier returns cannot leave residue. Error messages contain only fixed stage labels.

- [ ] **Step 4: Run the focused Node tests GREEN**

Run:

```powershell
node --test scripts/tests/run-tests.test.mjs
```

Expected: all tests pass; command composition remains closed and every failure path records cleanup.

- [ ] **Step 5: Run diff and residue checks**

```powershell
git diff --check
if (Test-Path .codex-test-artifacts/pytest) { throw 'pytest temp residue remains' }
```

Expected: both checks pass.

- [ ] **Step 6: Commit the implementation**

```powershell
git add scripts/run-tests.mjs scripts/tests/run-tests.test.mjs
git commit -m "fix: isolate formal pytest temp roots"
```

### Task 3: Re-run the formal Milestone 2 gate

**Files:**
- Modify only files required by a verified test failure.

- [ ] **Step 1: Run the formal aggregate**

```powershell
npm run test:milestone2
```

Expected: retained M1, unit/API, Node/frontend, disposable MySQL, and formal M2 browser all exit zero; disposable database summary reports `remaining=0`.

- [ ] **Step 2: Run build and repository checks**

```powershell
npm --prefix frontend run build
python -m compileall -q backend
git diff --check
if (Test-Path .codex-test-artifacts/pytest) { throw 'pytest temp residue remains' }
```

Expected: build transforms the production frontend successfully; compile/diff pass; no runner temp residue remains.

- [ ] **Step 3: Run the formal safety scans**

```powershell
if (-not $env:APPROVED_M2_PLAN_COMMIT) { throw 'APPROVED_M2_PLAN_COMMIT is required' }
node scripts/scan-m2-artifacts.mjs --base $env:APPROVED_M2_PLAN_COMMIT
$legacyMatches = @(git diff "$env:APPROVED_M2_PLAN_COMMIT...HEAD" -- backend frontend scripts package.json | rg -n "phase-e|e\.23|applyAdapter|providerAdapter")
if ($LASTEXITCODE -eq 0) { throw "New formal diff references shadow QA: $($legacyMatches -join '; ')" }
if ($LASTEXITCODE -ne 1) { throw "rg failed with exit code $LASTEXITCODE" }
```

Expected: artifact scan exits zero and the legacy-name scan finds no match.

- [ ] **Step 4: Record runtime evidence**

```powershell
python --version
python -m backend.scripts.verify_runtime_versions --test-mysql
python -m pip check
node --version
npm --prefix frontend exec playwright -- --version
```

Expected: every command exits zero and the runtime receipt contains versions only, never credentials.

- [ ] **Step 5: Commit only verified failure fixes, if any**

If Step 1 exposes a new product failure, add one failing test, implement the smallest fix, rerun Steps 1–4, then commit only that verified fix. Do not commit logs, raw corpus, temp directories, Provider output, or product database evidence.
