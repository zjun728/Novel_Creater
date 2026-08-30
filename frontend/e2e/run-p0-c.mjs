import { randomUUID } from 'node:crypto'
import { lstatSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  assertDatabaseName, BASE_ENV_ALLOWLIST, createDatabaseName, reserveLocalPort,
  runBoundedOwnedCommand, runPhase2BLifecycle, startOwnedServer, stopOwnedServer,
  validateTestEnvironment, waitForOwnedServer,
} from './support/product-runner.mjs'
import { runtimeSensitiveValues } from './runtime-observer.mjs'

export const FORMAL_SPECS = Object.freeze(['e2e/p0-c-topic-center.spec.ts'])
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const ROOT_PREFIX = 'novel-creator-p0c-'
const DEFAULT_DEADLINES = Object.freeze({ commandMs: 120_000, healthMs: 45_000, browserMs: 240_000, stopMs: 8_000 })

const PROVIDER_SOURCE = String.raw`
import http from 'node:http'
import { appendFileSync } from 'node:fs'
const port = Number(process.env.P0C_PROVIDER_PORT)
const counter = process.env.P0C_PROVIDER_COUNTER
const nonce = process.env.P0C_PROVIDER_NONCE
let calls = 0
const candidate = (title, promise) => ({
  title, genre:'东方玄幻', logline:'少年执掌残典，在诡异王朝重建一县秩序。',
  targetAudience:'偏爱建设流与成长升级的长篇读者', protagonist:'守典人沈砚',
  desire:'保住故乡并查清典籍真相', coreConflict:'每次借典改制都会惊动更高层势力',
  worldPressure:'王朝崩解与诡异复苏同时逼近', openingHook:'县城一夜从舆图上消失',
  differentiation:'以基层制度建设推动玄幻升级', storyPromise:promise,
  longFormPotential:'县、州、国、天下四级扩张，可支撑二百万字以上',
  marketBasis:'合成公开榜单显示建设流与规则怪谈均有稳定读者',
})
const direction = {
  title:'基层秩序建设型东方玄幻', genreOpportunity:'建设流与规则怪谈的交叉机会',
  targetAudience:'男频长篇成长读者', readerPromise:'每一卷都解决一层秩序危机',
  differentiation:'制度建设本身就是力量成长', longFormPotential:'从县到天下逐级扩张',
  risks:'需要避免制度说明压过人物冲突', evidenceSummary:'基于本次附加的公开榜单快照',
}
http.createServer((request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    response.writeHead(200, {'content-type':'application/json'}); response.end(JSON.stringify({browserRunNonce:nonce})); return
  }
  if (request.method !== 'POST' || !request.url.endsWith('/chat/completions')) {
    response.writeHead(404); response.end(); return
  }
  let body = ''
  request.setEncoding('utf8'); request.on('data', chunk => { body += chunk })
  request.on('end', () => {
    JSON.parse(body); calls += 1; appendFileSync(counter, 'topic-call\n')
    const first = calls === 1
    const result = {
      reply: first ? '这个方向适合用秩序建设承载长篇升级。' : '第二版把人物代价与每卷承诺绑定得更紧。',
      directionSuggestions: first ? [direction] : [],
      candidateSuggestions: [candidate('典镇山河', first ? '逐级重建秩序并揭开残典真相' : '每次重建秩序都迫使主角承担更高政治代价')],
    }
    const envelope = { choices: [{ message: { content: JSON.stringify(result) } }] }
    response.writeHead(200, {'content-type':'application/json'}); response.end(JSON.stringify(envelope))
  })
}).listen(port, '127.0.0.1')
`

const FIXTURE_SOURCE = String.raw`
import asyncio, json, os, time
from backend.config import clear_runtime_configuration, install_runtime_configuration, load_runtime_configuration
from backend.database import close_pool, transaction
from backend.domain.json_contracts import canonical_hash
from backend.domain.market_sources import SourcePolicy

async def main():
    now = int(time.time() * 1000)
    provider_id = 'c1000000-0000-4000-8000-000000000001'
    async with transaction() as session:
        await session.execute(
            """INSERT INTO provider_profiles
               (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
                stream,max_context_tokens,max_output_tokens,temperature,top_p,
                supports_json,supports_streaming,notes,thinking,lifecycle_status,
                revision,deleted_at,created_at,updated_at)
               VALUES (%s,'P0C Local JSON','openai-compatible','p0c-json',%s,
                       'p0c-local-only',1,0,0,128000,8192,0.7,0.95,1,0,'',NULL,
                       'active',1,NULL,%s,%s)""",
            (provider_id, os.environ['P0C_PROVIDER_URL'], now, now),
        )
        await session.execute(
            """UPDATE application_settings SET fallback_provider_id=%s,
                   revision=revision+1,updated_at=%s WHERE singleton_id=1""",
            (provider_id, now),
        )
        source = await session.fetchone("SELECT id FROM market_sources WHERE stable_key='qidian.newsign'")
        policy = SourcePolicy(
            status='verified_public', checkedAt=now,
            evidenceURL='https://www.qidian.com/rank/newsign/', evidenceHash='a' * 64,
            allowedOrigins=('https://www.qidian.com',), pathPrefixes=('/rank/newsign/',),
            requestIntervalSeconds=60, policyVersion='p0c-browser-v1', enabled=False,
        )
        policy_hash = canonical_hash(policy)
        revision_id = 'c1000000-0000-4000-8000-000000000002'
        await session.execute(
            """INSERT INTO market_source_policy_revisions
               (id,source_id,revision,policy_status,policy_version,checked_at,
                evidence_url,evidence_hash,allowed_origins_json,path_prefixes_json,
                enabled,interval_minutes,next_run_at,content_hash,created_at)
               VALUES (%s,%s,2,'verified_public',%s,%s,%s,%s,%s,%s,0,1,NULL,%s,%s)""",
            (revision_id,source['id'],policy.policy_version,now,policy.evidence_url,
             policy.evidence_hash,json.dumps(list(policy.allowed_origins)),
             json.dumps(list(policy.path_prefixes)),policy_hash,now),
        )
        await session.execute(
            """UPDATE market_source_policy_heads SET revision_id=%s,revision=2,
                   content_hash=%s,updated_at=%s WHERE source_id=%s""",
            (revision_id,policy_hash,now,source['id']),
        )

async def program():
    snapshot = load_runtime_configuration()
    install_runtime_configuration(snapshot)
    try:
        try: await main()
        finally: await close_pool()
    finally: clear_runtime_configuration(snapshot)
asyncio.run(program())
`

const BACKEND_SOURCE = String.raw`
import sys, uvicorn
from backend.database import connection, transaction
from backend.domain.market_sources import MarketSourceFailure
from backend.domain.routers.market_sources import get_market_source_service
from backend.gateways.market_sources.manual_snapshot import ManualSnapshotAdapter
from backend.main import app
from backend.repositories.market import MarketRepository
from backend.services.market_snapshots import MarketSnapshotService
from backend.services.market_sources import MarketSourceService
class FailingAdapter:
    adapter_version = 'p0c-local-failure-v1'
    async def fetch(self, **_values): raise MarketSourceFailure('MARKET_TRANSPORT_FAILED')
repository = MarketRepository()
snapshots = MarketSnapshotService(repository, transaction_factory=transaction,
    connection_factory=connection, adapters={'qidian_public_rank':FailingAdapter()},
    manual_adapter=ManualSnapshotAdapter())
service = MarketSourceService(repository, snapshots, connection_factory=connection,
    transaction_factory=transaction)
app.dependency_overrides[get_market_source_service] = lambda: service
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
`

const VERIFY_SOURCE = String.raw`
import asyncio, os
from pathlib import Path
from backend.config import clear_runtime_configuration, install_runtime_configuration, load_runtime_configuration
from backend.database import close_pool, connection
async def main():
    async with connection() as session:
        facts = await session.fetchone("""SELECT
          (SELECT COUNT(*) FROM topic_directions) directions,
          (SELECT COUNT(*) FROM topic_candidates) candidates,
          (SELECT COUNT(*) FROM topic_candidate_versions) versions,
          (SELECT COUNT(*) FROM topic_project_handoffs) handoffs,
          (SELECT COUNT(*) FROM projects p JOIN topic_project_handoffs h ON h.project_id=p.id) projects,
          (SELECT COUNT(*) FROM creative_seeds s JOIN topic_project_handoffs h ON h.project_id=s.project_id) seeds,
          (SELECT COUNT(*) FROM project_selected_seeds s JOIN topic_project_handoffs h ON h.project_id=s.project_id) selected,
          (SELECT COUNT(*) FROM market_snapshots) snapshots,
          (SELECT status FROM topic_candidates LIMIT 1) candidate_status""")
    expected = {'directions':1,'candidates':1,'versions':2,'handoffs':1,'projects':1,'seeds':1,'selected':1,'snapshots':1,'candidate_status':'archived'}
    for offset, key in enumerate(expected):
        if facts.get(key) != expected[key]:
            raise SystemExit(20 + offset)
    if Path(os.environ['P0C_PROVIDER_COUNTER']).read_text(encoding='utf-8').splitlines() != ['topic-call','topic-call']:
        raise SystemExit(29)
    print('p0c_browser_database=verified')
async def program():
    snapshot = load_runtime_configuration()
    install_runtime_configuration(snapshot)
    try:
        try: await main()
        finally: await close_pool()
    finally: clear_runtime_configuration(snapshot)
asyncio.run(program())
`

function normalized(value) { const resolved = path.resolve(value); return process.platform === 'win32' ? resolved.toLowerCase() : resolved }
function assertOwnedRoot(value) {
  const root = path.resolve(value); const stats = lstatSync(root)
  if (!stats.isDirectory() || stats.isSymbolicLink() || !path.basename(root).startsWith(ROOT_PREFIX)
    || normalized(path.dirname(realpathSync(root))) !== normalized(realpathSync(os.tmpdir()))) throw new Error('P0C root is not owned')
  return root
}
function createOwnedRoot() { return assertOwnedRoot(mkdtempSync(path.join(os.tmpdir(), ROOT_PREFIX))) }
function allowed(environment) { return Object.fromEntries(BASE_ENV_ALLOWLIST.filter(key => Object.hasOwn(environment, key)).map(key => [key, environment[key]])) }
function childOptions(cwd, env) { return { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] } }
function snapshot() {
  return { platform:'qidian',rankingName:'newsign',category:'male',capturedAt:Date.now(),sourceURL:'https://www.qidian.com/rank/newsign/',entries:[
    {rank:1,title:'山河典籍录',author:'合成作者',category:'东方玄幻',workURL:'https://www.qidian.com/book/900000001/',publicMetrics:{heat:100}},
  ] }
}

function browserFailureLocation(reportPath) {
  try {
    const report = JSON.parse(readFileSync(reportPath, 'utf8'))
    const pending = [...(report.suites || [])]
    while (pending.length) {
      const suite = pending.shift()
      pending.push(...(suite.suites || []))
      for (const spec of suite.specs || []) {
        const failedResult = (spec.tests || []).flatMap(test => test.results || [])
          .find(result => result.status !== 'passed')
        if (failedResult) {
          const stack = String(failedResult.error?.stack || '')
          const frames = [...stack.matchAll(/p0-c-topic-center\.spec\.ts:(\d+):\d+/gu)]
            .map(match => Number(match[1]))
            .filter(Number.isInteger)
          if (frames.length) {
            return [...new Set(frames)].map(line => `p0-c-topic-center.spec.ts:${line}`).join(' -> ')
          }
          const location = failedResult.error?.location || {}
          const file = path.basename(String(location.file || spec.file || FORMAL_SPECS[0]))
          const line = Number.isInteger(location.line) ? location.line
            : Number.isInteger(spec.line) ? spec.line : 0
          return `${file}:${line}`
        }
      }
    }
  } catch {}
  return 'unknown-spec:0'
}

async function runOne({ environment, deadlines }) {
  let environments; let sensitiveValues = []
  return runPhase2BLifecycle({
    async body(lifecycle) {
      const database = createDatabaseName(); assertDatabaseName(database); lifecycle.setDatabase(database)
      const root = lifecycle.setRoot(createOwnedRoot()); const files = path.join(root, 'files'); mkdirSync(files)
      const providerPath = path.join(files, 'provider.mjs'); const counterPath = path.join(files, 'provider.log'); const snapshotPath = path.join(files, 'qidian.json')
      writeFileSync(providerPath, PROVIDER_SOURCE, {encoding:'utf8',flag:'wx'}); writeFileSync(counterPath,'',{encoding:'utf8',flag:'wx'}); writeFileSync(snapshotPath,JSON.stringify(snapshot()),{encoding:'utf8',flag:'wx'})
      const providerPort = lifecycle.registerReservation(await reserveLocalPort()); const backendPort = lifecycle.registerReservation(await reserveLocalPort()); const vitePort = lifecycle.registerReservation(await reserveLocalPort())
      const nonce = randomUUID(); const providerUrl=`http://127.0.0.1:${providerPort.port}`; const backendUrl=`http://127.0.0.1:${backendPort.port}`; const viteUrl=`http://127.0.0.1:${vitePort.port}`
      const base=allowed(environment); const mysql={MYSQL_HOST:environment.TEST_MYSQL_HOST,MYSQL_PORT:environment.TEST_MYSQL_PORT,MYSQL_USER:environment.TEST_MYSQL_USER,MYSQL_PASSWORD:environment.TEST_MYSQL_PASSWORD,MYSQL_DB:database}
      const browserReportPath=path.join(root,'playwright-report.json')
      environments={
        prepare:{...base,TEST_MYSQL_HOST:environment.TEST_MYSQL_HOST,TEST_MYSQL_PORT:environment.TEST_MYSQL_PORT,TEST_MYSQL_USER:environment.TEST_MYSQL_USER,TEST_MYSQL_PASSWORD:environment.TEST_MYSQL_PASSWORD},
        provider:{...base,P0C_PROVIDER_PORT:String(providerPort.port),P0C_PROVIDER_COUNTER:counterPath,P0C_PROVIDER_NONCE:nonce},
        backend:{...base,...mysql,M2_BROWSER_RUN_NONCE:nonce,P0C_PROVIDER_URL:`${providerUrl}/v1`,P0C_PROVIDER_COUNTER:counterPath},
        vite:{...base,M2_BROWSER_RUN_NONCE:nonce,VITE_API_BASE_URL:`${backendUrl}/api`},
        browser:{...base,PLAYWRIGHT_BASE_URL:viteUrl,BROWSER_VITE_ORIGIN:viteUrl,BROWSER_BACKEND_ORIGIN:backendUrl,BROWSER_OWNED_ROOT:root,BROWSER_ARTIFACT_ROOT:path.join(root,'phase2b-test-results'),BROWSER_QIDIAN_SNAPSHOT_PATH:snapshotPath,PLAYWRIGHT_JSON_OUTPUT_FILE:browserReportPath},
      }
      sensitiveValues=runtimeSensitiveValues({...mysql,BROWSER_TEST_DATABASE:database})
      const python=environment.PYTHON||'python'; const viteCli=path.join(frontendRoot,'node_modules','vite','bin','vite.js'); const playwrightCli=path.join(frontendRoot,'node_modules','playwright','cli.js')
      await runBoundedOwnedCommand(python,['-m','backend.scripts.prepare_product_shell_browser_db','--database',database],childOptions(repositoryRoot,environments.prepare),{label:'P0C database preparation',sensitiveValues,timeoutMs:deadlines.commandMs,stopTimeoutMs:deadlines.stopMs})
      await runBoundedOwnedCommand(python,['-m','backend.scripts.seed_market_sources','--execute','--database',database,'--confirm-seed',database],childOptions(repositoryRoot,environments.backend),{label:'P0C source seed',sensitiveValues,timeoutMs:deadlines.commandMs,stopTimeoutMs:deadlines.stopMs})
      await lifecycle.releaseReservation(providerPort); const provider=lifecycle.registerServer(startOwnedServer(process.execPath,[providerPath],childOptions(repositoryRoot,environments.provider),{label:'P0C fake provider',sensitiveValues})); await waitForOwnedServer(provider,`${providerUrl}/health`,{expectedNonce:nonce,timeoutMs:deadlines.healthMs})
      await runBoundedOwnedCommand(python,['-c',FIXTURE_SOURCE],childOptions(repositoryRoot,environments.backend),{label:'P0C fixture',sensitiveValues,timeoutMs:deadlines.commandMs,stopTimeoutMs:deadlines.stopMs,states:[provider]})
      await lifecycle.releaseReservation(backendPort); const backend=lifecycle.registerServer(startOwnedServer(python,['-c',BACKEND_SOURCE,String(backendPort.port)],childOptions(repositoryRoot,environments.backend),{label:'P0C backend',sensitiveValues})); await waitForOwnedServer(backend,`${backendUrl}/api/health`,{expectedNonce:nonce,timeoutMs:deadlines.healthMs,states:[provider,backend]})
      await lifecycle.releaseReservation(vitePort); const vite=lifecycle.registerServer(startOwnedServer(process.execPath,[viteCli,'--host','127.0.0.1','--port',String(vitePort.port),'--strictPort'],childOptions(frontendRoot,environments.vite),{label:'P0C Vite',sensitiveValues})); await waitForOwnedServer(vite,`${viteUrl}/__m2-browser-owner`,{expectedNonce:nonce,timeoutMs:deadlines.healthMs,states:[provider,backend,vite]})
      try {
        await runBoundedOwnedCommand(process.execPath,[playwrightCli,'test',FORMAL_SPECS[0],'--config','playwright.phase2b.config.ts','--reporter=json'],childOptions(frontendRoot,environments.browser),{label:'P0C browser flow',sensitiveValues,timeoutMs:deadlines.browserMs,stopTimeoutMs:deadlines.stopMs,states:[provider,backend,vite]})
      } catch {
        throw new Error(`P0C browser flow failed at ${browserFailureLocation(browserReportPath)}`)
      }
      await runBoundedOwnedCommand(python,['-c',VERIFY_SOURCE],childOptions(repositoryRoot,environments.backend),{label:'P0C evidence',sensitiveValues,timeoutMs:deadlines.commandMs,stopTimeoutMs:deadlines.stopMs,states:[provider,backend,vite]})
    },
    stopServer: server => stopOwnedServer(server,{sensitiveValues,timeoutMs:deadlines.stopMs}), releaseReservation: reservation => reservation.release(),
    dropDatabase: database => runBoundedOwnedCommand(environment.PYTHON||'python',['-m','backend.scripts.prepare_product_shell_browser_db','--database',database,'--drop'],childOptions(repositoryRoot,environments.prepare),{label:'P0C database cleanup',sensitiveValues,timeoutMs:deadlines.commandMs,stopTimeoutMs:deadlines.stopMs}),
    async removeRoot(root) { assertOwnedRoot(root); rmSync(root,{recursive:true}) },
  })
}

export async function runP0C({ environment=process.env, deadlines={} }={}) {
  validateTestEnvironment(environment); const values={...DEFAULT_DEADLINES,...deadlines}; await runOne({environment,deadlines:values}); return 0
}
if (normalized(process.argv[1]||'') === normalized(fileURLToPath(import.meta.url))) {
  if (process.argv.length !== 2) { console.error('P0C runner accepts no spec arguments.'); process.exitCode=2 }
  else runP0C().then(code=>{process.exitCode=code},()=>{console.error('P0C browser runner failed.');process.exitCode=1})
}
