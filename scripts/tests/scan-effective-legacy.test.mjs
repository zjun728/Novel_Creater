import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
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
const formalAcceptancePlans = [
  'docs/superpowers/plans/2026-07-11-m2e-verification-and-live-acceptance.md',
  'docs/superpowers/plans/2026-07-16-formal-test-runner-pytest-temp.md',
]
const frozenBaseline = 'bc0919a2f8464a552c979a9601258fb148d98cac'
const normativeAmendment = 'b9b19e8ebdeefc3f88e547042cfc925da4adb1cf'
const expectedFormalGateBlock = `$approvedM2PlanCommit = 'bc0919a2f8464a552c979a9601258fb148d98cac'
if (-not $env:APPROVED_M2_PLAN_COMMIT) {
    throw 'APPROVED_M2_PLAN_COMMIT is required'
}
if ($env:APPROVED_M2_PLAN_COMMIT -ne $approvedM2PlanCommit) {
    throw 'APPROVED_M2_PLAN_COMMIT does not match the frozen M2 plan baseline'
}
node scripts/scan-m2-artifacts.mjs --base $env:APPROVED_M2_PLAN_COMMIT
if ($LASTEXITCODE -ne 0) { throw 'M2 artifact gate failed' }
node scripts/scan-effective-legacy.mjs
if ($LASTEXITCODE -ne 0) { throw 'Effective legacy gate failed' }`
const expectedFormalAmendmentParagraph = `The diff baseline remains \`bc0919a2f8464a552c979a9601258fb148d98cac\`.
The later \`b9b19e8ebdeefc3f88e547042cfc925da4adb1cf\` commit is the normative
10-style/64-card plan amendment and does not reset the implementation baseline.`
const rawLegacyAssignmentPattern = (
  /\$legacyMatches\s*=\s*@\(\s*git\s+diff/iu
)

const ownDefinition = `// BEGIN RETIRED SHADOW PATTERNS
export const RETIRED_SHADOW_PATTERNS = Object.freeze([
  { code: 'phase-e', pattern: /phase-e/iu },
  { code: 'e.23', pattern: /e\\.23/iu },
  { code: 'applyAdapter', pattern: /applyAdapter/iu },
  { code: 'providerAdapter', pattern: /providerAdapter/iu },
])
// END RETIRED SHADOW PATTERNS
`

const syntheticBlobId = '1'.repeat(40)

function lsTreeRecord(filePath, {
  mode = '100644',
  object = syntheticBlobId,
  type = 'blob',
} = {}) {
  return `${mode} ${type} ${object}\t${filePath}\0`
}

function runGit(cwd, args) {
  const result = spawnSync('git', args, {
    cwd,
    encoding: 'utf8',
    shell: false,
  })
  assert.equal(result.error, undefined)
  assert.equal(result.status, 0, result.stderr)
  return result.stdout.trim()
}

function writeRepositoryFile(rootDirectory, filePath, content) {
  const absolutePath = path.join(rootDirectory, ...filePath.split('/'))
  mkdirSync(path.dirname(absolutePath), { recursive: true })
  writeFileSync(absolutePath, content, 'utf8')
  return absolutePath
}

function commitRepositoryFile(rootDirectory, filePath, content, message) {
  const absolutePath = writeRepositoryFile(rootDirectory, filePath, content)
  runGit(rootDirectory, ['add', '--', filePath])
  runGit(rootDirectory, ['commit', '-m', message])
  return absolutePath
}

function createTemporaryGitRepository(t) {
  const rootDirectory = mkdtempSync(path.join(os.tmpdir(), 'effective-legacy-'))
  t.after(() => rmSync(rootDirectory, { recursive: true, force: true }))
  runGit(rootDirectory, ['init'])
  runGit(rootDirectory, ['config', 'user.email', 'legacy-test@example.invalid'])
  runGit(rootDirectory, ['config', 'user.name', 'Legacy Test'])
  commitRepositoryFile(rootDirectory, '.gitkeep', '', 'baseline')
  return rootDirectory
}

function runScanner(rootDirectory) {
  return spawnSync(process.execPath, [scannerPath], {
    cwd: rootDirectory,
    encoding: 'utf8',
    shell: false,
  })
}

function captureCli(dependencies = {}, args = []) {
  let stdout = ''
  let stderr = ''
  const status = runEffectiveLegacyCli(args, {
    ...dependencies,
    stderr: { write(chunk) { stderr += chunk } },
    stdout: { write(chunk) { stdout += chunk } },
  })
  return { status, stderr, stdout }
}

function countOccurrences(source, fragment) {
  return source.split(fragment).length - 1
}

function assertFormalAcceptancePlanContract(source) {
  const normalizedSource = source.replaceAll('\r\n', '\n')
  assert.equal(
    countOccurrences(normalizedSource, expectedFormalGateBlock),
    1,
    'formal acceptance plan must contain exactly one approved gate block',
  )
  assert.equal(
    countOccurrences(normalizedSource, expectedFormalAmendmentParagraph),
    1,
    'formal acceptance plan must contain exactly one baseline amendment paragraph',
  )
  assert.doesNotMatch(
    normalizedSource,
    rawLegacyAssignmentPattern,
    'formal acceptance plan must not contain a raw legacy diff assignment',
  )
}

test('formal acceptance plans use the frozen baseline and typed repository gates', async t => {
  for (const relativePath of formalAcceptancePlans) {
    await t.test(relativePath, () => {
      const source = readFileSync(
        path.join(repositoryRoot, ...relativePath.split('/')),
        'utf8',
      )

      assertFormalAcceptancePlanContract(source)
    })
  }
})

test('formal acceptance plan contract accepts CRLF line endings', () => {
  const validSource = [
    expectedFormalGateBlock,
    expectedFormalAmendmentParagraph,
  ].join('\n\n')

  assert.doesNotThrow(
    () => assertFormalAcceptancePlanContract(validSource.replaceAll('\n', '\r\n')),
  )
})

test('formal acceptance plan contract rejects a swapped baseline assignment', () => {
  const validSource = [
    expectedFormalGateBlock,
    expectedFormalAmendmentParagraph,
  ].join('\n\n')
  const swappedBaselineSource = validSource.replace(
    `$approvedM2PlanCommit = '${frozenBaseline}'`,
    `$approvedM2PlanCommit = '${normativeAmendment}'`,
  )

  assert.throws(
    () => assertFormalAcceptancePlanContract(swappedBaselineSource),
    /exactly one approved gate block/u,
  )
})

test('formal acceptance plan contract rejects a whitespace-obfuscated raw scan', () => {
  const validSource = [
    expectedFormalGateBlock,
    expectedFormalAmendmentParagraph,
  ].join('\n\n')
  const spacedRawSource = [
    validSource,
    '$legacyMatches  =  @(\n  git   diff baseline...HEAD\n)',
  ].join('\n\n')

  assert.throws(
    () => assertFormalAcceptancePlanContract(spacedRawSource),
    /must not contain a raw legacy diff assignment/u,
  )
})

test('retired pattern inventory is exact and each pattern matches only its own code', () => {
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
    for (const other of RETIRED_SHADOW_PATTERNS) {
      assert.equal(item.pattern.test(other.code), item === other)
    }
  }
})

test('only the four exact test path classes are excluded', () => {
  const files = [
    'backend/tests/unit/phase-e.py',
    'frontend/tests/providerAdapter.test.mjs',
    'scripts/tests/e.23.test.mjs',
    'tools/tests/applyAdapter.test.mjs',
    'tools/control-plane-qa/tests/providerAdapter.test.mjs',
  ]
  let reads = 0

  assert.deepEqual(scanEffectiveLegacy({
    files,
    readContent() {
      reads += 1
      return 'const providerAdapter = true'
    },
  }), [])
  assert.equal(reads, 0)
})

test('effective production paths match retired terms in paths and content case-insensitively', () => {
  const files = [
    'backend/scripts/PHASE-E-runner.py',
    'frontend/e2e/formal.spec.ts',
    'scripts/runner.mjs',
    'tools/qa/helper.mjs',
    'package.json',
  ]
  const contents = new Map([
    [files[0], 'print(1)'],
    [files[1], "const value = 'E.23'"],
    [files[2], 'const APPLYADAPTER = true'],
    [files[3], 'const ProviderAdapter = true'],
    [files[4], JSON.stringify({ scripts: { qa: 'phase-E' } })],
  ])

  assert.deepEqual(scanEffectiveLegacy({
    files,
    readContent: filePath => contents.get(filePath),
  }), files.map(filePath => ({
    path: filePath,
    reason: 'retired shadow reference',
  })))
})

test('paths outside the effective roots are ignored without content reads', () => {
  let reads = 0
  assert.deepEqual(scanEffectiveLegacy({
    files: ['docs/providerAdapter.md', 'tmp/phase-e.mjs', 'package-lock.json'],
    readContent() {
      reads += 1
      return 'applyAdapter'
    },
  }), [])
  assert.equal(reads, 0)
})

test('the pure scanner normalizes Windows separators and emits at most one finding per file', () => {
  const readPaths = []
  assert.deepEqual(scanEffectiveLegacy({
    files: ['frontend\\e2e\\formal.spec.ts', 'frontend/e2e/formal.spec.ts'],
    readContent(filePath) {
      readPaths.push(filePath)
      return 'applyAdapter providerAdapter phase-e'
    },
  }), [{
    path: 'frontend/e2e/formal.spec.ts',
    reason: 'retired shadow reference',
  }])
  assert.deepEqual(readPaths, ['frontend/e2e/formal.spec.ts'])
})

test('the exact own pattern block is the only protective source exception', () => {
  assert.deepEqual(scanEffectiveLegacy({
    files: ['scripts/scan-effective-legacy.mjs'],
    readContent: () => ownDefinition,
  }), [])
})

test('a retired term outside the scanner own block is rejected', () => {
  assert.deepEqual(scanEffectiveLegacy({
    files: ['scripts/scan-effective-legacy.mjs'],
    readContent: () => `${ownDefinition}\nconst applyAdapter = true\n`,
  }), [{
    path: 'scripts/scan-effective-legacy.mjs',
    reason: 'retired shadow reference',
  }])
})

test('the scanner throws for missing, duplicated, misplaced, or weakened own blocks', () => {
  const invalidSources = [
    ownDefinition.replace('// BEGIN RETIRED SHADOW PATTERNS\n', ''),
    ownDefinition.replace(
      '// END RETIRED SHADOW PATTERNS',
      '// BEGIN RETIRED SHADOW PATTERNS\n// END RETIRED SHADOW PATTERNS',
    ),
    ownDefinition.replace(
      '// BEGIN RETIRED SHADOW PATTERNS',
      '// END RETIRED SHADOW PATTERNS',
    ),
    ownDefinition.replace(
      "  { code: 'e.23', pattern: /e\\.23/iu },",
      "  { code: 'e.23', pattern: /e.23/iu },",
    ),
    ownDefinition.replace(
      "  { code: 'e.23', pattern: /e\\.23/iu },",
      "  { code: 'e.23', pattern:\n/e\\.23/iu },",
    ),
  ]

  for (const source of invalidSources) {
    assert.throws(() => scanEffectiveLegacy({
      files: ['scripts/scan-effective-legacy.mjs'],
      readContent: () => source,
    }), /^Error: invalid retired pattern block$/u)
  }
})

test('invalid tracked paths fail before any content read', () => {
  const invalidPaths = [
    '',
    '   ',
    '/absolute/providerAdapter.mjs',
    'C:\\outside\\providerAdapter.mjs',
    'C:outside\\providerAdapter.mjs',
    '..\\outside\\providerAdapter.mjs',
    'backend/../../outside/providerAdapter.mjs',
  ]

  for (const filePath of invalidPaths) {
    let reads = 0
    assert.throws(() => scanEffectiveLegacy({
      files: ['backend/safe.py', filePath],
      readContent() {
        reads += 1
        return ''
      },
    }), /non-empty|outside repository/u)
    assert.equal(reads, 0)
  }
})

test('the pure scanner fails closed for reader exceptions and non-string content', () => {
  assert.throws(() => scanEffectiveLegacy({
    files: ['backend/main.py'],
    readContent() {
      throw new Error('PRIVATE_PURE_READER_ERROR')
    },
  }), /PRIVATE_PURE_READER_ERROR/u)

  for (const content of [undefined, null, Buffer.from('safe')]) {
    assert.throws(() => scanEffectiveLegacy({
      files: ['backend/main.py'],
      readContent: () => content,
    }), /content reader did not return text/u)
  }
})

test('CLI rejects arguments before inventory access', () => {
  let listCalls = 0
  const result = captureCli({
    listFiles() {
      listCalls += 1
      return []
    },
  }, ['unexpected'])

  assert.deepEqual(result, {
    status: 2,
    stderr: 'usage: node scripts/scan-effective-legacy.mjs\n',
    stdout: '',
  })
  assert.equal(listCalls, 0)
})

test('CLI infrastructure failures use one fixed diagnostic without leaking details', () => {
  const privateMessage = 'PRIVATE_LEGACY_READER_MESSAGE'
  const result = captureCli({
    listFiles: () => ['backend/main.py'],
    readContent() {
      throw new Error(privateMessage)
    },
  })

  assert.deepEqual(result, {
    status: 2,
    stderr: 'Effective legacy scan failed.\n',
    stdout: '',
  })
  assert.equal((result.stdout + result.stderr).includes(privateMessage), false)
})

test('CLI findings contain only escaped paths and the stable reason', () => {
  const filePath = 'backend/ leading\n控制-phase-e.py'
  const result = captureCli({
    listFiles: () => [filePath],
    readContent: () => assert.fail('path findings do not need content'),
  })

  assert.deepEqual(result, {
    status: 1,
    stderr: '',
    stdout: 'backend/ leading\\n控制-phase-e.py: retired shadow reference\n',
  })
})

test('CLI findings escape injected C1 controls without leaking raw diagnostics', () => {
  const filePath = 'backend/csi\u009B-phase-e.py'
  const result = captureCli({
    listFiles: () => [filePath],
    readContent: () => assert.fail('path findings do not need content'),
  })

  assert.deepEqual(result, {
    status: 1,
    stderr: '',
    stdout: 'backend/csi\\u009b-phase-e.py: retired shadow reference\n',
  })
  assert.equal(result.stdout.split('\n').length, 2)
  assert.equal(result.stdout.includes('\u009B'), false)
})

test('a fully injected CLI accepts Windows paths and never touches Git', () => {
  const missingRoot = path.join(
    os.tmpdir(),
    `missing-effective-legacy-root-${process.pid}-${Date.now()}`,
  )
  const readPaths = []
  const result = captureCli({
    listFiles: () => ['backend\\main.py'],
    readContent(filePath) {
      readPaths.push(filePath)
      return 'safe'
    },
    rootDirectory: missingRoot,
    spawnSyncImpl: () => assert.fail('fully injected CLI must not spawn Git'),
  })

  assert.deepEqual(result, { status: 0, stderr: '', stdout: '' })
  assert.deepEqual(readPaths, ['backend/main.py'])
})

test('default Git orchestration batches inventory and skips safe noncandidate content', () => {
  const calls = []
  const result = captureCli({
    rootDirectory: 'synthetic-root',
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      if (args[0] === 'ls-tree') {
        return {
          status: 0,
          stdout: [
            lsTreeRecord('backend/ leading.py'),
            lsTreeRecord('backend/证据.py'),
          ].join(''),
        }
      }
      if (args[0] === 'grep') return { status: 1, stdout: '' }
      if (args[0] === 'cat-file') return { status: 0, stdout: 'blob\n' }
      if (args[0] === 'show') return { status: 0, stdout: 'safe\n' }
      return { status: 1, stdout: '', stderr: 'unexpected private git detail' }
    },
  })

  assert.deepEqual(result, { status: 0, stderr: '', stdout: '' })
  assert.deepEqual(calls.map(call => call.args), [
    [
      'ls-tree', '-r', '-z', 'HEAD', '--',
      'backend', 'frontend', 'scripts', 'tools', 'package.json',
    ],
    [
      'grep', '-z', '-l', '-i', '-F',
      '-e', 'phase-e',
      '-e', 'pha\u017Fe-e',
      '-e', 'e.23',
      '-e', 'applyAdapter',
      '-e', 'providerAdapter',
      'HEAD', '--',
      'backend', 'frontend', 'scripts', 'tools', 'package.json',
    ],
  ])
  for (const call of calls) {
    assert.equal(call.command, 'git')
    assert.equal(call.options.cwd, 'synthetic-root')
    assert.equal(call.options.encoding, 'utf8')
    assert.equal(call.options.maxBuffer, 6 * 1024 * 1024)
    assert.equal(call.options.shell, false)
  }
})

test('default clean orchestration uses a small constant number of Git processes', () => {
  const files = Array.from({ length: 40 }, (_value, index) => (
    `backend/safe-${index}.py`
  ))
  const calls = []
  const result = captureCli({
    rootDirectory: 'synthetic-root',
    spawnSyncImpl(_command, args) {
      calls.push(args)
      if (args[0] === 'ls-tree') {
        return {
          status: 0,
          stdout: files.map(filePath => lsTreeRecord(filePath)).join(''),
        }
      }
      if (args[0] === 'grep') return { status: 1, stdout: '' }
      if (args[0] === 'cat-file') return { status: 0, stdout: 'blob\n' }
      if (args[0] === 'show') return { status: 0, stdout: 'safe\n' }
      return { status: 2, stdout: '', stderr: 'PRIVATE_GIT_DETAIL' }
    },
  })

  assert.deepEqual(result, { status: 0, stderr: '', stdout: '' })
  assert.ok(calls.length <= 5, `expected at most 5 Git processes, received ${calls.length}`)
  assert.equal(calls.some(args => args[0] === 'cat-file'), false)
  assert.equal(calls.some(args => args[0] === 'show'), false)
})

test('default candidate grep is NUL-safe and reads only effective matching blobs', () => {
  const files = [
    'backend/safe.py',
    'backend/ leading.py',
    'backend/证据.py',
    'backend/tests/excluded.py',
  ]
  const calls = []
  const result = captureCli({
    rootDirectory: 'synthetic-root',
    spawnSyncImpl(_command, args) {
      calls.push(args)
      if (args[0] === 'ls-tree') {
        return {
          status: 0,
          stdout: files.map(filePath => lsTreeRecord(filePath)).join(''),
        }
      }
      if (args[0] === 'grep') {
        return {
          status: 0,
          stdout: [
            'HEAD:backend/ leading.py\0',
            'HEAD:backend/证据.py\0',
            'HEAD:backend/tests/excluded.py\0',
          ].join(''),
        }
      }
      if (args[0] === 'cat-file') return { status: 0, stdout: 'blob\n' }
      if (args[0] === 'show') {
        const filePath = args[1].slice('HEAD:'.length)
        const source = filePath === 'backend/ leading.py'
          ? "value = 'E.23'\n"
          : filePath === 'backend/证据.py'
            ? 'providerAdapter = True\n'
            : 'safe\n'
        return { status: 0, stdout: source }
      }
      return { status: 2, stdout: '', stderr: 'PRIVATE_GIT_DETAIL' }
    },
  })

  assert.deepEqual(result, {
    status: 1,
    stderr: '',
    stdout: [
      'backend/ leading.py: retired shadow reference\n',
      'backend/证据.py: retired shadow reference\n',
    ].join(''),
  })
  assert.deepEqual(calls.filter(args => args[0] === 'show'), [
    ['show', 'HEAD:backend/ leading.py'],
    ['show', 'HEAD:backend/证据.py'],
  ])
})

test('default orchestration reads the scanner even when grep finds no retired term', () => {
  const calls = []
  const result = captureCli({
    rootDirectory: 'synthetic-root',
    spawnSyncImpl(_command, args) {
      calls.push(args)
      if (args[0] === 'ls-tree') {
        return {
          status: 0,
          stdout: lsTreeRecord('scripts/scan-effective-legacy.mjs'),
        }
      }
      if (args[0] === 'grep') return { status: 1, stdout: '' }
      if (args[0] === 'cat-file') return { status: 0, stdout: 'blob\n' }
      if (args[0] === 'show') return { status: 0, stdout: 'export const safe = true\n' }
      return { status: 2, stdout: '', stderr: 'PRIVATE_GIT_DETAIL' }
    },
  })

  assert.deepEqual(result, {
    status: 2,
    stderr: 'Effective legacy scan failed.\n',
    stdout: '',
  })
  assert.deepEqual(calls.filter(args => args[0] === 'show'), [
    ['show', 'HEAD:scripts/scan-effective-legacy.mjs'],
  ])
})

test('default orchestration does not force-read an unrelated tool when grep is clean', () => {
  const calls = []
  const result = captureCli({
    rootDirectory: 'synthetic-root',
    spawnSyncImpl(_command, args) {
      calls.push(args)
      if (args[0] === 'ls-tree') {
        return {
          status: 0,
          stdout: lsTreeRecord('tools/control-plane-qa/ai-proxy-gateway.mjs'),
        }
      }
      if (args[0] === 'grep') return { status: 1, stdout: '' }
      if (args[0] === 'cat-file') return { status: 0, stdout: 'blob\n' }
      if (args[0] === 'show') return { status: 0, stdout: 'export const safe = true\n' }
      return { status: 2, stdout: '', stderr: 'PRIVATE_GIT_DETAIL' }
    },
  })

  assert.deepEqual(result, {
    status: 0,
    stderr: '',
    stdout: '',
  })
  assert.deepEqual(calls.filter(args => args[0] === 'show'), [])
})

test('default orchestration treats grep status above one as a redacted failure', () => {
  const result = captureCli({
    rootDirectory: 'synthetic-root',
    spawnSyncImpl(_command, args) {
      if (args[0] === 'ls-tree') {
        return { status: 0, stdout: lsTreeRecord('backend/safe.py') }
      }
      if (args[0] === 'grep') {
        return { status: 2, stdout: '', stderr: 'PRIVATE_GREP_FAILURE' }
      }
      if (args[0] === 'cat-file') return { status: 0, stdout: 'blob\n' }
      if (args[0] === 'show') return { status: 0, stdout: 'safe\n' }
      return { status: 2, stdout: '', stderr: 'PRIVATE_GIT_DETAIL' }
    },
  })

  assert.deepEqual(result, {
    status: 2,
    stderr: 'Effective legacy scan failed.\n',
    stdout: '',
  })
  assert.equal((result.stdout + result.stderr).includes('PRIVATE_GREP_FAILURE'), false)
})

test('default Git reader rejects a raw path alias before object reads', () => {
  let gitCalls = 0
  const result = captureCli({
    listFiles: () => ['backend\\main.py'],
    rootDirectory: 'synthetic-root',
    spawnSyncImpl() {
      gitCalls += 1
      return { status: 0, stdout: '' }
    },
  })

  assert.deepEqual(result, {
    status: 2,
    stderr: 'Effective legacy scan failed.\n',
    stdout: '',
  })
  assert.equal(gitCalls, 0)
})

test('default Git reader preflights each effective normalized blob only once', () => {
  const calls = []
  const result = captureCli({
    listFiles: () => [
      'backend/main.py',
      'backend/main.py',
      'backend/tests/reference',
      'docs/reference',
    ],
    rootDirectory: 'synthetic-root',
    spawnSyncImpl(_command, args) {
      calls.push(args)
      if (args[0] === 'cat-file') return { status: 0, stdout: 'blob\n' }
      if (args[0] === 'show') return { status: 0, stdout: 'safe\n' }
      return { status: 1, stdout: '', stderr: 'unexpected private git detail' }
    },
  })

  assert.deepEqual(result, { status: 0, stderr: '', stdout: '' })
  assert.deepEqual(calls, [
    ['cat-file', '-t', 'HEAD:backend/main.py'],
    ['show', 'HEAD:backend/main.py'],
  ])
})

test('real committed HEAD effective scan is clean', () => {
  const result = runScanner(repositoryRoot)
  assert.equal(result.status, 0, result.stderr || result.stdout)
  assert.equal(result.stdout, '')
  assert.equal(result.stderr, '')
})

test('effective legacy CLI reads a large committed HEAD source rather than dirty worktree content', t => {
  const rootDirectory = createTemporaryGitRepository(t)
  const sourcePath = commitRepositoryFile(
    rootDirectory,
    'backend/main.py',
    `value = "${'safe'.repeat(320_000)}"\n`,
    'safe large source',
  )

  writeFileSync(sourcePath, 'applyAdapter = True\n', 'utf8')
  const dirtyResult = runScanner(rootDirectory)
  assert.equal(dirtyResult.status, 0, dirtyResult.stderr || dirtyResult.stdout)
  assert.equal(dirtyResult.stdout, '')
  assert.equal(dirtyResult.stderr, '')

  runGit(rootDirectory, ['add', '--', 'backend/main.py'])
  runGit(rootDirectory, ['commit', '-m', 'unsafe source'])
  const committedResult = runScanner(rootDirectory)
  assert.equal(committedResult.status, 1, committedResult.stderr)
  assert.equal(
    committedResult.stdout,
    'backend/main.py: retired shadow reference\n',
  )
  assert.equal(committedResult.stderr, '')
  assert.doesNotMatch(committedResult.stdout, /applyAdapter/u)
})

test('default committed scan preserves JavaScript Unicode simple-fold matching', t => {
  const rootDirectory = createTemporaryGitRepository(t)
  const filePath = 'backend/unicode-fold.py'
  const unicodeFoldReference = 'pha\u017Fe-e = True\n'
  assert.equal(RETIRED_SHADOW_PATTERNS[0].pattern.test(unicodeFoldReference), true)
  commitRepositoryFile(
    rootDirectory,
    filePath,
    unicodeFoldReference,
    'Unicode fold reference',
  )

  const result = runScanner(rootDirectory)
  assert.equal(result.status, 1, result.stderr)
  assert.equal(result.stdout, `${filePath}: retired shadow reference\n`)
  assert.equal(result.stderr, '')
  assert.equal(result.stdout.includes(unicodeFoldReference.trim()), false)
})

test('default inventory preserves Unicode and leading-space effective paths', t => {
  const rootDirectory = createTemporaryGitRepository(t)
  commitRepositoryFile(rootDirectory, 'backend/ leading.py', 'safe\n', 'leading space path')
  commitRepositoryFile(
    rootDirectory,
    'backend/证据.py',
    'providerAdapter = True\n',
    'Unicode path',
  )

  const result = runScanner(rootDirectory)
  assert.equal(result.status, 1, result.stderr)
  assert.equal(result.stdout, 'backend/证据.py: retired shadow reference\n')
  assert.equal(result.stderr, '')
})

test('default reader fails closed for an effective gitlink', t => {
  const rootDirectory = createTemporaryGitRepository(t)
  const referencedCommit = runGit(rootDirectory, ['rev-parse', 'HEAD'])
  runGit(rootDirectory, [
    'update-index',
    '--add',
    '--cacheinfo',
    `160000,${referencedCommit},backend/reference`,
  ])
  runGit(rootDirectory, ['commit', '-m', 'effective gitlink'])

  const result = runScanner(rootDirectory)
  assert.equal(result.status, 2)
  assert.equal(result.stdout, '')
  assert.equal(result.stderr, 'Effective legacy scan failed.\n')
  assert.equal((result.stdout + result.stderr).includes(referencedCommit), false)
})

test('excluded test gitlinks do not trigger default blob or content reads', t => {
  const rootDirectory = createTemporaryGitRepository(t)
  const referencedCommit = runGit(rootDirectory, ['rev-parse', 'HEAD'])
  runGit(rootDirectory, [
    'update-index',
    '--add',
    '--cacheinfo',
    `160000,${referencedCommit},backend/tests/reference`,
  ])
  runGit(rootDirectory, ['commit', '-m', 'excluded test gitlink'])

  const result = runScanner(rootDirectory)
  assert.equal(result.status, 0, result.stderr || result.stdout)
  assert.equal(result.stdout, '')
  assert.equal(result.stderr, '')
})
