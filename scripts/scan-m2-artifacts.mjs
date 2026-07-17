import { spawnSync } from 'node:child_process'
import { readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const REVIEWED_ASSET_JSON_ALLOWLIST = new Set([
  'backend/assets/writer-core-v1.1.0/manifest.json',
  'backend/assets/writer-core-v1.1.0/style_templates.json',
  'backend/assets/writer-core-v1.1.0/experience_cards.json',
])
export const M2_REQUIREMENTS_LOCK = 'backend/requirements-m2.lock.txt'

export const MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
export const MAX_TOTAL_ARTIFACT_BYTES = 20 * 1024 * 1024

const FORBIDDEN_EBOOK_EXTENSION = /\.(?:epub|mobi)$/iu
const RAW_TEXT_EXTENSION = /\.txt$/iu
const IMPLEMENTATION_ROOT = /^(?:backend|frontend|scripts|tools)\//u
const IMPLEMENTATION_SOURCE_EXTENSIONS = new Set([
  '.py', '.pyi', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.vue', '.css', '.scss',
  '.html', '.sql', '.toml', '.ini', '.cfg', '.yaml', '.yml',
])
const STRICT_DIRECTORY = /^(?:backend\/assets|docs\/development)(?:\/|$)/u
const STRICT_PATH_SEGMENT = /(?:^|\/)(?:evidence|output|artifacts)(?:\/|$)/u
const SUPERPOWERS_DEFINITION_PATH = /^docs\/superpowers\/(?:specs|plans)\/.+/u
const RFC8785_RESTRICTED_VECTORS = 'tools/control-plane-qa/fixtures/rfc8785-restricted-vectors.json'
const PRIVATE_SENTINELS = [
  ['browser', 'secret', 'must', 'not', 'leak'].join('-'),
  ['https://private-provider', '.example/v1'].join(''),
  ['C:', '/private/corpus-root-must-not-leak'].join(''),
]
const PRIVATE_DSN = /\b(?:mysql(?:\+[a-z0-9_-]+)?|postgres(?:ql)?):\/\/[^\s'"\x60]+/iu
const LARGE_TEXT_MINIMUM = 20_000
const LARGE_CJK_MINIMUM = 1_000
const LARGE_WORD_MINIMUM = 3_000
const CJK_CHARACTER = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u
const LETTER_CHARACTER = /\p{L}/u

export function classifyM2ArtifactPath(value) {
  const filePath = normalizeRepositoryPath(value)
  if (REVIEWED_ASSET_JSON_ALLOWLIST.has(filePath)) return 'reviewed-asset'
  if (filePath === M2_REQUIREMENTS_LOCK) return 'implementation-definition'
  if (STRICT_DIRECTORY.test(filePath) || STRICT_PATH_SEGMENT.test(filePath)) {
    return 'strict-artifact'
  }
  const extension = path.posix.extname(filePath).toLowerCase()
  if (IMPLEMENTATION_ROOT.test(filePath) && IMPLEMENTATION_SOURCE_EXTENSIONS.has(extension)) {
    return 'implementation-definition'
  }
  if (filePath === RFC8785_RESTRICTED_VECTORS
    || filePath === '.gitattributes'
    || (extension === '.md' && SUPERPOWERS_DEFINITION_PATH.test(filePath))) {
    return 'implementation-definition'
  }
  return 'strict-artifact'
}

export function scanM2Artifacts({ changedFiles, readContent, getSize }) {
  if (!Array.isArray(changedFiles)) throw new TypeError('changedFiles must be an array')
  if (typeof readContent !== 'function') throw new TypeError('readContent must be a function')
  if (getSize !== undefined && typeof getSize !== 'function') {
    throw new TypeError('getSize must be a function when provided')
  }

  const findings = []
  let totalBytes = 0
  for (const rawPath of changedFiles) {
    const filePath = normalizeRepositoryPath(rawPath)
    if (hasForbiddenRawExtension(filePath)) {
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
      throw new TypeError('content reader did not return text: ' + filePath)
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
  }
  return findings
}

export function runArtifactScannerCli(args = process.argv.slice(2), dependencies = {}) {
  const stderr = dependencies.stderr ?? process.stderr
  const stdout = dependencies.stdout ?? process.stdout
  let base
  try {
    base = parseBaseArgument(args)
  } catch (error) {
    stderr.write(error.message + '\n')
    return 2
  }

  const rootDirectory = dependencies.rootDirectory ?? process.cwd()
  const listChangedFiles = dependencies.listChangedFiles ?? (requestedBase => (
    listNewGitFiles(rootDirectory, requestedBase)
  ))
  const resolvePath = filePath => path.join(rootDirectory, ...filePath.split('/'))
  const readContent = dependencies.readContent ?? (filePath => (
    readFileSync(resolvePath(filePath), 'utf8')
  ))
  const getSize = dependencies.getSize ?? (filePath => statSync(resolvePath(filePath)).size)

  let findings
  try {
    findings = scanM2Artifacts({
      changedFiles: listChangedFiles(base),
      getSize,
      readContent,
    })
  } catch (error) {
    stderr.write('M2 artifact scan failed: ' + error.message + '\n')
    return 2
  }

  for (const finding of findings) {
    stdout.write(finding.path + ': ' + finding.reason + '\n')
  }
  return findings.length === 0 ? 0 : 1
}

function parseBaseArgument(args) {
  let base = null
  if (args.length === 2 && args[0] === '--base' && args[1]?.trim()) base = args[1].trim()
  if (args.length === 1 && args[0].startsWith('--base=') && args[0].slice(7).trim()) {
    base = args[0].slice(7).trim()
  }
  if (base === null) {
    throw new Error('usage: node scripts/scan-m2-artifacts.mjs --base <commit>; --base is required')
  }
  if (base.startsWith('-') || !/^[A-Za-z0-9][A-Za-z0-9._/-]*$/u.test(base)) {
    throw new Error('invalid --base revision')
  }
  return base
}

function listNewGitFiles(rootDirectory, base) {
  const verifiedBase = verifyGitCommit(rootDirectory, base)
  const result = spawnGit(rootDirectory, [
    'diff',
    '--name-only',
    '--diff-filter=A',
    verifiedBase + '...HEAD',
    '--',
  ])
  return result.stdout.split(/\r?\n/u).map(value => value.trim()).filter(Boolean)
}

function verifyGitCommit(rootDirectory, base) {
  const result = spawnGit(rootDirectory, [
    'rev-parse',
    '--verify',
    '--end-of-options',
    base + '^{commit}',
  ])
  const commit = result.stdout.trim()
  if (!/^[0-9a-f]{40,64}$/iu.test(commit)) throw new Error('git returned an invalid commit id')
  return commit
}

function spawnGit(rootDirectory, args) {
  const result = spawnSync('git', args, {
    cwd: rootDirectory,
    encoding: 'utf8',
    shell: false,
  })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error((result.stderr || 'git command failed').trim())
  return result
}

function validateSize(value, filePath) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new TypeError('invalid artifact size: ' + filePath)
  }
  return value
}

function hasForbiddenRawExtension(filePath) {
  if (FORBIDDEN_EBOOK_EXTENSION.test(filePath)) return true
  return filePath !== M2_REQUIREMENTS_LOCK && RAW_TEXT_EXTENSION.test(filePath)
}

function containsPrivateSentinel(content) {
  if (PRIVATE_SENTINELS.some(sentinel => content.includes(sentinel))) return true
  return PRIVATE_DSN.test(content)
}

function looksLikeLargeSourceText(content) {
  if (content.length < LARGE_TEXT_MINIMUM) return false
  let cjkCount = 0
  let wordCount = 0
  let inWord = false
  for (const character of content) {
    if (CJK_CHARACTER.test(character)) {
      cjkCount += 1
      if (cjkCount >= LARGE_CJK_MINIMUM) return true
    }
    const isLetter = LETTER_CHARACTER.test(character)
    if (isLetter && !inWord) {
      wordCount += 1
      if (wordCount >= LARGE_WORD_MINIMUM) return true
    }
    inWord = isLetter
  }
  return false
}

function normalizeRepositoryPath(value) {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new TypeError('changed file path must be non-empty')
  }
  if (path.win32.isAbsolute(value) || /^[A-Za-z]:/u.test(value)) {
    throw new Error('changed file is outside repository: ' + value)
  }
  const normalized = path.posix.normalize(value.replaceAll('\\', '/').replace(/^\.\//u, ''))
  if (path.posix.isAbsolute(normalized) || normalized === '..' || normalized.startsWith('../')) {
    throw new Error('changed file is outside repository: ' + value)
  }
  return normalized
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : ''
if (invokedPath && path.resolve(fileURLToPath(import.meta.url)) === invokedPath) {
  process.exitCode = runArtifactScannerCli()
}
