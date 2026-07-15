import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  REVIEWED_ASSET_JSON_ALLOWLIST,
  runArtifactScannerCli,
  scanM2Artifacts,
} from '../scan-m2-artifacts.mjs'

const scriptsDirectory = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const scannerPath = path.join(scriptsDirectory, 'scan-m2-artifacts.mjs')

test('artifact scanner rejects every baseline-new raw novel extension case-insensitively', () => {
  const changedFiles = [
    'evidence/chapter.txt',
    'evidence/chapter.TXT',
    'evidence/book.epub',
    'evidence/book.MOBI',
  ]
  const findings = scanM2Artifacts({ changedFiles, readContent: () => '' })

  assert.equal(findings.length, changedFiles.length)
  assert.deepEqual(findings.map(finding => finding.path), changedFiles)
  assert.ok(findings.every(finding => finding.reason === 'forbidden raw source extension'))
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
