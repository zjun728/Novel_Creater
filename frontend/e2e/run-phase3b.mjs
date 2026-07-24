import { randomUUID } from 'node:crypto'
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  writeFileSync,
} from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import {
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


export const FORMAL_SPECS = Object.freeze([
  'phase3b-volumes-plots.spec.ts',
])
export const FORMAL_CONFIG = 'playwright.phase3b.config.ts'
export const FORMAL_SCENARIOS = Object.freeze([
  Object.freeze({ tag: '@manual', mode: 'manual' }),
  Object.freeze({ tag: '@gateway', mode: 'gateway' }),
])

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const OWNED_ROOT_PREFIX = 'novel-creator-phase3b-'
const PROJECT_ID = '81000000-0000-0000-0000-000000000001'
const SECRET_SENTINEL = 'phase3b-browser-secret-must-not-leak'
const FORBIDDEN_EVIDENCE_MARKERS = Object.freeze([
  'prompt',
  'raw provider',
  'input manifest',
  'corpus text',
  'apiKey',
  'Authorization',
  'password',
  'DSN',
])
const DEFAULT_DEADLINES = Object.freeze({
  commandMs: 90_000,
  healthMs: 45_000,
  browserMs: 180_000,
  stopMs: 8_000,
})
const phase3BFailureContexts = new WeakMap()

const FIXTURE_SOURCE = String.raw`
import asyncio
import os
from contextlib import asynccontextmanager

from backend.database import close_pool, connection, transaction
from backend.domain.json_contracts import canonical_hash
from backend.repositories.contracts import ContractRepository
from backend.repositories.planning import PlanningRepository
from backend.services.bibles import BIBLE_POLICY_VERSION
from backend.services.contracts import ConfirmContracts, ContractService, SaveContractDraft
from backend.services.planning import CreatePlanningDraft, PlanningService, SavePlanningDraft
from backend.services.projections import build_projection_bundle
from backend.tests.integration.test_contract_drafts import PROJECT, _bootstrap, _draft
from backend.tests.integration.test_planning_aggregate_lifecycle import _payload
from backend.tests.integration.test_project_archive import _insert_confirmed_bible

NOW = 2_020_000_000_000

async def main():
    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        assert selected == {"database_name": os.environ["MYSQL_DB"]}
        facts = await _bootstrap(session)

    @asynccontextmanager
    async def read_connection():
        async with connection() as session:
            yield session

    identifiers = iter(
        f"93000000-0000-0000-0000-{number:012d}"
        for number in range(1, 1000)
    )
    contracts = ContractService(
        ContractRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
        id_factory=identifiers.__next__,
        clock=lambda: NOW,
    )
    saved_contract = await contracts.save_draft(
        SaveContractDraft(PROJECT, 0, _draft(facts))
    )
    confirmed = await contracts.confirm(
        ConfirmContracts(
            PROJECT,
            "phase3b-contract-confirm",
            saved_contract.draft_version,
            saved_contract.content_hash,
        )
    )
    bundle = build_projection_bundle(0, ())
    async with transaction() as session:
        await _insert_confirmed_bible(
            session,
            confirmed,
            bible_id="93000000-0000-0000-0001-000000000001",
            now=NOW,
        )
        await session.execute(
            """UPDATE creation_bible_revisions
                  SET policy_version=%s
                WHERE id='93000000-0000-0000-0001-000000000001'""",
            (BIBLE_POLICY_VERSION,),
        )
        await session.execute(
            """INSERT INTO canon_revisions
               (id,project_id,revision_number,parent_revision_number,
                idempotency_key,source_type,source_id,content_hash,created_at)
               VALUES ('93000000-0000-0000-0001-000000000002',%s,0,0,
                       'phase3b-bootstrap','bootstrap',NULL,%s,%s)""",
            (PROJECT, bundle.content_hash, NOW),
        )
        await session.execute(
            """INSERT INTO projection_heads
               (project_id,canon_revision_number,projection_revision_number,
                content_hash,updated_at)
               VALUES (%s,0,0,%s,%s)""",
            (PROJECT, bundle.content_hash, NOW),
        )
        await session.execute(
            """INSERT INTO project_planning_heads
               (project_id,revision,planning_revision_id,content_hash,updated_at)
               VALUES (%s,0,NULL,NULL,%s)""",
            (PROJECT, NOW),
        )
        await session.execute(
            """UPDATE provider_profiles
                  SET base_url=%s,api_key=%s,enabled=%s,stream=0
                WHERE id='81000000-0000-0000-0000-000000000004'""",
            (
                os.environ["BROWSER_PROVIDER_BASE_URL"],
                os.environ["BROWSER_SECRET_SENTINEL"],
                1 if os.environ["BROWSER_SCENARIO_MODE"] == "gateway" else 0,
            ),
        )

    if os.environ["BROWSER_SCENARIO_MODE"] == "gateway":
        planning = PlanningService(
            PlanningRepository(),
            transaction_factory=transaction,
            id_factory=identifiers.__next__,
            clock=lambda: NOW + 1,
        )
        draft = await planning.create_draft(
            CreatePlanningDraft(PROJECT, "phase3b-ready-draft")
        )
        await planning.save_draft(
            SavePlanningDraft(
                PROJECT,
                draft.draft_id,
                draft.draft_revision,
                draft.content_hash,
                _payload("作者保存的第一卷"),
                "phase3b-ready-draft-save",
            )
        )

    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        assert selected == {"database_name": os.environ["MYSQL_DB"]}
        project = await session.fetchone(
            "SELECT id FROM projects WHERE id=%s",
            (PROJECT,),
        )
        assert project == {"id": PROJECT}

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
from urllib.parse import urlsplit

import httpx
import uvicorn

PROVIDER_BASE_URL = os.environ["BROWSER_PROVIDER_BASE_URL"]
OUTBOUND_LEDGER_PATH = os.environ["BROWSER_OUTBOUND_LEDGER_PATH"]

def provider_target():
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
        raise RuntimeError("invalid owned provider endpoint")
    return parsed.port

PROVIDER_PORT = provider_target()
RealAsyncClient = httpx.AsyncClient

class GuardedAsyncClient:
    def __init__(self, *args, **kwargs):
        self.inner = RealAsyncClient(*args, **kwargs)

    async def __aenter__(self):
        await self.inner.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.inner.__aexit__(*args)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def stream(self, method, url, *args, **kwargs):
        parsed = urlsplit(str(url))
        allowed = (
            method == "POST"
            and parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port == PROVIDER_PORT
            and parsed.path == "/v1/chat/completions"
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
        )
        if not allowed:
            with open(OUTBOUND_LEDGER_PATH, "a", encoding="utf-8") as ledger:
                ledger.write("forbidden-outbound\n")
            raise RuntimeError("forbidden outbound request")
        return self.inner.stream(method, url, *args, **kwargs)

httpx.AsyncClient = GuardedAsyncClient

from backend.main import app
uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(sys.argv[1]),
    log_level="warning",
)
`

const TRANSPARENT_FAULT_PROXY_SOURCE = String.raw`
const http = require('node:http')
const { appendFileSync, existsSync, writeFileSync } = require('node:fs')

const port = Number(process.argv[2])
const upstreamPort = Number(process.argv[3])
const nonce = process.env.M2_BROWSER_RUN_NONCE
const projectId = process.env.BROWSER_PROJECT_ID
const inject = process.env.BROWSER_DROP_GENERATION_RESPONSE === '1'
const enteredPath = process.env.BROWSER_GATEWAY_ENTERED_PATH
const releasePath = process.env.BROWSER_GATEWAY_RELEASE_PATH
const upstreamLedgerPath = process.env.BROWSER_UPSTREAM_LEDGER_PATH
const browserOrigin = process.env.BROWSER_VITE_ORIGIN
const parsedBrowserOrigin = new URL(browserOrigin)
if (
  parsedBrowserOrigin.protocol !== 'http:'
  || parsedBrowserOrigin.hostname !== '127.0.0.1'
  || !parsedBrowserOrigin.port
  || parsedBrowserOrigin.pathname !== '/'
  || parsedBrowserOrigin.search
  || parsedBrowserOrigin.hash
  || parsedBrowserOrigin.username
  || parsedBrowserOrigin.password
  || parsedBrowserOrigin.origin !== browserOrigin
) {
  throw new Error('invalid owned browser origin')
}
let injected = false
let upstreamDrained = !inject
const afterUpstreamDrain = []

function fixedUnknown(response) {
  const body = Buffer.from(JSON.stringify({
    error: {
      code: 'RESULT_UNKNOWN',
      message: 'Result must be reconciled',
    },
  }))
  response.writeHead(503, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': String(body.length),
    'access-control-allow-origin': browserOrigin,
    'vary': 'Origin',
  })
  response.end(body)
}

function waitForGatewayEntry(response) {
  const deadline = Date.now() + 30_000
  const check = () => {
    if (existsSync(enteredPath)) {
      if (!injected) {
        injected = true
        fixedUnknown(response)
      }
      return
    }
    if (Date.now() >= deadline) {
      if (!response.headersSent) {
        const body = Buffer.from('owned provider did not start')
        response.writeHead(504, {
          'content-type': 'text/plain; charset=utf-8',
          'content-length': String(body.length),
        })
        response.end(body)
      }
      return
    }
    setTimeout(check, 20)
  }
  check()
}

http.createServer((incoming, response) => {
  if (incoming.method === 'GET' && incoming.url === '/health') {
    const body = Buffer.from(JSON.stringify({ browserRunNonce: nonce }))
    response.writeHead(200, {
      'content-type': 'application/json; charset=utf-8',
      'content-length': String(body.length),
    })
    response.end(body)
    return
  }
  const generationPrefix = (
    '/api/projects/' + projectId + '/planning/drafts/'
  )
  const target = inject
    && !injected
    && incoming.method === 'POST'
    && incoming.url.startsWith(generationPrefix)
    && incoming.url.endsWith('/generate')
    && incoming.url.slice(generationPrefix.length, -'/generate'.length)
      .indexOf('/') === -1
  const pendingLookup = (
    incoming.method === 'GET'
    && incoming.url.startsWith(
      '/api/projects/' + projectId
        + '/planning/operations/by-idempotency-key/',
    )
  )
  const upstream = http.request({
    host: '127.0.0.1',
    port: upstreamPort,
    method: incoming.method,
    path: incoming.url,
    headers: { ...incoming.headers, host: '127.0.0.1:' + upstreamPort },
  }, upstreamResponse => {
    if (target) {
      upstreamResponse.resume()
      upstreamResponse.on('end', () => {
        appendFileSync(
          upstreamLedgerPath,
          'upstream-generation-status=' + String(upstreamResponse.statusCode) + '\n',
          'utf8',
        )
        upstreamDrained = true
        for (const deliver of afterUpstreamDrain.splice(0)) deliver()
      })
      return
    }
    if (!pendingLookup) {
      response.writeHead(upstreamResponse.statusCode, upstreamResponse.headers)
      upstreamResponse.pipe(response)
      return
    }
    const chunks = []
    upstreamResponse.on('data', chunk => chunks.push(chunk))
    upstreamResponse.on('end', () => {
      const body = Buffer.concat(chunks)
      const deliver = () => {
        response.writeHead(upstreamResponse.statusCode, upstreamResponse.headers)
        response.end(body)
      }
      if (upstreamResponse.statusCode >= 200 && upstreamResponse.statusCode < 300) {
        try {
          const operation = JSON.parse(body.toString('utf8'))
          if (
            operation.status === 'pending'
            && typeof operation.operationId === 'string'
            && operation.operationId.length > 0
            && !existsSync(releasePath)
          ) {
            writeFileSync(releasePath, 'release\n', { encoding: 'utf8', flag: 'wx' })
            if (upstreamDrained) deliver()
            else afterUpstreamDrain.push(deliver)
            return
          }
        } catch {
          // A non-operation payload is forwarded unchanged below.
        }
      }
      deliver()
    })
  })
  upstream.on('error', () => {
    if (!response.headersSent) {
      const body = Buffer.from('upstream unavailable')
      response.writeHead(502, {
        'content-type': 'text/plain; charset=utf-8',
        'content-length': String(body.length),
      })
      response.end(body)
    } else {
      response.destroy()
    }
  })
  incoming.pipe(upstream)
  if (target) waitForGatewayEntry(response)
}).listen(port, '127.0.0.1')
`

const FAKE_PLANNING_GATEWAY_SOURCE = String.raw`
const { appendFileSync, existsSync, writeFileSync } = require('node:fs')
const http = require('node:http')

const port = Number(process.argv[2])
const nonce = process.env.M2_BROWSER_RUN_NONCE
const counterPath = process.env.BROWSER_GATEWAY_COUNTER_PATH
const enteredPath = process.env.BROWSER_GATEWAY_ENTERED_PATH
const releasePath = process.env.BROWSER_GATEWAY_RELEASE_PATH
const expectedSecret = process.env.BROWSER_SECRET_SENTINEL

function send(response, status, payload) {
  const body = Buffer.from(JSON.stringify(payload))
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': String(body.length),
  })
  response.end(body)
}

function reject(response) {
  send(response, 404, { error: { code: 'NOT_FOUND', message: 'Not found' } })
}

http.createServer((incoming, response) => {
  if (incoming.method === 'GET' && incoming.url === '/health') {
    send(response, 200, { browserRunNonce: nonce })
    return
  }
  if (incoming.method !== 'POST' || incoming.url !== '/v1/chat/completions') {
    reject(response)
    return
  }
  const chunks = []
  incoming.on('data', chunk => chunks.push(chunk))
  incoming.on('end', () => {
    try {
      if (incoming.headers.authorization !== 'Bearer ' + expectedSecret) {
        reject(response)
        return
      }
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
      if (
        Object.keys(body).sort().join(',') !== [
          'max_tokens',
          'messages',
          'model',
          'response_format',
          'stream',
          'temperature',
        ].sort().join(',')
        || body.model !== 'test-model'
        || body.stream !== false
        || body.response_format?.type !== 'json_object'
        || !Array.isArray(body.messages)
        || body.messages.length !== 2
      ) {
        reject(response)
        return
      }
      const evidence = JSON.parse(body.messages[1].content)
      const draft = evidence.manifest.draft
      const output = {
        ...draft,
        volumes: draft.volumes.map((volume, index) => ({
          ...volume,
          title: 'AI 生成卷 ' + String(index + 1),
          coreChange: '群像在压力下完成一次不可逆的立场变化。',
        })),
        plots: draft.plots.map((plot, index) => ({
          ...plot,
          title: 'AI 持续情节线 ' + String(index + 1),
          futureDirection: '冲突持续升级，并让人物选择产生后果。',
        })),
      }
      appendFileSync(counterPath, 'planning-generation\n', 'utf8')
      if (!existsSync(enteredPath)) {
        writeFileSync(enteredPath, 'entered\n', { encoding: 'utf8', flag: 'wx' })
      }
      const deadline = Date.now() + 30_000
      const waitForRelease = () => {
        if (existsSync(releasePath)) {
          send(response, 200, {
            choices: [{ message: { content: JSON.stringify(output) } }],
          })
          return
        }
        if (Date.now() >= deadline) {
          reject(response)
          return
        }
        setTimeout(waitForRelease, 20)
      }
      waitForRelease()
    } catch {
      reject(response)
    }
  })
}).listen(port, '127.0.0.1')
`

const VERIFICATION_SOURCE = String.raw`
import asyncio
import os
from backend.database import close_pool, connection

async def main():
    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        assert selected == {"database_name": os.environ["MYSQL_DB"]}
        scenario = os.environ["BROWSER_SCENARIO_MODE"]
        project_id = os.environ["BROWSER_PROJECT_ID"]
        head = await session.fetchone(
            "SELECT revision FROM project_planning_heads WHERE project_id=%s",
            (project_id,),
        )
        attempts = await session.fetchone(
            """SELECT COUNT(*) AS total,
                      SUM(status='pending') AS pending,
                      SUM(status='succeeded' AND loaded_draft_revision IS NOT NULL) AS loaded
                 FROM planning_generation_attempts WHERE project_id=%s""",
            (project_id,),
        )
        project = await session.fetchone(
            "SELECT archived_at FROM projects WHERE id=%s",
            (project_id,),
        )
        if scenario == "manual":
            assert head == {"revision": 0}
            assert attempts["total"] == 0
            assert project["archived_at"] is None
        else:
            assert head == {"revision": 2}
            assert attempts["total"] == 1
            assert attempts["pending"] == 0
            assert attempts["loaded"] == 1
            assert project["archived_at"] is not None

async def program():
    try:
        await main()
    finally:
        await close_pool()

asyncio.run(program())
`

const VERIFY_DATABASE_ABSENT_SOURCE = String.raw`
import asyncio
import os
import aiomysql

async def main():
    pool = await aiomysql.create_pool(
        host=os.environ["TEST_MYSQL_HOST"],
        port=int(os.environ["TEST_MYSQL_PORT"]),
        user=os.environ["TEST_MYSQL_USER"],
        password=os.environ["TEST_MYSQL_PASSWORD"],
        autocommit=True,
        minsize=1,
        maxsize=1,
    )
    try:
        async with pool.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT COUNT(*) AS count FROM information_schema.schemata "
                    "WHERE schema_name=%s",
                    (os.environ["BROWSER_TEST_DATABASE"],),
                )
                row = await cursor.fetchone()
                assert row == {"count": 0}
    finally:
        pool.close()
        await pool.wait_closed()

asyncio.run(main())
`


function normalizedPathIdentity(value) {
  const resolved = path.resolve(value)
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}


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


function createRoots(ownedRoot) {
  const artifactRoot = path.join(ownedRoot, 'artifacts')
  const counterPath = path.join(ownedRoot, 'gateway-counter.log')
  const outboundLedgerPath = path.join(ownedRoot, 'outbound-ledger.log')
  const gatewayEnteredPath = path.join(ownedRoot, 'gateway-entered.signal')
  const gatewayReleasePath = path.join(ownedRoot, 'gateway-release.signal')
  const upstreamLedgerPath = path.join(ownedRoot, 'upstream-response.log')
  const viteConfigPath = path.join(ownedRoot, 'vite.config.mjs')
  const fixturePath = path.join(ownedRoot, 'fixture.py')
  const backendPath = path.join(ownedRoot, 'backend.py')
  const gatewayPath = path.join(ownedRoot, 'gateway.cjs')
  const proxyPath = path.join(ownedRoot, 'proxy.cjs')
  const browserResultPath = path.join(ownedRoot, 'browser-result.json')
  mkdirSync(artifactRoot)
  writeFileSync(counterPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(outboundLedgerPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(upstreamLedgerPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(fixturePath, FIXTURE_SOURCE, { encoding: 'utf8', flag: 'wx' })
  writeFileSync(backendPath, BACKEND_SOURCE, { encoding: 'utf8', flag: 'wx' })
  writeFileSync(gatewayPath, FAKE_PLANNING_GATEWAY_SOURCE, {
    encoding: 'utf8',
    flag: 'wx',
  })
  writeFileSync(proxyPath, TRANSPARENT_FAULT_PROXY_SOURCE, {
    encoding: 'utf8',
    flag: 'wx',
  })
  const baseConfigUrl = pathToFileURL(path.join(frontendRoot, 'vite.config.js')).href
  writeFileSync(
    viteConfigPath,
    [
      `import base from ${JSON.stringify(baseConfigUrl)}`,
      'export default {',
      '  ...base,',
      '  optimizeDeps: { ...base.optimizeDeps, noDiscovery: true },',
      '}',
      '',
    ].join('\n'),
    { encoding: 'utf8', flag: 'wx' },
  )
  return {
    root: ownedRoot,
    artifactRoot,
    counterPath,
    outboundLedgerPath,
    gatewayEnteredPath,
    gatewayReleasePath,
    upstreamLedgerPath,
    viteConfigPath,
    fixturePath,
    backendPath,
    gatewayPath,
    proxyPath,
    browserResultPath,
  }
}


function buildEnvironments(
  environment,
  databaseName,
  backendUrl,
  browserApiUrl,
  viteUrl,
  gatewayUrl,
  nonce,
  roots,
  scenario,
) {
  const base = allowlistedBaseEnvironment(environment)
  const prepare = {
    ...base,
    TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST,
    TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: environment.TEST_MYSQL_USER,
    TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    BROWSER_TEST_DATABASE: databaseName,
  }
  const backend = {
    ...base,
    MYSQL_HOST: environment.TEST_MYSQL_HOST,
    MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER,
    MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: databaseName,
    BROWSER_TEST_DATABASE: databaseName,
    BROWSER_PROJECT_ID: PROJECT_ID,
    BROWSER_SCENARIO_MODE: scenario.mode,
    BROWSER_PROVIDER_BASE_URL: gatewayUrl,
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_OUTBOUND_LEDGER_PATH: roots.outboundLedgerPath,
    BROWSER_DROP_GENERATION_RESPONSE: scenario.mode === 'gateway' ? '1' : '0',
    BROWSER_GATEWAY_ENTERED_PATH: roots.gatewayEnteredPath,
    BROWSER_GATEWAY_RELEASE_PATH: roots.gatewayReleasePath,
    BROWSER_UPSTREAM_LEDGER_PATH: roots.upstreamLedgerPath,
    BROWSER_VITE_ORIGIN: viteUrl,
    M2_BROWSER_RUN_NONCE: nonce,
    MARKET_SCHEDULER_ENABLED: 'false',
    SCHEDULER_ENABLED: '0',
  }
  const vite = {
    ...base,
    NODE_ENV: 'test',
    VITE_API_BASE_URL: `${browserApiUrl}/api`,
    M2_BROWSER_RUN_NONCE: nonce,
  }
  const browser = {
    ...base,
    PLAYWRIGHT_BASE_URL: viteUrl,
    BROWSER_OWNED_ROOT: roots.root,
    BROWSER_ARTIFACT_ROOT: roots.artifactRoot,
    BROWSER_RESULT_PATH: roots.browserResultPath,
    BROWSER_PROJECT_ID: PROJECT_ID,
    BROWSER_SCENARIO_MODE: scenario.mode,
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_PRIVATE_PROVIDER_URL: gatewayUrl,
    BROWSER_TEST_DATABASE: databaseName,
    MYSQL_HOST: environment.TEST_MYSQL_HOST,
    MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER,
    MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: databaseName,
  }
  const gateway = {
    ...base,
    M2_BROWSER_RUN_NONCE: nonce,
    BROWSER_GATEWAY_COUNTER_PATH: roots.counterPath,
    BROWSER_GATEWAY_ENTERED_PATH: roots.gatewayEnteredPath,
    BROWSER_GATEWAY_RELEASE_PATH: roots.gatewayReleasePath,
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
  }
  return { prepare, backend, vite, browser, gateway }
}


export function validateSpecs(specs) {
  if (
    !Array.isArray(specs)
    || specs.length !== FORMAL_SPECS.length
    || specs.some((spec, index) => spec !== FORMAL_SPECS[index])
  ) {
    throw new Error('Phase 3B requires its one exact formal browser spec')
  }
  return [...FORMAL_SPECS]
}


export function resolveCommandLineSpecs(argumentsList) {
  if (!Array.isArray(argumentsList) || argumentsList.length !== 0) {
    throw new Error('Phase 3B browser runner does not accept spec paths')
  }
  return [...FORMAL_SPECS]
}


function resolveScenarios(value) {
  if (value == null || value === '') return [...FORMAL_SCENARIOS]
  const scenario = FORMAL_SCENARIOS.find(item => item.tag === value)
  if (!scenario) throw new Error('PHASE3B_GREP must be exactly @manual or @gateway')
  return [scenario]
}


function assertExactGatewayLedger(value, scenario) {
  const entries = String(value).split(/\r?\n/u).filter(Boolean)
  const expected = scenario.mode === 'gateway' ? ['planning-generation'] : []
  assertDeepEqual(entries, expected, 'fake Planning gateway call ledger')
}


function assertDeepEqual(actual, expected, label) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${label} did not match its closed contract`)
  }
}


function assertForbiddenOutboundLedger(value) {
  if (String(value) !== '') {
    throw new Error('forbidden outbound ledger was not empty')
  }
}


function assertUpstreamLedger(value, scenario) {
  const expected = scenario.mode === 'gateway'
    ? 'upstream-generation-status=200\n'
    : ''
  if (String(value).replaceAll('\r\n', '\n') !== expected) {
    throw new Error('transparent proxy did not drain the exact upstream response')
  }
}


function viteTempCacheEntries() {
  const directory = path.join(frontendRoot, 'node_modules', '.vite')
  if (!existsSync(directory)) return []
  return readdirSync(directory, { withFileTypes: true })
    .filter(entry => entry.isDirectory() && entry.name.startsWith('deps_temp_'))
    .map(entry => entry.name)
}


function listFilesRecursively(root) {
  if (!existsSync(root)) return []
  const files = []
  const visit = directory => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name)
      if (entry.isDirectory()) visit(target)
      else if (entry.isFile()) files.push(target)
      else throw new Error('Phase 3B artifact root contains a non-regular entry')
    }
  }
  visit(root)
  return files
}


function assertArtifactEvidenceSafe(artifactRoot, sensitiveValues, extraFiles = []) {
  const markers = [...sensitiveValues, ...FORBIDDEN_EVIDENCE_MARKERS]
  for (const fileName of [
    ...listFilesRecursively(artifactRoot),
    ...extraFiles,
  ]) {
    const bytes = readFileSync(fileName)
    const text = bytes.toString('utf8')
    for (const marker of markers) {
      if (
        typeof marker === 'string'
        && marker
        && text.toLowerCase().includes(marker.toLowerCase())
      ) {
        throw new Error('Phase 3B artifact contains forbidden evidence')
      }
    }
  }
}


function browserFailure(error, resultPath, sensitiveValues) {
  let detail = 'formal scenario failed'
  try {
    const report = JSON.parse(readFileSync(resultPath, 'utf8'))
    const tests = (report.suites || []).flatMap(suite => suite.specs || [])
    const failed = tests.find(spec => (spec.tests || []).some(item => (
      (item.results || []).some(result => result.status !== 'passed')
    )))
    const result = failed?.tests?.flatMap(item => item.results || [])
      .find(item => item.status !== 'passed')
    const message = String(result?.error?.message || '').replace(/\s+/gu, ' ').trim()
    detail = `${String(failed?.title || 'formal scenario failed')}: ${message}`
  } catch {
    // The fixed fallback remains safe when the reporter file is unavailable.
  }
  for (const sensitive of sensitiveValues) {
    if (typeof sensitive === 'string' && sensitive) {
      detail = detail.replaceAll(sensitive, '[redacted]')
    }
  }
  return new Error(`Phase 3B browser test failed: ${detail.slice(0, 2000)}`, {
    cause: error,
  })
}


function ownedDiagnosticPath(ownedRoot, candidate) {
  if (
    typeof ownedRoot !== 'string'
    || typeof candidate !== 'string'
    || !path.basename(path.resolve(ownedRoot)).startsWith(OWNED_ROOT_PREFIX)
  ) return null
  const root = path.resolve(ownedRoot)
  const target = path.resolve(candidate)
  const relative = path.relative(root, target)
  if (relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))) {
    return target
  }
  return null
}


export function attachPhase3BFailureContext(error, {
  scenario,
  ownedRoot,
  artifactRoot,
  resultPath,
  sensitiveValues = [],
}) {
  if (!error || (typeof error !== 'object' && typeof error !== 'function')) {
    return error
  }
  const root = typeof ownedRoot === 'string' ? path.resolve(ownedRoot) : null
  const context = Object.freeze({
    scenario: ['manual', 'gateway'].includes(scenario) ? scenario : null,
    ownedRoot: root,
    artifactRoot: ownedDiagnosticPath(root, artifactRoot),
    resultPath: ownedDiagnosticPath(root, resultPath),
    sensitiveValues: Object.freeze(
      sensitiveValues.filter(value => typeof value === 'string' && value),
    ),
  })
  phase3BFailureContexts.set(error, context)
  return error
}


function collectFailureContexts(error, contexts = [], visited = new Set()) {
  if (!error || (typeof error !== 'object' && typeof error !== 'function')) {
    return contexts
  }
  if (visited.has(error)) return contexts
  visited.add(error)
  const context = phase3BFailureContexts.get(error)
  if (context) contexts.push(context)
  if (error instanceof AggregateError && Array.isArray(error.errors)) {
    for (const nested of error.errors) {
      collectFailureContexts(nested, contexts, visited)
    }
  }
  return contexts
}


function collectLeafFailures(error, failures = [], visited = new Set()) {
  if (error && (typeof error === 'object' || typeof error === 'function')) {
    if (visited.has(error)) return failures
    visited.add(error)
    if (error instanceof AggregateError && Array.isArray(error.errors)) {
      for (const nested of error.errors) {
        collectLeafFailures(nested, failures, visited)
      }
      if (error.errors.length > 0) return failures
    }
  }
  failures.push(error)
  return failures
}


function compactDiagnostic(value) {
  return String(value ?? '').replace(/\s+/gu, ' ').trim()
}


function commandSensitiveValues(environment, contexts) {
  const mapped = {
    ...environment,
    MYSQL_HOST: environment.MYSQL_HOST || environment.TEST_MYSQL_HOST,
    MYSQL_PORT: environment.MYSQL_PORT || environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.MYSQL_USER || environment.TEST_MYSQL_USER,
    MYSQL_PASSWORD: environment.MYSQL_PASSWORD || environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: environment.MYSQL_DB || environment.BROWSER_TEST_DATABASE,
  }
  const values = [
    ...runtimeSensitiveValues(mapped),
    environment.TEST_MYSQL_PASSWORD,
    environment.MYSQL_PASSWORD,
    environment.BROWSER_TEST_DATABASE,
    environment.MYSQL_DB,
    ...contexts.flatMap(context => context.sensitiveValues || []),
  ].filter(value => typeof value === 'string' && value)
  return [...new Set(values)].sort((left, right) => right.length - left.length)
}


function redactDiagnostic(value, sensitiveValues) {
  let redacted = String(value)
  for (const sensitive of sensitiveValues) {
    redacted = redacted.replaceAll(sensitive, '[redacted]')
    const encoded = encodeURIComponent(sensitive)
    if (encoded !== sensitive) redacted = redacted.replaceAll(encoded, '[redacted]')
  }
  return redacted
}


export function formatPhase3BCommandFailure(error, {
  environment = process.env,
} = {}) {
  const contexts = collectFailureContexts(error)
  const failures = collectLeafFailures(error)
  const configuredScenario = String(environment.PHASE3B_GREP || '')
    .replace(/^@/u, '')
  const scenario = contexts.find(context => context.scenario)?.scenario
    || (['manual', 'gateway'].includes(configuredScenario)
      ? configuredScenario
      : null)
    || 'unknown'
  const lines = [
    'Phase 3B browser runner failed.',
    `scenario=${scenario}`,
    `error.count=${String(failures.length)}`,
  ]
  failures.forEach((failure, index) => {
    const number = index + 1
    const name = failure instanceof Error ? failure.name : 'NonError'
    const message = failure instanceof Error ? failure.message : String(failure)
    const stack = failure instanceof Error && typeof failure.stack === 'string'
      ? failure.stack.split(/\r?\n/u).slice(0, 2).map(compactDiagnostic).join(' | ')
      : compactDiagnostic(message)
    lines.push(`error[${String(number)}].name=${compactDiagnostic(name)}`)
    lines.push(`error[${String(number)}].message=${compactDiagnostic(message)}`)
    lines.push(`error[${String(number)}].stack=${stack}`)
  })
  const pathContext = contexts.find(context => (
    context.artifactRoot || context.resultPath
  ))
  if (pathContext?.artifactRoot) lines.push(`trace=${pathContext.artifactRoot}`)
  if (pathContext?.resultPath) lines.push(`result=${pathContext.resultPath}`)
  return redactDiagnostic(
    lines.join('\n'),
    commandSensitiveValues(environment, contexts),
  )
}


export async function runPhase3BCommandLine({
  specs,
  environment = process.env,
  runPhase3BImpl = runPhase3B,
  writeError = message => console.error(message),
}) {
  try {
    return await runPhase3BImpl({ specs, environment })
  } catch (error) {
    writeError(formatPhase3BCommandFailure(error, { environment }))
    return 1
  }
}


function waitForPortRelease(port, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const probe = net.createServer()
      probe.unref()
      probe.once('error', error => {
        probe.close()
        if (Date.now() >= deadline) {
          reject(new Error(`owned port ${String(port)} remained allocated`))
        } else {
          setTimeout(attempt, 50)
        }
      })
      probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
        probe.close(error => {
          if (error) reject(error)
          else resolve()
        })
      })
    }
    attempt()
  })
}


export async function cleanupOwnedRoot({
  root,
  roots,
  ports,
  sensitiveValues,
  waitForPortReleaseImpl = waitForPortRelease,
  viteTempCacheEntriesImpl = viteTempCacheEntries,
  assertArtifactEvidenceSafeImpl = assertArtifactEvidenceSafe,
  removeOwnedRootImpl = removeOwnedRoot,
  existsSyncImpl = existsSync,
}) {
  const errors = []
  for (const port of ports) {
    try {
      await waitForPortReleaseImpl(port)
    } catch (error) {
      errors.push(error)
    }
  }
  try {
    const cacheResidue = viteTempCacheEntriesImpl()
    if (cacheResidue.length !== 0) {
      throw new Error('vite temp cache residue was not zero')
    }
  } catch (error) {
    errors.push(error)
  }
  if (roots) {
    try {
      assertArtifactEvidenceSafeImpl(
        roots.artifactRoot,
        sensitiveValues,
        [roots.browserResultPath],
      )
    } catch (error) {
      errors.push(error)
    }
  }
  try {
    removeOwnedRootImpl(root, OWNED_ROOT_PREFIX)
    if (existsSyncImpl(root)) throw new Error('owned temporary root remained')
  } catch (error) {
    errors.push(error)
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(errors, 'Phase 3B root validation and removal failed')
  }
  return true
}


export async function runOneScenario({
  spec,
  scenario,
  environment,
  databaseNameFactory,
  ownedRootFactory,
  portReservationFactory,
  deadlines,
  createRootsImpl = createRoots,
  cleanupOwnedRootImpl = cleanupOwnedRoot,
}) {
  let environments = null
  let roots = null
  let sensitiveValues = []
  const ports = []
  let databaseCreated = 0
  let databaseCleaned = 0
  let databaseRemaining = 1
  let ownedRootRemoved = false
  let ownedRootPath = null
  const databaseName = databaseNameFactory()
  const nonce = randomUUID()

  try {
    await runOwnedProductLifecycle({
      async body(lifecycle) {
        ownedRootPath = lifecycle.setRoot(ownedRootFactory(OWNED_ROOT_PREFIX))
        roots = createRootsImpl(ownedRootPath)
        lifecycle.setDatabase(databaseName)
        const gatewayReservation = lifecycle.registerReservation(
          await portReservationFactory(),
        )
        const backendReservation = lifecycle.registerReservation(
          await portReservationFactory(),
        )
        const proxyReservation = lifecycle.registerReservation(
          await portReservationFactory(),
        )
        const viteReservation = lifecycle.registerReservation(
          await portReservationFactory(),
        )
        ports.push(
          gatewayReservation.port,
          backendReservation.port,
          proxyReservation.port,
          viteReservation.port,
        )
        if (new Set(ports).size !== 4) {
          throw new Error('Phase 3B runner received duplicate owned ports')
        }
        const gatewayUrl = `http://127.0.0.1:${gatewayReservation.port}/v1`
        const backendUrl = `http://127.0.0.1:${backendReservation.port}`
        const browserApiUrl = `http://127.0.0.1:${proxyReservation.port}`
        const viteUrl = `http://127.0.0.1:${viteReservation.port}`
        environments = buildEnvironments(
          environment,
          databaseName,
          backendUrl,
          browserApiUrl,
          viteUrl,
          gatewayUrl,
          nonce,
          roots,
          scenario,
        )
        sensitiveValues = [
          ...runtimeSensitiveValues(environments.browser),
          ...FORBIDDEN_EVIDENCE_MARKERS,
        ]
        const python = environment.PYTHON || 'python'
        const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')
        const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js')
        const activeServers = []

        await runBoundedOwnedCommand(
          python,
          ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', databaseName],
          childOptions(repositoryRoot, environments.prepare),
          {
            label: 'database preparation',
            sensitiveValues,
            timeoutMs: deadlines.commandMs,
            stopTimeoutMs: deadlines.stopMs,
          },
        )
        databaseCreated = 1
        await runBoundedOwnedCommand(
          python,
          [
            '-c',
            `import runpy; runpy.run_path(${JSON.stringify(roots.fixturePath)}, run_name="__main__")`,
          ],
          childOptions(repositoryRoot, environments.backend),
          {
            label: 'Phase 3B fixture preparation',
            sensitiveValues,
            timeoutMs: deadlines.commandMs,
            stopTimeoutMs: deadlines.stopMs,
          },
        )

        await lifecycle.releaseReservation(gatewayReservation)
        const gateway = lifecycle.registerServer(startOwnedServer(
          process.execPath,
          [roots.gatewayPath, String(gatewayReservation.port)],
          childOptions(repositoryRoot, environments.gateway),
          { label: 'fake Planning gateway', sensitiveValues },
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
          [
            '-c',
            `import runpy; runpy.run_path(${JSON.stringify(roots.backendPath)}, run_name="__main__")`,
            String(backendReservation.port),
          ],
          childOptions(repositoryRoot, environments.backend),
          { label: 'backend', sensitiveValues },
        ))
        activeServers.push(backend)
        await waitForOwnedServer(backend, `${backendUrl}/api/health`, {
          expectedNonce: nonce,
          timeoutMs: deadlines.healthMs,
        })

        await lifecycle.releaseReservation(proxyReservation)
        const transportProxy = lifecycle.registerServer(startOwnedServer(
          process.execPath,
          [
            roots.proxyPath,
            String(proxyReservation.port),
            String(backendReservation.port),
          ],
          childOptions(repositoryRoot, environments.backend),
          { label: 'transparent result-unknown proxy', sensitiveValues },
        ))
        activeServers.push(transportProxy)
        await waitForOwnedServer(
          transportProxy,
          `http://127.0.0.1:${proxyReservation.port}/health`,
          { expectedNonce: nonce, timeoutMs: deadlines.healthMs },
        )

        await lifecycle.releaseReservation(viteReservation)
        const vite = lifecycle.registerServer(startOwnedServer(
          process.execPath,
          [
            viteCli,
            '--config', roots.viteConfigPath,
            '--host', '127.0.0.1',
            '--port', String(viteReservation.port),
            '--strictPort',
          ],
          childOptions(frontendRoot, environments.vite),
          { label: 'vite', sensitiveValues },
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
              `e2e/${spec}`,
              '--config',
              `e2e/${FORMAL_CONFIG}`,
              '--grep',
              scenario.tag,
            ],
            childOptions(frontendRoot, environments.browser),
            {
              label: 'Phase 3B browser test',
              sensitiveValues,
              timeoutMs: deadlines.browserMs,
              stopTimeoutMs: deadlines.stopMs,
              states: activeServers,
            },
          )
        } catch (error) {
          throw browserFailure(error, roots.browserResultPath, sensitiveValues)
        }
        assertForbiddenOutboundLedger(
          readFileSync(roots.outboundLedgerPath, 'utf8'),
        )
        assertExactGatewayLedger(
          readFileSync(roots.counterPath, 'utf8'),
          scenario,
        )
        assertUpstreamLedger(
          readFileSync(roots.upstreamLedgerPath, 'utf8'),
          scenario,
        )
        await runBoundedOwnedCommand(
          python,
          ['-c', VERIFICATION_SOURCE],
          childOptions(repositoryRoot, environments.backend),
          {
            label: 'Phase 3B database evidence',
            sensitiveValues,
            timeoutMs: deadlines.commandMs,
            stopTimeoutMs: deadlines.stopMs,
            states: activeServers,
          },
        )
      },
      stopServer: server => stopOwnedServer(server, {
        sensitiveValues,
        timeoutMs: deadlines.stopMs,
      }),
      releaseReservation: reservation => reservation.release(),
      async dropDatabase(database) {
        await runBoundedOwnedCommand(
          environment.PYTHON || 'python',
          [
            '-m',
            'backend.scripts.prepare_product_shell_browser_db',
            '--database',
            database,
            '--drop',
          ],
          childOptions(repositoryRoot, environments?.prepare || environment),
          {
            label: 'database cleanup',
            sensitiveValues,
            timeoutMs: deadlines.commandMs,
            stopTimeoutMs: deadlines.stopMs,
          },
        )
        databaseCleaned = 1
        await runBoundedOwnedCommand(
          environment.PYTHON || 'python',
          ['-c', VERIFY_DATABASE_ABSENT_SOURCE],
          childOptions(repositoryRoot, environments.prepare),
          {
            label: 'database cleanup verification',
            sensitiveValues,
            timeoutMs: deadlines.commandMs,
            stopTimeoutMs: deadlines.stopMs,
          },
        )
        databaseRemaining = 0
      },
      async removeRoot(root) {
        ownedRootRemoved = await cleanupOwnedRootImpl({
          root,
          roots,
          ports,
          sensitiveValues,
        })
      },
    })
  } catch (error) {
    attachPhase3BFailureContext(error, {
      scenario: scenario.mode,
      ownedRoot: ownedRootPath,
      artifactRoot: roots?.artifactRoot
        || (ownedRootPath && path.join(ownedRootPath, 'artifacts')),
      resultPath: roots?.browserResultPath
        || (ownedRootPath && path.join(ownedRootPath, 'browser-result.json')),
      sensitiveValues: [...sensitiveValues, databaseName],
    })
    throw error
  }

  if (
    databaseCreated !== 1
    || databaseCleaned !== 1
    || databaseRemaining !== 0
    || !ownedRootRemoved
  ) {
    const error = new AggregateError([], 'Phase 3B resource accounting failed')
    attachPhase3BFailureContext(error, {
      scenario: scenario.mode,
      ownedRoot: ownedRootPath,
      artifactRoot: roots?.artifactRoot,
      resultPath: roots?.browserResultPath,
      sensitiveValues: [...sensitiveValues, databaseName],
    })
    throw error
  }
  console.log(
    `Phase3B ${scenario.mode}: browser assertions passed; `
      + `DB created=${databaseCreated} cleaned=${databaseCleaned} `
      + `remaining=${databaseRemaining}; process=0 port=0 temp=0 cache=0`,
  )
}


export async function runPhase3B({
  specs = FORMAL_SPECS,
  environment = process.env,
  databaseNameFactory = createDatabaseName,
  ownedRootFactory = createOwnedRoot,
  portReservationFactory = reserveLocalPort,
  runOneScenarioImpl = runOneScenario,
  deadlines = {},
} = {}) {
  validateTestEnvironment(environment)
  const formalSpecs = validateSpecs(specs)
  const scenarios = resolveScenarios(environment.PHASE3B_GREP)
  const normalizedDeadlines = { ...DEFAULT_DEADLINES, ...deadlines }
  if (Object.values(normalizedDeadlines).some(value => (
    !Number.isFinite(value) || value <= 0
  ))) {
    throw new TypeError('Phase 3B deadlines must be positive finite numbers')
  }
  for (const spec of formalSpecs) {
    for (const scenario of scenarios) {
      await runOneScenarioImpl({
        spec,
        scenario,
        environment,
        databaseNameFactory,
        ownedRootFactory,
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
    console.error('Phase 3B browser runner does not accept spec paths.')
    process.exitCode = 2
  }
  if (specs) {
    runPhase3BCommandLine({ specs }).then(status => {
      process.exitCode = status
    })
  }
}
