import { randomUUID } from 'node:crypto'
import {
  mkdirSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  assertDatabaseName,
  assertOwnedRoot,
  BASE_ENV_ALLOWLIST,
  createDatabaseName,
  createOwnedRoot,
  removeOwnedRoot,
  reserveLocalPort,
  runBoundedOwnedCommand,
  runOwnedProductLifecycle,
  startOwnedServer,
  stopOwnedServer,
  validateTestEnvironment,
  waitForOwnedServer,
} from './support/product-runner.mjs'
import { runtimeSensitiveValues } from './runtime-observer.mjs'
import { createServerLogObserver } from './server-log-observer.mjs'


export const FORMAL_SPECS = Object.freeze([
  'e2e/phase2-creative-foundation.spec.ts',
])

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const OWNED_ROOT_PREFIX = 'novel-creator-phase2-'
const SECRET_SENTINEL = 'phase2-browser-secret-must-not-leak'
const MODEL_SENTINEL = 'phase2-browser-model-must-not-leak'
const TRANSCRIPT_SENTINEL = 'phase2-browser-transcript-must-not-leak'
const PROMPT_SENTINEL = 'phase2-browser-prompt-must-not-leak'
const RAW_PROVIDER_SENTINEL = 'phase2-browser-raw-provider-must-not-leak'
const CORPUS_TEXT_SENTINEL = 'phase2-browser-corpus-text-must-not-leak'
const DEFAULT_DEADLINES = Object.freeze({
  commandMs: 90_000,
  healthMs: 45_000,
  browserMs: 300_000,
  stopMs: 8_000,
})
const AUDIT_DIAGNOSTIC_METHODS = new Set([
  'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'UNKNOWN',
])
const AUDIT_DIAGNOSTIC_PATHNAMES = new Set([
  'project',
  'overview-preparation',
  'contract-head',
  'contract-draft',
  'bible-head',
  'bible-draft',
  'bible-history',
  'market',
  'assets',
  'other-api',
  'non-api',
  'unparsed',
])
const AUDIT_DIAGNOSTIC_ERRORS = new Set([
  'cancelled', 'target-closed', 'protocol-no-resource', 'other',
])
const AUDIT_DIAGNOSTIC_CONSOLES = new Set([
  'resource-404', 'resource-4xx', 'resource-5xx', 'ui-error-boundary',
  'other-error',
])
const AUDIT_DIAGNOSTIC_HEALTH = new Set([
  'page-error',
  'request-failure',
  'api-response-header-read-error',
  'api-response-body-read-error',
  'request-header-read-error',
  'request-body-read-error',
])
export const ALLOWED_BROWSER_STEPS = Object.freeze([
  'browser-test-started',
  'library-visible',
  'project-created',
  'assets-visible',
  'corpus-imported',
  'market-snapshots-imported',
  'seed-a-selected',
  'seed-b-selected',
  'seed-a-reselected',
  'contract-workspace-visible',
  'story-engines-recorded',
  'asset-recommendations-returned',
  'contract-scope-selected',
  'contract-confirmed',
  'bible-workspace-visible',
  'bible-generation-returned',
  'bible-generation-http-ok',
  'bible-generation-notice-visible',
  'bible-generation-succeeded',
  'bible-first-saved',
  'bible-first-confirmed',
  'bible-adjustment-created',
  'bible-failure-state-captured',
  'bible-failure-instructions-set',
  'bible-failure-ready',
  'bible-failure-submitted',
  'bible-failure-returned',
  'bible-failure-preserved',
  'bible-second-saved',
  'bible-second-confirmed',
  'navigation-boundaries-verified',
  'preparation-boundary-visible',
  'archive-project-card-visible',
  'archive-returned',
  'archive-status-visible',
  'archive-bible-visible',
  'project-archived-read-only',
  'not-found-visible',
  'audit-known-failures-verified',
  'audit-runtime-health-verified',
  'audit-writes-verified',
  'audit-origins-verified',
  'audit-secret-scan-verified',
  'runtime-clean',
])

const BACKEND_SOURCE = String.raw`
import os
import sys
from urllib.parse import urlsplit

import httpx
import uvicorn

PROVIDER_BASE_URL = os.environ["BROWSER_PROVIDER_BASE_URL"]
OUTBOUND_LEDGER_PATH = os.environ["BROWSER_OUTBOUND_LEDGER_PATH"]

def allowed_provider_target():
    parsed = urlsplit(PROVIDER_BASE_URL)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.path.rstrip("/") != "/v1"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RuntimeError("invalid runner-owned provider boundary")
    return ("http", "127.0.0.1", parsed.port, "/v1/chat/completions")

ALLOWED_PROVIDER_TARGET = allowed_provider_target()

def record_forbidden_outbound():
    descriptor = os.open(OUTBOUND_LEDGER_PATH, os.O_WRONLY | os.O_APPEND)
    try:
        os.write(descriptor, b"forbidden-outbound\n")
    finally:
        os.close(descriptor)

def outbound_allowed(url):
    try:
        parsed = urlsplit(str(url))
        target = (parsed.scheme, parsed.hostname, parsed.port, parsed.path)
    except (TypeError, ValueError):
        return False
    return (
        target == ALLOWED_PROVIDER_TARGET
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    )

OriginalAsyncClient = httpx.AsyncClient

class GuardedAsyncClient(OriginalAsyncClient):
    async def send(self, request, *args, **kwargs):
        if not outbound_allowed(request.url):
            record_forbidden_outbound()
            raise RuntimeError("forbidden test outbound")
        return await super().send(request, *args, **kwargs)

httpx.AsyncClient = GuardedAsyncClient

from backend.main import app

uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(sys.argv[1]),
    log_config=None,
    access_log=False,
)
`

const FAKE_GATEWAY_SOURCE = String.raw`
import http from 'node:http'
import { appendFileSync } from 'node:fs'

const port = Number(process.env.BROWSER_FAKE_GATEWAY_PORT)
const nonce = process.env.M2_BROWSER_RUN_NONCE
const apiKey = process.env.BROWSER_SECRET_SENTINEL
const counterPath = process.env.BROWSER_FAKE_COUNTER_PATH
const promptSentinel = process.env.BROWSER_PROMPT_SENTINEL
const rawProviderSentinel = process.env.BROWSER_RAW_PROVIDER_SENTINEL
const corpusTextSentinel = process.env.BROWSER_CORPUS_TEXT_SENTINEL
if (
  !Number.isInteger(port)
  || port <= 0
  || !nonce
  || !apiKey
  || !counterPath
  || !promptSentinel
  || !rawProviderSentinel
  || !corpusTextSentinel
) {
  throw new Error('fake gateway ownership configuration is invalid')
}

function recordCounter(token) {
  appendFileSync(counterPath, token + '\n', { encoding: 'utf8' })
}

function sendJson(response, status, value) {
  response.writeHead(status, {
    'content-type': 'application/json',
    'connection': 'close',
  })
  response.end(JSON.stringify(value))
}

async function readJson(request) {
  const chunks = []
  let size = 0
  for await (const chunk of request) {
    size += chunk.length
    if (size > 256 * 1024) throw new Error('request too large')
    chunks.push(chunk)
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

function classify(messages) {
  if (!Array.isArray(messages) || messages.length !== 2) return null
  const [system, user] = messages
  if (system?.role !== 'system' || user?.role !== 'user') return null
  let instruction
  let evidence
  try {
    instruction = JSON.parse(system.content)
    evidence = JSON.parse(user.content)
  } catch {
    return null
  }
  if (
    instruction?.task
      === 'Rank only the supplied eligible asset and corpus candidates.'
  ) return { kind: 'asset-ranking', evidence }
  if (instruction?.task === 'Generate one complete creation Bible') {
    return { kind: 'bible', evidence }
  }
  return null
}

function assetRankingResponse(evidence) {
  const candidate = evidence?.assetCandidates?.[0]
  if (!candidate?.assetRevisionId) return null
  return {
    assetRecommendations: [{
      assetRevisionId: candidate.assetRevisionId,
      reason: 'The fixture evidence is too weak for an automatic suggestion.',
      confidence: 0.2,
    }],
    corpusRecommendations: [],
  }
}

function bibleResponse() {
  return {
    premiseAndPromise: '一名穿越者借散落典籍解决现实危机，也在每次取舍中重建人与知识的关系。',
    worldRules: [
      { id: 'world-record-cost', text: '知识只能通过可验证的记录兑现，每次公开都会改变既有利益关系。' },
    ],
    powerOrProgressionSystem: '主角从辨认残卷、交叉验证到组织协作，成长来自证据能力与承担后果的范围扩大。',
    protagonist: '沈砚谨慎、重证据，却无法坐视具体的人被制度当成代价。',
    coreCast: [
      { id: 'cast-copyist', text: '抄书匠阿绫敏锐直接，负责把抽象知识转成普通人能使用的方法。' },
      { id: 'cast-guard', text: '守门校尉顾峤讲秩序也护百姓，经常逼主角说明证据之外的责任。' },
    ],
    factions: [
      { id: 'faction-archive', text: '秘阁希望垄断典籍解释权，并以秩序之名封存危险记录。' },
      { id: 'faction-folk', text: '民间抄书网络保存残卷，但成员的利益和立场并不一致。' },
    ],
    longTermConflicts: [
      { id: 'conflict-control', text: '公开知识能救眼前的人，也会加速各方争夺散落卷册。' },
    ],
    relationshipDynamics: [
      { id: 'relation-trust', text: '沈砚与同伴的信任由共同承担代价建立，而非靠单向说服。' },
    ],
    toneAndNarrativeBoundaries: '以清晰大白话讲丰满故事，人物先行动再解释；避免文献式概述和机械总结。',
    continuityGuardrails: [
      { id: 'guard-no-free-win', text: '知识优势不能无代价解决政治、人情与资源冲突。' },
      { id: 'guard-distinct-voices', text: '主要人物的欲望、语气和判断方式必须保持区别。' },
    ],
    openDesignQuestions: [
      { id: 'question-catalogue', text: '永乐大典的散佚是意外、权力斗争，还是更长远计划的一部分？' },
    ],
  }
}

const server = http.createServer(async (request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    sendJson(response, 200, { browserRunNonce: nonce })
    return
  }
  if (request.method === 'POST' && request.url === '/v1/chat/completions') {
    recordCounter('provider-attempt')
    if (request.headers.authorization !== 'Bearer ' + apiKey) {
      recordCounter('provider-rejected-auth')
      sendJson(response, 404, { error: { code: 'not_found' } })
      return
    }
    let body
    try {
      body = await readJson(request)
    } catch {
      recordCounter('provider-rejected-json')
      sendJson(response, 400, { error: { code: 'invalid_request' } })
      return
    }
    const classified = classify(body.messages)
    if (!classified) {
      recordCounter('provider-rejected-classify')
      sendJson(response, 422, { error: { code: 'unsupported_fixture_request' } })
      return
    }
    if (classified.kind === 'bible') {
      const serializedPrompt = JSON.stringify(body.messages)
      if (
        !serializedPrompt.includes(promptSentinel)
        || !serializedPrompt.includes(corpusTextSentinel)
      ) {
        recordCounter('provider-rejected-content')
        sendJson(response, 422, { error: { code: 'missing_fixture_evidence' } })
        return
      }
    }
    if (
      classified.kind === 'bible'
      && String(classified.evidence?.authorInstructions || '').includes('FAIL_SAFE')
    ) {
      recordCounter('bible-failure')
      sendJson(response, 503, { error: { code: 'fixture_provider_unavailable' } })
      return
    }
    const content = classified.kind === 'asset-ranking'
      ? assetRankingResponse(classified.evidence)
      : bibleResponse()
    if (!content) {
      recordCounter('provider-rejected-content')
      sendJson(response, 422, { error: { code: 'unsupported_fixture_request' } })
      return
    }
    const token = classified.kind === 'bible'
      ? 'bible-success'
      : 'asset-ranking'
    recordCounter(token)
    sendJson(response, 200, {
      rawProviderSentinel,
      choices: [{
        message: {
          role: 'assistant',
          content: JSON.stringify(content),
        },
      }],
    })
    return
  }
  sendJson(response, 404, { error: { code: 'not_found' } })
})

server.listen(port, '127.0.0.1')
`

const DATABASE_EVIDENCE_SOURCE = String.raw`
import asyncio
import os

from backend.database import close_pool, connection

async def main():
    expected = os.environ["BROWSER_TEST_DATABASE"]
    async with connection() as session:
        current = await session.fetchone("SELECT DATABASE() AS database_name")
        assert current == {"database_name": expected}
        styles = await session.fetchone("SELECT COUNT(*) AS count FROM style_templates")
        cards = await session.fetchone("SELECT COUNT(*) AS count FROM experience_cards")
        sources = await session.fetchone("SELECT COUNT(*) AS count FROM market_sources")
        providers = await session.fetchone(
            "SELECT COUNT(*) AS count FROM provider_profiles "
            "WHERE lifecycle_status='active'"
        )
        assert styles == {"count": 10}
        assert cards == {"count": 64}
        assert sources == {"count": 2}
        assert providers == {"count": 1}
    print("database_identity=verified")
    print("style_count=10")
    print("card_count=64")
    print("source_count=2")
    print("provider_count=1")

async def program():
    try:
        await main()
    finally:
        await close_pool()

asyncio.run(program())
`


function allowlistedBaseEnvironment(environment) {
  return Object.fromEntries(
    BASE_ENV_ALLOWLIST
      .filter(name => Object.hasOwn(environment, name))
      .map(name => [name, environment[name]]),
  )
}


function childOptions(cwd, env) {
  return { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] }
}


function snapshotDocument({
  platform,
  rankingName,
  sourceURL,
  title,
  author,
  workURL,
  capturedAt,
}) {
  return {
    platform,
    rankingName,
    category: 'male',
    capturedAt,
    sourceURL,
    entries: [{
      rank: 1,
      title,
      author,
      category: '历史穿越',
      workURL,
      publicMetrics: { heat: 100 },
    }],
  }
}


export function buildSyntheticCorpusFixture() {
  return [
    '第一章 雾港错钟',
    '沈砚守着潮墙上的旧钟。第三声钟鸣提前到来，港口却在无风的夜里退潮。巡夜人催他照旧登记，他没有动笔，而是先把钟摆、潮痕和守门人的口供逐项记在废纸背面。',
    '码头上的船工已经开始争抢缆绳，商会管事却坚持先保住装盐的官船。阿绫挤过人群，把一张被水泡软的轮值表塞进他手里，提醒他导师失踪那晚也出现过同样的空白时刻。',
    '沈砚知道只要敲响警钟，今夜的船队或许能获救，钟室被人篡改的证据却会立刻暴露。他让顾峤封住侧门，自己爬上钟架核对齿轮，把救人和追查都变成必须当场承担的选择。',
    `等最后一艘小船越过暗礁，他才在记录末尾留下这段只供完整语料链验证的标记：${CORPUS_TEXT_SENTINEL}`,
    '',
    '第二章 纸带回声',
    '他从导师留下的纸带中辨出一组反向刻度，决定先救被困船队，再追查谁篡改了钟室记录。',
  ].join('\n')
}


function prepareOwnedFiles(ownedRoot) {
  const root = assertOwnedRoot(ownedRoot, OWNED_ROOT_PREFIX)
  const filesRoot = path.join(root, 'files')
  const corpusRoot = path.join(root, 'corpus-incoming')
  const managedRoot = path.join(root, 'corpus-managed')
  mkdirSync(filesRoot)
  mkdirSync(corpusRoot)
  mkdirSync(managedRoot)
  const fakeGatewayPath = path.join(filesRoot, 'fake-provider-gateway.mjs')
  const outboundLedgerPath = path.join(filesRoot, 'forbidden-outbound.log')
  const corpusPath = path.join(corpusRoot, 'phase2-synthetic-corpus.txt')
  const stepLedgerPath = path.join(filesRoot, 'browser-steps.log')
  const runtimeAuditDiagnosticPath = path.join(
    filesRoot,
    'runtime-audit-diagnostic.json',
  )
  const counterPath = path.join(filesRoot, 'gateway-counters.log')
  const qidianPath = path.join(filesRoot, 'qidian-public-snapshot.json')
  const qqPath = path.join(filesRoot, 'qq-public-snapshot.json')
  const capturedAt = Date.now()
  writeFileSync(fakeGatewayPath, FAKE_GATEWAY_SOURCE, {
    encoding: 'utf8',
    flag: 'wx',
  })
  writeFileSync(outboundLedgerPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(stepLedgerPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(runtimeAuditDiagnosticPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(counterPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(qidianPath, JSON.stringify(snapshotDocument({
    platform: 'qidian',
    rankingName: 'newsign',
    sourceURL: 'https://www.qidian.com/rank/newsign/',
    title: '山河典籍录',
    author: '合成作者甲',
    workURL: 'https://www.qidian.com/book/900000001/',
    capturedAt,
  })), { encoding: 'utf8', flag: 'wx' })
  writeFileSync(qqPath, JSON.stringify(snapshotDocument({
    platform: 'qq_reading',
    rankingName: 'male_popular',
    sourceURL: 'https://book.qq.com/book-rank',
    title: '北境火种',
    author: '合成作者乙',
    workURL: 'https://book.qq.com/book-detail/900000002',
    capturedAt: capturedAt + 1,
  })), { encoding: 'utf8', flag: 'wx' })
  writeFileSync(
    corpusPath,
    buildSyntheticCorpusFixture(),
    { encoding: 'utf8', flag: 'wx' },
  )
  return {
    root,
    filesRoot,
    corpusRoot,
    managedRoot,
    corpusPath,
    qidianPath,
    qqPath,
    fakeGatewayPath,
    outboundLedgerPath,
    stepLedgerPath,
    runtimeAuditDiagnosticPath,
    counterPath,
  }
}


export function buildEnvironments(
  environment,
  databaseName,
  backendUrl,
  viteUrl,
  gatewayUrl,
  nonce,
  roots,
) {
  const base = allowlistedBaseEnvironment(environment)
  const database = {
    MYSQL_HOST: environment.TEST_MYSQL_HOST,
    MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER,
    MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: databaseName,
  }
  const providerFixture = {
    BROWSER_PROVIDER_BASE_URL: gatewayUrl,
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_MODEL_SENTINEL: MODEL_SENTINEL,
  }
  const prepare = {
    ...base,
    TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST,
    TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: environment.TEST_MYSQL_USER,
    TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    ...database,
    ...providerFixture,
  }
  const backend = {
    ...base,
    ...database,
    ...providerFixture,
    BROWSER_TEST_DATABASE: databaseName,
    BROWSER_OUTBOUND_LEDGER_PATH: roots.outboundLedgerPath,
    BROWSER_TRANSCRIPT_SENTINEL: TRANSCRIPT_SENTINEL,
    M2_BROWSER_RUN_NONCE: nonce,
    MARKET_SCHEDULER_ENABLED: 'false',
    CORPUS_ROOT: roots.corpusRoot,
    MANAGED_CORPUS_ROOT: roots.managedRoot,
  }
  const vite = {
    ...base,
    M2_BROWSER_RUN_NONCE: nonce,
    VITE_API_BASE_URL: `${backendUrl}/api`,
  }
  const browser = {
    ...base,
    PLAYWRIGHT_BASE_URL: viteUrl,
    BROWSER_VITE_ORIGIN: viteUrl,
    BROWSER_BACKEND_ORIGIN: backendUrl,
    BROWSER_OWNED_ROOT: roots.root,
    BROWSER_ARTIFACT_ROOT: path.join(roots.root, 'phase2-test-results'),
    BROWSER_CORPUS_FILE: roots.corpusPath,
    BROWSER_QIDIAN_SNAPSHOT_PATH: roots.qidianPath,
    BROWSER_QQ_SNAPSHOT_PATH: roots.qqPath,
    BROWSER_STEP_LEDGER: roots.stepLedgerPath,
    BROWSER_RUNTIME_AUDIT_DIAGNOSTIC: roots.runtimeAuditDiagnosticPath,
    BROWSER_TEST_DATABASE: databaseName,
    ...providerFixture,
    BROWSER_PRIVATE_PROVIDER_URL: gatewayUrl,
    BROWSER_TRANSCRIPT_SENTINEL: TRANSCRIPT_SENTINEL,
    BROWSER_PROMPT_SENTINEL: PROMPT_SENTINEL,
    BROWSER_RAW_PROVIDER_SENTINEL: RAW_PROVIDER_SENTINEL,
    BROWSER_CORPUS_TEXT_SENTINEL: CORPUS_TEXT_SENTINEL,
    BROWSER_CORPUS_ROOT_SENTINEL: roots.root,
  }
  const gateway = {
    ...base,
    M2_BROWSER_RUN_NONCE: nonce,
    BROWSER_FAKE_GATEWAY_PORT: String(new URL(gatewayUrl).port),
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_PROMPT_SENTINEL: PROMPT_SENTINEL,
    BROWSER_RAW_PROVIDER_SENTINEL: RAW_PROVIDER_SENTINEL,
    BROWSER_CORPUS_TEXT_SENTINEL: CORPUS_TEXT_SENTINEL,
    BROWSER_FAKE_COUNTER_PATH: roots.counterPath,
  }
  const sensitiveController = {
    ...database,
    BROWSER_TEST_DATABASE: databaseName,
    BROWSER_PROVIDER_BASE_URL: gatewayUrl,
    BROWSER_PRIVATE_PROVIDER_URL: gatewayUrl,
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_TRANSCRIPT_SENTINEL: TRANSCRIPT_SENTINEL,
    BROWSER_PROMPT_SENTINEL: PROMPT_SENTINEL,
    BROWSER_RAW_PROVIDER_SENTINEL: RAW_PROVIDER_SENTINEL,
    BROWSER_CORPUS_TEXT_SENTINEL: CORPUS_TEXT_SENTINEL,
    BROWSER_CORPUS_ROOT_SENTINEL: roots.root,
  }
  return { prepare, backend, vite, browser, gateway, sensitiveController }
}


export function resolveCommandLineSpecs(argumentsList) {
  if (!Array.isArray(argumentsList)) {
    throw new TypeError('Phase 2 browser CLI arguments must be an array')
  }
  if (argumentsList.length !== 0) {
    throw new Error('Phase 2 browser runner does not accept spec paths')
  }
  return [...FORMAL_SPECS]
}


function validateSpecs(specs) {
  if (
    !Array.isArray(specs)
    || specs.length !== FORMAL_SPECS.length
    || specs.some((spec, index) => spec !== FORMAL_SPECS[index])
  ) {
    throw new Error('Phase 2 browser requires the exact formal spec path')
  }
  return [...FORMAL_SPECS]
}


export function verifyGatewayCounterLedger(ledger) {
  const expected = Object.freeze({
    'provider-attempt': 4,
    'asset-ranking': 2,
    'bible-success': 1,
    'bible-failure': 1,
    'provider-rejected-auth': 0,
    'provider-rejected-json': 0,
    'provider-rejected-classify': 0,
    'provider-rejected-content': 0,
  })
  const allowed = Object.keys(expected)
  const counts = Object.fromEntries(allowed.map(kind => [kind, 0]))
  const lines = String(ledger || '').split(/\r?\n/u).filter(Boolean)
  for (const line of lines) {
    if (!Object.hasOwn(counts, line)) {
      throw new Error('Phase 2 gateway call ledger contains an unknown type')
    }
    counts[line] += 1
  }
  if (allowed.some(kind => counts[kind] !== expected[kind])) {
    throw new Error('Phase 2 gateway call ledger has unexpected formal counts')
  }
  return counts
}


export function verifyForbiddenOutboundLedger(ledger) {
  if (String(ledger || '') !== '') {
    throw new Error('Phase 2 forbidden outbound ledger is not empty')
  }
  return { 'forbidden-outbound': 0 }
}


export function summarizeBrowserStepLedger(ledger) {
  const lines = String(ledger || '').split(/\r?\n/u).filter(Boolean)
  const firstMismatchIndex = lines.findIndex((line, index) => (
    line !== ALLOWED_BROWSER_STEPS[index]
  ))
  const mismatch = firstMismatchIndex === -1 ? null : firstMismatchIndex
  const actualLine = mismatch === null ? null : lines[mismatch]
  return {
    lineCount: lines.length,
    firstMismatchIndex: mismatch,
    expected: mismatch === null
      ? 'none'
      : ALLOWED_BROWSER_STEPS[mismatch] || 'none',
    actual: mismatch === null
      ? 'none'
      : ALLOWED_BROWSER_STEPS.includes(actualLine) ? actualLine : 'unknown',
    duplicateCount: lines.length - new Set(lines).size,
  }
}


export function verifyBrowserStepLedger(
  ledger,
  { requireComplete = false } = {},
) {
  const lines = String(ledger || '').split(/\r?\n/u).filter(Boolean)
  if (
    lines.some((line, index) => line !== ALLOWED_BROWSER_STEPS[index])
    || (
      requireComplete
      && (
        lines.length !== ALLOWED_BROWSER_STEPS.length
        || lines.some((line, index) => line !== ALLOWED_BROWSER_STEPS[index])
      )
    )
  ) {
    throw new Error('Phase 2 browser progress ledger is invalid')
  }
  return lines
}


function exactObjectKeys(value, expected) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const actual = Object.keys(value).sort()
  const wanted = [...expected].sort()
  return (
    actual.length === wanted.length
    && actual.every((key, index) => key === wanted[index])
  )
}


export function verifyRuntimeAuditDiagnostic(serialized) {
  let diagnostic
  try {
    diagnostic = JSON.parse(String(serialized || ''))
  } catch {
    throw new Error('Phase 2 runtime audit diagnostic is invalid')
  }
  if (
    !exactObjectKeys(
      diagnostic,
      [
        'responseFailures',
        'consoleErrors',
        'healthErrors',
        'requestFailureDetails',
        'apiResponseBodyReadErrorDetails',
      ],
    )
    || !Array.isArray(diagnostic.responseFailures)
    || !Array.isArray(diagnostic.consoleErrors)
    || !Array.isArray(diagnostic.healthErrors)
    || !Array.isArray(diagnostic.requestFailureDetails)
    || !Array.isArray(diagnostic.apiResponseBodyReadErrorDetails)
    || diagnostic.responseFailures.length > 20
    || diagnostic.consoleErrors.length > 20
    || diagnostic.healthErrors.length > 20
    || diagnostic.requestFailureDetails.length > 20
    || diagnostic.apiResponseBodyReadErrorDetails.length > 20
  ) {
    throw new Error('Phase 2 runtime audit diagnostic is invalid')
  }
  const responseKeys = new Set()
  for (const entry of diagnostic.responseFailures) {
    const statusIsSafe = entry?.status === 'unparsed'
      || (
        Number.isInteger(entry?.status)
        && entry.status >= 400
        && entry.status <= 599
      )
    const key = `${String(entry?.status)}:${String(entry?.method)}:`
      + String(entry?.pathnameCategory)
    if (
      !exactObjectKeys(
        entry,
        ['status', 'method', 'pathnameCategory', 'count'],
      )
      || !statusIsSafe
      || !AUDIT_DIAGNOSTIC_METHODS.has(entry.method)
      || !AUDIT_DIAGNOSTIC_PATHNAMES.has(entry.pathnameCategory)
      || !Number.isInteger(entry.count)
      || entry.count < 1
      || entry.count > 100
      || responseKeys.has(key)
    ) {
      throw new Error('Phase 2 runtime audit diagnostic is invalid')
    }
    responseKeys.add(key)
  }
  const consoleKeys = new Set()
  for (const entry of diagnostic.consoleErrors) {
    if (
      !exactObjectKeys(entry, ['category', 'count'])
      || !AUDIT_DIAGNOSTIC_CONSOLES.has(entry.category)
      || !Number.isInteger(entry.count)
      || entry.count < 1
      || entry.count > 100
      || consoleKeys.has(entry.category)
    ) {
      throw new Error('Phase 2 runtime audit diagnostic is invalid')
    }
    consoleKeys.add(entry.category)
  }
  const healthKeys = new Set()
  for (const entry of diagnostic.healthErrors) {
    if (
      !exactObjectKeys(entry, ['category', 'count'])
      || !AUDIT_DIAGNOSTIC_HEALTH.has(entry.category)
      || !Number.isInteger(entry.count)
      || entry.count < 1
      || entry.count > 100
      || healthKeys.has(entry.category)
    ) {
      throw new Error('Phase 2 runtime audit diagnostic is invalid')
    }
    healthKeys.add(entry.category)
  }
  const requestFailureKeys = new Set()
  for (const entry of diagnostic.requestFailureDetails) {
    const key = `${String(entry?.method)}:${String(entry?.pathCategory)}:`
      + String(entry?.errorCategory)
    if (
      !exactObjectKeys(
        entry,
        ['method', 'pathCategory', 'errorCategory', 'count'],
      )
      || !AUDIT_DIAGNOSTIC_METHODS.has(entry.method)
      || !AUDIT_DIAGNOSTIC_PATHNAMES.has(entry.pathCategory)
      || !AUDIT_DIAGNOSTIC_ERRORS.has(entry.errorCategory)
      || !Number.isInteger(entry.count)
      || entry.count < 1
      || entry.count > 100
      || requestFailureKeys.has(key)
    ) {
      throw new Error('Phase 2 runtime audit diagnostic is invalid')
    }
    requestFailureKeys.add(key)
  }
  const bodyReadErrorKeys = new Set()
  for (const entry of diagnostic.apiResponseBodyReadErrorDetails) {
    const key = `${String(entry?.method)}:${String(entry?.status)}:`
      + `${String(entry?.pathCategory)}:${String(entry?.errorCategory)}`
    if (
      !exactObjectKeys(
        entry,
        ['method', 'status', 'pathCategory', 'errorCategory', 'count'],
      )
      || !AUDIT_DIAGNOSTIC_METHODS.has(entry.method)
      || !Number.isInteger(entry.status)
      || entry.status < 100
      || entry.status > 599
      || !AUDIT_DIAGNOSTIC_PATHNAMES.has(entry.pathCategory)
      || !AUDIT_DIAGNOSTIC_ERRORS.has(entry.errorCategory)
      || !Number.isInteger(entry.count)
      || entry.count < 1
      || entry.count > 100
      || bodyReadErrorKeys.has(key)
    ) {
      throw new Error('Phase 2 runtime audit diagnostic is invalid')
    }
    bodyReadErrorKeys.add(key)
  }
  const response = diagnostic.responseFailures.length === 0
    ? 'none'
    : diagnostic.responseFailures
      .map(entry => (
        `${String(entry.status)}:${entry.method}:${entry.pathnameCategory}`
        + `=${String(entry.count)}`
      ))
      .join(',')
  const console = diagnostic.consoleErrors.length === 0
    ? 'none'
    : diagnostic.consoleErrors
      .map(entry => `${entry.category}=${String(entry.count)}`)
      .join(',')
  const health = diagnostic.healthErrors.length === 0
    ? 'none'
    : diagnostic.healthErrors
      .map(entry => `${entry.category}=${String(entry.count)}`)
      .join(',')
  const requestFailures = diagnostic.requestFailureDetails.length === 0
    ? 'none'
    : diagnostic.requestFailureDetails
      .map(entry => (
        `${entry.method}:${entry.pathCategory}:${entry.errorCategory}`
        + `=${String(entry.count)}`
      ))
      .join(',')
  const apiBodyReadErrors =
    diagnostic.apiResponseBodyReadErrorDetails.length === 0
      ? 'none'
      : diagnostic.apiResponseBodyReadErrorDetails
        .map(entry => (
          `${entry.method}:${String(entry.status)}:${entry.pathCategory}:`
          + `${entry.errorCategory}=${String(entry.count)}`
        ))
        .join(',')
  return `response[${response}];console[${console}];health[${health}];`
    + `requestFailures[${requestFailures}];`
    + `apiBodyReadErrors[${apiBodyReadErrors}]`
}


const PHASE2_FAILURE_CATEGORIES = new Map([
  ['Phase 2 browser test process exited with status 1', 'browser-process-exit'],
  [
    'Phase 2 browser test process log contained runtime-sensitive values',
    'browser-log-sensitive',
  ],
  ['Phase 2 browser progress ledger is invalid', 'step-ledger'],
  ['Phase 2 gateway call ledger has unexpected formal counts', 'gateway-counts'],
  ['Phase 2 gateway call ledger contains an unknown type', 'gateway-unknown'],
  ['Phase 2 forbidden outbound ledger is not empty', 'forbidden-outbound'],
  ['Phase 2 database evidence process exited with status 1', 'database-evidence'],
  ['Runtime evidence contains response failures', 'runtime-audit'],
  ['Runtime evidence contains console errors', 'runtime-audit'],
  ['Runtime evidence contains page errors', 'runtime-audit'],
  ['Runtime evidence contains request failures', 'runtime-audit'],
  ['Runtime API response headers could not be read', 'runtime-audit'],
  ['Runtime API response bodies could not be read', 'runtime-audit'],
  ['Runtime request headers could not be read', 'runtime-audit'],
  ['Runtime request bodies could not be read', 'runtime-audit'],
  [
    'fake Provider gateway log contained runtime-sensitive values',
    'server-cleanup',
  ],
  ['fake Provider gateway stop, drain, or log audit failed', 'server-cleanup'],
  ['backend log contained runtime-sensitive values', 'server-cleanup'],
  ['backend stop, drain, or log audit failed', 'server-cleanup'],
  ['vite log contained runtime-sensitive values', 'server-cleanup'],
  ['vite stop, drain, or log audit failed', 'server-cleanup'],
  ['Phase 2 database cleanup process failed to start', 'database-cleanup'],
  ['Phase 2 database cleanup process exited with status 1', 'database-cleanup'],
  [
    'Phase 2 database cleanup process log contained runtime-sensitive values',
    'database-cleanup',
  ],
  ['Phase 2 server cleanup failed', 'server-cleanup'],
  ['Phase 2 reservation cleanup failed', 'reservation-cleanup'],
  ['Phase 2 database cleanup failed', 'database-cleanup'],
  ['Phase 2 root cleanup failed', 'root-cleanup'],
])

const PHASE2_CLEANUP_FAILURE_MESSAGES = new Map([
  ['server', 'Phase 2 server cleanup failed'],
  ['reservation', 'Phase 2 reservation cleanup failed'],
  ['database', 'Phase 2 database cleanup failed'],
  ['root', 'Phase 2 root cleanup failed'],
])


function errorGraph(error) {
  const pending = [error]
  const seen = new Set()
  return {
    next() {
      while (pending.length > 0) {
        const current = pending.pop()
        if (
          current === null
          || (typeof current !== 'object' && typeof current !== 'function')
          || seen.has(current)
        ) continue
        seen.add(current)
        if (Array.isArray(current.errors)) pending.push(...current.errors)
        if (current.cause !== undefined) pending.push(current.cause)
        return { value: current, done: false }
      }
      return { value: undefined, done: true }
    },
    [Symbol.iterator]() {
      return this
    },
  }
}


export function classifyPhase2Failure(error) {
  for (const current of errorGraph(error)) {
    const category = current instanceof Error
      ? PHASE2_FAILURE_CATEGORIES.get(current.message)
      : undefined
    if (category) return category
  }
  return 'unknown'
}


function phase2FailureStep(error) {
  const prefix = 'Phase 2 browser stopped after '
  for (const current of errorGraph(error)) {
    const message = current instanceof Error ? current.message : ''
    const step = message.startsWith(prefix) ? message.slice(prefix.length) : ''
    if (ALLOWED_BROWSER_STEPS.includes(step)) return step
  }
  return ''
}


function stepLedgerFailureSummary(error) {
  const safeTokens = new Set([...ALLOWED_BROWSER_STEPS, 'none', 'unknown'])
  for (const current of errorGraph(error)) {
    const summary = current.phase2StepLedgerSummary
    if (
      !exactObjectKeys(summary, [
        'lineCount',
        'firstMismatchIndex',
        'expected',
        'actual',
        'duplicateCount',
      ])
      || !Number.isSafeInteger(summary.lineCount)
      || summary.lineCount < 0
      || !(
        summary.firstMismatchIndex === null
        || (
          Number.isSafeInteger(summary.firstMismatchIndex)
          && summary.firstMismatchIndex >= 0
          && summary.firstMismatchIndex < summary.lineCount
        )
      )
      || !safeTokens.has(summary.expected)
      || !safeTokens.has(summary.actual)
      || !Number.isSafeInteger(summary.duplicateCount)
      || summary.duplicateCount < 0
      || summary.duplicateCount > summary.lineCount
    ) continue
    return summary
  }
  return null
}


function phase2AuditFailureSummary(error) {
  for (const current of errorGraph(error)) {
    if (!Object.hasOwn(current, 'phase2AuditDiagnostic')) continue
    try {
      return verifyRuntimeAuditDiagnostic(current.phase2AuditDiagnostic)
    } catch {
      // Invalid diagnostics are intentionally omitted from the CLI rendering.
    }
  }
  return ''
}


export function renderPhase2CliFailure(error) {
  const category = classifyPhase2Failure(error)
  const step = phase2FailureStep(error)
  const suffix = step ? ` after ${step}` : ''
  const summary = category === 'step-ledger'
    ? stepLedgerFailureSummary(error)
    : null
  const ledger = summary
    ? '; stepLedger['
      + `lineCount=${String(summary.lineCount)},`
      + `firstMismatchIndex=${summary.firstMismatchIndex === null
        ? 'none'
        : String(summary.firstMismatchIndex)},`
      + `expected=${summary.expected},actual=${summary.actual},`
      + `duplicateCount=${String(summary.duplicateCount)}]`
    : ''
  const audit = phase2AuditFailureSummary(error)
  const auditSuffix = audit ? `; audit[${audit}]` : ''
  return `Phase 2 browser acceptance failed${suffix}; `
    + `category=${category}${ledger}${auditSuffix}.\n`
}


export async function runPhase2CleanupBoundary(kind, operation) {
  const message = PHASE2_CLEANUP_FAILURE_MESSAGES.get(kind)
  if (message === undefined) {
    throw new Error('Invalid Phase 2 cleanup boundary kind')
  }
  if (typeof operation !== 'function') {
    throw new Error('Invalid Phase 2 cleanup boundary operation')
  }
  try {
    return await operation()
  } catch (cause) {
    throw new Error(message, { cause })
  }
}


function validatePhase2ResourceSummary(summary) {
  if (
    !exactObjectKeys(summary, [
      'scenarios',
      'disposableMysql',
      'ports',
      'tempRoots',
    ])
    || !Number.isSafeInteger(summary.scenarios)
    || summary.scenarios <= 0
  ) {
    throw new Error('Phase 2 resource summary is invalid')
  }
  const sections = [
    ['disposableMysql', 'created', 'cleaned'],
    ['ports', 'reserved', 'released'],
    ['tempRoots', 'created', 'cleaned'],
  ]
  const normalized = { scenarios: summary.scenarios }
  for (const [sectionName, acquiredName, releasedName] of sections) {
    const section = summary[sectionName]
    if (
      !exactObjectKeys(section, [acquiredName, releasedName, 'remaining'])
      || !Number.isSafeInteger(section[acquiredName])
      || section[acquiredName] < 0
      || !Number.isSafeInteger(section[releasedName])
      || section[releasedName] < 0
      || !Number.isSafeInteger(section.remaining)
      || section.remaining < 0
      || section.remaining !== section[acquiredName] - section[releasedName]
    ) {
      throw new Error('Phase 2 resource summary is invalid')
    }
    normalized[sectionName] = {
      [acquiredName]: section[acquiredName],
      [releasedName]: section[releasedName],
      remaining: section.remaining,
    }
  }
  return normalized
}


export function aggregatePhase2ResourceSummaries(summaries) {
  if (!Array.isArray(summaries) || summaries.length === 0) {
    throw new Error('Phase 2 resource summary is invalid')
  }
  const aggregate = {
    scenarios: 0,
    disposableMysql: { created: 0, cleaned: 0, remaining: 0 },
    ports: { reserved: 0, released: 0, remaining: 0 },
    tempRoots: { created: 0, cleaned: 0, remaining: 0 },
  }
  for (const candidate of summaries) {
    const summary = validatePhase2ResourceSummary(candidate)
    aggregate.scenarios += summary.scenarios
    for (const [sectionName, acquiredName, releasedName] of [
      ['disposableMysql', 'created', 'cleaned'],
      ['ports', 'reserved', 'released'],
      ['tempRoots', 'created', 'cleaned'],
    ]) {
      aggregate[sectionName][acquiredName] += summary[sectionName][acquiredName]
      aggregate[sectionName][releasedName] += summary[sectionName][releasedName]
      aggregate[sectionName].remaining =
        aggregate[sectionName][acquiredName]
        - aggregate[sectionName][releasedName]
    }
  }
  return validatePhase2ResourceSummary(aggregate)
}


export function formatPhase2ResourceSummary(candidate) {
  const summary = validatePhase2ResourceSummary(candidate)
  return `phase2_browser: scenarios=${String(summary.scenarios)}\n`
    + 'disposable_mysql: '
    + `created=${String(summary.disposableMysql.created)} `
    + `cleaned=${String(summary.disposableMysql.cleaned)} `
    + `remaining=${String(summary.disposableMysql.remaining)}\n`
    + `ports: reserved=${String(summary.ports.reserved)} `
    + `released=${String(summary.ports.released)} `
    + `remaining=${String(summary.ports.remaining)}\n`
    + `temp_roots: created=${String(summary.tempRoots.created)} `
    + `cleaned=${String(summary.tempRoots.cleaned)} `
    + `remaining=${String(summary.tempRoots.remaining)}\n`
}


function summarizePhase2ResourceCounts(resourceCounts) {
  return validatePhase2ResourceSummary({
    scenarios: 1,
    disposableMysql: {
      ...resourceCounts.disposableMysql,
      remaining:
        resourceCounts.disposableMysql.created
        - resourceCounts.disposableMysql.cleaned,
    },
    ports: {
      ...resourceCounts.ports,
      remaining: resourceCounts.ports.reserved - resourceCounts.ports.released,
    },
    tempRoots: {
      ...resourceCounts.tempRoots,
      remaining:
        resourceCounts.tempRoots.created - resourceCounts.tempRoots.cleaned,
    },
  })
}


async function runOneScenario({
  spec,
  environment,
  databaseNameFactory,
  ownedRootFactory,
  portReservationFactory,
  deadlines,
}) {
  let environments
  let sensitiveValues = []
  const resourceCounts = {
    disposableMysql: { created: 0, cleaned: 0 },
    ports: { reserved: 0, released: 0 },
    tempRoots: { created: 0, cleaned: 0 },
  }
  await runOwnedProductLifecycle({
    async body(lifecycle) {
      const databaseName = lifecycle.setDatabase(databaseNameFactory())
      assertDatabaseName(databaseName)
      const ownedRoot = lifecycle.setRoot(ownedRootFactory())
      resourceCounts.tempRoots.created += 1
      const roots = prepareOwnedFiles(ownedRoot)
      async function registerPortReservation() {
        const reservation = await portReservationFactory()
        resourceCounts.ports.reserved += 1
        return lifecycle.registerReservation(reservation)
      }
      const backendReservation = await registerPortReservation()
      const viteReservation = await registerPortReservation()
      const gatewayReservation = await registerPortReservation()
      const reservations = [
        backendReservation,
        viteReservation,
        gatewayReservation,
      ]
      if (
        reservations.some(reservation => (
          !Number.isInteger(reservation?.port)
          || typeof reservation.release !== 'function'
        ))
        || new Set(reservations.map(item => item.port)).size !== reservations.length
      ) {
        throw new Error('Phase 2 runner received invalid port reservations')
      }

      const nonce = randomUUID()
      const backendUrl = `http://127.0.0.1:${backendReservation.port}`
      const viteUrl = `http://127.0.0.1:${viteReservation.port}`
      const gatewayUrl = `http://127.0.0.1:${gatewayReservation.port}/v1`
      environments = buildEnvironments(
        environment,
        databaseName,
        backendUrl,
        viteUrl,
        gatewayUrl,
        nonce,
        roots,
      )
      sensitiveValues = [
        ...runtimeSensitiveValues(environments.sensitiveController),
        environments.sensitiveController.BROWSER_TRANSCRIPT_SENTINEL,
        environments.sensitiveController.BROWSER_PROMPT_SENTINEL,
        environments.sensitiveController.BROWSER_RAW_PROVIDER_SENTINEL,
        environments.sensitiveController.BROWSER_CORPUS_TEXT_SENTINEL,
      ].filter(value => typeof value === 'string' && value.length > 0)
      const python = environment.PYTHON || 'python'
      const playwrightCli = path.join(
        frontendRoot,
        'node_modules',
        'playwright',
        'cli.js',
      )
      const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js')
      const activeServers = []

      await runBoundedOwnedCommand(
        python,
        [
          '-m',
          'backend.scripts.prepare_phase2_browser_db',
          '--database',
          databaseName,
        ],
        childOptions(repositoryRoot, environments.prepare),
        {
          label: 'Phase 2 database preparation',
          sensitiveValues,
          timeoutMs: deadlines.commandMs,
          stopTimeoutMs: deadlines.stopMs,
        },
      )
      resourceCounts.disposableMysql.created += 1

      await lifecycle.releaseReservation(gatewayReservation)
      const gateway = lifecycle.registerServer(startOwnedServer(
        process.execPath,
        [roots.fakeGatewayPath],
        childOptions(repositoryRoot, environments.gateway),
        {
          label: 'fake Provider gateway',
          sensitiveValues,
          serverLogObserverFactory: createServerLogObserver,
        },
      ))
      activeServers.push(gateway)
      await waitForOwnedServer(
        gateway,
        `http://127.0.0.1:${gatewayReservation.port}/health`,
        { expectedNonce: nonce, timeoutMs: deadlines.healthMs },
      )

      await lifecycle.releaseReservation(backendReservation)
      const backend = lifecycle.registerServer(startOwnedServer(
        python,
        ['-c', BACKEND_SOURCE, String(backendReservation.port)],
        childOptions(repositoryRoot, environments.backend),
        {
          label: 'backend',
          sensitiveValues,
          serverLogObserverFactory: createServerLogObserver,
        },
      ))
      activeServers.push(backend)
      await waitForOwnedServer(backend, `${backendUrl}/api/health`, {
        expectedNonce: nonce,
        timeoutMs: deadlines.healthMs,
      })

      await lifecycle.releaseReservation(viteReservation)
      const vite = lifecycle.registerServer(startOwnedServer(
        process.execPath,
        [
          viteCli,
          '--host',
          '127.0.0.1',
          '--port',
          String(viteReservation.port),
          '--strictPort',
        ],
        childOptions(frontendRoot, environments.vite),
        {
          label: 'vite',
          sensitiveValues,
          serverLogObserverFactory: createServerLogObserver,
        },
      ))
      activeServers.push(vite)
      await waitForOwnedServer(vite, `${viteUrl}/__m2-browser-owner`, {
        expectedNonce: nonce,
        timeoutMs: deadlines.healthMs,
      })

      try {
        await runBoundedOwnedCommand(
          process.execPath,
          [
            playwrightCli,
            'test',
            spec,
            '--config',
            'playwright.phase2.config.ts',
          ],
          childOptions(frontendRoot, environments.browser),
          {
            label: 'Phase 2 browser test',
            sensitiveValues,
            timeoutMs: deadlines.browserMs,
            stopTimeoutMs: deadlines.stopMs,
            states: activeServers,
          },
        )
      } catch (error) {
        const ledger = readFileSync(roots.stepLedgerPath, 'utf8')
        const ledgerSummary = summarizeBrowserStepLedger(ledger)
        let steps
        try {
          steps = verifyBrowserStepLedger(ledger)
        } catch (ledgerError) {
          const failure = new Error(
            'Phase 2 browser progress ledger is invalid',
            {
              cause: new AggregateError(
                [error, ledgerError],
                'Phase 2 browser process and step ledger failed',
              ),
            },
          )
          failure.phase2StepLedgerSummary = ledgerSummary
          throw failure
        }
        const lastStep = steps.at(-1) || 'no-browser-step'
        const stopped = new Error(
          `Phase 2 browser stopped after ${lastStep}`,
          { cause: error },
        )
        stopped.phase2AuditDiagnostic = readFileSync(
          roots.runtimeAuditDiagnosticPath,
          'utf8',
        )
        throw stopped
      }
      verifyBrowserStepLedger(
        readFileSync(roots.stepLedgerPath, 'utf8'),
        { requireComplete: true },
      )
      verifyForbiddenOutboundLedger(
        readFileSync(roots.outboundLedgerPath, 'utf8'),
      )
      verifyGatewayCounterLedger(
        readFileSync(roots.counterPath, 'utf8'),
      )
      await runBoundedOwnedCommand(
        python,
        ['-c', DATABASE_EVIDENCE_SOURCE],
        childOptions(repositoryRoot, environments.backend),
        {
          label: 'Phase 2 database evidence',
          sensitiveValues,
          timeoutMs: deadlines.commandMs,
          stopTimeoutMs: deadlines.stopMs,
          states: activeServers,
        },
      )
    },
    stopServer: server => runPhase2CleanupBoundary(
      'server',
      () => stopOwnedServer(server, {
        sensitiveValues,
        timeoutMs: deadlines.stopMs,
      }),
    ),
    releaseReservation: reservation => runPhase2CleanupBoundary(
      'reservation',
      async () => {
        await reservation.release()
        resourceCounts.ports.released += 1
      },
    ),
    dropDatabase: database => runPhase2CleanupBoundary(
      'database',
      async () => {
        await runBoundedOwnedCommand(
          environment.PYTHON || 'python',
          [
            '-m',
            'backend.scripts.prepare_phase2_browser_db',
            '--database',
            database,
            '--drop',
          ],
          childOptions(repositoryRoot, environments.prepare),
          {
            label: 'Phase 2 database cleanup',
            sensitiveValues,
            timeoutMs: deadlines.commandMs,
            stopTimeoutMs: deadlines.stopMs,
          },
        )
        resourceCounts.disposableMysql.cleaned += 1
      },
    ),
    removeRoot: root => runPhase2CleanupBoundary(
      'root',
      async () => {
        await removeOwnedRoot(root, OWNED_ROOT_PREFIX)
        resourceCounts.tempRoots.cleaned += 1
      },
    ),
  })
  return summarizePhase2ResourceCounts(resourceCounts)
}


export async function runPhase2({
  specs = FORMAL_SPECS,
  environment = process.env,
  databaseNameFactory = createDatabaseName,
  ownedRootFactory = () => createOwnedRoot(OWNED_ROOT_PREFIX),
  portReservationFactory = reserveLocalPort,
  runOneScenarioImpl = runOneScenario,
  deadlines = {},
} = {}) {
  validateTestEnvironment(environment)
  const formalSpecs = validateSpecs(specs)
  const normalizedDeadlines = { ...DEFAULT_DEADLINES, ...deadlines }
  if (
    Object.values(normalizedDeadlines).some(value => (
      !Number.isFinite(value) || value <= 0
    ))
  ) {
    throw new TypeError('Phase 2 deadlines must be positive finite numbers')
  }
  const scenarioSummaries = []
  for (const spec of formalSpecs) {
    scenarioSummaries.push(await runOneScenarioImpl({
      spec,
      environment,
      databaseNameFactory,
      ownedRootFactory,
      portReservationFactory,
      deadlines: normalizedDeadlines,
    }))
  }
  return aggregatePhase2ResourceSummaries(scenarioSummaries)
}


export function isCommandLineEntrypoint(argumentPath, modulePath) {
  if (!argumentPath || !modulePath) return false
  try {
    const argumentIdentity = realpathSync(argumentPath)
    const moduleFile = modulePath.startsWith('file:')
      ? fileURLToPath(modulePath)
      : modulePath
    const moduleIdentity = realpathSync(moduleFile)
    return process.platform === 'win32'
      ? argumentIdentity.toLowerCase() === moduleIdentity.toLowerCase()
      : argumentIdentity === moduleIdentity
  } catch {
    return false
  }
}


if (isCommandLineEntrypoint(process.argv[1], import.meta.url)) {
  runPhase2({ specs: resolveCommandLineSpecs(process.argv.slice(2)) })
    .then(summary => {
      process.stdout.write(formatPhase2ResourceSummary(summary))
    })
    .catch(error => {
      process.stderr.write(renderPhase2CliFailure(error))
      process.exitCode = 1
      return error
    })
}
