import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
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
