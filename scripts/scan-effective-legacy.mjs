import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SCANNER_PATH = 'scripts/scan-effective-legacy.mjs'
const GATEWAY_PATH = 'tools/control-plane-qa/ai-proxy-gateway.mjs'
const HEAD_PATHS = ['backend', 'frontend', 'scripts', 'tools', 'package.json']
const EFFECTIVE_PREFIXES = ['backend/', 'frontend/', 'scripts/', 'tools/']
const EXCLUDED_TEST_PATHS = [
  /^backend\/tests\//u,
  /^frontend\/tests\//u,
  /^scripts\/tests\//u,
  /^tools\/(?:.+\/)?tests\//u,
]
const BLOCK_START = '// BEGIN RETIRED SHADOW PATTERNS'
const BLOCK_END = '// END RETIRED SHADOW PATTERNS'
const MAX_GIT_OUTPUT_BYTES = 6 * 1024 * 1024
const DIAGNOSTIC_CONTROL_CHARACTER = /[\u0000-\u001F\u007F-\u009F\u2028\u2029]/gu
const UNICODE_SIMPLE_FOLD_SUPPLEMENTS = new Map([
  ['k', '\u212A'],
  ['s', '\u017F'],
])

// BEGIN RETIRED SHADOW PATTERNS
export const RETIRED_SHADOW_PATTERNS = Object.freeze([
  { code: 'phase-e', pattern: /phase-e/iu },
  { code: 'e.23', pattern: /e\.23/iu },
  { code: 'applyAdapter', pattern: /applyAdapter/iu },
  { code: 'providerAdapter', pattern: /providerAdapter/iu },
])
// END RETIRED SHADOW PATTERNS

export function scanEffectiveLegacy({ files, readContent }) {
  if (!Array.isArray(files)) throw new TypeError('files must be an array')
  if (typeof readContent !== 'function') throw new TypeError('readContent must be a function')

  const normalizedFiles = [...new Set(files.map(normalizeRepositoryPath))]
  const findings = []
  for (const filePath of normalizedFiles) {
    if (!isEffectivePath(filePath)) continue
    if (containsRetiredReference(filePath)) {
      findings.push(createFinding(filePath))
      continue
    }

    const rawSource = readContent(filePath)
    if (typeof rawSource !== 'string') {
      throw new TypeError('content reader did not return text')
    }

    let source = rawSource
    if (filePath === SCANNER_PATH) source = removeOwnPatternBlock(source)
    if (filePath === GATEWAY_PATH) {
      source = removeGatewayProtectiveEntries(source)
      if (source === null) {
        findings.push(createFinding(filePath))
        continue
      }
    }
    if (containsRetiredReference(source)) findings.push(createFinding(filePath))
  }
  return findings
}

export function runEffectiveLegacyCli(args = process.argv.slice(2), dependencies = {}) {
  const stderr = dependencies.stderr ?? process.stderr
  const stdout = dependencies.stdout ?? process.stdout
  if (args.length !== 0) {
    stderr.write('usage: node scripts/scan-effective-legacy.mjs\n')
    return 2
  }

  const rootDirectory = dependencies.rootDirectory ?? process.cwd()
  const spawnSyncImpl = dependencies.spawnSyncImpl ?? spawnSync
  const usesDefaultListFiles = dependencies.listFiles == null
  const usesDefaultReadContent = dependencies.readContent == null
  const listFiles = dependencies.listFiles ?? (() => (
    listHeadFiles(rootDirectory, spawnSyncImpl)
  ))
  const verifiedHeadBlobs = new Set()
  const verifyHeadBlob = filePath => {
    if (verifiedHeadBlobs.has(filePath)) return
    assertHeadBlob(rootDirectory, filePath, spawnSyncImpl)
    verifiedHeadBlobs.add(filePath)
  }
  const readContent = dependencies.readContent ?? (filePath => {
    verifyHeadBlob(filePath)
    return readHeadContent(rootDirectory, filePath, spawnSyncImpl)
  })

  let findings
  try {
    if (usesDefaultListFiles && usesDefaultReadContent) {
      findings = scanDefaultHead(rootDirectory, spawnSyncImpl)
    } else {
      const rawFiles = listFiles()
      if (!Array.isArray(rawFiles)) throw new TypeError('file inventory must be an array')
      const normalizedFiles = rawFiles.map(normalizeRepositoryPath)
      if (usesDefaultReadContent) {
        for (let index = 0; index < rawFiles.length; index += 1) {
          if (rawFiles[index] !== normalizedFiles[index]) {
            throw new Error('ambiguous tracked path')
          }
        }
        for (const filePath of new Set(normalizedFiles)) {
          if (isEffectivePath(filePath)) verifyHeadBlob(filePath)
        }
      }
      findings = scanEffectiveLegacy({ files: normalizedFiles, readContent })
    }
  } catch {
    stderr.write('Effective legacy scan failed.\n')
    return 2
  }

  for (const finding of findings) {
    stdout.write(`${escapeDiagnosticPath(finding.path)}: ${finding.reason}\n`)
  }
  return findings.length === 0 ? 0 : 1
}

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

function containsRetiredReference(value) {
  return RETIRED_SHADOW_PATTERNS.some(item => item.pattern.test(value))
}

function createFinding(filePath) {
  return { path: filePath, reason: 'retired shadow reference' }
}

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
  if (protectedIndices.length !== expected.size
    || protectedTokens.size !== expected.size
    || protectedIndices[0] !== tokens.length - 2
    || protectedIndices[1] !== tokens.length - 1) {
    return null
  }

  const absoluteProtected = new Set(
    protectedIndices.map(index => starts[0] + 1 + index),
  )
  return lines.map((line, index) => (
    absoluteProtected.has(index) ? '' : line
  )).join('\n')
}

function scanDefaultHead(rootDirectory, spawnSyncImpl) {
  const inventory = listHeadInventory(rootDirectory, spawnSyncImpl)
  const rawFiles = inventory.map(entry => entry.path)
  const normalizedFiles = rawFiles.map(normalizeRepositoryPath)
  const inventoryPaths = new Set()

  for (let index = 0; index < inventory.length; index += 1) {
    const entry = inventory[index]
    const filePath = normalizedFiles[index]
    if (entry.path !== filePath) throw new Error('ambiguous tracked path')
    if (inventoryPaths.has(filePath)) throw new Error('duplicate tracked path')
    inventoryPaths.add(filePath)
    if (isEffectivePath(filePath) && entry.type !== 'blob') {
      throw new Error('git object is not a blob')
    }
  }

  const candidates = new Set()
  for (const rawCandidate of listHeadCandidates(rootDirectory, spawnSyncImpl)) {
    const candidate = normalizeRepositoryPath(rawCandidate)
    if (rawCandidate !== candidate) throw new Error('ambiguous tracked path')
    if (!inventoryPaths.has(candidate)) throw new Error('unexpected grep path')
    if (isEffectivePath(candidate)) candidates.add(candidate)
  }
  for (const protectivePath of [SCANNER_PATH, GATEWAY_PATH]) {
    if (inventoryPaths.has(protectivePath)) candidates.add(protectivePath)
  }

  const contentCache = new Map()
  const readContent = filePath => {
    if (!candidates.has(filePath)) return ''
    if (!contentCache.has(filePath)) {
      contentCache.set(
        filePath,
        readHeadContent(rootDirectory, filePath, spawnSyncImpl),
      )
    }
    return contentCache.get(filePath)
  }
  return scanEffectiveLegacy({ files: normalizedFiles, readContent })
}

function listHeadFiles(rootDirectory, spawnSyncImpl) {
  return listHeadInventory(rootDirectory, spawnSyncImpl).map(entry => entry.path)
}

function listHeadInventory(rootDirectory, spawnSyncImpl) {
  const result = spawnGit(rootDirectory, [
    'ls-tree', '-r', '-z', 'HEAD', '--', ...HEAD_PATHS,
  ], spawnSyncImpl)
  return splitNulRecords(result.stdout).map(record => {
    const match = /^([0-7]{6}) ([a-z]+) ((?:[0-9a-f]{40}|[0-9a-f]{64}))\t([\s\S]+)$/u
      .exec(record)
    if (!match) throw new Error('invalid ls-tree inventory')
    return {
      mode: match[1],
      type: match[2],
      object: match[3],
      path: match[4],
    }
  })
}

function listHeadCandidates(rootDirectory, spawnSyncImpl) {
  const candidatePatterns = new Set(RETIRED_SHADOW_PATTERNS.flatMap(item => (
    gitFixedPatternVariants(item.code)
  )))
  const patternArguments = [...candidatePatterns].flatMap(pattern => ['-e', pattern])
  const result = spawnGit(rootDirectory, [
    'grep', '-z', '-l', '-i', '-F',
    ...patternArguments,
    'HEAD', '--', ...HEAD_PATHS,
  ], spawnSyncImpl, [0, 1])
  if (result.status === 1) {
    if (result.stdout !== '') throw new Error('invalid grep result')
    return []
  }
  return splitNulRecords(result.stdout).map(record => {
    if (!record.startsWith('HEAD:') || record.length === 'HEAD:'.length) {
      throw new Error('invalid grep path')
    }
    return record.slice('HEAD:'.length)
  })
}

function gitFixedPatternVariants(value) {
  let variants = ['']
  for (const character of value) {
    const alternatives = [character]
    const supplement = UNICODE_SIMPLE_FOLD_SUPPLEMENTS.get(character.toLowerCase())
    if (supplement) alternatives.push(supplement)
    variants = variants.flatMap(prefix => (
      alternatives.map(alternative => prefix + alternative)
    ))
  }
  return variants
}

function splitNulRecords(output) {
  if (typeof output !== 'string') throw new TypeError('git did not return text')
  if (output === '') return []
  if (!output.endsWith('\0')) throw new Error('unterminated Git output')
  const records = output.slice(0, -1).split('\0')
  if (records.some(record => record.length === 0)) {
    throw new Error('empty Git output record')
  }
  return records
}

function assertHeadBlob(rootDirectory, filePath, spawnSyncImpl) {
  const result = spawnGit(
    rootDirectory,
    ['cat-file', '-t', `HEAD:${filePath}`],
    spawnSyncImpl,
  )
  if (result.stdout.trim() !== 'blob') throw new Error('git object is not a blob')
}

function readHeadContent(rootDirectory, filePath, spawnSyncImpl) {
  return spawnGit(
    rootDirectory,
    ['show', `HEAD:${filePath}`],
    spawnSyncImpl,
  ).stdout
}

function spawnGit(rootDirectory, args, spawnSyncImpl, allowedStatuses = [0]) {
  const result = spawnSyncImpl('git', args, {
    cwd: rootDirectory,
    encoding: 'utf8',
    maxBuffer: MAX_GIT_OUTPUT_BYTES,
    shell: false,
  })
  if (result.error || !allowedStatuses.includes(result.status)) {
    throw new Error('git command failed')
  }
  return result
}

function escapeDiagnosticPath(value) {
  return value.replace(DIAGNOSTIC_CONTROL_CHARACTER, character => {
    if (character === '\b') return '\\b'
    if (character === '\t') return '\\t'
    if (character === '\n') return '\\n'
    if (character === '\f') return '\\f'
    if (character === '\r') return '\\r'
    return '\\u' + character.codePointAt(0).toString(16).padStart(4, '0')
  })
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : ''
if (invokedPath && path.resolve(fileURLToPath(import.meta.url)) === invokedPath) {
  process.exitCode = runEffectiveLegacyCli()
}
