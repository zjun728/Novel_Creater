# Vite Test Cache Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `projectBibleView` unit tests from leaving Vite `deps_temp_*` directories while preserving their existing SSR behavior and lifecycle.

**Architecture:** Move the single-purpose Vite SSR server configuration into one test-support module that always disables dependency discovery. Import that helper from `projectBibleView.test.mjs`, replace all ten direct Vite server constructions, and protect both the configuration and exclusive-helper usage with a focused executable contract.

**Tech Stack:** Node.js test runner, Vite 8, Vue 3, `@vitejs/plugin-vue`, PowerShell cache inspection, Git.

---

## File Map

- Create `frontend/tests/support/projectBibleViteServer.mjs`: owns the Project Bible test server configuration and server factory.
- Create `frontend/tests/unit/projectBibleViteServer.test.mjs`: verifies dependency discovery is disabled and the Project Bible suite uses only the helper.
- Modify `frontend/tests/unit/projectBibleView.test.mjs`: imports the helper and replaces ten direct `createServer(...)` calls.
- No production source, Vite production configuration, package manifest, database code, or product behavior changes.

### Task 1: Establish the RED Runtime Evidence

**Files:**
- Inspect: `frontend/node_modules/.vite`
- Run: `frontend/tests/unit/projectBibleView.test.mjs`

- [ ] **Step 1: Verify the cache baseline**

Run from the repository root:

```powershell
$cache = Resolve-Path -LiteralPath 'frontend/node_modules/.vite' -ErrorAction SilentlyContinue
if ($cache) {
  @(Get-ChildItem -LiteralPath $cache -Directory -Filter 'deps_temp_*').Count
} else {
  0
}
```

Expected: `0`.

- [ ] **Step 2: Run the current Project Bible suite**

Run:

```powershell
node --test frontend/tests/unit/projectBibleView.test.mjs
```

Expected: the existing tests pass.

- [ ] **Step 3: Prove the current implementation leaks ten directories**

Run:

```powershell
$cache = Resolve-Path -LiteralPath 'frontend/node_modules/.vite'
@(Get-ChildItem -LiteralPath $cache -Directory -Filter 'deps_temp_*').Count
```

Expected before implementation: `10`. If the number differs, stop and re-investigate instead of encoding the assumed count.

- [ ] **Step 4: Remove only the reproduced RED artifacts**

Resolve and verify the exact cache root before removal:

```powershell
$expected = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) 'frontend/node_modules/.vite'))
$cache = (Resolve-Path -LiteralPath $expected).Path
if ($cache -ne $expected) { throw "Unexpected cache root: $cache" }
$owned = @(Get-ChildItem -LiteralPath $cache -Directory -Filter 'deps_temp_*')
if ($owned.Count -ne 10) { throw "Expected 10 reproduced directories, found $($owned.Count)" }
$owned | ForEach-Object {
  if ($_.Parent.FullName -ne $cache -or $_.Name -notlike 'deps_temp_*' -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "Refusing unsafe removal: $($_.FullName)"
  }
  [System.IO.Directory]::Delete($_.FullName, $true)
}
```

Expected: the exact ten directories created by Step 2 are removed; no other cache or worktree is touched.

### Task 2: Add the Failing Configuration and Routing Contract

**Files:**
- Create: `frontend/tests/unit/projectBibleViteServer.test.mjs`
- Future create: `frontend/tests/support/projectBibleViteServer.mjs`
- Inspect: `frontend/tests/unit/projectBibleView.test.mjs`

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/projectBibleViteServer.test.mjs` with:

```javascript
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { projectBibleViteConfig } from '../support/projectBibleViteServer.mjs'

test('Project Bible Vite test servers disable dependency discovery', () => {
  const config = projectBibleViteConfig()

  assert.equal(config.configFile, false)
  assert.equal(config.server.middlewareMode, true)
  assert.equal(config.server.hmr, false)
  assert.equal(config.server.ws, false)
  assert.equal(config.appType, 'custom')
  assert.equal(config.logLevel, 'error')
  assert.deepEqual(config.optimizeDeps, { noDiscovery: true })
  assert.equal(config.plugins.length, 1)
  assert.ok(config.resolve.alias['@'])
})

test('Project Bible view tests create Vite servers only through the cache-safe helper', async () => {
  const suite = await readFile(new URL('./projectBibleView.test.mjs', import.meta.url), 'utf8')

  assert.doesNotMatch(suite, /from\s+['"]vite['"]/)
  assert.doesNotMatch(suite, /\bcreateServer\s*\(/)
  assert.equal(suite.match(/\bcreateProjectBibleViteServer\s*\(\s*\)/g)?.length, 10)
})
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```powershell
node --test frontend/tests/unit/projectBibleViteServer.test.mjs
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for
`frontend/tests/support/projectBibleViteServer.mjs`.

### Task 3: Implement the Single Cache-Safe Server Entry

**Files:**
- Create: `frontend/tests/support/projectBibleViteServer.mjs`
- Modify: `frontend/tests/unit/projectBibleView.test.mjs`
- Test: `frontend/tests/unit/projectBibleViteServer.test.mjs`
- Test: `frontend/tests/unit/projectBibleView.test.mjs`

- [ ] **Step 1: Create the test-support module**

Create `frontend/tests/support/projectBibleViteServer.mjs` with:

```javascript
import { fileURLToPath } from 'node:url'

import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const sourceRoot = fileURLToPath(new URL('../../src', import.meta.url))

export function projectBibleViteConfig() {
  return {
    configFile: false,
    root: frontendRoot,
    resolve: { alias: { '@': sourceRoot } },
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin()],
    optimizeDeps: { noDiscovery: true },
  }
}

export function createProjectBibleViteServer() {
  return createServer(projectBibleViteConfig())
}
```

- [ ] **Step 2: Route all ten test servers through the helper**

In `frontend/tests/unit/projectBibleView.test.mjs`, replace:

```javascript
import { createServer } from 'vite'
import vuePlugin from '@vitejs/plugin-vue'
```

with:

```javascript
import { createProjectBibleViteServer } from '../support/projectBibleViteServer.mjs'
```

Remove the now-unused declaration:

```javascript
const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
```

Replace each of the ten identical direct constructions:

```javascript
const vite = await createServer({ configFile: false, root: frontendRoot, resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error', plugins: [vuePlugin()] })
```

with:

```javascript
const vite = await createProjectBibleViteServer()
```

Do not change any `try/finally`, `await vite.close()`, SSR load, fetch stub, or assertion.

- [ ] **Step 3: Run the focused tests**

Run:

```powershell
node --test frontend/tests/unit/projectBibleViteServer.test.mjs frontend/tests/unit/projectBibleView.test.mjs
```

Expected: both files pass with no failures.

- [ ] **Step 4: Verify the first GREEN run creates no cache residue**

Run:

```powershell
$cache = Resolve-Path -LiteralPath 'frontend/node_modules/.vite' -ErrorAction SilentlyContinue
if ($cache) {
  @(Get-ChildItem -LiteralPath $cache -Directory -Filter 'deps_temp_*').Count
} else {
  0
}
```

Expected: `0`.

- [ ] **Step 5: Run the focused tests a second time**

Run:

```powershell
node --test frontend/tests/unit/projectBibleViteServer.test.mjs frontend/tests/unit/projectBibleView.test.mjs
```

Expected: both files pass again.

- [ ] **Step 6: Verify the second GREEN run creates no cache residue**

Run:

```powershell
$cache = Resolve-Path -LiteralPath 'frontend/node_modules/.vite' -ErrorAction SilentlyContinue
if ($cache) {
  @(Get-ChildItem -LiteralPath $cache -Directory -Filter 'deps_temp_*').Count
} else {
  0
}
```

Expected: `0`.

- [ ] **Step 7: Commit the implementation**

Run:

```powershell
git add -- frontend/tests/support/projectBibleViteServer.mjs frontend/tests/unit/projectBibleViteServer.test.mjs frontend/tests/unit/projectBibleView.test.mjs
git commit -m "test: prevent Vite cache leakage"
```

Expected: one commit containing only the helper, focused contract, and Project Bible suite routing changes.

### Task 4: Run Final Regression Gates

**Files:**
- Verify: `frontend/tests/support/projectBibleViteServer.mjs`
- Verify: `frontend/tests/unit/projectBibleViteServer.test.mjs`
- Verify: `frontend/tests/unit/projectBibleView.test.mjs`

- [ ] **Step 1: Run the complete frontend unit suite**

Run:

```powershell
npm --prefix frontend run test:unit
```

Expected: all frontend unit tests pass.

- [ ] **Step 2: Confirm the full frontend suite did not recreate temp caches**

Run:

```powershell
$cache = Resolve-Path -LiteralPath 'frontend/node_modules/.vite' -ErrorAction SilentlyContinue
if ($cache) {
  @(Get-ChildItem -LiteralPath $cache -Directory -Filter 'deps_temp_*').Count
} else {
  0
}
```

Expected: `0`.

- [ ] **Step 3: Run the root Node test suite**

Run:

```powershell
npm test
```

Expected: Python, root Node, and frontend test groups pass according to the repository test dispatcher.

- [ ] **Step 4: Confirm the root suite did not recreate temp caches**

Run the cache count command from Step 2.

Expected: `0`.

- [ ] **Step 5: Run static Git checks**

Run:

```powershell
git diff --check
git show --check --stat --oneline HEAD
git status --short --branch
```

Expected: no whitespace errors; the implementation commit passes `git show --check`; the worktree is clean.

- [ ] **Step 6: Report exact evidence**

Report the two focused-run results, complete frontend result, root test result, and all four observed cache counts. Do not claim the leak is fixed unless every reported post-run count is `0`.
