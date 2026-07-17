# M2 Artifact and Legacy Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the frozen-baseline M2 artifact gate distinguish implementation definitions from publishable artifacts, and replace the raw legacy-name grep with a deterministic committed-HEAD execution-surface gate.

**Architecture:** Keep `scan-m2-artifacts.mjs` responsible only for baseline-added repository artifacts, with a closed path-role classifier and Git HEAD blob readers. Add a separate `scan-effective-legacy.mjs` that inventories effective executable paths at committed HEAD, excludes only four exact test path families, and permits only the scanner's own validated pattern block plus the gateway's exact deny-list lines. Both CLIs remain local, injected-testable, bounded, and fail-closed.

**Tech Stack:** Node.js 24.13.0, `node:test`, Git plumbing through `spawnSync` with `shell:false`, PowerShell verification, existing Python 3.12 `.venv-m2`, pytest, Playwright.

---

## File map

- Modify `scripts/scan-m2-artifacts.mjs`: closed artifact roles, strict precedence, committed-HEAD blob/size readers, bounded diagnostics.
- Modify `scripts/tests/scan-m2-artifacts.test.mjs`: role, strict-precedence, HEAD-snapshot, redaction, and real-baseline coverage.
- Create `scripts/scan-effective-legacy.mjs`: pure effective-surface scan plus committed-HEAD CLI.
- Create `scripts/tests/scan-effective-legacy.test.mjs`: exclusions, protective definitions, active-reference failures, HEAD behavior, and plan-command contract.
- Modify `docs/superpowers/plans/2026-07-11-m2e-verification-and-live-acceptance.md`: replace raw artifact/legacy commands with the two official gates and exact frozen baseline check.
- Modify `docs/superpowers/plans/2026-07-16-formal-test-runner-pytest-temp.md`: use the same two official gates in final acceptance.

The approved design authority is `docs/superpowers/specs/2026-07-17-m2-artifact-and-legacy-gates-design.md`. The frozen diff baseline is `bc0919a2f8464a552c979a9601258fb148d98cac`; `b9b19e8ebdeefc3f88e547042cfc925da4adb1cf` remains only the normative 10-style/64-card amendment.

### Task 1: Classify M2-added files by repository role

**Files:**
- Modify: `scripts/tests/scan-m2-artifacts.test.mjs`
- Modify: `scripts/scan-m2-artifacts.mjs`

- [ ] **Step 1: Add failing role and precedence tests**

Extend the scanner import with `M2_REQUIREMENTS_LOCK` and `classifyM2ArtifactPath`, then add these tests. Keep the existing absolute-path, size, invalid-base, and missing-base tests.

```javascript
import {
  M2_REQUIREMENTS_LOCK,
  REVIEWED_ASSET_JSON_ALLOWLIST,
  classifyM2ArtifactPath,
  runArtifactScannerCli,
  scanM2Artifacts,
} from '../scan-m2-artifacts.mjs'

const syntheticSentinels = () => [
  ['browser', 'secret', 'must', 'not', 'leak'].join('-'),
  ['https://private-provider', '.example/v1'].join(''),
  ['mysql', '://private-user:private-password@127.0.0.1/novel_creator'].join(''),
  ['C:', '/private/corpus-root-must-not-leak'].join(''),
]

test('only the exact M2 requirements lock escapes the raw txt ban', () => {
  const changedFiles = [
    M2_REQUIREMENTS_LOCK,
    'backend/requirements-copy.txt',
    'evidence/chapter.TXT',
    'evidence/book.epub',
    'evidence/book.MOBI',
  ]
  const findings = scanM2Artifacts({
    changedFiles,
    readContent: () => 'fastapi==0.115.0\n',
  })

  assert.deepEqual(findings, changedFiles.slice(1).map(filePath => ({
    path: filePath,
    reason: 'forbidden raw source extension',
  })))
  assert.equal(classifyM2ArtifactPath(M2_REQUIREMENTS_LOCK), 'implementation-definition')
  assert.deepEqual(scanM2Artifacts({
    changedFiles: [M2_REQUIREMENTS_LOCK],
    readContent: () => syntheticSentinels()[0],
  }), [])
})

test('closed implementation definitions accept long code and sentinel definitions', () => {
  const sentinel = syntheticSentinels()[0]
  const changedFiles = [
    'backend/services/long_service.py',
    'frontend/e2e/runner.mjs',
    'scripts/tests/gate.test.mjs',
    'docs/superpowers/specs/approved-design.md',
    'tools/control-plane-qa/fixtures/rfc8785-restricted-vectors.json',
    '.gitattributes',
  ]
  const content = `${sentinel}\n${'sourceWord '.repeat(3500)}`

  assert.deepEqual(scanM2Artifacts({
    changedFiles,
    readContent: () => content,
  }), [])
  assert.deepEqual(changedFiles.map(classifyM2ArtifactPath), [
    'implementation-definition',
    'implementation-definition',
    'implementation-definition',
    'implementation-definition',
    'implementation-definition',
    'implementation-definition',
  ])
})

test('strict artifact paths override source-looking extensions', () => {
  const sentinel = syntheticSentinels()[0]
  const changedFiles = [
    'backend/assets/unreviewed.py',
    'docs/development/private.py',
    'release/evidence/private.mjs',
    'release/output/private.ts',
    'release/artifacts/private.sql',
  ]
  const findings = scanM2Artifacts({
    changedFiles,
    readContent: () => sentinel,
  })

  assert.deepEqual(findings, changedFiles.map(filePath => ({
    path: filePath,
    reason: 'private sentinel content',
  })))
  assert.ok(changedFiles.every(filePath => (
    classifyM2ArtifactPath(filePath) === 'strict-artifact'
  )))
})

test('only reviewed asset JSON may contain large prose and never private sentinels', () => {
  const reviewedPath = [...REVIEWED_ASSET_JSON_ALLOWLIST][0]
  const novelLikeText = '这是一段完全合成的测试故事。'.repeat(2500)
  const sentinel = syntheticSentinels()[0]

  assert.deepEqual(scanM2Artifacts({
    changedFiles: [reviewedPath],
    readContent: () => novelLikeText,
  }), [])
  assert.deepEqual(scanM2Artifacts({
    changedFiles: [reviewedPath],
    readContent: () => sentinel,
  }), [{ path: reviewedPath, reason: 'private sentinel content' }])
  assert.deepEqual(scanM2Artifacts({
    changedFiles: ['backend/assets/writer-core-v1.1.0/unreviewed.json'],
    readContent: () => novelLikeText,
  }), [{
    path: 'backend/assets/writer-core-v1.1.0/unreviewed.json',
    reason: 'large source-like text outside reviewed assets',
  }])
})

test('unknown textual paths use the strict artifact policy', () => {
  const novelLikeText = 'This is synthetic story prose. '.repeat(3500)
  assert.equal(classifyM2ArtifactPath('unknown/generated.json'), 'strict-artifact')
  assert.deepEqual(scanM2Artifacts({
    changedFiles: ['unknown/generated.json'],
    readContent: () => novelLikeText,
  }), [{
    path: 'unknown/generated.json',
    reason: 'large source-like text outside reviewed assets',
  }])
})
```

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```powershell
node --test scripts/tests/scan-m2-artifacts.test.mjs
```

Expected: FAIL because `M2_REQUIREMENTS_LOCK` and `classifyM2ArtifactPath` are not exported and the current scanner still rejects every `.txt` and scans definitions as artifacts.

- [ ] **Step 3: Implement the closed role classifier**

Add these constants and classifier after the reviewed-asset allowlist. Keep path normalization as the first operation used by callers.

```javascript
export const M2_REQUIREMENTS_LOCK = 'backend/requirements-m2.lock.txt'

const IMPLEMENTATION_ROOTS = ['backend/', 'frontend/', 'scripts/', 'tools/']
const IMPLEMENTATION_SUFFIXES = new Set([
  '.py', '.pyi', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.vue',
  '.css', '.scss', '.html', '.sql', '.toml', '.ini', '.cfg', '.yaml', '.yml',
])
const EXACT_IMPLEMENTATION_FILES = new Set([
  '.gitattributes',
  M2_REQUIREMENTS_LOCK,
  'tools/control-plane-qa/fixtures/rfc8785-restricted-vectors.json',
])
const STRICT_PREFIXES = ['backend/assets/', 'docs/development/']
const STRICT_SEGMENTS = new Set(['evidence', 'output', 'artifacts'])
const RAW_NOVEL_EXTENSION = /\.(?:epub|mobi)$/iu
const RAW_TEXT_EXTENSION = /\.txt$/iu

export function classifyM2ArtifactPath(rawPath) {
  const filePath = normalizeRepositoryPath(rawPath)
  if (REVIEWED_ASSET_JSON_ALLOWLIST.has(filePath)) return 'reviewed-writing-asset'
  if (filePath === M2_REQUIREMENTS_LOCK) return 'implementation-definition'

  const segments = filePath.split('/')
  if (STRICT_PREFIXES.some(prefix => filePath.startsWith(prefix))
    || segments.some(segment => STRICT_SEGMENTS.has(segment))) {
    return 'strict-artifact'
  }

  if (EXACT_IMPLEMENTATION_FILES.has(filePath)) return 'implementation-definition'
  if ((filePath.startsWith('docs/superpowers/specs/')
      || filePath.startsWith('docs/superpowers/plans/'))
    && filePath.toLowerCase().endsWith('.md')) {
    return 'implementation-definition'
  }

  const suffix = path.posix.extname(filePath).toLowerCase()
  if (IMPLEMENTATION_ROOTS.some(prefix => filePath.startsWith(prefix))
    && IMPLEMENTATION_SUFFIXES.has(suffix)) {
    return 'implementation-definition'
  }
  return 'strict-artifact'
}
```

Delete the superseded `FORBIDDEN_RAW_EXTENSION` constant; no second raw-extension
rule remains active.

Replace the unconditional raw-extension check and content checks inside `scanM2Artifacts` with this exact order:

```javascript
const filePath = normalizeRepositoryPath(rawPath)
if (RAW_NOVEL_EXTENSION.test(filePath)
  || (RAW_TEXT_EXTENSION.test(filePath) && filePath !== M2_REQUIREMENTS_LOCK)) {
  findings.push({ path: filePath, reason: 'forbidden raw source extension' })
  continue
}

const role = classifyM2ArtifactPath(filePath)
const declaredSize = getSize ? validateSize(getSize(filePath), filePath) : null
if (declaredSize !== null
  && (declaredSize > MAX_ARTIFACT_BYTES
    || totalBytes + declaredSize > MAX_TOTAL_ARTIFACT_BYTES)) {
  findings.push({ path: filePath, reason: 'oversized artifact' })
  continue
}

const content = readContent(filePath)
if (typeof content !== 'string') {
  throw new TypeError('content reader did not return text')
}
const contentBytes = declaredSize ?? Buffer.byteLength(content, 'utf8')
if (contentBytes > MAX_ARTIFACT_BYTES
  || totalBytes + contentBytes > MAX_TOTAL_ARTIFACT_BYTES) {
  findings.push({ path: filePath, reason: 'oversized artifact' })
  continue
}
totalBytes += contentBytes

if (role !== 'implementation-definition' && containsPrivateSentinel(content)) {
  findings.push({ path: filePath, reason: 'private sentinel content' })
  continue
}
if (role === 'strict-artifact' && looksLikeLargeSourceText(content)) {
  findings.push({ path: filePath, reason: 'large source-like text outside reviewed assets' })
}
```

Do not add a directory-wide JSON, Markdown, test, or asset exemption.

- [ ] **Step 4: Run focused and complete script tests**

Run:

```powershell
node --test scripts/tests/scan-m2-artifacts.test.mjs
node --test scripts/tests/*.test.mjs
```

Expected: both exit 0. The focused count includes all existing tests plus five new role tests; the complete script count increases by the same five.

- [ ] **Step 5: Commit the pure role change**

```powershell
git add scripts/scan-m2-artifacts.mjs scripts/tests/scan-m2-artifacts.test.mjs
git diff --cached --check
git commit -m "fix: classify M2 repository artifacts"
```

Expected: one commit containing only the artifact scanner and its tests.

### Task 2: Make the artifact CLI read committed HEAD

**Files:**
- Modify: `scripts/tests/scan-m2-artifacts.test.mjs`
- Modify: `scripts/scan-m2-artifacts.mjs`

- [ ] **Step 1: Add failing committed-snapshot and diagnostic tests**

Add the filesystem imports and helper below to the artifact test file:

```javascript
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import os from 'node:os'

function runGit(cwd, args) {
  const result = spawnSync('git', args, {
    cwd,
    encoding: 'utf8',
    shell: false,
  })
  assert.equal(result.status, 0, result.stderr)
  return result.stdout.trim()
}

function withTemporaryGitRepository(callback) {
  const repository = mkdtempSync(path.join(os.tmpdir(), 'm2-artifact-git-'))
  try {
    runGit(repository, ['init'])
    runGit(repository, ['config', 'user.email', 'artifact-test@example.invalid'])
    runGit(repository, ['config', 'user.name', 'Artifact Test'])
    writeFileSync(path.join(repository, '.gitkeep'), '', 'utf8')
    runGit(repository, ['add', '.gitkeep'])
    runGit(repository, ['commit', '-m', 'baseline'])
    callback(repository, runGit(repository, ['rev-parse', 'HEAD']))
  } finally {
    rmSync(repository, { recursive: true, force: true })
  }
}
```

Add these tests:

```javascript
test('artifact CLI reads committed HEAD rather than dirty worktree content', () => {
  withTemporaryGitRepository((repository, base) => {
    const evidenceDirectory = path.join(repository, 'evidence')
    const receiptPath = path.join(evidenceDirectory, 'receipt.json')
    mkdirSync(evidenceDirectory)
    writeFileSync(receiptPath, JSON.stringify({ matchCount: 0 }), 'utf8')
    runGit(repository, ['add', 'evidence/receipt.json'])
    runGit(repository, ['commit', '-m', 'safe evidence'])

    const dirtySentinel = syntheticSentinels()[0]
    writeFileSync(receiptPath, dirtySentinel, 'utf8')
    const result = spawnSync(process.execPath, [scannerPath, '--base', base], {
      cwd: repository,
      encoding: 'utf8',
      shell: false,
    })

    assert.equal(result.status, 0, result.stderr)
    assert.equal(readFileSync(receiptPath, 'utf8'), dirtySentinel)
    assert.doesNotMatch(result.stdout + result.stderr, new RegExp(dirtySentinel))
  })
})

test('artifact CLI reports committed evidence leaks by path without content', () => {
  withTemporaryGitRepository((repository, base) => {
    const evidenceDirectory = path.join(repository, 'evidence')
    mkdirSync(evidenceDirectory)
    const sentinel = syntheticSentinels()[0]
    writeFileSync(path.join(evidenceDirectory, 'receipt.json'), sentinel, 'utf8')
    runGit(repository, ['add', 'evidence/receipt.json'])
    runGit(repository, ['commit', '-m', 'unsafe evidence'])

    const result = spawnSync(process.execPath, [scannerPath, '--base', base], {
      cwd: repository,
      encoding: 'utf8',
      shell: false,
    })
    assert.equal(result.status, 1)
    assert.match(result.stdout, /evidence\/receipt\.json: private sentinel content/u)
    assert.doesNotMatch(result.stdout + result.stderr, new RegExp(sentinel))
  })
})

test('artifact CLI suppresses injected reader error content', () => {
  let stderr = ''
  const status = runArtifactScannerCli(['--base', 'approved'], {
    listChangedFiles: () => ['evidence/receipt.json'],
    readContent() {
      throw new Error('PRIVATE_READER_MESSAGE')
    },
    getSize: () => 1,
    stderr: { write(chunk) { stderr += chunk } },
  })
  assert.equal(status, 2)
  assert.equal(stderr, 'M2 artifact scan failed.\n')
  assert.doesNotMatch(stderr, /PRIVATE_READER_MESSAGE/u)
})

test('artifact CLI reads a committed source blob above the Node default buffer', () => {
  withTemporaryGitRepository((repository, base) => {
    const backendDirectory = path.join(repository, 'backend')
    mkdirSync(backendDirectory)
    writeFileSync(
      path.join(backendDirectory, 'large.py'),
      `value = "${'safe'.repeat(320_000)}"\n`,
      'utf8',
    )
    runGit(repository, ['add', 'backend/large.py'])
    runGit(repository, ['commit', '-m', 'large safe source'])
    const result = spawnSync(process.execPath, [scannerPath, '--base', base], {
      cwd: repository,
      encoding: 'utf8',
      shell: false,
    })
    assert.equal(result.status, 0, result.stderr)
    assert.equal(result.stdout, '')
  })
})
```

- [ ] **Step 2: Run focused tests to verify RED**

```powershell
node --test scripts/tests/scan-m2-artifacts.test.mjs
```

Expected: the dirty-worktree test fails because the CLI reads filesystem content, and the diagnostic test fails because the current CLI echoes the injected error message.

- [ ] **Step 3: Implement committed HEAD blob and size readers**

Remove the default `readFileSync` and `statSync` use from the CLI. Keep no filesystem fallback. Add:

```javascript
function readHeadContent(rootDirectory, filePath) {
  return spawnGit(rootDirectory, ['show', `HEAD:${filePath}`]).stdout
}

function getHeadSize(rootDirectory, filePath) {
  const result = spawnGit(rootDirectory, ['cat-file', '-s', `HEAD:${filePath}`])
  const value = Number(result.stdout.trim())
  return validateSize(value, filePath)
}
```

Set a bounded Git buffer that exceeds the scanner's 5 MiB per-file allowance:

```javascript
const MAX_GIT_OUTPUT_BYTES = 6 * 1024 * 1024
```

Add it to every `spawnSync('git', ...)` options object:

```javascript
maxBuffer: MAX_GIT_OUTPUT_BYTES,
```

Set the CLI defaults exactly as follows:

```javascript
const readContent = dependencies.readContent ?? (filePath => (
  readHeadContent(rootDirectory, filePath)
))
const getSize = dependencies.getSize ?? (filePath => (
  getHeadSize(rootDirectory, filePath)
))
```

Replace infrastructure error output with a stable message:

```javascript
} catch {
  stderr.write('M2 artifact scan failed.\n')
  return 2
}
```

Make `spawnGit` return only a stable failure without including Git stderr:

```javascript
if (result.error || result.status !== 0) throw new Error('git command failed')
```

Remove unused `readFileSync` and `statSync` imports from the scanner.

- [ ] **Step 4: Verify focused tests, all script tests, and the frozen baseline**

```powershell
node --test scripts/tests/scan-m2-artifacts.test.mjs
node --test scripts/tests/*.test.mjs
node scripts/scan-m2-artifacts.mjs --base bc0919a2f8464a552c979a9601258fb148d98cac
```

Expected: all commands exit 0. The real CLI prints nothing.

- [ ] **Step 5: Commit the HEAD snapshot boundary**

```powershell
git add scripts/scan-m2-artifacts.mjs scripts/tests/scan-m2-artifacts.test.mjs
git diff --cached --check
git commit -m "fix: scan committed M2 artifact snapshots"
```

### Task 3: Add the effective legacy-shadow gate

**Files:**
- Create: `scripts/tests/scan-effective-legacy.test.mjs`
- Create: `scripts/scan-effective-legacy.mjs`

- [ ] **Step 1: Write the missing-module RED tests**

Create `scripts/tests/scan-effective-legacy.test.mjs` with these pure contracts:

```javascript
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import {
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  RETIRED_SHADOW_PATTERNS,
  runEffectiveLegacyCli,
  scanEffectiveLegacy,
} from '../scan-effective-legacy.mjs'

const scriptsDirectory = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const repositoryRoot = path.dirname(scriptsDirectory)
const scannerPath = path.join(scriptsDirectory, 'scan-effective-legacy.mjs')

function runGit(cwd, args) {
  const result = spawnSync('git', args, {
    cwd,
    encoding: 'utf8',
    shell: false,
  })
  assert.equal(result.status, 0, result.stderr)
  return result.stdout.trim()
}

const ownDefinition = `// BEGIN RETIRED SHADOW PATTERNS
export const RETIRED_SHADOW_PATTERNS = Object.freeze([
  { code: 'phase-e', pattern: /phase-e/iu },
  { code: 'e.23', pattern: /e\\.23/iu },
  { code: 'applyAdapter', pattern: /applyAdapter/iu },
  { code: 'providerAdapter', pattern: /providerAdapter/iu },
])
// END RETIRED SHADOW PATTERNS
`

test('retired pattern inventory is exact', () => {
  assert.deepEqual(RETIRED_SHADOW_PATTERNS.map(item => ({
    code: item.code,
    source: item.pattern.source,
    flags: item.pattern.flags,
  })), [
    { code: 'phase-e', source: 'phase-e', flags: 'iu' },
    { code: 'e.23', source: 'e\\.23', flags: 'iu' },
    { code: 'applyAdapter', source: 'applyAdapter', flags: 'iu' },
    { code: 'providerAdapter', source: 'providerAdapter', flags: 'iu' },
  ])
  for (const item of RETIRED_SHADOW_PATTERNS) {
    assert.equal(item.pattern.test(item.code), true)
    for (const other of RETIRED_SHADOW_PATTERNS) {
      assert.equal(item.pattern.test(other.code), item === other)
    }
  }
})

test('excluded test paths do not create findings', () => {
  const files = [
    'backend/tests/unit/phase-e.py',
    'frontend/tests/providerAdapter.test.mjs',
    'scripts/tests/run-tests.test.mjs',
    'tools/control-plane-qa/tests/applyAdapter.test.mjs',
  ]
  assert.deepEqual(scanEffectiveLegacy({
    files,
    readContent: () => 'const providerAdapter = true',
  }), [])
})

test('own validated pattern block and gateway deny-list lines are protective', () => {
  const files = [
    'scripts/scan-effective-legacy.mjs',
    'tools/control-plane-qa/ai-proxy-gateway.mjs',
  ]
  const contents = new Map([
    [files[0], ownDefinition],
    [files[1], `const FORBIDDEN_NORMALIZED_KEYS = new Set([
  'apikey',
  'baseurl',
  'authorization',
  'headers',
  'provideradapter',
  'applyadapter'
])
`],
  ])
  assert.deepEqual(scanEffectiveLegacy({
    files,
    readContent: filePath => contents.get(filePath),
  }), [])
})

test('a second occurrence in either protective file is rejected', () => {
  const scannerFinding = scanEffectiveLegacy({
    files: ['scripts/scan-effective-legacy.mjs'],
    readContent: () => `${ownDefinition}\nconst applyAdapter = true\n`,
  })
  const gatewayFinding = scanEffectiveLegacy({
    files: ['tools/control-plane-qa/ai-proxy-gateway.mjs'],
    readContent: () => `const FORBIDDEN_NORMALIZED_KEYS = new Set([
  'apikey',
  'baseurl',
  'authorization',
  'headers',
  'provideradapter',
  'provideradapter',
  'applyadapter'
])
`,
  })
  assert.deepEqual(scannerFinding, [{
    path: 'scripts/scan-effective-legacy.mjs',
    reason: 'retired shadow reference',
  }])
  assert.deepEqual(gatewayFinding, [{
    path: 'tools/control-plane-qa/ai-proxy-gateway.mjs',
    reason: 'retired shadow reference',
  }])
})

test('gateway adapter deny entries must both exist as the final unique entries', () => {
  const invalidSources = [
    `const FORBIDDEN_NORMALIZED_KEYS = new Set([
  'apikey',
  'provideradapter'
])
`,
    `const FORBIDDEN_NORMALIZED_KEYS = new Set([
  'provideradapter',
  'apikey',
  'applyadapter'
])
`,
  ]
  for (const source of invalidSources) {
    assert.deepEqual(scanEffectiveLegacy({
      files: ['tools/control-plane-qa/ai-proxy-gateway.mjs'],
      readContent: () => source,
    }), [{
      path: 'tools/control-plane-qa/ai-proxy-gateway.mjs',
      reason: 'retired shadow reference',
    }])
  }
})

test('the scanner rejects a malformed own protective block', () => {
  const malformed = ownDefinition.replace(
    "  { code: 'e.23', pattern: /e\\.23/iu },",
    "  { code: 'e.23', pattern: /e\\.23/iu },\n  const applyAdapter = true",
  )
  assert.throws(() => scanEffectiveLegacy({
    files: ['scripts/scan-effective-legacy.mjs'],
    readContent: () => malformed,
  }), /invalid retired pattern block/u)
})

test('invalid tracked paths fail before content reads', () => {
  let reads = 0
  assert.throws(() => scanEffectiveLegacy({
    files: ['C:\\outside\\providerAdapter.mjs'],
    readContent() { reads += 1; return '' },
  }), /outside repository/u)
  assert.equal(reads, 0)
})

test('effective paths reject retired names in paths and content', () => {
  const files = [
    'backend/scripts/phase-e-runner.py',
    'frontend/e2e/formal.spec.ts',
    'scripts/runner.mjs',
    'tools/qa/helper.mjs',
    'package.json',
  ]
  const contents = new Map([
    [files[0], 'print(1)'],
    [files[1], "const value = 'e.23'"],
    [files[2], 'const applyAdapter = true'],
    [files[3], 'const providerAdapter = true'],
    [files[4], JSON.stringify({ scripts: { qa: 'phase-e' } })],
  ])
  assert.deepEqual(scanEffectiveLegacy({
    files,
    readContent: filePath => contents.get(filePath),
  }), files.map(filePath => ({
    path: filePath,
    reason: 'retired shadow reference',
  })))
})

test('CLI fails closed without echoing reader errors', () => {
  let stderr = ''
  const status = runEffectiveLegacyCli([], {
    listFiles: () => ['backend/main.py'],
    readContent() { throw new Error('PRIVATE_LEGACY_READER_MESSAGE') },
    stderr: { write(chunk) { stderr += chunk } },
  })
  assert.equal(status, 2)
  assert.equal(stderr, 'Effective legacy scan failed.\n')
  assert.doesNotMatch(stderr, /PRIVATE_LEGACY_READER_MESSAGE/u)
})

test('CLI rejects arguments before reading Git', () => {
  let listCalls = 0
  let stderr = ''
  const status = runEffectiveLegacyCli(['unexpected'], {
    listFiles() { listCalls += 1; return [] },
    stderr: { write(chunk) { stderr += chunk } },
  })
  assert.equal(status, 2)
  assert.equal(listCalls, 0)
  assert.equal(stderr, 'usage: node scripts/scan-effective-legacy.mjs\n')
})

test('real committed HEAD effective scan is clean', () => {
  const result = spawnSync(process.execPath, [scannerPath], {
    cwd: repositoryRoot,
    encoding: 'utf8',
    shell: false,
  })
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout, '')
})

test('effective legacy CLI reads committed HEAD rather than dirty worktree content', () => {
  const repository = mkdtempSync(path.join(os.tmpdir(), 'm2-legacy-git-'))
  try {
    runGit(repository, ['init'])
    runGit(repository, ['config', 'user.email', 'legacy-test@example.invalid'])
    runGit(repository, ['config', 'user.name', 'Legacy Test'])
    writeFileSync(path.join(repository, '.gitkeep'), '', 'utf8')
    runGit(repository, ['add', '.gitkeep'])
    runGit(repository, ['commit', '-m', 'baseline'])
    mkdirSync(path.join(repository, 'backend'))
    const sourcePath = path.join(repository, 'backend', 'main.py')
    writeFileSync(
      sourcePath,
      `value = "${'safe'.repeat(320_000)}"\n`,
      'utf8',
    )
    runGit(repository, ['add', 'backend/main.py'])
    runGit(repository, ['commit', '-m', 'safe source'])

    writeFileSync(sourcePath, 'applyAdapter = True\n', 'utf8')
    const dirtyResult = spawnSync(process.execPath, [scannerPath], {
      cwd: repository,
      encoding: 'utf8',
      shell: false,
    })
    assert.equal(dirtyResult.status, 0, dirtyResult.stderr)

    runGit(repository, ['add', 'backend/main.py'])
    runGit(repository, ['commit', '-m', 'unsafe source'])
    const committedResult = spawnSync(process.execPath, [scannerPath], {
      cwd: repository,
      encoding: 'utf8',
      shell: false,
    })
    assert.equal(committedResult.status, 1)
    assert.equal(
      committedResult.stdout,
      'backend/main.py: retired shadow reference\n',
    )
    assert.doesNotMatch(committedResult.stdout, /applyAdapter/u)
  } finally {
    rmSync(repository, { recursive: true, force: true })
  }
})
```

- [ ] **Step 2: Run the new test to verify RED**

```powershell
node --test scripts/tests/scan-effective-legacy.test.mjs
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `scripts/scan-effective-legacy.mjs`.

- [ ] **Step 3: Implement the pure scanner and committed-HEAD CLI**

Create `scripts/scan-effective-legacy.mjs`. Use this public structure and exact protective pattern block:

```javascript
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SCANNER_PATH = 'scripts/scan-effective-legacy.mjs'
const GATEWAY_PATH = 'tools/control-plane-qa/ai-proxy-gateway.mjs'
const EFFECTIVE_PREFIXES = ['backend/', 'frontend/', 'scripts/', 'tools/']
const EXCLUDED_TEST_PATHS = [
  /^backend\/tests\//u,
  /^frontend\/tests\//u,
  /^scripts\/tests\//u,
  /^tools\/(?:.+\/)?tests\//u,
]
const BLOCK_START = '// BEGIN RETIRED SHADOW PATTERNS'
const BLOCK_END = '// END RETIRED SHADOW PATTERNS'

// BEGIN RETIRED SHADOW PATTERNS
export const RETIRED_SHADOW_PATTERNS = Object.freeze([
  { code: 'phase-e', pattern: /phase-e/iu },
  { code: 'e.23', pattern: /e\.23/iu },
  { code: 'applyAdapter', pattern: /applyAdapter/iu },
  { code: 'providerAdapter', pattern: /providerAdapter/iu },
])
// END RETIRED SHADOW PATTERNS
```

Implement normalization and effective-path selection without filesystem access:

```javascript
function normalizeRepositoryPath(value) {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new TypeError('tracked path must be non-empty')
  }
  if (path.win32.isAbsolute(value) || /^[A-Za-z]:/u.test(value)) {
    throw new Error('tracked path is outside repository')
  }
  const normalized = path.posix.normalize(value.replaceAll('\\', '/').replace(/^\.\//u, ''))
  if (path.posix.isAbsolute(normalized)
    || normalized === '..'
    || normalized.startsWith('../')) {
    throw new Error('tracked path is outside repository')
  }
  return normalized
}

function isEffectivePath(filePath) {
  if (filePath === 'package.json') return true
  if (!EFFECTIVE_PREFIXES.some(prefix => filePath.startsWith(prefix))) return false
  return !EXCLUDED_TEST_PATHS.some(pattern => pattern.test(filePath))
}
```

Validate and remove only the scanner's own definition block. The runtime values
reconstruct all six exact source lines, while the unit test independently freezes
the four code/regex-source/flag triples. This permits no extra or weakened line:

```javascript
function removeOwnPatternBlock(source) {
  const lines = source.split(/\r?\n/u)
  const starts = lines.flatMap((line, index) => line === BLOCK_START ? [index] : [])
  const ends = lines.flatMap((line, index) => line === BLOCK_END ? [index] : [])
  if (starts.length !== 1 || ends.length !== 1 || ends[0] <= starts[0]) {
    throw new Error('invalid retired pattern block')
  }
  const block = lines.slice(starts[0] + 1, ends[0])
  const expectedBlock = [
    'export const RETIRED_SHADOW_PATTERNS = Object.freeze([',
    ...RETIRED_SHADOW_PATTERNS.map(item => (
      `  { code: '${item.code}', pattern: /${item.pattern.source}/${item.pattern.flags} },`
    )),
    '])',
  ]
  if (JSON.stringify(block) !== JSON.stringify(expectedBlock)) {
    throw new Error('invalid retired pattern block')
  }
  return lines.map((line, index) => (
    index >= starts[0] && index <= ends[0] ? '' : line
  )).join('\n')
}
```

Validate the gateway exception as exactly one `FORBIDDEN_NORMALIZED_KEYS` block
whose final two entries are the two unique alphabetic adapter patterns. A missing,
moved, or duplicate entry returns `null` and therefore becomes a finding. Strip
only the two validated lines:

```javascript
function removeGatewayProtectiveEntries(source) {
  const lines = source.split(/\r?\n/u)
  const declaration = 'const FORBIDDEN_NORMALIZED_KEYS = new Set(['
  const starts = lines.flatMap((line, index) => line === declaration ? [index] : [])
  if (starts.length !== 1) return null
  const end = lines.findIndex((line, index) => index > starts[0] && line === '])')
  if (end < 0) return null

  const entryLines = lines.slice(starts[0] + 1, end)
  const tokens = entryLines.map(line => {
    const match = /^  '([a-z]+)'[,]?$/u.exec(line)
    return match?.[1] ?? null
  })
  if (tokens.some(token => token === null)) return null

  const expected = new Set(RETIRED_SHADOW_PATTERNS
    .filter(item => !/[-.]/u.test(item.code))
    .map(item => item.code.toLowerCase()))
  const protectedIndices = tokens.flatMap((token, index) => (
    expected.has(token) ? [index] : []
  ))
  const protectedTokens = new Set(protectedIndices.map(index => tokens[index]))
  if (protectedIndices.length !== 2
    || protectedTokens.size !== 2
    || protectedIndices[0] !== tokens.length - 2
    || protectedIndices[1] !== tokens.length - 1) {
    return null
  }

  const absoluteProtected = new Set(protectedIndices.map(index => starts[0] + 1 + index))
  return lines.map((line, index) => absoluteProtected.has(index) ? '' : line).join('\n')
}
```

Implement one bounded finding per effective file:

```javascript
export function scanEffectiveLegacy({ files, readContent }) {
  if (!Array.isArray(files)) throw new TypeError('files must be an array')
  if (typeof readContent !== 'function') throw new TypeError('readContent must be a function')

  const findings = []
  for (const rawPath of files) {
    const filePath = normalizeRepositoryPath(rawPath)
    if (!isEffectivePath(filePath)) continue
    if (RETIRED_SHADOW_PATTERNS.some(item => item.pattern.test(filePath))) {
      findings.push({ path: filePath, reason: 'retired shadow reference' })
      continue
    }

    const rawSource = readContent(filePath)
    if (typeof rawSource !== 'string') throw new TypeError('content reader did not return text')
    let source = rawSource
    if (filePath === SCANNER_PATH) source = removeOwnPatternBlock(source)
    if (filePath === GATEWAY_PATH) {
      source = removeGatewayProtectiveEntries(source)
      if (source === null) {
        findings.push({ path: filePath, reason: 'retired shadow reference' })
        continue
      }
    }
    const lines = source.split(/\r?\n/u)
    const unsafe = lines.some(line => (
      RETIRED_SHADOW_PATTERNS.some(item => item.pattern.test(line))
    ))
    if (unsafe) findings.push({ path: filePath, reason: 'retired shadow reference' })
  }
  return findings
}
```

Implement Git HEAD inventory/read and the CLI with `shell:false`, no arguments, stable status, and no raw errors:

```javascript
function spawnGit(rootDirectory, args) {
  const result = spawnSync('git', args, {
    cwd: rootDirectory,
    encoding: 'utf8',
    maxBuffer: 6 * 1024 * 1024,
    shell: false,
  })
  if (result.error || result.status !== 0) throw new Error('git command failed')
  return result.stdout
}

function listHeadFiles(rootDirectory) {
  return spawnGit(rootDirectory, [
    'ls-tree', '-r', '--name-only', 'HEAD', '--',
    'backend', 'frontend', 'scripts', 'tools', 'package.json',
  ]).split(/\r?\n/u).map(value => value.trim()).filter(Boolean)
}

function readHeadContent(rootDirectory, filePath) {
  return spawnGit(rootDirectory, ['show', `HEAD:${filePath}`])
}

export function runEffectiveLegacyCli(args = process.argv.slice(2), dependencies = {}) {
  const stderr = dependencies.stderr ?? process.stderr
  const stdout = dependencies.stdout ?? process.stdout
  if (args.length !== 0) {
    stderr.write('usage: node scripts/scan-effective-legacy.mjs\n')
    return 2
  }
  const rootDirectory = dependencies.rootDirectory ?? process.cwd()
  const listFiles = dependencies.listFiles ?? (() => listHeadFiles(rootDirectory))
  const readContent = dependencies.readContent ?? (filePath => (
    readHeadContent(rootDirectory, filePath)
  ))
  let findings
  try {
    findings = scanEffectiveLegacy({ files: listFiles(), readContent })
  } catch {
    stderr.write('Effective legacy scan failed.\n')
    return 2
  }
  for (const finding of findings) {
    stdout.write(`${finding.path}: ${finding.reason}\n`)
  }
  return findings.length === 0 ? 0 : 1
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : ''
if (invokedPath && path.resolve(fileURLToPath(import.meta.url)) === invokedPath) {
  process.exitCode = runEffectiveLegacyCli()
}
```

- [ ] **Step 4: Run focused tests and resolve only contract defects**

```powershell
node --test scripts/tests/scan-effective-legacy.test.mjs
```

Expected: all tests except `real committed HEAD effective scan is clean` pass before the new file is committed. The real-HEAD test may still execute the previous HEAD where the new scanner is absent from inventory; it must still return 0. Do not weaken a finding to make the test pass.

- [ ] **Step 5: Run all script tests and commit**

```powershell
node --test scripts/tests/*.test.mjs
git add scripts/scan-effective-legacy.mjs scripts/tests/scan-effective-legacy.test.mjs
git diff --cached --check
git commit -m "test: scan effective legacy paths"
node scripts/scan-effective-legacy.mjs
```

Expected: tests and post-commit real HEAD scan exit 0; the real scanner prints nothing.

### Task 4: Replace raw acceptance commands with official gates

**Files:**
- Modify: `scripts/tests/scan-effective-legacy.test.mjs`
- Modify: `docs/superpowers/plans/2026-07-11-m2e-verification-and-live-acceptance.md`
- Modify: `docs/superpowers/plans/2026-07-16-formal-test-runner-pytest-temp.md`

- [ ] **Step 1: Add a failing documentation contract test**

Add `readFileSync` to the test imports and this test:

```javascript
import { readFileSync } from 'node:fs'

test('formal plans require the frozen artifact base and official legacy gate', () => {
  const planPaths = [
    'docs/superpowers/plans/2026-07-11-m2e-verification-and-live-acceptance.md',
    'docs/superpowers/plans/2026-07-16-formal-test-runner-pytest-temp.md',
  ]
  for (const planPath of planPaths) {
    const content = readFileSync(path.join(repositoryRoot, planPath), 'utf8')
    assert.match(content, /bc0919a2f8464a552c979a9601258fb148d98cac/u)
    assert.match(content, /b9b19e8ebdeefc3f88e547042cfc925da4adb1cf/u)
    assert.match(content, /node scripts\/scan-m2-artifacts\.mjs --base \$env:APPROVED_M2_PLAN_COMMIT/u)
    assert.match(content, /node scripts\/scan-effective-legacy\.mjs/u)
    assert.doesNotMatch(content, /\$legacyMatches\s*=\s*@\(git diff/iu)
  }
})
```

- [ ] **Step 2: Run the documentation contract to verify RED**

```powershell
node --test scripts/tests/scan-effective-legacy.test.mjs
```

Expected: FAIL because both plans still contain the raw diff/grep acceptance command and do not record the exact full baseline next to the gate.

- [ ] **Step 3: Update both formal acceptance blocks**

Replace each raw artifact/legacy scan block with exactly:

```powershell
$approvedM2PlanCommit = 'bc0919a2f8464a552c979a9601258fb148d98cac'
if (-not $env:APPROVED_M2_PLAN_COMMIT) {
    throw 'APPROVED_M2_PLAN_COMMIT is required'
}
if ($env:APPROVED_M2_PLAN_COMMIT -ne $approvedM2PlanCommit) {
    throw 'APPROVED_M2_PLAN_COMMIT does not match the frozen M2 plan baseline'
}
node scripts/scan-m2-artifacts.mjs --base $env:APPROVED_M2_PLAN_COMMIT
if ($LASTEXITCODE -ne 0) { throw 'M2 artifact gate failed' }
node scripts/scan-effective-legacy.mjs
if ($LASTEXITCODE -ne 0) { throw 'Effective legacy gate failed' }
```

Immediately below the block, state:

```markdown
The diff baseline remains `bc0919a2f8464a552c979a9601258fb148d98cac`.
The later `b9b19e8ebdeefc3f88e547042cfc925da4adb1cf` commit is the normative
10-style/64-card plan amendment and does not reset the implementation baseline.
```

Do not rewrite other historical task instructions.

- [ ] **Step 4: Verify documentation and all script contracts**

```powershell
node --test scripts/tests/scan-effective-legacy.test.mjs
node --test scripts/tests/*.test.mjs
```

Expected: all tests exit 0.

- [ ] **Step 5: Commit the acceptance command switch**

```powershell
git add scripts/tests/scan-effective-legacy.test.mjs docs/superpowers/plans/2026-07-11-m2e-verification-and-live-acceptance.md docs/superpowers/plans/2026-07-16-formal-test-runner-pytest-temp.md
git diff --cached --check
git commit -m "docs: use typed M2 repository gates"
```

### Task 5: Run full non-live acceptance and independent review

**Files:**
- No product-code changes expected.
- No product database, corpus import, service session, browser outside the formal disposable runner, or Provider call is authorized.

- [ ] **Step 1: Verify the worktree environment and official gates**

```powershell
$venvPython = (Resolve-Path .\.venv-m2\Scripts\python.exe).Path
$env:PYTHON = $venvPython
$env:APPROVED_M2_PLAN_COMMIT = 'bc0919a2f8464a552c979a9601258fb148d98cac'

& $venvPython --version
& $venvPython -m pip --version
& $venvPython -m pip check
& $venvPython -m backend.scripts.verify_runtime_versions --test-mysql
node --version
npm --version
npm --prefix frontend exec playwright -- --version
node scripts/scan-m2-artifacts.mjs --base $env:APPROVED_M2_PLAN_COMMIT
node scripts/scan-effective-legacy.mjs
```

Expected:

- Python `3.12.10`, pip `25.0.1`, and `No broken requirements found`;
- runtime receipt contains MySQL `8.4.10` and no credentials;
- Node `v24.13.0`, npm `11.6.2`, Playwright `1.61.1`;
- both repository gates exit 0 and print no findings.

- [ ] **Step 2: Run focused and aggregate tests from the isolated environment**

```powershell
$venvPython = (Resolve-Path .\.venv-m2\Scripts\python.exe).Path
$env:PYTHON = $venvPython
node --test scripts/tests/scan-m2-artifacts.test.mjs scripts/tests/scan-effective-legacy.test.mjs
node --test scripts/tests/*.test.mjs
npm run test:milestone2
```

Expected:

- focused and all-script suites exit 0;
- retained M1 Python 310 and frontend 23 pass;
- backend unit/API 1260 pass with the same 3 platform skips;
- all script and frontend unit tests pass with their new increased counts;
- disposable MySQL integration 161 passes with `created=161 cleaned=161 remaining=0`;
- the four guarded Playwright goals complete silently and the aggregate exits 0.

- [ ] **Step 3: Build and compile**

```powershell
$venvPython = (Resolve-Path .\.venv-m2\Scripts\python.exe).Path
npm --prefix frontend run build
& $venvPython -m compileall -q backend
```

Expected: Vite transforms 2857 modules and exits 0; compileall exits 0.

- [ ] **Step 4: Prove cleanup and repository hygiene**

Run this read-only disposable-database residue query:

```powershell
$venvPython = (Resolve-Path .\.venv-m2\Scripts\python.exe).Path
@'
import asyncio
import os
import aiomysql

async def main():
    connection = await aiomysql.connect(
        host=os.environ['TEST_MYSQL_HOST'],
        port=int(os.environ['TEST_MYSQL_PORT']),
        user=os.environ['TEST_MYSQL_USER'],
        password=os.environ['TEST_MYSQL_PASSWORD'],
    )
    try:
        cursor = await connection.cursor(aiomysql.DictCursor)
        try:
            await cursor.execute(
                "SELECT COUNT(*) AS count FROM information_schema.SCHEMATA "
                "WHERE SCHEMA_NAME LIKE 'novel_creator_test_%'"
            )
            row = await cursor.fetchone()
            print(f"DISPOSABLE_DATABASES_REMAINING={row['count']}")
        finally:
            await cursor.close()
    finally:
        connection.close()

asyncio.run(main())
'@ | & $venvPython -

if (Test-Path -LiteralPath '.codex-test-artifacts\pytest') {
    throw 'pytest artifact namespace remains'
}
git diff --check
git status --short --branch
```

Expected: `DISPOSABLE_DATABASES_REMAINING=0`, no pytest namespace, clean diff check, and no uncommitted changes.

- [ ] **Step 5: Run two-stage independent review**

Dispatch one reviewer for specification compliance against
`docs/superpowers/specs/2026-07-17-m2-artifact-and-legacy-gates-design.md`, then a
second reviewer for code quality/security. Both reviews must examine the full
diff from `0cd2d63` through HEAD and return no P0/P1/P2 before Task 5 is marked
complete. Fixes require focused RED/GREEN tests and a separate commit; rerun all
commands affected by the fix.

- [ ] **Step 6: Record the non-live boundary**

Report the exact gate/test/build results and state explicitly:

```text
M2 L1-L3 repository and disposable-browser gates are green.
Product DB rebuild, L4 human asset/corpus review, and L5 Provider acceptance remain separate explicit checkpoints.
```

Do not claim L5, chapter-writing, prose-quality, finalization, or Product Ready.
