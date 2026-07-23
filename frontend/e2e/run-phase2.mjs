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
const DEFAULT_DEADLINES = Object.freeze({
  commandMs: 90_000,
  healthMs: 45_000,
  browserMs: 300_000,
  stopMs: 8_000,
})
const ALLOWED_BROWSER_STEPS = Object.freeze([
  'library-navigation-start',
  'library-navigation-finished',
  'library-heading-visible',
  'library-button-visible',
  'library-visible',
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

const port = Number(process.env.BROWSER_FAKE_GATEWAY_PORT)
const nonce = process.env.M2_BROWSER_RUN_NONCE
const apiKey = process.env.BROWSER_SECRET_SENTINEL
if (!Number.isInteger(port) || port <= 0 || !nonce || !apiKey) {
  throw new Error('fake gateway ownership configuration is invalid')
}

function sendJson(response, status, value) {
  response.writeHead(status, {
    'content-type': 'application/json',
    'connection': 'close',
  })
  response.end(JSON.stringify(value))
}

async function discardBody(request) {
  let size = 0
  for await (const chunk of request) {
    size += chunk.length
    if (size > 256 * 1024) throw new Error('request too large')
  }
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
    try {
      await discardBody(request)
    } catch {
      sendJson(response, 400, { error: { code: 'invalid_request' } })
      return
    }
    sendJson(response, 422, { error: { code: 'unsupported_fixture_request' } })
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
  writeFileSync(fakeGatewayPath, FAKE_GATEWAY_SOURCE, {
    encoding: 'utf8',
    flag: 'wx',
  })
  writeFileSync(outboundLedgerPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(stepLedgerPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(corpusPath, [
    '第一章 山河初醒',
    '沈砚在陌生朝代醒来时，怀里只剩一页被火燎过的旧典。他先救下抄书匠，再决定追查谁在销毁散落民间的卷册。',
    '',
    '第二章 城门夜问',
    '守门校尉不信一页残纸能救人，沈砚便把纸上的水道记载与城外决堤痕迹逐项对上。',
  ].join('\n'), { encoding: 'utf8', flag: 'wx' })
  return {
    root,
    filesRoot,
    corpusRoot,
    managedRoot,
    corpusPath,
    fakeGatewayPath,
    outboundLedgerPath,
    stepLedgerPath,
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
  const privateFixture = {
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
    ...privateFixture,
  }
  const backend = {
    ...base,
    ...database,
    ...privateFixture,
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
    BROWSER_STEP_LEDGER: roots.stepLedgerPath,
    BROWSER_TEST_DATABASE: databaseName,
    ...privateFixture,
    BROWSER_TRANSCRIPT_SENTINEL: TRANSCRIPT_SENTINEL,
    BROWSER_CORPUS_ROOT_SENTINEL: roots.root,
  }
  const gateway = {
    ...base,
    M2_BROWSER_RUN_NONCE: nonce,
    BROWSER_FAKE_GATEWAY_PORT: String(new URL(gatewayUrl).port),
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
  }
  const sensitiveController = {
    ...database,
    BROWSER_TEST_DATABASE: databaseName,
    ...privateFixture,
    BROWSER_TRANSCRIPT_SENTINEL: TRANSCRIPT_SENTINEL,
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


export function verifyForbiddenOutboundLedger(ledger) {
  if (String(ledger || '') !== '') {
    throw new Error('Phase 2 forbidden outbound ledger is not empty')
  }
  return { 'forbidden-outbound': 0 }
}


export function verifyBrowserStepLedger(ledger) {
  const lines = String(ledger || '').split(/\r?\n/u).filter(Boolean)
  if (
    lines.some(line => !ALLOWED_BROWSER_STEPS.includes(line))
    || lines.some((line, index) => (
      index > 0
      && ALLOWED_BROWSER_STEPS.indexOf(line)
        <= ALLOWED_BROWSER_STEPS.indexOf(lines[index - 1])
    ))
  ) {
    throw new Error('Phase 2 browser progress ledger is invalid')
  }
  return lines
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
  return runOwnedProductLifecycle({
    async body(lifecycle) {
      const databaseName = lifecycle.setDatabase(databaseNameFactory())
      assertDatabaseName(databaseName)
      const ownedRoot = lifecycle.setRoot(ownedRootFactory())
      const roots = prepareOwnedFiles(ownedRoot)
      const backendReservation = lifecycle.registerReservation(
        await portReservationFactory(),
      )
      const viteReservation = lifecycle.registerReservation(
        await portReservationFactory(),
      )
      const gatewayReservation = lifecycle.registerReservation(
        await portReservationFactory(),
      )
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
      sensitiveValues = runtimeSensitiveValues(environments.sensitiveController)
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
        const steps = verifyBrowserStepLedger(
          readFileSync(roots.stepLedgerPath, 'utf8'),
        )
        const lastStep = steps.at(-1) || 'no-browser-step'
        throw new Error(
          `Phase 2 browser stopped after ${lastStep}`,
          { cause: error },
        )
      }
      verifyBrowserStepLedger(readFileSync(roots.stepLedgerPath, 'utf8'))
      verifyForbiddenOutboundLedger(
        readFileSync(roots.outboundLedgerPath, 'utf8'),
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
    stopServer: server => stopOwnedServer(server, {
      sensitiveValues,
      timeoutMs: deadlines.stopMs,
    }),
    releaseReservation: reservation => reservation.release(),
    dropDatabase: database => runBoundedOwnedCommand(
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
    ),
    removeRoot: root => removeOwnedRoot(root, OWNED_ROOT_PREFIX),
  })
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
  for (const spec of formalSpecs) {
    await runOneScenarioImpl({
      spec,
      environment,
      databaseNameFactory,
      ownedRootFactory,
      portReservationFactory,
      deadlines: normalizedDeadlines,
    })
  }
  return 0
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
    .catch(error => {
      process.stderr.write('Phase 2 browser acceptance failed.\n')
      process.exitCode = 1
      return error
    })
}
