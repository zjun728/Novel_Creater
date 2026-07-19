import { randomUUID } from 'node:crypto'
import {
  lstatSync,
  mkdirSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { StringDecoder } from 'node:string_decoder'
import { fileURLToPath } from 'node:url'

import {
  assertDatabaseName,
  createDatabaseName,
  reserveLocalPort,
  validateTestEnvironment,
  waitForOwnedUrl,
} from './run-milestone2.mjs'
import {
  BASE_ENV_ALLOWLIST,
  spawnOwnedChild,
  terminateOwnedProcessTree,
} from './run-product-shell.mjs'
import { createServerLogObserver } from './server-log-observer.mjs'
import { runtimeSensitiveValues } from './runtime-observer.mjs'


export const FORMAL_SPECS = Object.freeze([
  'e2e/phase2a-assets-settings.spec.ts',
])

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const OWNED_ROOT_PREFIX = 'novel-creator-phase2a-'
const SECRET_SENTINEL = 'phase2a-browser-secret-must-not-leak-9e84318c'
const PRIVATE_PROVIDER_URL = 'https://phase2a-private-provider.example/v1'
const DEFAULT_DEADLINES = Object.freeze({
  commandMs: 90_000,
  healthMs: 45_000,
  browserMs: 180_000,
  stopMs: 8_000,
})

const SYNTHETIC_CORPUS = Object.freeze({
  'phase2a-version-1.txt': [
    '第一章 合成样本',
    '这是只用于浏览器验收的第一版合成文本。人物甲推开窗，确认院中没有访客，才把一张空白纸放到桌上。',
    '这段文字不来自真实语料，也不承担任何创作参考价值。',
  ].join('\n\n'),
  'phase2a-version-2.txt': [
    '第一章 合成样本第二版',
    '这是只用于浏览器验收的第二版合成文本。人物甲合上窗，把纸折成两半，随后与人物乙核对一条虚构线索。',
    '新增内容仍为自动化测试合成文本，与真实作品无关。',
  ].join('\n\n'),
  'phase2a-referenced.txt': [
    '第一章 引用保护样本',
    '这份合成文本用于建立一条创作契约引用，以验证归档后永久删除会被产品规则阻止。',
    '所有人名、情节和句子均为测试夹具。',
  ].join('\n\n'),
})

const FIXTURE_SOURCE = String.raw`
import asyncio
import hashlib
import os
from pathlib import Path
import time

from backend.database import close_pool, connection, transaction
from backend.repositories.corpus import CorpusRepository
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.projects import ProjectRepository
from backend.services.corpus_import import CorpusImportService
from backend.services.model_bindings import ModelBindingService
from backend.services.project_lifecycle import CreateProject, ProjectLifecycleService
from backend.services.provider_profiles import (
    ProviderCreateCommand,
    ProviderProfileService,
    SqlProviderProfileRepository,
)

PROJECT_ID = "2a000000-0000-4000-8000-000000000001"
SEED_ID = "2a000000-0000-4000-8000-000000000002"
SEED_REVISION_ID = "2a000000-0000-4000-8000-000000000003"
CONTRACT_ID = "2a000000-0000-4000-8000-000000000004"

async def main():
    provider_service = ProviderProfileService(
        SqlProviderProfileRepository(),
        transaction_factory=transaction,
        connection_factory=connection,
        connection_gateway=None,
    )
    for order, suffix in enumerate(("A", "B")):
        await provider_service.create(ProviderCreateCommand(
            name=f"Phase 2A \u5408\u6210 Provider {suffix}",
            provider_type="openai-compatible",
            model=f"phase2a-model-{suffix.lower()}",
            base_url=os.environ["BROWSER_PRIVATE_PROVIDER_URL"],
            api_key=os.environ["BROWSER_SECRET_SENTINEL"],
            enabled=True,
            sort_order=order,
            stream=True,
            max_context_tokens=200000,
            max_output_tokens=4096,
            temperature=0.8,
            top_p=0.9,
            supports_json=True,
            supports_streaming=True,
            notes="Synthetic browser fixture.",
            thinking=None,
            idempotency_key=f"phase2a-provider-{suffix.lower()}-create",
        ))

    model_bindings = ModelBindingService(
        ModelBindingRepository(),
        transaction_factory=transaction,
        connection_factory=connection,
    )
    projects = ProjectLifecycleService(
        ProjectRepository(),
        transaction,
        connection,
        model_binding_service=model_bindings,
    )
    await projects.create(CreateProject(
        id=PROJECT_ID,
        title="Phase 2A \u4fdd\u62a4\u5939\u5177\u9879\u76ee",
    ))

    corpus = CorpusImportService(
        CorpusRepository(),
        corpus_root=Path(os.environ["CORPUS_ROOT"]),
        managed_root=Path(os.environ["MANAGED_CORPUS_ROOT"]),
        transaction_factory=transaction,
        connection_factory=transaction,
    )
    imported = await corpus.import_source(
        "phase2a-referenced.txt",
        "phase2a-referenced-import",
        display_name="\u5408\u6210\u5f15\u7528\u4fdd\u62a4\u6837\u672c",
        notes="runner-owned synthetic fixture",
    )

    now = int(time.time() * 1000)
    empty_hash = hashlib.sha256(b"{}").hexdigest()
    async with transaction() as session:
        binding = await session.fetchone(
            """SELECT binding_revision_id,content_hash
                 FROM project_model_binding_heads WHERE project_id=%s""",
            (PROJECT_ID,),
        )
        revision = await session.fetchone(
            """SELECT source_id,revision,content_hash
                 FROM corpus_source_revisions
                WHERE source_id=%s AND revision=%s""",
            (imported["corpus_source_id"], imported["source_revision"]),
        )
        await session.execute(
            """INSERT INTO creative_seeds
               (id,project_id,status,created_at,updated_at)
               VALUES (%s,%s,'candidate',%s,%s)""",
            (SEED_ID, PROJECT_ID, now, now),
        )
        await session.execute(
            """INSERT INTO creative_seed_revisions
               (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
               VALUES (%s,%s,%s,1,'{}',%s,%s)""",
            (SEED_REVISION_ID, PROJECT_ID, SEED_ID, empty_hash, now),
        )
        await session.execute(
            """INSERT INTO creative_seed_heads
               (seed_id,revision_id,revision,content_hash,updated_at)
               VALUES (%s,%s,1,%s,%s)""",
            (SEED_ID, SEED_REVISION_ID, empty_hash, now),
        )
        await session.execute(
            """INSERT INTO project_seed_selection_revisions
               (project_id,selection_revision,seed_id,seed_revision_id,seed_hash,
                selected_at)
               VALUES (%s,1,%s,%s,%s,%s)""",
            (PROJECT_ID, SEED_ID, SEED_REVISION_ID, empty_hash, now),
        )
        await session.execute(
            """INSERT INTO project_selected_seeds
               (project_id,seed_id,seed_revision_id,seed_hash,selection_revision,
                selected_at,updated_at)
               VALUES (%s,%s,%s,%s,1,%s,%s)""",
            (PROJECT_ID, SEED_ID, SEED_REVISION_ID, empty_hash, now, now),
        )
        await session.execute(
            """INSERT INTO creation_contracts
               (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
                seed_hash,binding_revision_id,binding_hash,channel_profile_key,
                genre_profile_key,quality_charter_version,total_word_min,
                total_word_max,chapter_capacity_policy,reference_manifest_json,
                reference_manifest_hash,content_json,content_hash,confirmed_at)
               VALUES (%s,%s,1,1,%s,%s,%s,%s,%s,'phase2a','phase2a','phase2a-v1',
                       1,2,'rolling','{}',%s,'{}',%s,%s)""",
            (
                CONTRACT_ID, PROJECT_ID, SEED_ID, SEED_REVISION_ID, empty_hash,
                binding["binding_revision_id"], binding["content_hash"],
                empty_hash, empty_hash, now,
            ),
        )
        await session.execute(
            """INSERT INTO creation_contract_corpus_refs
               (creation_contract_id,corpus_source_id,source_revision,source_hash,
                selection_mode,sort_order)
               VALUES (%s,%s,%s,%s,'author',1)""",
            (
                CONTRACT_ID, revision["source_id"], revision["revision"],
                revision["content_hash"],
            ),
        )

async def program():
    try:
        await main()
    finally:
        await close_pool()

asyncio.run(program())
`

const BACKEND_SOURCE = String.raw`
import copy
import os
import sys
import uvicorn
from uvicorn.config import LOGGING_CONFIG

from backend.main import app
from backend.routers.providers import build_provider_profile_service

class FakeProviderConnectionGateway:
    async def test_connection(self, profile):
        if profile.get("api_key") != os.environ["BROWSER_SECRET_SENTINEL"]:
            raise RuntimeError("synthetic provider secret mismatch")
        if profile.get("base_url") != os.environ["BROWSER_PRIVATE_PROVIDER_URL"]:
            raise RuntimeError("synthetic provider URL mismatch")
        return {
            "ok": True,
            "code": "connected",
            "latencyMs": 12,
        }

fake_gateway = object.__new__(FakeProviderConnectionGateway)
app.state.provider_profile_service = build_provider_profile_service(
    connection_gateway=fake_gateway
)
log_config = copy.deepcopy(LOGGING_CONFIG)
log_config["formatters"]["access"]["fmt"] = '%(client_addr)s - "%(request_line)s" %(status_code)s'
log_config["formatters"]["access"]["use_colors"] = False
uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(sys.argv[1]),
    log_level="info",
    access_log=True,
    log_config=log_config,
)
`


export function validateSpecs(specs) {
  if (
    !Array.isArray(specs)
    || specs.length !== FORMAL_SPECS.length
    || specs.some((spec, index) => spec !== FORMAL_SPECS[index])
  ) {
    throw new Error('Phase 2A browser requires the exact formal spec path')
  }
  return [...FORMAL_SPECS]
}


export function resolveCommandLineSpecs(argumentsList) {
  if (!Array.isArray(argumentsList)) {
    throw new TypeError('Phase 2A browser CLI arguments must be an array')
  }
  if (argumentsList.length !== 0) {
    throw new Error('Phase 2A browser runner does not accept spec paths')
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
  const temporaryRoot = realpathSync(os.tmpdir())
  const stats = lstatSync(root)
  if (!stats.isDirectory() || stats.isSymbolicLink()) {
    throw new Error('Phase 2A owned root is not a real directory')
  }
  if (
    !path.basename(root).startsWith(OWNED_ROOT_PREFIX)
    || normalizedPathIdentity(path.dirname(realpathSync(root)))
      !== normalizedPathIdentity(temporaryRoot)
  ) {
    throw new Error('Phase 2A owned root is outside its temporary namespace')
  }
  return root
}


export function createOwnedRoot() {
  const ownedRoot = mkdtempSync(path.join(os.tmpdir(), OWNED_ROOT_PREFIX))
  assertOwnedRoot(ownedRoot)
  return ownedRoot
}


function prepareOwnedCorpus(ownedRoot) {
  const root = assertOwnedRoot(ownedRoot)
  const discoveryRoot = path.join(root, 'discovery')
  const managedRoot = path.join(root, 'managed')
  mkdirSync(discoveryRoot)
  mkdirSync(managedRoot)
  for (const [fileName, content] of Object.entries(SYNTHETIC_CORPUS)) {
    writeFileSync(path.join(discoveryRoot, fileName), content, {
      encoding: 'utf8',
      flag: 'wx',
    })
  }
  return { discoveryRoot, managedRoot }
}


function childOptions(cwd, env) {
  return {
    cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  }
}


function buildProcessEnvironments(
  environment,
  databaseName,
  backendUrl,
  viteUrl,
  nonce,
  roots,
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
    M2_BROWSER_RUN_NONCE: nonce,
    CORPUS_ROOT: roots.discoveryRoot,
    MANAGED_CORPUS_ROOT: roots.managedRoot,
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_PRIVATE_PROVIDER_URL: PRIVATE_PROVIDER_URL,
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
    BROWSER_ARTIFACT_ROOT: path.join(
      path.dirname(roots.discoveryRoot),
      'phase2a-test-results',
    ),
    BROWSER_TEST_DATABASE: databaseName,
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_PRIVATE_PROVIDER_URL: PRIVATE_PROVIDER_URL,
    BROWSER_CORPUS_ROOT_SENTINEL: roots.managedRoot,
    BROWSER_ACTUAL_CORPUS_ROOT_SENTINEL: roots.discoveryRoot,
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
    BROWSER_CORPUS_ROOT_SENTINEL: roots.managedRoot,
    BROWSER_ACTUAL_CORPUS_ROOT_SENTINEL: roots.discoveryRoot,
  }
  return { prepare, backend, vite, browser, sensitiveController }
}


function waitForClose(child) {
  return new Promise((resolve, reject) => {
    child.once('error', () => reject(new Error('owned process failed to start')))
    child.once('close', (status, signal) => resolve({ status, signal }))
  })
}


async function runOwnedCommand(command, args, options, {
  label,
  sensitiveValues,
  timeoutMs,
}) {
  const child = spawnOwnedChild(command, args, options)
  const observer = createServerLogObserver(child, { sensitiveValues })
  const diagnosticChunks = []
  let diagnosticBytes = 0
  const captureDiagnostic = chunk => {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8')
    const remaining = 32 * 1024 - diagnosticBytes
    if (remaining <= 0) return
    diagnosticChunks.push(buffer.subarray(0, remaining))
    diagnosticBytes += Math.min(buffer.length, remaining)
  }
  child.stdout?.on?.('data', captureDiagnostic)
  child.stderr?.on?.('data', captureDiagnostic)
  let timer
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(
      () => reject(new Error(`${label} deadline exceeded`)),
      timeoutMs,
    )
  })
  let outcome
  try {
    outcome = await Promise.race([waitForClose(child), timeout])
  } catch (error) {
    try {
      await terminateOwnedProcessTree(child, { timeoutMs: DEFAULT_DEADLINES.stopMs })
    } catch (stopError) {
      throw new AggregateError([error, stopError], `${label} and stop failed`)
    }
    throw error
  } finally {
    clearTimeout(timer)
  }
  const scan = observer.finish(sensitiveValues)
  if (scan.matchCount !== 0) {
    throw new Error(`${label} log contained runtime-sensitive values`)
  }
  if (outcome.status !== 0) {
    const detail = Buffer.concat(diagnosticChunks)
      .toString('utf8')
      .replaceAll(/\u001b\[[0-9;]*m/gu, '')
      .trim()
      .slice(-4_000)
    throw new Error(
      `${label} exited with status ${String(outcome.status)}`
      + (detail ? `\n${detail}` : ''),
    )
  }
}


function startOwnedServer(command, args, options, label, sensitiveValues) {
  const child = spawnOwnedChild(command, args, options)
  return {
    child,
    label,
    observer: createServerLogObserver(child, { sensitiveValues }),
  }
}

export function createDelete204AccessObserver(child) {
  const sourcePattern = String.raw`[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`
  const exactPath = new RegExp(
    String.raw`^/api/corpus/sources/${sourcePattern}$`,
    'u',
  )
  const accessPattern = /"([A-Z]+) ([^"\s]+) HTTP\/[0-9.]+" ([0-9]{3})\b/gu
  const records = []
  let prefixLines = 0
  let parsedAccessRecords = 0
  let invalidEvidence = false
  let finished = false

  const createScanner = stream => {
    const decoder = new StringDecoder('utf8')
    let tail = ''
    const inspectLine = line => {
      if (line.includes('"DELETE /api/corpus/sources/')) {
        prefixLines += 1
      }
      accessPattern.lastIndex = 0
      let match
      let sawDeleteCorpusPrefix = false
      while ((match = accessPattern.exec(line)) !== null) {
        parsedAccessRecords += 1
        const [, method, target, rawStatus] = match
        if (method !== 'DELETE' || !target.startsWith('/api/corpus/sources/')) {
          continue
        }
        sawDeleteCorpusPrefix = true
        try {
          const parsed = new URL(target, 'http://127.0.0.1')
          if (
            parsed.search
            || parsed.hash
            || !exactPath.test(parsed.pathname)
          ) {
            invalidEvidence = true
            continue
          }
          records.push({ status: Number(rawStatus) })
        } catch {
          invalidEvidence = true
        }
      }
      if (
        !sawDeleteCorpusPrefix
        && line.includes('"DELETE /api/corpus/sources/')
      ) {
        invalidEvidence = true
      }
    }
    const scan = chunk => {
      const text = tail + decoder.write(
        Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8'),
      )
      const lines = text.split(/\r?\n/u)
      tail = lines.pop() || ''
      for (const line of lines) inspectLine(line)
      if (tail.length > 4_096) {
        if (tail.includes('"DELETE /api/corpus/sources/')) {
          invalidEvidence = true
        }
        tail = ''
      }
    }
    const flush = () => {
      const final = tail + decoder.end()
      tail = ''
      if (final) inspectLine(final)
    }
    stream?.on?.('data', scan)
    return {
      detach() {
        stream?.off?.('data', scan)
        flush()
      },
    }
  }

  const stdout = createScanner(child?.stdout)
  const stderr = createScanner(child?.stderr)
  return {
    finish() {
      if (finished) throw new Error('DELETE 204 access observer already finished')
      finished = true
      stdout.detach()
      stderr.detach()
      if (
        invalidEvidence
        || records.length !== 1
        || records[0].status !== 204
      ) {
        throw new Error(
          'Backend access evidence requires exactly one corpus DELETE 204 '
          + `(prefixLines=${String(prefixLines)}, `
          + `parsedAccessRecords=${String(parsedAccessRecords)}, `
          + `corpusRecords=${String(records.length)}, `
          + `invalid=${String(invalidEvidence)})`,
        )
      }
      return { matchCount: 1 }
    },
  }
}


async function waitForServer(server, url, nonce, timeoutMs) {
  let onClose
  const closed = new Promise((_, reject) => {
    onClose = status => reject(
      new Error(`${server.label} exited before health with status ${String(status)}`),
    )
    server.child.once('close', onClose)
  })
  try {
    await Promise.race([
      waitForOwnedUrl(url, { expectedNonce: nonce, timeoutMs }),
      closed,
    ])
  } finally {
    server.child.off('close', onClose)
  }
}


async function stopOwnedServer(server, sensitiveValues, stopMs) {
  const errors = []
  try {
    await terminateOwnedProcessTree(server.child, { timeoutMs: stopMs })
  } catch (error) {
    errors.push(error)
  }
  try {
    const scan = server.observer.finish(sensitiveValues)
    if (scan.matchCount !== 0) {
      errors.push(new Error(`${server.label} log contained runtime-sensitive values`))
    }
  } catch (error) {
    errors.push(error)
  }
  if (server.accessObserver) {
    try {
      server.accessObserver.finish()
    } catch (error) {
      errors.push(error)
    }
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(errors, `${server.label} stop and log audit failed`)
  }
}


async function runOneSpec({
  spec,
  environment,
  databaseNameFactory,
  ownedRootFactory,
  portReservationFactory,
  deadlines,
}) {
  let databaseName
  let ownedRoot
  let roots
  let nonce
  const reservations = []
  const released = new Set()
  const servers = []
  const errors = []
  let databaseStarted = false
  let environments
  let sensitiveValues = []
  const release = async reservation => {
    if (!reservation || released.has(reservation)) return
    released.add(reservation)
    await reservation.release()
  }

  try {
    databaseName = databaseNameFactory()
    assertDatabaseName(databaseName)
    ownedRoot = ownedRootFactory()
    roots = prepareOwnedCorpus(ownedRoot)
    nonce = randomUUID()
    const backendReservation = await portReservationFactory()
    reservations.push(backendReservation)
    if (
      !Number.isInteger(backendReservation?.port)
      || typeof backendReservation.release !== 'function'
    ) {
      throw new Error('Phase 2A runner received invalid backend port reservation')
    }
    const viteReservation = await portReservationFactory()
    reservations.push(viteReservation)
    if (
      !Number.isInteger(viteReservation?.port)
      || backendReservation.port === viteReservation.port
      || typeof viteReservation.release !== 'function'
    ) {
      throw new Error('Phase 2A runner received invalid Vite port reservation')
    }
    const backendUrl = `http://127.0.0.1:${backendReservation.port}`
    const viteUrl = `http://127.0.0.1:${viteReservation.port}`
    environments = buildProcessEnvironments(
      environment,
      databaseName,
      backendUrl,
      viteUrl,
      nonce,
      roots,
    )
    sensitiveValues = runtimeSensitiveValues(environments.sensitiveController)
    const python = environment.PYTHON || 'python'
    const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')
    const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js')

    databaseStarted = true
    await runOwnedCommand(
      python,
      [
        '-m',
        'backend.scripts.prepare_product_shell_browser_db',
        '--database',
        databaseName,
      ],
      childOptions(repositoryRoot, environments.prepare),
      {
        label: 'database preparation',
        sensitiveValues,
        timeoutMs: deadlines.commandMs,
      },
    )
    await runOwnedCommand(
      python,
      [
        '-m',
        'backend.scripts.seed_writer_assets',
        '--execute',
        '--database',
        databaseName,
        '--confirm-seed',
        databaseName,
      ],
      childOptions(repositoryRoot, environments.backend),
      {
        label: 'approved asset seed',
        sensitiveValues,
        timeoutMs: deadlines.commandMs,
      },
    )
    await runOwnedCommand(
      python,
      ['-c', FIXTURE_SOURCE],
      childOptions(repositoryRoot, environments.backend),
      {
        label: 'synthetic fixture seed',
        sensitiveValues,
        timeoutMs: deadlines.commandMs,
      },
    )

    await release(backendReservation)
    const backend = startOwnedServer(
      python,
      ['-c', BACKEND_SOURCE, String(backendReservation.port)],
      childOptions(repositoryRoot, environments.backend),
      'backend',
      sensitiveValues,
    )
    servers.push(backend)
    await waitForServer(
      backend,
      `${backendUrl}/api/health`,
      nonce,
      deadlines.healthMs,
    )

    await release(viteReservation)
    const vite = startOwnedServer(
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
      'vite',
      sensitiveValues,
    )
    servers.push(vite)
    await waitForServer(
      vite,
      `${viteUrl}/__m2-browser-owner`,
      nonce,
      deadlines.healthMs,
    )

    backend.accessObserver = createDelete204AccessObserver(backend.child)
    await runOwnedCommand(
      process.execPath,
      [
        playwrightCli,
        'test',
        spec,
        '--config',
        'playwright.phase2a.config.ts',
      ],
      childOptions(frontendRoot, environments.browser),
      {
        label: 'Phase 2A browser test',
        sensitiveValues,
        timeoutMs: deadlines.browserMs,
      },
    )
  } catch (error) {
    errors.push(error)
  } finally {
    for (const server of [...servers].reverse()) {
      try {
        await stopOwnedServer(server, sensitiveValues, deadlines.stopMs)
      } catch (error) {
        errors.push(error)
      }
    }
    for (const reservation of reservations) {
      try {
        await release(reservation)
      } catch (error) {
        errors.push(error)
      }
    }
    if (databaseStarted) {
      try {
        await runOwnedCommand(
          environment.PYTHON || 'python',
          [
            '-m',
            'backend.scripts.prepare_product_shell_browser_db',
            '--database',
            databaseName,
            '--drop',
          ],
          childOptions(repositoryRoot, environments.prepare),
          {
            label: 'database cleanup',
            sensitiveValues,
            timeoutMs: deadlines.commandMs,
          },
        )
      } catch (error) {
        errors.push(error)
      }
    }
    if (ownedRoot) {
      try {
        assertOwnedRoot(ownedRoot)
        rmSync(ownedRoot, { recursive: true })
      } catch (error) {
        errors.push(error)
      }
    }
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(errors, 'Phase 2A body and cleanup failed')
  }
}


export async function runPhase2A({
  specs = FORMAL_SPECS,
  environment = process.env,
  databaseNameFactory = createDatabaseName,
  ownedRootFactory = createOwnedRoot,
  portReservationFactory = reserveLocalPort,
  deadlines = {},
} = {}) {
  validateTestEnvironment(environment)
  const formalSpecs = validateSpecs(specs)
  const normalizedDeadlines = { ...DEFAULT_DEADLINES, ...deadlines }
  for (const [name, value] of Object.entries(normalizedDeadlines)) {
    if (!Number.isFinite(value) || value <= 0) {
      throw new TypeError(`${name} deadline must be a positive finite number`)
    }
  }
  for (const spec of formalSpecs) {
    await runOneSpec({
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


const isMain = process.argv[1]
  && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isMain) {
  let specs
  try {
    specs = resolveCommandLineSpecs(process.argv.slice(2))
  } catch {
    console.error('Phase 2A browser runner does not accept spec paths.')
    process.exitCode = 2
  }
  if (specs) {
    runPhase2A({ specs }).then(
      status => { process.exitCode = status },
      () => {
        console.error('Phase 2A browser runner failed.')
        process.exitCode = 1
      },
    )
  }
}
