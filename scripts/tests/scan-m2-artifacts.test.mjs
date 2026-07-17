import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import * as artifactScanner from '../scan-m2-artifacts.mjs'

const {
  MAX_ARTIFACT_BYTES,
  REVIEWED_ASSET_JSON_ALLOWLIST,
  runArtifactScannerCli,
  scanM2Artifacts,
} = artifactScanner

const scriptsDirectory = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const scannerPath = path.join(scriptsDirectory, 'scan-m2-artifacts.mjs')

function runGit(rootDirectory, args) {
  const result = spawnSync('git', args, {
    cwd: rootDirectory,
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
  const rootDirectory = mkdtempSync(path.join(tmpdir(), 'scan-m2-artifacts-'))
  t.after(() => rmSync(rootDirectory, { recursive: true, force: true }))
  runGit(rootDirectory, ['init'])
  runGit(rootDirectory, ['config', 'user.name', 'Artifact Scanner Test'])
  runGit(rootDirectory, ['config', 'user.email', 'artifact-scanner@example.invalid'])
  runGit(rootDirectory, ['config', 'core.quotePath', 'true'])
  commitRepositoryFile(rootDirectory, 'README.md', 'baseline\n', 'baseline')
  return {
    baseline: runGit(rootDirectory, ['rev-parse', 'HEAD']),
    rootDirectory,
  }
}

function runScanner(rootDirectory, baseline) {
  return spawnSync(process.execPath, [scannerPath, '--base', baseline], {
    cwd: rootDirectory,
    encoding: 'utf8',
    shell: false,
  })
}

test('artifact classifier exports the M2 requirements lock and assigns repository roles', () => {
  assert.equal(artifactScanner.M2_REQUIREMENTS_LOCK, 'backend/requirements-m2.lock.txt')
  assert.equal(typeof artifactScanner.classifyM2ArtifactPath, 'function')

  for (const filePath of REVIEWED_ASSET_JSON_ALLOWLIST) {
    assert.equal(artifactScanner.classifyM2ArtifactPath(filePath), 'reviewed-asset')
  }

  const implementationDefinitions = [
    artifactScanner.M2_REQUIREMENTS_LOCK,
    'backend/app.py',
    'frontend/src/app.vue',
    'scripts/check.mjs',
    'tools/check.ts',
    'tools/control-plane-qa/fixtures/rfc8785-restricted-vectors.json',
    '.gitattributes',
    'docs/superpowers/specs/m2-contract.md',
    'docs/superpowers/plans/nested/m2-plan.md',
  ]
  for (const filePath of implementationDefinitions) {
    assert.equal(
      artifactScanner.classifyM2ArtifactPath(filePath),
      'implementation-definition',
      filePath,
    )
  }

  const strictArtifacts = [
    'backend/assets/source-looking.py',
    'docs/development/source-looking.ts',
    'backend/evidence/source-looking.py',
    'frontend/output/source-looking.mjs',
    'scripts/artifacts/source-looking.ts',
    'notes/story.md',
  ]
  for (const filePath of strictArtifacts) {
    assert.equal(artifactScanner.classifyM2ArtifactPath(filePath), 'strict-artifact', filePath)
  }
})

test('artifact classifier matches implementation suffixes case-insensitively', () => {
  const implementationDefinitions = [
    'backend/service.PY',
    'frontend/app.TsX',
    'scripts/check.MJS',
    'tools/config.YaML',
    'docs/superpowers/specs/design.MD',
    'docs/superpowers/plans/nested/release.mD',
  ]
  for (const filePath of implementationDefinitions) {
    assert.equal(
      artifactScanner.classifyM2ArtifactPath(filePath),
      'implementation-definition',
      filePath,
    )
  }

  for (const filePath of ['backend/assets/service.PY', 'backend/evidence/service.PY']) {
    assert.equal(artifactScanner.classifyM2ArtifactPath(filePath), 'strict-artifact', filePath)
  }
})

test('artifact scanner accepts upper-case implementation suffixes with strict-only content', () => {
  const syntheticSentinel = ['browser', 'secret', 'must', 'not', 'leak'].join('-')
  const largeProse = '这是一段完全合成的测试故事。'.repeat(2500)
  const changedFiles = [
    'backend/service.PY',
    'frontend/app.TSX',
    'scripts/check.MJS',
    'tools/config.YAML',
    'docs/superpowers/specs/design.MD',
  ]

  assert.deepEqual(scanM2Artifacts({
    changedFiles,
    readContent: () => `${syntheticSentinel}\n${largeProse}`,
  }), [])
})

test('artifact scanner accepts only the exact requirements lock among raw text extensions', () => {
  const changedFiles = [
    'evidence/chapter.txt',
    'evidence/chapter.TXT',
    'backend/requirements-m2.lock.TXT',
    'evidence/book.epub',
    'evidence/book.MOBI',
  ]
  const findings = scanM2Artifacts({ changedFiles, readContent: () => '' })

  assert.equal(findings.length, changedFiles.length)
  assert.deepEqual(findings.map(finding => finding.path), changedFiles)
  assert.ok(findings.every(finding => finding.reason === 'forbidden raw source extension'))

  assert.deepEqual(scanM2Artifacts({
    changedFiles: [artifactScanner.M2_REQUIREMENTS_LOCK],
    readContent: () => ['browser', 'secret', 'must', 'not', 'leak'].join('-'),
  }), [])
})

test('artifact scanner rejects epub and mobi files for every repository role', () => {
  const changedFiles = [
    'backend/book.epub',
    'frontend/book.MOBI',
  ]
  const findings = scanM2Artifacts({ changedFiles, readContent: () => '' })

  assert.equal(findings.length, changedFiles.length)
  assert.deepEqual(findings.map(finding => finding.path), changedFiles)
  assert.ok(findings.every(finding => finding.reason === 'forbidden raw source extension'))
})

test('artifact scanner skips sentinel and large-prose checks for implementation definitions', () => {
  const syntheticSentinel = ['browser', 'secret', 'must', 'not', 'leak'].join('-')
  const largeProse = '这是一段完全合成的测试故事。'.repeat(2500)
  const changedFiles = [
    'backend/app.py',
    'frontend/e2e/acceptance.mjs',
    'scripts/tests/scanner.test.mjs',
    'docs/superpowers/specs/m2-contract.md',
    'tools/control-plane-qa/fixtures/rfc8785-restricted-vectors.json',
    '.gitattributes',
  ]

  assert.deepEqual(scanM2Artifacts({
    changedFiles,
    readContent: () => `${syntheticSentinel}\n${largeProse}`,
  }), [])
})

test('artifact scanner keeps strict paths strict before source-looking extension rules', () => {
  const syntheticSentinel = ['browser', 'secret', 'must', 'not', 'leak'].join('-')
  const changedFiles = [
    'backend/assets/source-looking.py',
    'docs/development/source-looking.ts',
    'backend/evidence/source-looking.py',
    'frontend/output/source-looking.mjs',
    'scripts/artifacts/source-looking.ts',
  ]

  assert.deepEqual(scanM2Artifacts({
    changedFiles,
    readContent: () => syntheticSentinel,
  }), changedFiles.map(filePath => ({
    path: filePath,
    reason: 'private sentinel content',
  })))
})

test('artifact scanner rejects fixed secret, provider URL, DSN, and absolute-root sentinels', () => {
  const sentinels = [
    ['browser', 'secret', 'must', 'not', 'leak'].join('-'),
    ['https://private-provider', '.example/v1'].join(''),
    ['mysql', '://private-user:private-password@127.0.0.1/novel_creator'].join(''),
    ['C:', '/private/corpus-root-must-not-leak'].join(''),
  ]
  const contents = new Map(sentinels.map((sentinel, index) => [
    `evidence/sentinel-${index}.json`,
    JSON.stringify({ value: sentinel }),
  ]))
  const findings = scanM2Artifacts({
    changedFiles: [...contents.keys()],
    readContent: name => contents.get(name),
  })

  assert.equal(findings.length, sentinels.length)
  assert.ok(findings.every(finding => finding.reason === 'private sentinel content'))
  for (const finding of findings) {
    for (const sentinel of sentinels) assert.doesNotMatch(finding.reason, new RegExp(sentinel))
  }
})

test('artifact scanner rejects large source-like text outside reviewed asset JSON files', () => {
  const novelLikeText = '这是一段完全合成的测试故事。'.repeat(2500)
  const outsidePath = 'docs/evidence/generated-story.json'
  const allowedPath = [...REVIEWED_ASSET_JSON_ALLOWLIST][0]

  const outsideFindings = scanM2Artifacts({
    changedFiles: [outsidePath],
    readContent: () => novelLikeText,
  })
  assert.deepEqual(outsideFindings, [{
    path: outsidePath,
    reason: 'large source-like text outside reviewed assets',
  }])

  assert.deepEqual(scanM2Artifacts({
    changedFiles: [allowedPath],
    readContent: () => novelLikeText,
  }), [])
})

test('artifact scanner rejects sentinels in reviewed assets and prose in unreviewed assets', () => {
  const allowedPath = [...REVIEWED_ASSET_JSON_ALLOWLIST][0]
  const unreviewedPath = 'backend/assets/unreviewed.json'
  const syntheticSentinel = ['browser', 'secret', 'must', 'not', 'leak'].join('-')
  const largeProse = '这是一段完全合成的测试故事。'.repeat(2500)

  assert.deepEqual(scanM2Artifacts({
    changedFiles: [allowedPath],
    readContent: () => syntheticSentinel,
  }), [{ path: allowedPath, reason: 'private sentinel content' }])

  assert.deepEqual(scanM2Artifacts({
    changedFiles: [unreviewedPath],
    readContent: () => largeProse,
  }), [{
    path: unreviewedPath,
    reason: 'large source-like text outside reviewed assets',
  }])
})

test('artifact scanner rejects large prose at unknown textual paths', () => {
  const filePath = 'notes/generated-story.md'
  const largeProse = 'synthetic narrative words '.repeat(3500)

  assert.deepEqual(scanM2Artifacts({
    changedFiles: [filePath],
    readContent: () => largeProse,
  }), [{
    path: filePath,
    reason: 'large source-like text outside reviewed assets',
  }])
})

test('artifact scanner applies size limits to every repository role', () => {
  const changedFiles = [
    [...REVIEWED_ASSET_JSON_ALLOWLIST][0],
    'backend/app.py',
    'notes/generated-story.md',
  ]

  assert.deepEqual(scanM2Artifacts({
    changedFiles,
    getSize: () => 6 * 1024 * 1024,
    readContent: () => assert.fail('oversized content must not be read'),
  }), changedFiles.map(filePath => ({
    path: filePath,
    reason: 'oversized artifact',
  })))
})

test('artifact scanner applies the aggregate size limit across mixed repository roles', () => {
  const changedFiles = [
    [...REVIEWED_ASSET_JSON_ALLOWLIST][0],
    'backend/app.py',
    '.gitattributes',
    'notes/metadata.json',
    'frontend/final.ts',
  ]
  const sizes = new Map(changedFiles.map((filePath, index) => [
    filePath,
    index === changedFiles.length - 1 ? 1 : MAX_ARTIFACT_BYTES,
  ]))
  const readPaths = []
  const boundedContent = 'bounded metadata\n'.repeat(4)

  assert.deepEqual(scanM2Artifacts({
    changedFiles,
    getSize: filePath => sizes.get(filePath),
    readContent(filePath) {
      readPaths.push(filePath)
      return boundedContent
    },
  }), [{ path: changedFiles.at(-1), reason: 'oversized artifact' }])
  assert.deepEqual(readPaths, changedFiles.slice(0, -1))
})

test('artifact scanner accepts ordinary source and metadata changes', () => {
  assert.deepEqual(scanM2Artifacts({
    changedFiles: ['scripts/safe.mjs', 'docs/evidence/receipt.json'],
    readContent: name => name.endsWith('.mjs')
      ? 'export const value = 1\n'
      : JSON.stringify({ matchCount: 0, publicHash: 'abc123' }),
  }), [])
})

test('artifact scanner rejects Windows absolute paths before reading content', () => {
  let readCount = 0
  for (const filePath of ['C:\\outside\\receipt.json', 'C:outside\\receipt.json']) {
    assert.throws(() => scanM2Artifacts({
      changedFiles: [filePath],
      readContent() {
        readCount += 1
        return '{}'
      },
    }), /outside repository/)
  }
  assert.equal(readCount, 0)
})

test('artifact scanner rejects oversized files without reading their content', () => {
  let readCount = 0
  const findings = scanM2Artifacts({
    changedFiles: ['evidence/huge.json'],
    getSize: () => 6 * 1024 * 1024,
    readContent() {
      readCount += 1
      return ''
    },
  })

  assert.deepEqual(findings, [{ path: 'evidence/huge.json', reason: 'oversized artifact' }])
  assert.equal(readCount, 0)
})

test('artifact scanner CLI rejects option-like bases before invoking git', () => {
  let listCount = 0
  let stderr = ''
  const status = runArtifactScannerCli(['--base=--output=scan-bypass'], {
    listChangedFiles() {
      listCount += 1
      return []
    },
    stderr: { write(chunk) { stderr += chunk } },
  })

  assert.equal(status, 2)
  assert.equal(listCount, 0)
  assert.match(stderr, /invalid --base/)
})

test('artifact scanner CLI requires an explicit base commit', () => {
  const result = spawnSync(process.execPath, [scannerPath], {
    cwd: path.dirname(scriptsDirectory),
    encoding: 'utf8',
    shell: false,
  })

  assert.equal(result.status, 2)
  assert.match(result.stderr, /--base is required/)
})

test('artifact scanner CLI reads committed HEAD instead of the dirty worktree', t => {
  const { baseline, rootDirectory } = createTemporaryGitRepository(t)
  const safeReceipt = JSON.stringify({ matchCount: 0, publicHash: 'safe' })
  const receiptPath = commitRepositoryFile(
    rootDirectory,
    'evidence/receipt.json',
    safeReceipt,
    'add safe receipt',
  )
  const syntheticSentinel = ['browser', 'secret', 'must', 'not', 'leak'].join('-')
  writeFileSync(receiptPath, JSON.stringify({ value: syntheticSentinel }), 'utf8')

  const result = runScanner(rootDirectory, baseline)

  assert.equal(result.status, 0, result.stderr || result.stdout)
  assert.equal(readFileSync(receiptPath, 'utf8'), JSON.stringify({ value: syntheticSentinel }))
  assert.equal((result.stdout + result.stderr).includes(syntheticSentinel), false)
})

test('artifact scanner CLI reports a committed sentinel by path without echoing its value', t => {
  const { baseline, rootDirectory } = createTemporaryGitRepository(t)
  const syntheticSentinel = ['browser', 'secret', 'must', 'not', 'leak'].join('-')
  commitRepositoryFile(
    rootDirectory,
    'evidence/receipt.json',
    JSON.stringify({ value: syntheticSentinel }),
    'add unsafe receipt',
  )

  const result = runScanner(rootDirectory, baseline)

  assert.equal(result.status, 1, result.stderr)
  assert.equal(result.stdout, 'evidence/receipt.json: private sentinel content\n')
  assert.equal(result.stderr, '')
  assert.equal((result.stdout + result.stderr).includes(syntheticSentinel), false)
})

test('artifact scanner CLI suppresses injected reader error details', () => {
  let stdout = ''
  let stderr = ''
  const privateReaderMessage = 'PRIVATE_READER_MESSAGE'

  const status = runArtifactScannerCli(['--base', 'baseline'], {
    getSize: () => 2,
    listChangedFiles: () => ['evidence/receipt.json'],
    readContent() {
      throw new Error(privateReaderMessage)
    },
    stderr: { write(chunk) { stderr += chunk } },
    stdout: { write(chunk) { stdout += chunk } },
  })

  assert.equal(status, 2)
  assert.equal(stdout, '')
  assert.equal(stderr, 'M2 artifact scan failed.\n')
  assert.equal(stderr.includes(privateReaderMessage), false)
})

test('artifact scanner CLI reads a safe committed file larger than the default spawn buffer', t => {
  const { baseline, rootDirectory } = createTemporaryGitRepository(t)
  const largeSafeSource = '#'.repeat(Math.floor(1.28 * 1024 * 1024))
  commitRepositoryFile(
    rootDirectory,
    'backend/large.py',
    largeSafeSource,
    'add large safe source',
  )

  const result = runScanner(rootDirectory, baseline)

  assert.equal(result.status, 0, result.stderr || result.stdout)
  assert.equal(result.stdout, '')
})

test('artifact scanner CLI fails closed for a committed gitlink without leaking object details', t => {
  const { baseline, rootDirectory } = createTemporaryGitRepository(t)
  const referencedCommit = runGit(rootDirectory, ['rev-parse', 'HEAD'])
  runGit(rootDirectory, [
    'update-index',
    '--add',
    '--cacheinfo',
    `160000,${referencedCommit},artifacts/reference`,
  ])
  runGit(rootDirectory, ['commit', '-m', 'add gitlink'])

  const result = runScanner(rootDirectory, baseline)

  assert.equal(result.status, 2, result.stderr || result.stdout)
  assert.equal(result.stdout, '')
  assert.equal(result.stderr, 'M2 artifact scan failed.\n')
  assert.equal((result.stdout + result.stderr).includes(referencedCommit), false)
})

test('artifact scanner CLI preserves a committed Unicode path in findings', t => {
  const { baseline, rootDirectory } = createTemporaryGitRepository(t)
  const filePath = 'evidence/证据收据.json'
  const syntheticSentinel = ['browser', 'secret', 'must', 'not', 'leak'].join('-')
  commitRepositoryFile(
    rootDirectory,
    filePath,
    JSON.stringify({ value: syntheticSentinel }),
    'add Unicode evidence',
  )

  const result = runScanner(rootDirectory, baseline)

  assert.equal(result.status, 1, result.stderr || result.stdout)
  assert.equal(result.stdout, `${filePath}: private sentinel content\n`)
  assert.equal(result.stderr, '')
  assert.equal((result.stdout + result.stderr).includes(syntheticSentinel), false)
})

test('artifact scanner CLI preserves a safe top-level path with a leading space', t => {
  const { baseline, rootDirectory } = createTemporaryGitRepository(t)
  const filePath = ' evidence.json'
  commitRepositoryFile(
    rootDirectory,
    filePath,
    JSON.stringify({ matchCount: 0, publicHash: 'safe' }),
    'add leading-space evidence',
  )

  const result = runScanner(rootDirectory, baseline)

  assert.equal(result.status, 0, result.stderr || result.stdout)
  assert.equal(result.stdout, '')
  assert.equal(result.stderr, '')
})

test('artifact scanner CLI preflights a raw-extension gitlink before policy findings', t => {
  const { baseline, rootDirectory } = createTemporaryGitRepository(t)
  const referencedCommit = runGit(rootDirectory, ['rev-parse', 'HEAD'])
  runGit(rootDirectory, [
    'update-index',
    '--add',
    '--cacheinfo',
    `160000,${referencedCommit},evidence/reference.txt`,
  ])
  runGit(rootDirectory, ['commit', '-m', 'add raw-extension gitlink'])

  const result = runScanner(rootDirectory, baseline)

  assert.equal(result.status, 2, result.stderr || result.stdout)
  assert.equal(result.stdout, '')
  assert.equal(result.stderr, 'M2 artifact scan failed.\n')
  assert.equal((result.stdout + result.stderr).includes(referencedCommit), false)
})

test('artifact scanner CLI preflights a gitlink before an injected oversized finding', t => {
  const { rootDirectory } = createTemporaryGitRepository(t)
  const filePath = 'artifacts/reference'
  const referencedCommit = runGit(rootDirectory, ['rev-parse', 'HEAD'])
  runGit(rootDirectory, [
    'update-index',
    '--add',
    '--cacheinfo',
    `160000,${referencedCommit},${filePath}`,
  ])
  runGit(rootDirectory, ['commit', '-m', 'add oversized gitlink'])
  let stdout = ''
  let stderr = ''

  const status = runArtifactScannerCli(['--base', 'baseline'], {
    getSize: () => MAX_ARTIFACT_BYTES + 1,
    listChangedFiles: () => [filePath],
    rootDirectory,
    stderr: { write(chunk) { stderr += chunk } },
    stdout: { write(chunk) { stdout += chunk } },
  })

  assert.equal(status, 2)
  assert.equal(stdout, '')
  assert.equal(stderr, 'M2 artifact scan failed.\n')
  assert.equal((stdout + stderr).includes(referencedCommit), false)
})

test('artifact scanner CLI with fully injected readers never touches an invalid Git root', () => {
  let stdout = ''
  let stderr = ''

  const status = runArtifactScannerCli(['--base', 'baseline'], {
    getSize: () => 2,
    listChangedFiles: () => ['evidence/receipt.json'],
    readContent: () => '{}',
    rootDirectory: path.join(
      tmpdir(),
      `missing-artifact-scanner-root-${process.pid}-${Date.now()}`,
    ),
    stderr: { write(chunk) { stderr += chunk } },
    stdout: { write(chunk) { stdout += chunk } },
  })

  assert.equal(status, 0)
  assert.equal(stdout, '')
  assert.equal(stderr, '')
})
