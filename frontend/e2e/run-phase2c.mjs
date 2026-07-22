import { randomUUID } from 'node:crypto'
import {
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  assertDatabaseName,
  BASE_ENV_ALLOWLIST,
  createDatabaseName,
  reserveLocalPort,
  runBoundedOwnedCommand,
  runOwnedProductLifecycle,
  startOwnedServer,
  stopOwnedServer,
  validateTestEnvironment,
  waitForOwnedServer,
} from './support/product-runner.mjs'
import { runtimeSensitiveValues } from './runtime-observer.mjs'


export const FORMAL_SPECS = Object.freeze([
  'e2e/phase2c-contract.spec.ts',
])
export const FORMAL_SCENARIOS = Object.freeze([
  Object.freeze({ tag: '@manual', mode: 'manual' }),
  Object.freeze({ tag: '@gateway', mode: 'gateway' }),
])

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const OWNED_ROOT_PREFIX = 'novel-creator-phase2c-'
const SECRET_SENTINEL = 'phase2c-browser-secret-must-not-leak'
const PRIVATE_PROVIDER_URL = 'https://phase2c-private-provider.invalid/v1'
const MODEL_SENTINEL = 'phase2c-private-model-must-not-leak'
const TRANSCRIPT_SENTINEL = 'phase2c-private-transcript-must-not-leak'
const DEFAULT_DEADLINES = Object.freeze({
  commandMs: 90_000,
  healthMs: 45_000,
  browserMs: 180_000,
  stopMs: 8_000,
})

const FIXTURE_SOURCE = String.raw`
import asyncio
import json
import os
import time

from backend.database import close_pool, connection, transaction
from backend.domain.json_contracts import canonical_hash
from backend.domain.market_sources import SourcePolicy
from backend.domain.model_bindings import BindingItem, BindingRevision, TASK_KEYS

PROJECT_ID = os.environ["BROWSER_PROJECT_ID"]
PROVIDER_ID = "2b000000-0000-4000-8000-000000000002"
BINDING_ID = "2b000000-0000-4000-8000-000000000003"
POLICY_ID = "2b000000-0000-4000-8000-000000000004"

async def main():
    now = int(time.time() * 1000)
    async with transaction() as session:
        await session.execute(
            """INSERT INTO projects
               (id,title,genre,description,target_words,target_chapters,status,
                current_chapter,archived_at,lifecycle_revision,created_at,updated_at)
               VALUES (%s,'Phase 2C \u5e02\u573a\u4e0e\u79cd\u5b50\u9879\u76ee',
                       '\u5386\u53f2\u7a7f\u8d8a',
                       '\u6d4f\u89c8\u5668\u9a8c\u6536\u5939\u5177',
                       1800000,600,'drafting',0,NULL,0,%s,%s)""",
            (PROJECT_ID, now, now),
        )
        await session.execute(
            """INSERT INTO provider_profiles
               (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
                stream,max_context_tokens,max_output_tokens,temperature,top_p,
                supports_json,supports_streaming,notes,thinking,lifecycle_status,
                revision,deleted_at,created_at,updated_at)
               VALUES (%s,'Phase 2C Hidden Provider','openai-compatible',%s,%s,%s,
                       1,0,0,128000,4096,0.700,0.950,1,1,'',NULL,'active',
                       1,NULL,%s,%s)""",
            (
                PROVIDER_ID,
                os.environ["BROWSER_MODEL_SENTINEL"],
                os.environ["BROWSER_PROVIDER_BASE_URL"],
                os.environ["BROWSER_SECRET_SENTINEL"],
                now,
                now,
            ),
        )
        await session.execute(
            """INSERT INTO project_contract_heads
               (project_id,revision,creation_contract_id,style_contract_id,
                creation_hash,style_hash,updated_at)
               VALUES (%s,0,NULL,NULL,NULL,NULL,%s)""",
            (PROJECT_ID, now),
        )
        binding_items = tuple(
            BindingItem(
                task_key=task_key,
                resolution_status="bound",
                provider_id=PROVIDER_ID,
                provider_name_snapshot="Phase 2C Hidden Provider",
                model_name_snapshot=os.environ["BROWSER_MODEL_SENTINEL"],
            )
            for task_key in TASK_KEYS
        )
        binding_hash = canonical_hash(BindingRevision(
            project_id=PROJECT_ID,
            revision=1,
            items=binding_items,
        ))
        await session.execute(
            """INSERT INTO project_model_binding_revisions
               (id,project_id,revision,content_hash,source_project_id,created_at)
               VALUES (%s,%s,1,%s,NULL,%s)""",
            (BINDING_ID, PROJECT_ID, binding_hash, now),
        )
        for item in binding_items:
            await session.execute(
                """INSERT INTO project_model_binding_items
                   (binding_revision_id,task_key,resolution_status,provider_id,
                    provider_name_snapshot,model_name_snapshot,item_hash)
                   VALUES (%s,%s,'bound',%s,'Phase 2C Hidden Provider',%s,%s)""",
                (
                    BINDING_ID,
                    item.task_key,
                    PROVIDER_ID,
                    os.environ["BROWSER_MODEL_SENTINEL"],
                    canonical_hash(item),
                ),
            )
        await session.execute(
            """INSERT INTO project_model_binding_heads
               (project_id,revision,binding_revision_id,content_hash,updated_at)
               VALUES (%s,1,%s,%s,%s)""",
            (PROJECT_ID, BINDING_ID, binding_hash, now),
        )
        qidian = await session.fetchone(
            "SELECT id FROM market_sources WHERE stable_key='qidian.newsign'"
        )
        if qidian is None:
            raise RuntimeError("versioned qidian source was not seeded")
        policy = SourcePolicy(
            status="verified_public",
            checkedAt=now,
            evidenceURL="https://www.qidian.com/rank/newsign/",
            evidenceHash="a" * 64,
            allowedOrigins=("https://www.qidian.com",),
            pathPrefixes=("/rank/newsign/",),
            requestIntervalSeconds=60,
            policyVersion="phase2c-browser-verified-v1",
            enabled=False,
        )
        policy_hash = canonical_hash(policy)
        await session.execute(
            """INSERT INTO market_source_policy_revisions
               (id,source_id,revision,policy_status,policy_version,checked_at,
                evidence_url,evidence_hash,allowed_origins_json,path_prefixes_json,
                enabled,interval_minutes,next_run_at,content_hash,created_at)
               VALUES (%s,%s,2,'verified_public',%s,%s,%s,%s,%s,%s,
                       0,1,NULL,%s,%s)""",
            (
                POLICY_ID,
                qidian["id"],
                policy.policy_version,
                policy.checked_at,
                policy.evidence_url,
                policy.evidence_hash,
                json.dumps(list(policy.allowed_origins)),
                json.dumps(list(policy.path_prefixes)),
                policy_hash,
                now,
            ),
        )
        await session.execute(
            """UPDATE market_source_policy_heads
                  SET revision_id=%s,revision=2,content_hash=%s,updated_at=%s
                WHERE source_id=%s""",
            (POLICY_ID, policy_hash, now, qidian["id"]),
        )

async def program():
    try:
        await main()
    finally:
        await close_pool()

asyncio.run(program())
`

const BACKEND_SOURCE = String.raw`
import os
import sys

import httpx
import uvicorn
from urllib.parse import urlsplit

SCENARIO_MODE = os.environ["BROWSER_SCENARIO_MODE"]
PROVIDER_BASE_URL = os.environ["BROWSER_PROVIDER_BASE_URL"]
OUTBOUND_LEDGER_PATH = os.environ["BROWSER_OUTBOUND_LEDGER_PATH"]

def gateway_target():
    if SCENARIO_MODE == "manual":
        return None
    if SCENARIO_MODE != "gateway":
        raise RuntimeError("invalid browser scenario mode")
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

ALLOWED_GATEWAY_TARGET = gateway_target()

def record_forbidden_outbound():
    descriptor = os.open(OUTBOUND_LEDGER_PATH, os.O_WRONLY | os.O_APPEND)
    try:
        os.write(descriptor, b"forbidden-outbound\\n")
    finally:
        os.close(descriptor)

def outbound_allowed(url):
    if ALLOWED_GATEWAY_TARGET is None:
        return False
    try:
        parsed = urlsplit(str(url))
        target = (parsed.scheme, parsed.hostname, parsed.port, parsed.path)
    except (TypeError, ValueError):
        return False
    return (
        target == ALLOWED_GATEWAY_TARGET
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

uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_config=None, access_log=False)
`

const FAKE_GATEWAY_SOURCE = String.raw`
import { appendFileSync } from 'node:fs'
import http from 'node:http'

const port = Number(process.env.BROWSER_FAKE_GATEWAY_PORT)
const nonce = process.env.M2_BROWSER_RUN_NONCE
const counterPath = process.env.BROWSER_FAKE_COUNTER_PATH
const apiKey = process.env.BROWSER_SECRET_SENTINEL
if (!Number.isInteger(port) || port <= 0 || !nonce || !counterPath || !apiKey) {
  throw new Error('fake gateway ownership configuration is invalid')
}

const STORY_ENGINE_OPTIONS = [
  {
    name: 'Tide Clock Pursuit',
    storyPromise: 'Decode each false bell before the next harbor disaster.',
    protagonistDesire: 'Find the missing mentor and clear the clock room.',
    sustainedPressure: 'Every proof lets the council seal more records.',
    growthDirection: 'A cautious apprentice learns to share dangerous evidence.',
    conflictLoop: 'Measure, expose, rescue, and pay a new public cost.',
    ensembleRoles: [{ role: 'Harbor pilot', purpose: 'Challenges evidence with lived risk.' }],
    advantageAndCost: 'Precision reveals sabotage but makes allies traceable.',
    satisfactionSources: ['Evidence reversals', 'Collective rescues'],
    longFormVariation: ['New clock mechanisms', 'Changing political coalitions'],
    endingAnchor: 'The harbor chooses an accountable public time standard.',
    risks: ['Puzzles could crowd out character choices.'],
    differentiation: 'Clock error produces ethical deadlines rather than magic answers.',
  },
  {
    name: 'Ledger of Borrowed Storms',
    storyPromise: 'Trade forecasts across rival guilds while every bargain changes the storm.',
    protagonistDesire: 'Recover the mentor through the guild debt network.',
    sustainedPressure: 'Each alliance transfers danger to another district.',
    growthDirection: 'A solitary observer becomes a coalition negotiator.',
    conflictLoop: 'Forecast, bargain, redirect, and inherit the displaced cost.',
    ensembleRoles: [{ role: 'Guild courier', purpose: 'Makes every bargain visible to its victims.' }],
    advantageAndCost: 'Forecast knowledge wins time but creates moral debt.',
    satisfactionSources: ['Strategic bargains', 'Consequences returning later'],
    longFormVariation: ['District rivalries', 'Storm patterns and debt chains'],
    endingAnchor: 'The districts replace secret forecasts with shared responsibility.',
    risks: ['Negotiation could become repetitive.'],
    differentiation: 'Information advantage moves danger instead of erasing it.',
  },
  {
    name: 'The Third Bell Witnesses',
    storyPromise: 'Build a witness network whose conflicting memories expose engineered history.',
    protagonistDesire: 'Prove the mentor left a distributed warning.',
    sustainedPressure: 'Protecting one witness discredits another in public.',
    growthDirection: 'A fact-driven apprentice learns to preserve human testimony.',
    conflictLoop: 'Locate, compare, protect, and reconcile costly testimony.',
    ensembleRoles: [{ role: 'Dock archivist', purpose: 'Preserves contradictions that institutions erase.' }],
    advantageAndCost: 'Cross-checking exposes lies but endangers every witness.',
    satisfactionSources: ['Witness convergence', 'Institutional reversals'],
    longFormVariation: ['New witness communities', 'Competing versions of the past'],
    endingAnchor: 'The city accepts a public archive that retains disagreement.',
    risks: ['Testimony scenes need strong physical action.'],
    differentiation: 'Historical truth remains plural while decisions stay concrete.',
  },
]

function sendJson(response, status, value) {
  response.writeHead(status, {
    'content-type': 'application/json',
    'connection': 'close',
  })
  response.end(JSON.stringify(value))
}

function classify(messages) {
  if (!Array.isArray(messages) || messages.length !== 2) return null
  const [system, user] = messages
  if (
    system?.role === 'system'
    && system.content === '故事具体、人物有欲望和代价、冲突能够长期变化。'
    && user?.role === 'user'
  ) return 'story-engine'
  if (system?.role !== 'system' || user?.role !== 'user') return null
  let instruction
  try {
    instruction = JSON.parse(system.content)
    JSON.parse(user.content)
  } catch {
    return null
  }
  if (
    instruction?.task
      === 'Write one original style-trial scene for the supplied scenario.'
  ) return 'style-trial'
  if (
    instruction?.task
      === 'Rank only the supplied eligible asset and corpus candidates.'
  ) return 'asset-ranking'
  return null
}

function responseFor(kind, messages) {
  if (kind === 'story-engine') return { options: STORY_ENGINE_OPTIONS }
  if (kind === 'style-trial') {
    return {
      sample: '第三声钟鸣压过雾里的潮声。沈砚没有解释刻度，只把沾盐的纸带递给守门人。门外船灯一盏盏熄灭，他听见同伴问：若证据是真的，先救谁？他推开钟室侧窗，把自己的姓名写进公开值守簿，然后指向仍在倒转的秒针。'.repeat(4),
    }
  }
  const evidence = JSON.parse(messages[1].content)
  const candidate = evidence.assetCandidates?.[0]
  if (!candidate?.assetRevisionId) return null
  return {
    assetRecommendations: [{
      assetRevisionId: candidate.assetRevisionId,
      reason: 'The evidence is intentionally too weak for an automatic suggestion.',
      confidence: 0.2,
    }],
    corpusRecommendations: [],
  }
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

const server = http.createServer(async (request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    sendJson(response, 200, { browserRunNonce: nonce })
    return
  }
  if (request.method === 'POST' && request.url === '/v1/chat/completions') {
    if (request.headers.authorization !== 'Bearer ' + apiKey) {
      sendJson(response, 404, { error: { code: 'not_found' } })
      return
    }
    let body
    try {
      body = await readJson(request)
    } catch {
      sendJson(response, 400, { error: { code: 'invalid_request' } })
      return
    }
    const kind = classify(body.messages)
    const content = kind ? responseFor(kind, body.messages) : null
    if (!kind || !content) {
      sendJson(response, 422, { error: { code: 'unsupported_fixture_request' } })
      return
    }
    appendFileSync(counterPath, kind + '\n', { encoding: 'utf8' })
    sendJson(response, 200, {
      choices: [{ message: { role: 'assistant', content: JSON.stringify(content) } }],
    })
    return
  }
  sendJson(response, 404, { error: { code: 'not_found' } })
})
server.listen(port, '127.0.0.1')
`


const VERIFICATION_SOURCE = String.raw`
import asyncio
import os
from backend.database import close_pool, connection

async def main():
    expected = os.environ["BROWSER_TEST_DATABASE"]
    async with connection() as session:
        current = await session.fetchone("SELECT DATABASE() AS database_name")
        assert current == {"database_name": expected}
    print("database_identity=verified")

async def program():
    try:
        await main()
    finally:
        await close_pool()

asyncio.run(program())
`

const MANUAL_CONFIGURATION_SOURCE = String.raw`
import asyncio
import os
from backend.database import close_pool, connection, transaction

async def main():
    expected = os.environ["BROWSER_TEST_DATABASE"]
    async with transaction() as session:
        current = await session.fetchone("SELECT DATABASE() AS database_name")
        assert current == {"database_name": expected}
        await session.execute("UPDATE provider_profiles SET enabled=0")
    async with connection() as session:
        ready = await session.fetchone(
            "SELECT COUNT(*) AS ready_providers FROM provider_profiles WHERE enabled=1"
        )
        assert ready == {"ready_providers": 0}
    print("database_identity=verified")
    print("ready_providers=0")

async def program():
    try:
        await main()
    finally:
        await close_pool()

asyncio.run(program())
`

export function validateSpecs(specs) {
  if (
    !Array.isArray(specs)
    || specs.length !== FORMAL_SPECS.length
    || specs.some((spec, index) => spec !== FORMAL_SPECS[index])
  ) {
    throw new Error('Phase 2C browser requires the exact formal spec path')
  }
  return [...FORMAL_SPECS]
}


export function resolveFormalScenarios(grep) {
  if (grep == null || grep === '') return [...FORMAL_SCENARIOS]
  if (grep !== '@manual' && grep !== '@gateway') {
    throw new Error('Phase 2C grep must be exactly @manual or @gateway')
  }
  return FORMAL_SCENARIOS.filter(scenario => scenario.tag === grep)
}


export function resolveCommandLineSpecs(argumentsList) {
  if (!Array.isArray(argumentsList)) {
    throw new TypeError('Phase 2C browser CLI arguments must be an array')
  }
  if (argumentsList.length !== 0) {
    throw new Error('Phase 2C browser runner does not accept spec paths')
  }
  return [...FORMAL_SPECS]
}


function allowlistedBaseEnvironment(environment) {
  return Object.fromEntries(
    BASE_ENV_ALLOWLIST
      .filter(name => Object.hasOwn(environment, name))
      .map(name => [name, environment[name]]),
  )
}


function normalizedPathIdentity(value) {
  const resolved = path.resolve(value)
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}


function assertOwnedRoot(ownedRoot) {
  const root = path.resolve(ownedRoot)
  const stats = lstatSync(root)
  if (!stats.isDirectory() || stats.isSymbolicLink()) {
    throw new Error('Phase 2C owned root is not a real directory')
  }
  if (
    !path.basename(root).startsWith(OWNED_ROOT_PREFIX)
    || normalizedPathIdentity(path.dirname(realpathSync(root)))
      !== normalizedPathIdentity(realpathSync(os.tmpdir()))
  ) {
    throw new Error('Phase 2C owned root is outside its temporary namespace')
  }
  return root
}


export function createOwnedRoot() {
  const ownedRoot = mkdtempSync(path.join(os.tmpdir(), OWNED_ROOT_PREFIX))
  assertOwnedRoot(ownedRoot)
  return ownedRoot
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


function prepareOwnedFiles(ownedRoot) {
  const root = assertOwnedRoot(ownedRoot)
  const filesRoot = path.join(root, 'files')
  mkdirSync(filesRoot)
  const corpusRoot = path.join(root, 'corpus-incoming')
  const managedRoot = path.join(root, 'corpus-managed')
  mkdirSync(corpusRoot)
  mkdirSync(managedRoot)
  const capturedAt = Date.now()
  const qidianPath = path.join(filesRoot, 'qidian-public-snapshot.json')
  const qqPath = path.join(filesRoot, 'qq-public-snapshot.json')
  const counterPath = path.join(filesRoot, 'gateway-counters.json')
  const outboundLedgerPath = path.join(filesRoot, 'forbidden-outbound.log')
  const fakeGatewayPath = path.join(filesRoot, 'owned-fake-gateway.mjs')
  const corpusPath = path.join(corpusRoot, 'phase2c-synthetic-corpus.txt')
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
  writeFileSync(counterPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(outboundLedgerPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(fakeGatewayPath, FAKE_GATEWAY_SOURCE, {
    encoding: 'utf8',
    flag: 'wx',
  })
  if (
    normalizedPathIdentity(path.dirname(realpathSync(fakeGatewayPath)))
      !== normalizedPathIdentity(realpathSync(filesRoot))
  ) throw new Error('Phase 2C fake gateway source escaped its owned root')
  writeFileSync(corpusPath, [
    '第一章 雾港错钟',
    '沈砚守着潮墙上的旧钟。第三声钟鸣提前到来，港口却在无风的夜里退潮。',
    '',
    '第二章 纸带回声',
    '他从导师留下的纸带中辨出一组反向刻度，决定先救被困船队，再追查谁篡改了钟室记录。',
  ].join('\n'), { encoding: 'utf8', flag: 'wx' })
  return {
    root, filesRoot, qidianPath, qqPath, counterPath, outboundLedgerPath,
    fakeGatewayPath,
    corpusPath, corpusRoot, managedRoot,
  }
}


function childOptions(cwd, env) {
  return { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] }
}


export function buildEnvironments(
  environment,
  databaseName,
  backendUrl,
  viteUrl,
  gatewayUrl,
  nonce,
  roots,
  projectId,
  scenario,
) {
  const base = allowlistedBaseEnvironment(environment)
  const prepare = {
    ...base,
    TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST,
    TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: environment.TEST_MYSQL_USER,
    TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
  }
  const backend = {
    ...base,
    MYSQL_HOST: environment.TEST_MYSQL_HOST,
    MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER,
    MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: databaseName,
    BROWSER_TEST_DATABASE: databaseName,
    BROWSER_PROJECT_ID: projectId,
    M2_BROWSER_RUN_NONCE: nonce,
    MARKET_SCHEDULER_ENABLED: 'false',
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_PRIVATE_PROVIDER_URL: PRIVATE_PROVIDER_URL,
    BROWSER_SCENARIO_MODE: scenario.mode,
    BROWSER_PROVIDER_BASE_URL: scenario.mode === 'gateway'
      ? gatewayUrl
      : PRIVATE_PROVIDER_URL,
    BROWSER_OUTBOUND_LEDGER_PATH: roots.outboundLedgerPath,
    BROWSER_MODEL_SENTINEL: MODEL_SENTINEL,
    BROWSER_TRANSCRIPT_SENTINEL: TRANSCRIPT_SENTINEL,
    BROWSER_FAKE_COUNTER_PATH: roots.counterPath,
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
    BROWSER_SCENARIO_MODE: scenario.mode,
    PLAYWRIGHT_BASE_URL: viteUrl,
    BROWSER_VITE_ORIGIN: viteUrl,
    BROWSER_BACKEND_ORIGIN: backendUrl,
    BROWSER_OWNED_ROOT: roots.root,
    BROWSER_ARTIFACT_ROOT: path.join(roots.root, 'phase2c-test-results'),
    BROWSER_QIDIAN_SNAPSHOT_PATH: roots.qidianPath,
    BROWSER_QQ_SNAPSHOT_PATH: roots.qqPath,
    BROWSER_CORPUS_FILE: roots.corpusPath,
    BROWSER_PROJECT_ID: projectId,
    BROWSER_TEST_DATABASE: databaseName,
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_PRIVATE_PROVIDER_URL: PRIVATE_PROVIDER_URL,
    BROWSER_MODEL_SENTINEL: MODEL_SENTINEL,
    BROWSER_TRANSCRIPT_SENTINEL: TRANSCRIPT_SENTINEL,
    BROWSER_CORPUS_ROOT_SENTINEL: roots.root,
    BROWSER_ACTUAL_CORPUS_ROOT_SENTINEL: roots.filesRoot,
  }
  const sensitiveController = {
    MYSQL_HOST: environment.TEST_MYSQL_HOST,
    MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER,
    MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: databaseName,
    BROWSER_TEST_DATABASE: databaseName,
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_PRIVATE_PROVIDER_URL: PRIVATE_PROVIDER_URL,
    BROWSER_MODEL_SENTINEL: MODEL_SENTINEL,
    BROWSER_TRANSCRIPT_SENTINEL: TRANSCRIPT_SENTINEL,
    BROWSER_CORPUS_ROOT_SENTINEL: roots.root,
    BROWSER_ACTUAL_CORPUS_ROOT_SENTINEL: roots.filesRoot,
  }
  const gateway = scenario.mode === 'gateway' ? {
    ...base,
    M2_BROWSER_RUN_NONCE: nonce,
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_FAKE_GATEWAY_PORT: String(new URL(gatewayUrl).port),
    BROWSER_FAKE_COUNTER_PATH: roots.counterPath,
  } : null
  return { prepare, backend, vite, browser, gateway, sensitiveController }
}


export function redactRuntimeDiagnostic(diagnostic, sensitiveValues) {
  let rendered = String(diagnostic || '')
  const ordered = [...new Set(
    (sensitiveValues || []).filter(value => (
      typeof value === 'string' && value.length > 0
    )),
  )].sort((left, right) => right.length - left.length)
  for (const sensitive of ordered) {
    rendered = rendered.replaceAll(sensitive, '[REDACTED]')
  }
  return rendered
}


export function verifyGatewayCounterLedger(ledger) {
  const expected = Object.freeze({
    'story-engine': 1,
    'style-trial': 1,
    'asset-ranking': 2,
  })
  const allowed = Object.keys(expected)
  const counts = Object.fromEntries(allowed.map(kind => [kind, 0]))
  const lines = String(ledger || '').split(/\r?\n/u).filter(Boolean)
  for (const line of lines) {
    if (!Object.hasOwn(counts, line)) {
      throw new Error('Phase 2C gateway call ledger contains an unknown type')
    }
    counts[line] += 1
  }
  if (allowed.some(kind => counts[kind] !== expected[kind])) {
    const summary = allowed.map(kind => `${kind}=${String(counts[kind])}`).join(',')
    throw new Error(
      `Phase 2C gateway call ledger has unexpected formal counts (${summary})`,
    )
  }
  return counts
}


export function verifyForbiddenOutboundLedger(ledger) {
  const kind = 'forbidden-outbound'
  const lines = String(ledger || '').split(/\r?\n/u).filter(Boolean)
  if (lines.some(line => line !== kind) || lines.length !== 0) {
    throw new Error('Phase 2C forbidden outbound ledger is not empty')
  }
  return { [kind]: 0 }
}


async function runOneScenario({
  spec,
  scenario,
  environment,
  databaseNameFactory,
  ownedRootFactory,
  projectIdFactory,
  portReservationFactory,
  deadlines,
}) {
  let databaseName
  let projectId
  let environments
  let sensitiveValues = []
  return runOwnedProductLifecycle({
    async body(lifecycle) {
      databaseName = databaseNameFactory()
      assertDatabaseName(databaseName)
      projectId = projectIdFactory()
      if (typeof projectId !== 'string' || projectId.length === 0) {
        throw new Error('Phase 2C project identity is invalid')
      }
      const ownedRoot = lifecycle.setRoot(ownedRootFactory())
      const roots = prepareOwnedFiles(ownedRoot)
      const backendReservation = lifecycle.registerReservation(
        await portReservationFactory(),
      )
      const viteReservation = lifecycle.registerReservation(
        await portReservationFactory(),
      )
      const gatewayReservation = scenario.mode === 'gateway'
        ? lifecycle.registerReservation(await portReservationFactory())
        : null
      const reservations = [backendReservation, viteReservation, gatewayReservation]
        .filter(Boolean)
      if (
        reservations.some(reservation => (
          !Number.isInteger(reservation?.port)
          || typeof reservation.release !== 'function'
        ))
        || new Set(reservations.map(reservation => reservation.port)).size
          !== reservations.length
      ) throw new Error('Phase 2C runner received invalid port reservations')

      const nonce = randomUUID()
      const backendUrl = `http://127.0.0.1:${backendReservation.port}`
      const viteUrl = `http://127.0.0.1:${viteReservation.port}`
      const gatewayUrl = gatewayReservation
        ? `http://127.0.0.1:${gatewayReservation.port}/v1`
        : null
      environments = buildEnvironments(
        environment,
        databaseName,
        backendUrl,
        viteUrl,
        gatewayUrl,
        nonce,
        roots,
        projectId,
        scenario,
      )
      sensitiveValues = runtimeSensitiveValues(environments.sensitiveController)
      const python = environment.PYTHON || 'python'
      const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')
      const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js')
      const activeServers = []

      lifecycle.setDatabase(databaseName)
      await runBoundedOwnedCommand(
        python,
        ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', databaseName],
        childOptions(repositoryRoot, environments.prepare),
        {
          label: 'database preparation', sensitiveValues,
          timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs,
        },
      )
      await runBoundedOwnedCommand(
        python,
        [
          '-m', 'backend.scripts.seed_market_sources', '--execute',
          '--database', databaseName, '--confirm-seed', databaseName,
        ],
        childOptions(repositoryRoot, environments.backend),
        {
          label: 'versioned market source seed', sensitiveValues,
          timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs,
        },
      )
      await runBoundedOwnedCommand(
        python,
        ['-c', FIXTURE_SOURCE],
        childOptions(repositoryRoot, environments.backend),
        {
          label: 'Phase 2C fixture preparation', sensitiveValues,
          timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs,
        },
      )
      await runBoundedOwnedCommand(
        python,
        [
          '-m', 'backend.scripts.seed_writer_assets', '--execute',
          '--database', databaseName, '--confirm-seed', databaseName,
        ],
        childOptions(repositoryRoot, environments.backend),
        {
          label: 'writer asset seed', sensitiveValues,
          timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs,
        },
      )
      if (scenario.mode === 'manual') {
        await runBoundedOwnedCommand(
          python,
          ['-c', MANUAL_CONFIGURATION_SOURCE],
          childOptions(repositoryRoot, environments.backend),
          {
            label: 'manual no-model configuration', sensitiveValues,
            timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs,
          },
        )
      }

      if (scenario.mode === 'gateway') {
        await lifecycle.releaseReservation(gatewayReservation)
        const fakeGateway = lifecycle.registerServer(startOwnedServer(
          process.execPath,
          [roots.fakeGatewayPath],
          childOptions(repositoryRoot, environments.gateway),
          { label: 'fake gateway', sensitiveValues },
        ))
        activeServers.push(fakeGateway)
        await waitForOwnedServer(
          fakeGateway,
          `http://127.0.0.1:${gatewayReservation.port}/health`,
          { expectedNonce: nonce, timeoutMs: deadlines.healthMs },
        )
      }

      await lifecycle.releaseReservation(backendReservation)
      const backend = lifecycle.registerServer(startOwnedServer(
        python,
        ['-c', BACKEND_SOURCE, String(backendReservation.port)],
        childOptions(repositoryRoot, environments.backend),
        { label: 'backend', sensitiveValues },
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
          viteCli, '--host', '127.0.0.1', '--port',
          String(viteReservation.port), '--strictPort',
        ],
        childOptions(frontendRoot, environments.vite),
        { label: 'vite', sensitiveValues },
      ))
      activeServers.push(vite)
      await waitForOwnedServer(vite, `${viteUrl}/__m2-browser-owner`, {
        expectedNonce: nonce,
        timeoutMs: deadlines.healthMs,
      })

      await runBoundedOwnedCommand(
        process.execPath,
        [
          playwrightCli, 'test', spec, '--config',
          'playwright.phase2c.config.ts',
          '--grep', scenario.tag,
        ],
        childOptions(frontendRoot, environments.browser),
        {
          label: 'Phase 2C browser test', sensitiveValues,
          timeoutMs: deadlines.browserMs, stopTimeoutMs: deadlines.stopMs,
          states: activeServers,
        },
      )
      verifyForbiddenOutboundLedger(
        readFileSync(roots.outboundLedgerPath, 'utf8'),
      )
      if (scenario.mode === 'gateway') {
        verifyGatewayCounterLedger(readFileSync(roots.counterPath, 'utf8'))
      }
      await runBoundedOwnedCommand(
        python,
        ['-c', VERIFICATION_SOURCE],
        childOptions(repositoryRoot, environments.backend),
        {
          label: 'Phase 2C database evidence', sensitiveValues,
          timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs,
          states: activeServers,
        },
      )
    },
    stopServer: server => stopOwnedServer(server, {
      sensitiveValues,
      timeoutMs: deadlines.stopMs,
    }),
    releaseReservation: reservation => reservation.release(),
    dropDatabase: database => runBoundedOwnedCommand(
      environment.PYTHON || 'python',
      [
        '-m', 'backend.scripts.prepare_product_shell_browser_db',
        '--database', database, '--drop',
      ],
      childOptions(repositoryRoot, environments.prepare),
      {
        label: 'database cleanup', sensitiveValues,
        timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs,
      },
    ),
    async removeRoot(root) {
      assertOwnedRoot(root)
      rmSync(root, { recursive: true })
    },
  })
}


export async function runPhase2C({
  specs = FORMAL_SPECS,
  environment = process.env,
  databaseNameFactory = createDatabaseName,
  ownedRootFactory = createOwnedRoot,
  projectIdFactory = randomUUID,
  portReservationFactory = reserveLocalPort,
  runOneScenarioImpl = runOneScenario,
  deadlines = {},
} = {}) {
  validateTestEnvironment(environment)
  const formalSpecs = validateSpecs(specs)
  const formalScenarios = resolveFormalScenarios(environment.PHASE2C_GREP)
  const normalizedDeadlines = { ...DEFAULT_DEADLINES, ...deadlines }
  for (const value of Object.values(normalizedDeadlines)) {
    if (!Number.isFinite(value) || value <= 0) {
      throw new TypeError('Phase 2C deadlines must be positive finite numbers')
    }
  }
  for (const spec of formalSpecs) {
    for (const scenario of formalScenarios) {
      await runOneScenarioImpl({
        spec,
        scenario,
        environment,
        databaseNameFactory,
        ownedRootFactory,
        projectIdFactory,
        portReservationFactory,
        deadlines: normalizedDeadlines,
      })
    }
  }
  return 0
}


export function isCommandLineEntrypoint(argumentPath, modulePath) {
  if (!argumentPath || !modulePath) return false
  try {
    return normalizedPathIdentity(realpathSync(argumentPath))
      === normalizedPathIdentity(realpathSync(modulePath))
  } catch {
    return false
  }
}


const isMain = isCommandLineEntrypoint(
  process.argv[1],
  fileURLToPath(import.meta.url),
)

if (isMain) {
  let specs
  try {
    specs = resolveCommandLineSpecs(process.argv.slice(2))
  } catch {
    console.error('Phase 2C browser runner does not accept spec paths.')
    process.exitCode = 2
  }
  if (specs) {
    runPhase2C({ specs }).then(
      status => { process.exitCode = status },
      () => {
        console.error('Phase 2C browser runner failed.')
        process.exitCode = 1
      },
    )
  }
}
