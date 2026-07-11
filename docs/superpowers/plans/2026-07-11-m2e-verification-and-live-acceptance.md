# M2E Verification and Live Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the formal M2 L1–L3 test entrypoint, complete L4 human asset/corpus/browser checks, explicitly rebuild the local product database, and perform one controlled L5 story-engine Provider acceptance from the real ProjectView.

**Architecture:** Automated tests use only synthetic content, injected transports, and disposable MySQL databases. Browser tests exercise formal UI writes with an exact network allowlist and no direct API helpers. Product DB rebuild and real Provider execution are separate human checkpoints after every non-live gate passes; the live call is never placed in an automated runner.

**Tech Stack:** pytest, Node `node:test`, Playwright, Vite, FastAPI/Uvicorn, MySQL 8.4, PowerShell.

---

### Task 1: Browser source and repository artifact gates

**Files:**
- Create: `scripts/browser-source-contract.mjs`
- Create: `scripts/scan-m2-artifacts.mjs`
- Create: `scripts/tests/milestone2-browser-contract.test.mjs`
- Create: `scripts/tests/scan-m2-artifacts.test.mjs`

- [ ] **Step 1: Write RED dispatcher/source-gate tests**

```javascript
import assert from 'node:assert/strict'
import test from 'node:test'
import { assertSafeBrowserSource, assertSafeBrowserGraph } from '../browser-source-contract.mjs'

test('source contract accepts UI actions and rejects shadow writes', () => {
  assert.doesNotThrow(() => assertSafeBrowserSource("await page.getByRole('button', { name: '确认' }).click()"))
  assert.throws(() => assertSafeBrowserSource("await page.request.post('/api/contracts/confirm')"), /shadow browser write/)
  assert.throws(() => assertSafeBrowserSource("await fetch('/api/contracts/confirm', { method: 'POST' })"), /shadow browser write/)
  assert.throws(() => assertSafeBrowserSource("await request.put('/api/contracts/confirm')"), /shadow browser write/)
  assert.throws(() => assertSafeBrowserSource("await page.route('**/api/**', route => route.fulfill({ status: 200 }))"), /shadow browser write/)
  assert.throws(() => assertSafeBrowserSource("await route.continue()"), /shadow browser write/)
  assert.throws(() => assertSafeBrowserSource("import { api } from '@/api/db/client'; await api.contracts.confirm('p1')"), /shadow browser write/)
  assert.throws(() => assertSafeBrowserSource("import axios from 'axios'; await axios.post('/api/contracts/confirm')"), /shadow browser write/)
})

test('source contract scans the local import closure', () => {
  const files = new Map([
    ['spec.ts', "import './helper.js'; await page.getByRole('button').click()"],
    ['helper.js', "await page.request.post('/api/contracts/confirm')"],
  ])
  assert.throws(() => assertSafeBrowserGraph('spec.ts', name => files.get(name)), /shadow browser write/)
})
```

Implement/export `assertSafeBrowserSource(source)` and `assertSafeBrowserGraph(entry, readSource)` in `scripts/browser-source-contract.mjs`. The graph walker resolves every relative import recursively, rejects missing/outside-root/cyclicly unsafe helpers, and applies the same source gate to the complete formal dependency closure. The source gate rejects `page.request`, `request.post|put|patch|delete`, `fetch`, imports/calls of the product API client, `page.route`, `route.fulfill|continue|fallback|abort`, axios/got/undici/XMLHttpRequest and direct node `http|https` clients. Add artifact-scanner tests with synthetic git-name/content input that reject every baseline-new `.txt/.TXT/.epub/.mobi`, secret/base URL/DSN/absolute-root sentinel, and large source-like text outside the reviewed asset JSON directory. Task 1 does not read formal spec files that are created only in Task 3.

- [ ] **Step 2: Verify RED**

```powershell
node --test scripts/tests/milestone2-browser-contract.test.mjs scripts/tests/scan-m2-artifacts.test.mjs
```

Expected: source-contract helper and artifact scanner modules are missing.

- [ ] **Step 3: Implement the two pure gates**

`browser-source-contract.mjs` implements only source-string inspection. `scan-m2-artifacts.mjs` accepts injected changed-file/content readers for unit tests; its CLI requires `--base`, reads the git diff, uses an explicit reviewed-asset JSON allowlist, and exits nonzero on forbidden extension/sentinel/large-source findings.

- [ ] **Step 4: Verify gate tests GREEN**

Run Step 2. Expected: all pure gate tests pass without starting a DB or browser.

- [ ] **Step 5: Commit the formal entry contract**

```powershell
git add scripts/browser-source-contract.mjs scripts/scan-m2-artifacts.mjs scripts/tests/milestone2-browser-contract.test.mjs scripts/tests/scan-m2-artifacts.test.mjs
git commit -m "test: guard milestone two browser sources"
```

### Task 2: Guarded M2 browser DB preparation and runner

**Files:**
- Create: `backend/scripts/prepare_milestone2_browser_db.py`
- Create: `backend/tests/unit/test_prepare_milestone2_browser_db.py`
- Create: `frontend/e2e/run-milestone2.mjs`
- Create: `frontend/e2e/server-log-observer.mjs`
- Create: `frontend/playwright.m2.config.ts`
- Modify: `frontend/e2e/runtime-observer.mjs`
- Modify: `scripts/tests/browser-runner.test.mjs`
- Modify: `scripts/tests/runtime-observer.test.mjs`
- Create: `scripts/tests/server-log-observer.test.mjs`

- [ ] **Step 1: Write RED tests for isolation, cleanup, and exact write observation**

Assert each formal spec gets its own DB name matching `novel_creator_test_[a-f0-9]{32}` and its own corpus directory; only `TEST_MYSQL_*` become child `MYSQL_*`; product DB names are rejected; preparation accepts a closed `foundation|manual|recovery|settings` scenario and seeds only that scenario's preconditions; recovery includes one `running` Provider batch with attempt marker and expired lease plus one stale reserved batch, never a completed UI goal; runner creates a repository-external temporary corpus root plus one synthetic UTF-8 `.txt`; child `CORPUS_ROOT` points to it; runner owns Uvicorn/Vite processes and captures stdout/stderr; finally removes servers, DB and directory for each spec; body+cleanup failures form AggregateError; observer write method/path/count equals each spec's allowlist.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_prepare_milestone2_browser_db.py -q
node --test scripts/tests/browser-runner.test.mjs scripts/tests/runtime-observer.test.mjs scripts/tests/server-log-observer.test.mjs
```

- [ ] **Step 3: Implement guarded preparation and runner**

```javascript
// core shape inside frontend/e2e/run-milestone2.mjs
export const REQUIRED_TEST_VARIABLES = ['TEST_MYSQL_HOST', 'TEST_MYSQL_PORT', 'TEST_MYSQL_USER', 'TEST_MYSQL_PASSWORD']
export const DISPOSABLE_DATABASE = /^novel_creator_test_[a-f0-9]{32}$/

export function buildChildEnvironment(environment, databaseName) {
  if (!DISPOSABLE_DATABASE.test(databaseName)) throw new Error(`Refusing non-disposable browser database: ${databaseName}`)
  const clean = Object.fromEntries(Object.entries(environment).filter(([key]) => !key.startsWith('MYSQL_')))
  return {
    ...clean,
    MYSQL_HOST: environment.TEST_MYSQL_HOST, MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER, MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: databaseName, BROWSER_TEST_DATABASE: databaseName,
    BROWSER_SECRET_SENTINEL: 'browser-secret-must-not-leak',
    BROWSER_PRIVATE_PROVIDER_URL: 'https://private-provider.example/v1',
    BROWSER_CORPUS_ROOT_SENTINEL: 'C:/private/corpus-root-must-not-leak',
  }
}
```

Before building each spec's child environment, use `mkdtempSync(path.join(os.tmpdir(), 'novel-creator-m2-corpus-'))`, write `synthetic-browser-corpus.txt` with two original synthetic chapters, and add both `CORPUS_ROOT: corpusRoot` and `BROWSER_ACTUAL_CORPUS_ROOT_SENTINEL: corpusRoot` to the child environment. The latter is test-observer input only and must never be rendered/logged. The preparation command has `--database`, exact `--scenario`, and `--drop`; no generic DB name/scenario is accepted. It initializes v1.1 and inserts only synthetic preconditions. It never pre-confirms the contract user goal tested by Playwright.

`playwright.m2.config.ts` has no `webServer` block. The runner accepts an explicit closed spec list from its caller, starts Uvicorn and Vite with `spawn(..., {shell:false, stdio:['ignore','pipe','pipe']})`, captures bounded stdout/stderr through `server-log-observer.mjs`, waits for both health URLs, runs exactly that spec, terminates both children, scans captured logs for every fixed sentinel **and the actual dynamic `corpusRoot` string**, then drops the DB and removes the temp directory. Playwright runtime observers use the same dynamic root sentinel for API/DOM/console scanning. The runner reports only match count zero, not raw logs/request bodies. Preserve body, server-stop, DB-cleanup and directory-cleanup errors in one AggregateError. Do not switch package scripts or the formal dispatcher until Task 3 creates all real specs.

- [ ] **Step 4: Verify runner tests GREEN**

Run Step 2. Expected: all pass with injected process runners; no real process/DB starts.

- [ ] **Step 5: Commit browser infrastructure**

```powershell
git add backend/scripts/prepare_milestone2_browser_db.py backend/tests/unit/test_prepare_milestone2_browser_db.py frontend/e2e/run-milestone2.mjs frontend/e2e/server-log-observer.mjs frontend/e2e/runtime-observer.mjs frontend/playwright.m2.config.ts scripts/tests/browser-runner.test.mjs scripts/tests/runtime-observer.test.mjs scripts/tests/server-log-observer.test.mjs
git commit -m "test: add guarded milestone two browser runner"
```

### Task 3: Formal Playwright L3 goals

**Files:**
- Modify: `package.json`
- Modify: `frontend/package.json`
- Modify: `scripts/run-tests.mjs`
- Modify: `scripts/tests/run-tests.test.mjs`
- Create: `frontend/e2e/m2-foundation-regression.spec.ts`
- Create: `frontend/e2e/m2-wizard-manual.spec.ts`
- Create: `frontend/e2e/m2-wizard-recovery.spec.ts`
- Create: `frontend/e2e/m2-settings-assets-corpus.spec.ts`
- Modify: `frontend/e2e/run-milestone2.mjs`

- [ ] **Step 1: Write the formal UI flows**

Every project spec starts from `page.goto('/project/00000000-0000-0000-0000-000000000201')`; the settings spec starts from `/settings`. The preparation script always uses that synthetic project ID. Specs use roles/labels to click/type and make no direct request. The normal L3 wizard path uses the product's manual-three-engine feature, not a route mock or Provider fixture. The recovery spec starts from its preseeded expired running/stale reserved batches, clicks the formal reconcile controls, and relies on M2B's fake-Gateway unit assertion `call_count=0`; it never clicks Provider generation and its network allowlist contains no Provider-batch creation route.

Update `run-milestone2.mjs` in this task so its no-argument CLI default is the exact four files listed above in that order; reject arbitrary spec paths. Unit tests may still inject a closed list.

At this point freeze root scripts `test:browser:m2 -> browser-m2`, `test:milestone1 -> m1-regression`, and `test:milestone2 -> milestone2`; freeze frontend scripts `test:e2e:m1 -> run-milestone1.mjs`, `test:e2e:m2 -> run-milestone2.mjs`, and `test:e2e -> run-milestone2.mjs`. `run-tests.mjs` defines `m1-regression` as v1.1 retained behavior—not frozen v1.0 exact gates—and defines `milestone2` as m1-regression plus ordered unit/API, integration and browser-m2 commands. Dispatcher tests reject recursion, `tmp`, phase-e and missing formal files. All integration/browser suites require explicit `TEST_MYSQL_*`.

```json
{
  "root": {
    "test:browser": "node scripts/run-tests.mjs browser-m2",
    "test:browser:m2": "node scripts/run-tests.mjs browser-m2",
    "test:milestone1": "node scripts/run-tests.mjs m1-regression",
    "test:milestone2": "node scripts/run-tests.mjs milestone2"
  },
  "frontend": {
    "test:e2e:m1": "node e2e/run-milestone1.mjs",
    "test:e2e:m2": "node e2e/run-milestone2.mjs",
    "test:e2e": "node e2e/run-milestone2.mjs"
  }
}
```

Apply the entries inside each file's existing `scripts` object; `root`/`frontend` above are explanatory containers and are not written as literal package keys.

- [ ] **Step 2: Declare exact network write allowlists**

```javascript
const manualWizardWrites = [
  { method: 'PUT', path: /\/selected-seed$/, count: 1, statuses: [200] },
  { method: 'POST', path: /\/story-engine-batches\/manual$/, count: 1, statuses: [201] },
  { method: 'PUT', path: /\/contract-draft$/, count: 3, statuses: [200] },
  { method: 'POST', path: /\/contracts\/preview$/, count: 1, statuses: [200] },
  { method: 'POST', path: /\/contracts\/confirm$/, count: 1, statuses: [201] },
]
```

Recovery specs separately allow only their expected 409/reconcile/new-batch actions with exact counts and allowed statuses. Observer fails on any unmatched write, excess/missing count or unexpected status, then scans requests/responses, DOM, console, page errors, request failures, and Uvicorn logs for secret/base URL/DSN/absolute-root sentinels.

- [ ] **Step 3: Run source gates before browser execution**

Extend `milestone2-browser-contract.test.mjs` at this point with a test that reads all four now-existing formal specs, resolves their repository-local import closures, and passes every graph to `assertSafeBrowserGraph`. Run it together with `scripts/tests/run-tests.test.mjs` so the formal dispatcher and package commands become GREEN in the same task/commit.

```powershell
node --test scripts/tests/milestone2-browser-contract.test.mjs scripts/tests/runtime-observer.test.mjs scripts/tests/run-tests.test.mjs
```

- [ ] **Step 4: Run the Disposable MySQL browser suite**

```powershell
npm run test:browser:m2
```

Expected: foundation v1.1 regression, manual five-step flow, refresh/back/repeat/double-tab 409/unbound/outcome_unknown, confirmed read-only head/Writer disabled, asset/corpus Settings all pass; every disposable DB is removed.

- [ ] **Step 5: Commit Playwright goals**

```powershell
git add package.json frontend/package.json scripts/run-tests.mjs scripts/tests/run-tests.test.mjs scripts/tests/milestone2-browser-contract.test.mjs frontend/e2e/m2-foundation-regression.spec.ts frontend/e2e/m2-wizard-manual.spec.ts frontend/e2e/m2-wizard-recovery.spec.ts frontend/e2e/m2-settings-assets-corpus.spec.ts frontend/e2e/run-milestone2.mjs
git commit -m "test: cover milestone two product flows"
```

### Task 4: Explicit product rebuild and read-only verification commands

**Files:**
- Modify: `backend/scripts/reset_writer_core_data.py`
- Create: `backend/scripts/verify_milestone2_product.py`
- Create: `backend/scripts/verify_runtime_versions.py`
- Create: `backend/scripts/run_milestone2_l4_session.py`
- Create: `backend/scripts/run_milestone2_product_session.py`
- Modify: `backend/tests/unit/test_reset_writer_core_data.py`
- Create: `backend/tests/unit/test_verify_milestone2_product.py`
- Create: `backend/tests/unit/test_verify_runtime_versions.py`
- Create: `backend/tests/unit/test_run_milestone2_l4_session.py`
- Create: `backend/tests/unit/test_run_milestone2_product_session.py`
- Create: `backend/tests/integration/test_milestone2_product_rebuild.py`

- [ ] **Step 1: Write RED dry-run/execute/receipt tests**

Tests require exact product DB confirmation, private execute authority, advisory lock, expected v1.0 source inventory or v1.1 idempotent state, preservation of one project/three seeds/all current Providers, v1.1 fresh manifest, selected `典镇山河`, binding/head0/Canon0/Projection0, zero planning/draft/final rows, rollback/cleanup, and receipts containing no key/base URL/DSN/notes/thinking. Product verifier tests cover base/head0 mode plus `--require-assets` (exactly 8 active style heads, 40–60 active card heads, package/hash consistency), `--require-corpus` (at least one succeeded source/import run, relative path, four analysis versions, positive chapter/fragment counts, no absolute path/text), and `--require-l5` (head/revision 1, one succeeded `source_type='provider'` batch for the selected seed/binding, exactly one attempt, exactly three options, selected engine ref, CreationContract/StyleContract revision/hash/refs internally equal). Runtime-version verifier tests inject a read-only test-server session, require only `SELECT VERSION()`, and record Python/Pydantic/httpx/FastAPI/Starlette/Uvicorn/pytest plus MySQL server versions without credentials. L4-session tests inject process/health/input/prepare/drop/verifier collaborators and prove missing `TEST_MYSQL_*`, non-test DB names, missing/outside-root files, process failures and Ctrl+C all enter one `finally` that terminates/waits both children, scans/flushed logs, drops only the captured disposable DB, deletes temp logs and reports combined body+cleanup errors. Product-session tests cover closed `corpus-import|provider-l5` modes, require exact product DB/confirmation plus source hash, load actual Provider keys/base URLs/DB config/corpus root only into an in-memory scan set, capture both services, wait for manual UI completion, run mode-specific read-only product/corpus verification, terminate/wait children, scan logs against actual sensitive values, delete logs and report combined errors without dropping product data.

- [ ] **Step 2: Verify RED using fake sessions and disposable source fixtures only**

```powershell
python -m pytest backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_verify_milestone2_product.py backend/tests/unit/test_verify_runtime_versions.py backend/tests/unit/test_run_milestone2_l4_session.py backend/tests/unit/test_run_milestone2_product_session.py -q
python -m pytest backend/tests/integration/test_milestone2_product_rebuild.py -m mysql -q
```

- [ ] **Step 3: Implement explicit destructive rebuild, not runtime compatibility**

Dry-run is default and performs no DDL/DML. Execute snapshots only approved foundation rows in memory, locks and rechecks the exact target, rebuilds the whole manifest, inserts v1.1 foundation, verifies counts/hashes, and drops/rolls back incomplete state on failure. The normal application never invokes it. `verify_milestone2_product.py` is SELECT-only and emits a bounded receipt.

`run_milestone2_l4_session.py` is a guarded acceptance helper, not a test shortcut: it creates one random test-prefix DB through the official prepare command, maps only `TEST_MYSQL_*`, starts Python/Uvicorn and the Vite Node entry directly with `shell=False`, captures logs, prints the formal UI URL, waits for the controller to complete UI actions, invokes the read-only corpus verifier, and guarantees cleanup in Python `try/finally`. It never accepts or reads product `MYSQL_*` as authority.

`run_milestone2_product_session.py` is the corresponding product-session evidence boundary. It requires `--mode corpus-import|provider-l5 --database novel_creator --confirm-product novel_creator --source-hash $sourceHash`, validates the hash as 64 lowercase hex, loads private scan values without printing them, starts/captures the two services, waits for the controller's one UI goal, and always stops/scans/deletes logs. `corpus-import` runs product verification with assets+corpus and requires head0; `provider-l5` adds `--require-l5` and requires head1/provider batch/three options/attempt1/contracts. It never invokes Provider itself and never drops/rebuilds the product DB.

- [ ] **Step 4: Verify unit/integration GREEN**

Run Step 2. Expected: all pass; disposable terminal summary reports remaining=0.

- [ ] **Step 5: Commit commands but do not run them on product DB**

```powershell
git add backend/scripts/reset_writer_core_data.py backend/scripts/verify_milestone2_product.py backend/scripts/verify_runtime_versions.py backend/scripts/run_milestone2_l4_session.py backend/scripts/run_milestone2_product_session.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_verify_milestone2_product.py backend/tests/unit/test_verify_runtime_versions.py backend/tests/unit/test_run_milestone2_l4_session.py backend/tests/unit/test_run_milestone2_product_session.py backend/tests/integration/test_milestone2_product_rebuild.py
git commit -m "feat: rebuild and verify milestone two product state"
```

### Task 5: Complete automated L1–L3 and independent code review

**Files:**
- Modify only files required to fix verified failures.

- [ ] **Step 1: Run the formal aggregate**

```powershell
npm run test:milestone2
```

Expected: unit/API, Node/frontend, disposable MySQL and M2 browser all exit 0; no Provider or product DB access.

- [ ] **Step 2: Run build and repository safety scans**

```powershell
npm --prefix frontend run build
git diff --check
if (-not $env:APPROVED_M2_PLAN_COMMIT) { throw 'APPROVED_M2_PLAN_COMMIT is required' }
node scripts/scan-m2-artifacts.mjs --base $env:APPROVED_M2_PLAN_COMMIT
$legacyMatches = @(git diff "$env:APPROVED_M2_PLAN_COMMIT...HEAD" -- backend frontend scripts package.json | rg -n "phase-e|e\.23|applyAdapter|providerAdapter")
if ($LASTEXITCODE -eq 0) { throw "New formal diff references shadow QA: $($legacyMatches -join '; ')" }
if ($LASTEXITCODE -ne 1) { throw "rg failed with exit code $LASTEXITCODE" }
```

Expected: build/diff pass; raw corpus scan empty; legacy names do not appear in new formal paths.

- [ ] **Step 3: Record reproducible environment versions**

```powershell
python --version
python -m backend.scripts.verify_runtime_versions --test-mysql
python -m pip check
node --version
npm --prefix frontend exec playwright -- --version
```

Expected: verifier uses `TEST_MYSQL_*` and `SELECT VERSION()` instead of assuming a local `mysql` CLI. Record the resolved versions; broad requirement lower bounds alone are not reproducible evidence. Review Starlette's resolved version specifically before accepting the file-serving boundary.

- [ ] **Step 4: Request independent spec and code review**

Reviewer checks every M2 spec section, transaction/failure paths, no secret leaks, no shadow QA, browser source gates, and actual test output. Fix all P0/P1 and rerun affected plus aggregate tests.

- [ ] **Step 5: Commit only verified review fixes**

If changes exist, commit `fix: close M2 pre-live review findings`; otherwise create no empty commit. Do not proceed to product DB until the controller sees the dry-run target and authorizes the destructive checkpoint.

### Task 6: L4 asset, corpus, and exploratory browser checkpoint

**Files:**
- Create: `docs/development/writer-core-m2-asset-audit.md`
- Create: `docs/development/writer-core-m2-exploratory-evidence.md`

- [ ] **Step 1: Confirm the reviewed asset package**

Verify all 8 style templates and 40–60 cards against the approved human criteria. Reports record reviewer/commit/decision and do not self-award quality.

- [ ] **Step 2: Create a guarded manual L4 disposable session**

Activate `.venv-m2`, set only the authorized source's relative path, and run the tested lifecycle helper:

```powershell
& .\.venv-m2\Scripts\Activate.ps1
if (-not $env:CORPUS_ROOT) { throw 'CORPUS_ROOT must be explicitly configured outside the repository' }
if (-not $env:M2_AUTHORIZED_CORPUS_FILE) { throw 'M2_AUTHORIZED_CORPUS_FILE must be a root-relative authorized txt path' }
$relativeCorpusFile = $env:M2_AUTHORIZED_CORPUS_FILE
python -m backend.scripts.run_milestone2_l4_session --corpus-root $env:CORPUS_ROOT --relative-file $relativeCorpusFile
```

The helper verifies all four `TEST_MYSQL_*` values, validates the authorized file under the resolved root, creates a random test-prefix DB, maps test credentials to child `MYSQL_*`, starts hidden Uvicorn/Vite children with captured logs, waits for health and prints `http://127.0.0.1:5173`. It never reads product DB configuration. Keep this command running while completing Step 3; press Enter only when UI exploration is finished.

- [ ] **Step 3: Import one authorized real file and explore through formal UI**

Open the printed URL, select `$relativeCorpusFile` by relative name in Settings, and click import. Record the discovery receipt's `scannedCount`, `eligibleCount`, `skippedByReason`, plus import succeeded/failed counts and reasons; zero skipped/failed is recorded explicitly rather than omitted. Compare the displayed hash with independent `Get-FileHash` in a second read-only shell.

```powershell
$sourcePath = Join-Path $env:CORPUS_ROOT $relativeCorpusFile
$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
```

After Enter, the helper runs the read-only corpus verifier before cleanup and reports relative path, matching hash, encoding, size, chapter/fragment counts, first/last raw-byte and normalized-char boundaries, parser/normalizer/fragmenter/index versions and succeeded import-run status, with no absolute path or text. It also resolves repository/root variables itself and fails if a corpus-root file is tracked. Inspect only metadata and one bounded short preview.

Try refresh, back, rapid repeated click, double tab, incomplete step, manual engine edits, deleted Provider, unbound binding, stale draft, 409, expired reserved and outcome_unknown. Use API/DB only for read diagnosis, never to complete a UI goal.

- [ ] **Step 4: Scan evidence and always clean the manual session**

The helper terminates and waits both exact children, flushes/scans logs for actual root/key/base URL/DSN/full-text sentinels, drops only its captured test-prefix DB, deletes its temp directory and scrubs child env inside tested Python `finally`. It returns nonzero on any body or cleanup failure and preserves both errors. Record only match counts and public IDs/hashes; verify the final receipt says `remaining_database=0`, `remaining_processes=0`, and `remaining_temp_paths=0`.

- [ ] **Step 5: Commit evidence only after human completion**

```powershell
git add docs/development/writer-core-m2-asset-audit.md docs/development/writer-core-m2-exploratory-evidence.md
git commit -m "docs: record M2 L4 acceptance evidence"
```

### Task 7: Explicitly rebuild and seed the local product DB

**Files:**
- No code changes expected; this task changes only the explicitly named local product database.

- [ ] **Step 1: Run product dry-run only**

```powershell
python -m backend.scripts.reset_writer_core_data --database novel_creator --project-title 永乐大典 --seed-title 永乐长明 --seed-title 文渊山海 --seed-title 典镇山河 --preferred-provider-name 联通云 --preferred-model deepseek-v4-flash --confirm-reset novel_creator
```

Expected: no writes; exactly named project/seeds/provider model are found; current Provider count is reported but not treated as constant; no secret fields printed.

- [ ] **Step 2: Present the dry-run receipt and obtain explicit execute confirmation**

Do not infer permission from prior test runs. The confirmation identifies `127.0.0.1:3307/novel_creator` and states that the full v1.0 Schema/derived test data will be destroyed and rebuilt as v1.1 while preserving only the approved foundation.

- [ ] **Step 3: Execute the guarded rebuild once**

```powershell
python -m backend.scripts.reset_writer_core_data --database novel_creator --project-title 永乐大典 --seed-title 永乐长明 --seed-title 文渊山海 --seed-title 典镇山河 --preferred-provider-name 联通云 --preferred-model deepseek-v4-flash --confirm-reset novel_creator --execute
```

- [ ] **Step 4: Seed approved assets and verify read-only state**

```powershell
python -m backend.scripts.seed_writer_assets --manifest backend/assets/writer-core-v1.1.0/manifest.json --database novel_creator --confirm-database novel_creator --execute
python -m backend.scripts.verify_milestone2_product --database novel_creator --require-assets
```

Expected: schema v1.1, project1/seeds3/selected典镇山河, current Providers preserved, binding revision1/eight ready, contract head0, 8 style heads, 40–60 card heads, Canon/Projection0, later domains empty.

- [ ] **Step 5: Import the authorized corpus source through product Settings UI**

Compute `$sourceHash` from the same authorized file and run the captured product session. Do not use a CLI/direct API write as the product acceptance substitute:

```powershell
$relativeCorpusFile = $env:M2_AUTHORIZED_CORPUS_FILE
if (-not $relativeCorpusFile) { throw 'M2_AUTHORIZED_CORPUS_FILE is required' }
$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $env:CORPUS_ROOT $relativeCorpusFile)).Hash.ToLowerInvariant()
python -m backend.scripts.run_milestone2_product_session --mode corpus-import --database novel_creator --confirm-product novel_creator --source-hash $sourceHash
```

Use the printed Settings UI and press Enter after the import/reload. Expected: the helper captures/scans both service logs, the corpus receipt matches the source hash and shows succeeded/positive chapter+fragment counts/all versions, and the product receipt contains no root/text and requires assets plus at least one succeeded corpus source.

### Task 8: One controlled L5 real Provider acceptance

**Files:**
- Create: `docs/development/writer-core-m2-evidence.md`

- [ ] **Step 1: Start the guarded captured product session**

```powershell
& .\.venv-m2\Scripts\Activate.ps1
$relativeCorpusFile = $env:M2_AUTHORIZED_CORPUS_FILE
if (-not $relativeCorpusFile) { throw 'M2_AUTHORIZED_CORPUS_FILE is required' }
$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $env:CORPUS_ROOT $relativeCorpusFile)).Hash.ToLowerInvariant()
python -m backend.scripts.run_milestone2_product_session --mode provider-l5 --database novel_creator --confirm-product novel_creator --source-hash $sourceHash
```

The helper prints only the local UI URL and public session ID, captures Uvicorn/Vite logs, and waits for Enter. Keep it running through Steps 2–4. It loads actual Provider secrets/base URLs, DB configuration and corpus root only into an in-memory scan set and never prints them.

- [ ] **Step 2: Verify binding before the only outbound call**

Open formal `永乐大典 / 典镇山河` ProjectView. Confirm selected seed revision/hash and that the frozen `seed` binding resolves to `联通云 / deepseek-v4-flash`. Ensure there is no pending/unknown batch whose retry could duplicate a call.

- [ ] **Step 3: Generate once, compare, select, and confirm**

Click Provider generation once—no double click, refresh, retry runner or automatic fallback. Require exactly three structurally complete and visibly different engines. Judge story promise, long conflict loop, protagonist desire/cost, ensemble differentiation, long-form variation and repeat-upgrade risk. Select one, choose style/cards/corpus scope, preview and atomically confirm revision 1.

- [ ] **Step 4: Reload and reconcile UI/DB evidence**

Record commit/branch/time/environment, project/seed/binding IDs+revisions+hashes, batch/request/attempt/raw-response hashes, option IDs/order/hashes, CreationContract/StyleContract revision+hash, outbound attempt count 1, UI reload equality, Canon/Projection0 and empty planning/draft/final tables. Press Enter only after reload; the helper then runs `verify_corpus_import` for `$sourceHash`, runs the product verifier with `--require-assets --require-corpus --require-l5`, stops/waits both services, flushes and scans logs against all actual sensitive values, deletes logs and reports zero matches/remaining processes/temp paths. Never record key, base URL, DSN, corpus root, raw Provider output or novel text.

- [ ] **Step 5: Handle outcome and close M2**

Provider explicit failure, transport failure, parse failure, fewer/more than three options, missing required fields, duplicate hashes, structural-difference rejection, or `outcome_unknown` all make this L5 attempt fail. None permits automatic replay or repair by a hidden static option. Any second outbound call requires a new idempotency key and new explicit human approval. If successful, write the evidence doc, run the read-only verifier and `git diff --check`, commit `docs: record M2 L5 acceptance evidence`, and label only **L5 M2 Contract-Generation Ready**.
