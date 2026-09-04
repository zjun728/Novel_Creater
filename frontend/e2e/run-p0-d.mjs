import { randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  BASE_ENV_ALLOWLIST,
  assertDatabaseName,
  createDatabaseName,
  createOwnedRoot,
  removeOwnedRoot,
  reserveLocalPort,
  runBoundedOwnedCommand,
  runPhase2BLifecycle,
  startOwnedServer,
  stopOwnedServer,
  validateTestEnvironment,
  waitForOwnedServer,
} from './support/product-runner.mjs'
import { runtimeSensitiveValues } from './runtime-observer.mjs'

export const FORMAL_SPECS = Object.freeze(['e2e/p0-d-creative-foundation.spec.ts'])

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const ROOT_PREFIX = 'novel-creator-p0d-'
const PROJECT_ID = 'd0000000-0000-4000-8000-000000000201'
const PROVIDER_SECRET = 'p0d-loopback-provider-secret-do-not-print'
const DEFAULT_DEADLINES = Object.freeze({ commandMs: 120_000, healthMs: 45_000, browserMs: 300_000, stopMs: 8_000 })

const ASSET_SEED_SOURCE = String.raw`
import asyncio, os
from backend.config import clear_runtime_configuration, install_runtime_configuration, load_runtime_configuration
from backend.scripts.seed_writer_assets import run_cli
async def main():
  database=os.environ['MYSQL_DB']
  await run_cli(['--execute','--database',database,'--confirm-seed',database])
snapshot=load_runtime_configuration(); install_runtime_configuration(snapshot)
try: asyncio.run(main())
finally: clear_runtime_configuration(snapshot)
`

const FIXTURE_SOURCE = String.raw`
import os
import asyncio, json, time
from backend.config import clear_runtime_configuration, install_runtime_configuration, load_runtime_configuration
from backend.database import close_pool, transaction
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import SeedPayload
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.projects import ProjectRepository
from backend.services.model_bindings import ModelBindingService
from backend.services.project_lifecycle import CreateProject, ProjectLifecycleService

PROJECT_ID = os.environ['BROWSER_PROJECT_ID']
PROVIDER_ID = 'd0000000-0000-4000-8000-000000000202'

def payload(title, hook, market):
    return SeedPayload.model_validate({
      'title': title, 'genre': '东方玄幻',
      'targetAudience': '偏爱建设流、群像成长与规则悬疑的男频长篇读者',
      'logline': '守典人沈砚从一座被舆图抹去的县城起步，以公开规则重建失序山河。',
      'protagonist': '谨慎克制、相信证据但必须学会承担公共代价的守典人沈砚',
      'desire': '保住故乡、找回失踪师父，并让普通人拥有可依赖的秩序',
      'coreConflict': '每次借残典修复一层秩序，都会暴露沈砚并惊动更高层的既得势力',
      'worldPressure': '王朝崩解、诡异复苏和地方豪强同时挤压基层生存空间',
      'openingHook': hook,
      'differentiation': '把基层制度建设写成可见行动、人物选择和玄幻成长，而非设定说明',
      'storyPromise': '每卷解决一层秩序危机，同时让人物为扩张后的责任支付更高代价',
      'longFormPotential': '县、州、国、天下四级扩张，二十四卷与七百二十章都有独立矛盾及回收点',
      'marketBasis': market,
    }, strict=True)

async def main():
    now = int(time.time() * 1000)
    async with transaction() as session:
        await session.execute("""INSERT INTO provider_profiles
          (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,stream,
           max_context_tokens,max_output_tokens,temperature,top_p,supports_json,
           supports_streaming,notes,thinking,lifecycle_status,revision,deleted_at,created_at,updated_at)
          VALUES (%s,'P0-D Loopback Provider','openai-compatible','p0d-json',%s,%s,1,0,0,
                  128000,8192,0.7,0.95,1,0,'runner-owned',NULL,'active',1,NULL,%s,%s)""",
          (PROVIDER_ID, os.environ['P0D_PROVIDER_URL'], os.environ['P0D_PROVIDER_SECRET'], now, now))
        await session.execute("UPDATE application_settings SET fallback_provider_id=%s,revision=revision+1,updated_at=%s WHERE singleton_id=1", (PROVIDER_ID, now))
    model_bindings = ModelBindingService(ModelBindingRepository(), transaction_factory=transaction)
    projects = ProjectLifecycleService(ProjectRepository(), transaction, model_binding_service=model_bindings)
    await projects.create(CreateProject(id=PROJECT_ID, title='P0-D 创作地基验收', genre='东方玄幻', description='确定性作者流程夹具', target_words=2100000, target_chapters=630))
    values = (
      payload('山河夜巡', '巡夜人发现城门影子比城墙先一步坍塌。', '合成榜单显示巡夜悬疑具有稳定读者。'),
      payload('万民旧契', '全城百姓醒来后都忘记了同一条律令。', '合成榜单显示规则悬疑与群像题材交叉活跃。'),
      payload('典镇山河', '县城一夜从王朝舆图上消失，只有沈砚手中的残典仍记得它。', '合成公开榜单显示建设流与规则悬疑均有稳定读者。'),
    )
    async with transaction() as session:
      for index, seed in enumerate(values, 1):
        seed_id = f'd0000000-0000-4000-8000-{210 + index:012d}'
        revision_id = f'd0000000-0000-4000-8000-{220 + index:012d}'
        digest = canonical_hash(seed)
        document = canonical_json(seed)
        await session.execute("INSERT INTO creative_seeds (id,project_id,status,created_at,updated_at) VALUES (%s,%s,'candidate',%s,%s)", (seed_id,PROJECT_ID,now,now))
        await session.execute("""INSERT INTO creative_seed_revisions
          (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
          VALUES (%s,%s,%s,1,%s,%s,%s)""", (revision_id,PROJECT_ID,seed_id,document,digest,now))
        await session.execute("""INSERT INTO creative_seed_heads
          (seed_id,revision_id,revision,content_hash,updated_at) VALUES (%s,%s,1,%s,%s)""", (seed_id,revision_id,digest,now))

async def program():
  try: await main()
  finally: await close_pool()
snapshot=load_runtime_configuration(); install_runtime_configuration(snapshot)
try: asyncio.run(program())
finally: clear_runtime_configuration(snapshot)
`

const PROVIDER_SOURCE = String.raw`
import http from 'node:http'
import { appendFileSync } from 'node:fs'
const port = Number(process.env.P0D_PROVIDER_PORT)
const nonce = process.env.P0D_PROVIDER_NONCE
const counter = process.env.P0D_PROVIDER_COUNTER
const secret = process.env.P0D_PROVIDER_SECRET

const engines = [
 {name:'山河重建',storyPromise:'每卷修复一层公共秩序，同时揭开残典来源。',protagonistDesire:'守住故乡并找回师父。',sustainedPressure:'每次改革都会触发更高层反扑。',growthDirection:'从独自校勘成长为公开承担责任的治理者。',conflictLoop:'发现失序、核验证据、建立规则、承受反扑。',ensembleRoles:[{role:'县吏陆青禾',purpose:'把制度变化落实到普通人的代价。'}],advantageAndCost:'残典能指出规则裂缝，但每次使用都会暴露持有者。',satisfactionSources:['秩序重建','证据反转'],longFormVariation:['县州国天下四级扩张','不同群体对秩序的竞争'],endingAnchor:'天下建立可公开校验的新典制。',risks:['避免制度说明挤压人物行动。'],differentiation:'制度建设本身构成玄幻升级。'},
 {name:'旧典追凶',storyPromise:'沿被篡改的地方典籍追查王朝失序源头。',protagonistDesire:'证明师父没有背叛守典司。',sustainedPressure:'每找到一页真相便失去一处庇护。',growthDirection:'从求证个人清白走向保存公共记忆。',conflictLoop:'寻页、辨伪、救人、公开。',ensembleRoles:[{role:'游医',purpose:'见证被规则遗漏的人。'}],advantageAndCost:'辨伪能力可靠但会留下踪迹。',satisfactionSources:['线索闭环','身份反转'],longFormVariation:['地方悬案','中央旧档'],endingAnchor:'失落档案被公开保存。',risks:['避免重复查档。'],differentiation:'真相调查直接改变现实规则。'},
 {name:'百城立约',storyPromise:'联合百城建立互相校验的生存契约。',protagonistDesire:'让故乡不再依赖某位强者。',sustainedPressure:'联盟扩大时利益冲突同步扩大。',growthDirection:'从守城者成长为制度协调者。',conflictLoop:'结盟、试行、背叛、修约。',ensembleRoles:[{role:'商队首领',purpose:'衡量规则的跨城成本。'}],advantageAndCost:'联盟提供资源也放大责任。',satisfactionSources:['联盟博弈','群像成长'],longFormVariation:['城市生态','势力重组'],endingAnchor:'百城保留差异并形成共同底线。',risks:['控制会议场景比例。'],differentiation:'联盟规则随冲突持续演化。'},
]
const item=(id,text)=>({id,text})
const bible={
 premiseAndPromise:'读者将跟随沈砚看见一座座失序城池被具体行动重新连接，并见证每次胜利如何带来更重的公共责任。',
 worldRules:[item('rule-public','任何借残典改变的规则都必须公开记录，否则会转化为新的诡异缺口。')],
 powerOrProgressionSystem:'沈砚通过校勘、试行和公众见证修复典制；成长不是单纯战力，而是能承担更大范围规则后果的能力。',
 protagonist:'沈砚谨慎克制，擅长核验证据，初期只想保住故乡，最终必须学会把权力交给可被监督的共同制度。',
 coreCast:[item('cast-lu','陆青禾负责把抽象规则落到民生现场，她既是同盟也是最严格的质疑者。')],
 factions:[item('faction-office','守典司掌握旧档与合法性，却因维护封闭权威而成为改革阻力。')],
 longTermConflicts:[item('conflict-scale','秩序扩张越快，地方自主与统一规则之间的冲突越尖锐。')],
 relationshipDynamics:[item('relation-trust','沈砚与陆青禾的信任建立在公开分歧和共同承担后果之上。')],
 toneAndNarrativeBoundaries:'叙事克制、具体、以行动和选择展示设定；不靠无代价升级解决矛盾，不用旁白替代人物冲突。',
 continuityGuardrails:[item('guard-cost','每次残典介入必须留下可追踪代价，已经公开的规则不能无解释失效。')],
 openDesignQuestions:[item('question-master','师父为何主动留下残缺而非完整典籍，留待中后期逐层回答。')],
}
function send(res,status,value){res.writeHead(status,{'content-type':'application/json','connection':'close'});res.end(JSON.stringify(value))}
async function body(req){const chunks=[];for await(const chunk of req)chunks.push(chunk);return JSON.parse(Buffer.concat(chunks).toString('utf8'))}
function classify(messages){
 const [system,user]=messages||[]
 if(system?.content==='故事具体、人物有欲望和代价、冲突能够长期变化。只返回符合 outputContract 的 json 对象。') return ['story-engine',null]
 try{const instruction=JSON.parse(system.content);const evidence=JSON.parse(user.content)
   if(instruction.task==='Rank only the supplied eligible asset and corpus candidates.') return ['asset-ranking',evidence]
   if(instruction.task==='Propose one complete creation Bible') return ['bible-'+instruction.proposalScope,evidence]
 }catch{}
 return [null,null]
}
function output(kind,evidence){
 if(kind==='story-engine') return {options:engines}
 if(kind==='asset-ranking'){
   const candidates=(evidence.assetCandidates||[]).filter(value=>value.assetRevisionId)
   const styles=candidates.filter(value=>value.type==='style').slice(0,3)
   const chosen=styles.length?styles:(candidates[0]?[candidates[0]]:[])
   return {assetRecommendations:chosen.map(value=>({assetRevisionId:value.assetRevisionId,reason:'与当前故事发动机的长期压力相符。',confidence:0.91})),corpusRecommendations:[]}
 }
 if(kind==='bible-whole') return bible
 if(kind==='bible-premise') return {...evidence.currentBible,premiseAndPromise:'秩序每扩张一级，沈砚都必须公开承担新的制度代价。'}
 return null
}
http.createServer(async(req,res)=>{
 if(req.method==='GET'&&req.url==='/health') return send(res,200,{browserRunNonce:nonce})
 if(req.method!=='POST'||req.url!=='/v1/chat/completions') return send(res,404,{error:{code:'not_found'}})
 if(req.headers.authorization!=='Bearer '+secret) return send(res,404,{error:{code:'not_found'}})
 try{const request=await body(req);const [kind,evidence]=classify(request.messages);const result=output(kind,evidence)
   if(!kind||!result){appendFileSync(counter,'unexpected\n');return send(res,422,{error:{code:'unsupported_fixture_request'}})}
   appendFileSync(counter,kind+'\n');return send(res,200,{choices:[{message:{role:'assistant',content:JSON.stringify(result)}}]})
 }catch{return send(res,400,{error:{code:'invalid_request'}})}
}).listen(port,'127.0.0.1')
`

const BACKEND_SOURCE = String.raw`
import os, sys
from urllib.parse import urlsplit
import httpx, uvicorn
base=urlsplit(os.environ['P0D_PROVIDER_URL'])
allowed=('http','127.0.0.1',base.port,'/v1/chat/completions')
ledger=os.environ['P0D_OUTBOUND_LEDGER']
Original=httpx.AsyncClient
class Guarded(Original):
 async def send(self,request,*args,**kwargs):
  parsed=urlsplit(str(request.url)); target=(parsed.scheme,parsed.hostname,parsed.port,parsed.path)
  if target!=allowed or parsed.query or parsed.fragment or parsed.username or parsed.password:
   descriptor=os.open(ledger,os.O_WRONLY|os.O_APPEND)
   try: os.write(descriptor,b'forbidden-outbound\\n')
   finally: os.close(descriptor)
   raise RuntimeError('forbidden test outbound')
  return await super().send(request,*args,**kwargs)
httpx.AsyncClient=Guarded
from backend.main import app
uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[1]),log_config=None,access_log=False)
`

const VERIFY_SOURCE = String.raw`
import asyncio, os
from pathlib import Path
from backend.config import clear_runtime_configuration, install_runtime_configuration, load_runtime_configuration
from backend.database import close_pool, connection
async def main():
 expected=os.environ['BROWSER_TEST_DATABASE']
 async with connection() as session:
  current=await session.fetchone('SELECT DATABASE() database_name')
  if current!={'database_name':expected}: raise SystemExit(20)
  project=await session.fetchone('SELECT target_words,target_chapters FROM projects WHERE id=%s',(os.environ['BROWSER_PROJECT_ID'],))
  if project!={'target_words':2400000,'target_chapters':720}: raise SystemExit(21)
  facts=await session.fetchone("""SELECT
   (SELECT COUNT(*) FROM creative_seeds WHERE project_id=%s) seeds,
   (SELECT COUNT(*) FROM creative_seed_revisions WHERE project_id=%s) seed_revisions,
   (SELECT COUNT(*) FROM project_selected_seeds WHERE project_id=%s) selected,
   (SELECT COUNT(*) FROM story_engine_batches WHERE project_id=%s AND source_type='provider' AND status='succeeded') engine_batches,
   (SELECT COUNT(*) FROM story_engine_options WHERE project_id=%s) engine_options,
   (SELECT COUNT(*) FROM asset_recommendation_attempts WHERE project_id=%s AND status='succeeded') recommendation_attempts,
   (SELECT COUNT(*) FROM project_contract_drafts WHERE project_id=%s) contract_drafts,
   (SELECT COUNT(*) FROM creation_contracts WHERE project_id=%s) contracts,
   (SELECT COUNT(*) FROM style_contracts WHERE project_id=%s) styles,
   (SELECT revision FROM project_contract_heads WHERE project_id=%s) contract_revision,
   (SELECT COUNT(*) FROM bible_generation_attempts WHERE project_id=%s AND status='succeeded') bible_attempts,
   (SELECT COUNT(*) FROM project_bible_drafts WHERE project_id=%s AND active_slot IS NULL AND draft_version=2) closed_bible_drafts,
   (SELECT COUNT(*) FROM creation_bible_revisions WHERE project_id=%s) bibles,
   (SELECT revision FROM project_bible_heads WHERE project_id=%s) bible_revision,
   (SELECT COUNT(*) FROM bible_confirmation_requests WHERE project_id=%s AND status='succeeded') bible_confirms""",tuple([os.environ['BROWSER_PROJECT_ID']]*15))
 expected_facts={'seeds':3,'seed_revisions':4,'selected':1,'engine_batches':1,'engine_options':3,'recommendation_attempts':2,'contract_drafts':0,'contracts':1,'styles':1,'contract_revision':1,'bible_attempts':2,'closed_bible_drafts':1,'bibles':1,'bible_revision':1,'bible_confirms':1}
 if facts!=expected_facts: raise SystemExit(22)
 counter=Path(os.environ['P0D_PROVIDER_COUNTER']).read_text(encoding='utf-8').splitlines()
 if counter!=['story-engine','asset-ranking','asset-ranking','bible-whole','bible-premise']: raise SystemExit(23)
 if Path(os.environ['P0D_OUTBOUND_LEDGER']).read_text(encoding='utf-8'): raise SystemExit(24)
async def program():
 try: await main()
 finally: await close_pool()
snapshot=load_runtime_configuration(); install_runtime_configuration(snapshot)
try: asyncio.run(program())
finally: clear_runtime_configuration(snapshot)
`

function normalized(value) {
  const resolved = path.resolve(value)
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}
function allowed(environment) {
  return Object.fromEntries(BASE_ENV_ALLOWLIST.filter(key => Object.hasOwn(environment, key)).map(key => [key, environment[key]]))
}
function childOptions(cwd, env) { return { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] } }

function failureLocation(reportPath) {
  try {
    const report = JSON.parse(readFileSync(reportPath, 'utf8'))
    const pending = [...(report.suites || [])]
    while (pending.length) {
      const suite = pending.shift(); pending.push(...(suite.suites || []))
      for (const spec of suite.specs || []) for (const test of spec.tests || []) {
        const failed = (test.results || []).find(result => result.status !== 'passed')
        if (failed) {
          const frames = [...String(failed.error?.stack || '').matchAll(/p0-d-creative-foundation\.spec\.ts:(\d+):\d+/gu)].map(match => match[1])
          return frames.length ? [...new Set(frames)].map(line => `p0-d-creative-foundation.spec.ts:${line}`).join(' -> ') : `p0-d-creative-foundation.spec.ts:${failed.error?.location?.line || spec.line || 0}`
        }
      }
    }
  } catch {}
  return 'p0-d-creative-foundation.spec.ts:0'
}

function failureSummary(reportPath) {
  try {
    const report = JSON.parse(readFileSync(reportPath, 'utf8'))
    const pending = [report]
    while (pending.length) {
      const value = pending.shift()
      if (!value || typeof value !== 'object') continue
      if (value.error?.message) return String(value.error.message).replaceAll(/https?:\/\/[^\s]+/gu, '[loopback-url]').slice(0, 500)
      pending.push(...Object.values(value).filter(item => item && typeof item === 'object'))
    }
  } catch {}
  return 'browser assertion failed'
}

async function runOne({ environment, deadlines, dependencies = {} }) {
  const createRoot = dependencies.createOwnedRoot || createOwnedRoot
  const runCommand = dependencies.runBoundedOwnedCommand || runBoundedOwnedCommand
  const base = allowed(environment)
  let environments = {
    prepare: {
      ...base,
      TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST,
      TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
      TEST_MYSQL_USER: environment.TEST_MYSQL_USER,
      TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    },
  }
  let sensitiveValues = []
  await runPhase2BLifecycle({
    async body(lifecycle) {
      const database = createDatabaseName(); assertDatabaseName(database); lifecycle.setDatabase(database)
      const root = lifecycle.setRoot(createRoot(ROOT_PREFIX)); const files = path.join(root, 'files'); mkdirSync(files)
      const providerPath = path.join(files, 'provider.mjs'); const fixturePath = path.join(files, 'fixture.py'); const verifyPath = path.join(files, 'verify.py'); const counterPath = path.join(files, 'provider.log'); const ledgerPath = path.join(files, 'outbound.log'); const reportPath = path.join(root, 'playwright-report.json')
      writeFileSync(providerPath, PROVIDER_SOURCE, { encoding: 'utf8', flag: 'wx' }); writeFileSync(fixturePath, FIXTURE_SOURCE, { encoding: 'utf8', flag: 'wx' }); writeFileSync(verifyPath, VERIFY_SOURCE, { encoding: 'utf8', flag: 'wx' }); writeFileSync(counterPath, '', { encoding: 'utf8', flag: 'wx' }); writeFileSync(ledgerPath, '', { encoding: 'utf8', flag: 'wx' })
      const providerPort = lifecycle.registerReservation(await reserveLocalPort()); const backendPort = lifecycle.registerReservation(await reserveLocalPort()); const vitePort = lifecycle.registerReservation(await reserveLocalPort())
      const nonce = randomUUID(); const providerUrl = `http://127.0.0.1:${providerPort.port}/v1`; const backendUrl = `http://127.0.0.1:${backendPort.port}`; const viteUrl = `http://127.0.0.1:${vitePort.port}`
      const mysql = { MYSQL_HOST: environment.TEST_MYSQL_HOST, MYSQL_PORT: environment.TEST_MYSQL_PORT, MYSQL_USER: environment.TEST_MYSQL_USER, MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD, MYSQL_DB: database }
      environments = {
        prepare: { ...base, TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST, TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT, TEST_MYSQL_USER: environment.TEST_MYSQL_USER, TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD },
        provider: { ...base, P0D_PROVIDER_PORT: String(providerPort.port), P0D_PROVIDER_NONCE: nonce, P0D_PROVIDER_COUNTER: counterPath, P0D_PROVIDER_SECRET: PROVIDER_SECRET },
        backend: { ...base, ...mysql, M2_BROWSER_RUN_NONCE: nonce, MARKET_SCHEDULER_ENABLED: 'false', P0D_PROVIDER_URL: providerUrl, P0D_PROVIDER_SECRET: PROVIDER_SECRET, P0D_PROVIDER_COUNTER: counterPath, P0D_OUTBOUND_LEDGER: ledgerPath, BROWSER_PROJECT_ID: PROJECT_ID, BROWSER_TEST_DATABASE: database },
        vite: { ...base, M2_BROWSER_RUN_NONCE: nonce, VITE_API_BASE_URL: `${backendUrl}/api` },
        browser: { ...base, PLAYWRIGHT_BASE_URL: viteUrl, BROWSER_VITE_ORIGIN: viteUrl, BROWSER_BACKEND_ORIGIN: backendUrl, BROWSER_PROJECT_ID: PROJECT_ID, BROWSER_SECRET_SENTINEL: PROVIDER_SECRET, BROWSER_OWNED_ROOT: root, BROWSER_ARTIFACT_ROOT: path.join(root, 'phase2b-test-results'), PLAYWRIGHT_JSON_OUTPUT_NAME: reportPath },
      }
      sensitiveValues = runtimeSensitiveValues({ ...mysql, BROWSER_TEST_DATABASE: database, BROWSER_SECRET_SENTINEL: PROVIDER_SECRET })
      const python = environment.PYTHON || 'python'; const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js'); const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')
      await runCommand(python, ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', database], childOptions(repositoryRoot, environments.prepare), { label: 'P0-D database preparation', sensitiveValues, timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs })
      await runCommand(python, ['-c', ASSET_SEED_SOURCE], childOptions(repositoryRoot, environments.backend), { label: 'P0-D asset seed', sensitiveValues, timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs })
      await lifecycle.releaseReservation(providerPort); const provider = lifecycle.registerServer(startOwnedServer(process.execPath, [providerPath], childOptions(repositoryRoot, environments.provider), { label: 'P0-D fake provider', sensitiveValues })); await waitForOwnedServer(provider, `http://127.0.0.1:${providerPort.port}/health`, { expectedNonce: nonce, timeoutMs: deadlines.healthMs })
      await runCommand(python, ['-c', "import runpy,sys;runpy.run_path(sys.argv[1],run_name='__main__')", fixturePath], childOptions(repositoryRoot, environments.backend), { label: 'P0-D fixture', sensitiveValues, timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs, states: [provider] })
      await lifecycle.releaseReservation(backendPort); const backend = lifecycle.registerServer(startOwnedServer(python, ['-c', BACKEND_SOURCE, String(backendPort.port)], childOptions(repositoryRoot, environments.backend), { label: 'P0-D backend', sensitiveValues })); await waitForOwnedServer(backend, `${backendUrl}/api/health`, { expectedNonce: nonce, timeoutMs: deadlines.healthMs, states: [provider, backend] })
      await lifecycle.releaseReservation(vitePort); const vite = lifecycle.registerServer(startOwnedServer(process.execPath, [viteCli, '--host', '127.0.0.1', '--port', String(vitePort.port), '--strictPort'], childOptions(frontendRoot, environments.vite), { label: 'P0-D Vite', sensitiveValues })); await waitForOwnedServer(vite, `${viteUrl}/__m2-browser-owner`, { expectedNonce: nonce, timeoutMs: deadlines.healthMs, states: [provider, backend, vite] })
      try {
        await runCommand(process.execPath, [playwrightCli, 'test', FORMAL_SPECS[0], '--config', 'playwright.phase2b.config.ts', '--reporter=json'], childOptions(frontendRoot, environments.browser), { label: 'P0-D browser flow', sensitiveValues, timeoutMs: deadlines.browserMs, stopTimeoutMs: deadlines.stopMs, states: [provider, backend, vite] })
      } catch { throw new Error(`P0-D browser flow failed at ${failureLocation(reportPath)}: ${failureSummary(reportPath)}`) }
      await runCommand(python, ['-c', "import runpy,sys;runpy.run_path(sys.argv[1],run_name='__main__')", verifyPath], childOptions(repositoryRoot, environments.backend), { label: 'P0-D evidence', sensitiveValues, timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs, states: [provider, backend, vite] })
      console.log('p0d_browser_database=verified')
    },
    stopServer: server => stopOwnedServer(server, { sensitiveValues, timeoutMs: deadlines.stopMs }),
    releaseReservation: reservation => reservation.release(),
    dropDatabase: database => runCommand(environment.PYTHON || 'python', ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', database, '--drop'], childOptions(repositoryRoot, environments.prepare), { label: 'P0-D database cleanup', sensitiveValues, timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs }),
    removeRoot: root => removeOwnedRoot(root, ROOT_PREFIX),
  })
  console.log('p0d_browser_cleanup=verified')
}

export async function runP0D({ environment = process.env, deadlines = {}, dependencies = {} } = {}) {
  validateTestEnvironment(environment)
  await runOne({ environment, deadlines: { ...DEFAULT_DEADLINES, ...deadlines }, dependencies })
  return 0
}

if (normalized(process.argv[1] || '') === normalized(fileURLToPath(import.meta.url))) {
  if (process.argv.length !== 2) { console.error('P0-D runner accepts no spec arguments.'); process.exitCode = 2 }
  else runP0D().then(code => { process.exitCode = code }, () => { console.error('P0-D browser runner failed.'); process.exitCode = 1 })
}
