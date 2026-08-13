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
import { fileURLToPath } from 'node:url'

import {
  assertDatabaseName,
  BASE_ENV_ALLOWLIST,
  createDatabaseName,
  reserveLocalPort,
  runBoundedOwnedCommand,
  runPhase2BLifecycle,
  startOwnedServer,
  stopOwnedServer,
  validateTestEnvironment,
  waitForOwnedServer,
} from './support/product-runner.mjs'
import { runtimeSensitiveValues } from './runtime-observer.mjs'


export const FORMAL_SPECS = Object.freeze([
  'e2e/phase2b-market-seeds.spec.ts',
])

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const OWNED_ROOT_PREFIX = 'novel-creator-phase2b-'
const PROJECT_ID = '2b000000-0000-4000-8000-000000000001'
const SECRET_SENTINEL = 'phase2b-browser-secret-must-not-leak'
const PRIVATE_PROVIDER_URL = 'https://phase2b-private-provider.invalid/v1'
const MODEL_SENTINEL = 'phase2b-private-model-must-not-leak'
const TRANSCRIPT_SENTINEL = 'phase2b-private-transcript-must-not-leak'
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

PROJECT_ID = "2b000000-0000-4000-8000-000000000001"
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
               VALUES (%s,'Phase 2B \u5e02\u573a\u4e0e\u79cd\u5b50\u9879\u76ee',
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
               VALUES (%s,'Phase 2B Hidden Provider','openai-compatible',%s,%s,%s,
                       1,0,0,128000,4096,0.700,0.950,1,1,'',NULL,'active',
                       1,NULL,%s,%s)""",
            (
                PROVIDER_ID,
                os.environ["BROWSER_MODEL_SENTINEL"],
                os.environ["BROWSER_PRIVATE_PROVIDER_URL"],
                os.environ["BROWSER_SECRET_SENTINEL"],
                now,
                now,
            ),
        )
        await session.execute(
            """INSERT INTO project_model_binding_revisions
               (id,project_id,revision,content_hash,source_project_id,created_at)
               VALUES (%s,%s,1,%s,NULL,%s)""",
            (BINDING_ID, PROJECT_ID, "b" * 64, now),
        )
        for task_key in ("market", "seed"):
            await session.execute(
                """INSERT INTO project_model_binding_items
                   (binding_revision_id,task_key,resolution_status,provider_id,
                    provider_name_snapshot,model_name_snapshot,item_hash)
                   VALUES (%s,%s,'bound',%s,'Phase 2B Hidden Provider',%s,%s)""",
                (
                    BINDING_ID,
                    task_key,
                    PROVIDER_ID,
                    os.environ["BROWSER_MODEL_SENTINEL"],
                    canonical_hash({"task": task_key}),
                ),
            )
        await session.execute(
            """INSERT INTO project_model_binding_heads
               (project_id,revision,binding_revision_id,content_hash,updated_at)
               VALUES (%s,1,%s,%s,%s)""",
            (PROJECT_ID, BINDING_ID, "b" * 64, now),
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
            policyVersion="phase2b-browser-verified-v1",
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
import copy
import json
import os
import re
from pathlib import Path
import sys
import time
import httpx
import uvicorn
from uvicorn.config import LOGGING_CONFIG

COUNTER_PATH = Path(os.environ["BROWSER_FAKE_COUNTER_PATH"])
PROJECT_ID = "2b000000-0000-4000-8000-000000000001"
DATABASE_PATTERN = re.compile(r"novel_creator_test_[a-f0-9]{32}\Z")

def record_counter(name):
    with COUNTER_PATH.open("a", encoding="utf-8") as ledger:
        ledger.write(name + "\n")

def assert_disposable_database_environment():
    database_name = os.environ.get("MYSQL_DB")
    expected_name = os.environ.get("BROWSER_TEST_DATABASE")
    if (
        database_name != expected_name
        or not isinstance(database_name, str)
        or DATABASE_PATTERN.fullmatch(database_name) is None
    ):
        raise RuntimeError("Phase 2B requires one exact disposable database")

class ForbiddenOutboundAsyncClient:
    def __init__(self, *_args, **_kwargs):
        record_counter("forbidden_outbound_httpx_calls")
        raise RuntimeError("unexpected outbound HTTP client")

assert_disposable_database_environment()
httpx.AsyncClient = ForbiddenOutboundAsyncClient

from backend.database import connection, transaction
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.market_sources import MarketSourceFailure
from backend.gateways.market_sources.manual_snapshot import ManualSnapshotAdapter
from backend.main import app
from backend.repositories.market import MarketRepository
from backend.repositories.seeds import SeedRepository
from backend.domain.routers.market_sources import (
    get_market_analysis_service,
    get_market_source_service,
)
from backend.domain.routers.seeds import (
    get_seed_generation_service,
    get_seed_service,
)
from backend.services.market_analysis import MarketAnalysisService
from backend.services.market_snapshots import MarketSnapshotService
from backend.services.market_sources import MarketSourceService
from backend.services.seed_generation import SeedGenerationService
from backend.services.seeds import SeedService

class FakeFailingQidianAdapter:
    adapter_version = "phase2b-failing-adapter-v1"

    async def fetch(self, **_values):
        record_counter("fake_market_adapter_calls")
        raise MarketSourceFailure("MARKET_TRANSPORT_FAILED")

repository = MarketRepository()
snapshot_service = MarketSnapshotService(
    repository,
    transaction_factory=transaction,
    connection_factory=connection,
    adapters={"qidian_public_rank": FakeFailingQidianAdapter()},
    manual_adapter=ManualSnapshotAdapter(),
)

market_source_service = MarketSourceService(
    repository,
    snapshot_service,
    connection_factory=connection,
    transaction_factory=transaction,
)

class FakeMarketAnalysisGateway:
    async def generate(self, *, messages, **_values):
        record_counter("fake_market_analysis_calls")
        facts = json.loads(messages[1]["content"])
        ids = [item["id"] for item in facts["snapshots"]]
        fact = {
            "text": "\u51bb\u7ed3\u699c\u5355\u663e\u793a\u7a7f\u8d8a\u4e0e\u5347\u7ea7\u9898\u6750\u4ecd\u6709\u660e\u786e\u4f9b\u7ed9\u3002",
            "snapshotIds": ids,
            "inference": False,
        }
        inference = {
            "text": "\u7a7f\u8d8a\u77e5\u8bc6\u5151\u73b0\u4e0e\u7fa4\u50cf\u4e89\u593a\u7ed3\u5408\u53ef\u80fd\u5f62\u6210\u5dee\u5f02\u5316\u3002",
            "snapshotIds": ids,
            "inference": True,
        }
        return json.dumps({
            "currentHeat": [fact],
            "growthDirections": [inference],
            "crowding": [fact],
            "opportunities": [inference],
            "uncertainties": [fact],
            "sourceCoverage": {
                "snapshotIds": ids,
                "summary": "\u8986\u76d6\u8d77\u70b9\u4e0e QQ \u9605\u8bfb\u4e24\u4efd\u72ec\u7acb\u51bb\u7ed3\u5feb\u7167\u3002",
            },
        }, ensure_ascii=False)

class FakeSeedGateway:
    async def generate(self, **_values):
        record_counter("fake_seed_gateway_calls")
        return "\u8ba9\u77e5\u8bc6\u4f18\u52bf\u5206\u4e09\u6b21\u5151\u73b0\uff0c\u6bcf\u6b21\u90fd\u8feb\u4f7f\u4e0d\u540c\u914d\u89d2\u4e89\u593a\u89e3\u91ca\u6743\u3002"

market_analysis_service = MarketAnalysisService(
    MarketRepository(),
    transaction_factory=transaction,
    connection_factory=connection,
    provider_gateway=FakeMarketAnalysisGateway(),
)
seed_generation_service = SeedGenerationService(
    SeedRepository(),
    transaction_factory=transaction,
    connection_factory=connection,
    provider_gateway=FakeSeedGateway(),
)

async def install_downstream_fixture(seed):
    if int(seed.selection_revision) != 1:
        return
    now = int(time.time() * 1000)
    creation_id = "2b000000-0000-4000-8000-000000000101"
    style_id = "2b000000-0000-4000-8000-000000000102"
    creation_content = {"fixture": "selection-1"}
    style_content = {"fixture": "selection-1-style"}
    async with transaction() as session:
        existing = await session.fetchone(
            "SELECT revision FROM project_contract_heads WHERE project_id=%s",
            (seed.project_id,),
        )
        if existing is not None:
            return
        binding = await session.fetchone(
            """SELECT binding_revision_id,content_hash
                 FROM project_model_binding_heads WHERE project_id=%s""",
            (seed.project_id,),
        )
        await session.execute(
            """INSERT INTO creation_contracts
               (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
                seed_hash,binding_revision_id,binding_hash,channel_profile_key,
                genre_profile_key,quality_charter_version,total_word_min,
                total_word_max,chapter_capacity_policy,reference_manifest_json,
                reference_manifest_hash,content_json,content_hash,confirmed_at)
               VALUES (%s,%s,1,1,%s,%s,%s,%s,%s,'qidian','historical-crossing',
                       'phase2b-v1',1500000,2000000,'rolling',%s,%s,%s,%s,%s)""",
            (
                creation_id,
                seed.project_id,
                seed.id,
                seed.revision_id,
                seed.content_hash,
                binding["binding_revision_id"],
                binding["content_hash"],
                canonical_json({}),
                canonical_hash({}),
                canonical_json(creation_content),
                canonical_hash(creation_content),
                now,
            ),
        )
        await session.execute(
            """INSERT INTO style_contracts
               (id,project_id,creation_contract_id,revision,merged_style_json,
                likes_json,dislikes_json,content_hash,confirmed_at)
               VALUES (%s,%s,%s,1,%s,'[]','[]',%s,%s)""",
            (
                style_id,
                seed.project_id,
                creation_id,
                canonical_json(style_content),
                canonical_hash(style_content),
                now,
            ),
        )
        await session.execute(
            """INSERT INTO project_contract_heads
               (project_id,revision,creation_contract_id,style_contract_id,
                creation_hash,style_hash,updated_at)
               VALUES (%s,1,%s,%s,%s,%s,%s)""",
            (
                seed.project_id,
                creation_id,
                style_id,
                canonical_hash(creation_content),
                canonical_hash(style_content),
                now,
            ),
        )
    record_counter("downstream_fixtures")

class AcceptanceSeedService:
    def __init__(self):
        self.inner = SeedService(
            SeedRepository(),
            transaction_factory=transaction,
            connection_factory=connection,
        )

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def select(self, command):
        import asyncio
        await asyncio.sleep(0.25)
        result = await self.inner.select(command)
        await install_downstream_fixture(result)
        return result

app.dependency_overrides[get_market_source_service] = lambda: market_source_service
app.dependency_overrides[get_market_analysis_service] = lambda: market_analysis_service
app.dependency_overrides[get_seed_service] = lambda: AcceptanceSeedService()
app.dependency_overrides[get_seed_generation_service] = lambda: seed_generation_service

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

const VERIFICATION_SOURCE = String.raw`
import asyncio
import json
import os
from pathlib import Path
import re

from backend.database import close_pool, connection
from backend.repositories.seeds import SeedRepository
from backend.services.seeds import SeedService

PROJECT_ID = "2b000000-0000-4000-8000-000000000001"
DATABASE_PATTERN = re.compile(r"novel_creator_test_[a-f0-9]{32}\Z")

async def main():
    expected_database = os.environ["BROWSER_TEST_DATABASE"]
    assert DATABASE_PATTERN.fullmatch(expected_database) is not None
    async with connection() as session:
        database_identity = await session.fetchone(
            "SELECT DATABASE() AS database_name"
        )
        selected = await session.fetchone(
            """SELECT selection_revision,seed_id
                 FROM project_selected_seeds WHERE project_id=%s""",
            (PROJECT_ID,),
        )
        revisions = await session.fetchone(
            """SELECT COUNT(*) AS count
                 FROM project_seed_selection_revisions WHERE project_id=%s""",
            (PROJECT_ID,),
        )
        contract = await session.fetchone(
            """SELECT selection_revision,seed_id
                 FROM creation_contracts WHERE project_id=%s AND revision=1""",
            (PROJECT_ID,),
        )
        seeds = await session.fetchone(
            """SELECT COUNT(*) AS active_count,
                      (SELECT COUNT(*) FROM creative_seed_revisions
                        WHERE project_id=%s) AS revision_count
                 FROM creative_seeds WHERE project_id=%s""",
            (PROJECT_ID, PROJECT_ID),
        )
        snapshots = await session.fetchone(
            """SELECT COUNT(*) AS count,
                      COUNT(DISTINCT source_id) AS source_count
                 FROM market_snapshots"""
        )
        qidian = await session.fetchone(
            """SELECT p.revision,p.enabled,s.last_snapshot_id,s.public_error_code
                 FROM market_sources m
                 JOIN market_source_policy_heads h ON h.source_id=m.id
                 JOIN market_source_policy_revisions p
                   ON p.source_id=h.source_id AND p.id=h.revision_id
                 JOIN market_source_refresh_states s ON s.source_id=m.id
                WHERE m.stable_key='qidian.newsign'"""
        )
        analyses = await session.fetchone(
            """SELECT COUNT(*) AS count FROM market_analyses
                WHERE project_id=%s AND status='succeeded'""",
            (PROJECT_ID,),
        )
        inspiration = await session.fetchone(
            """SELECT COUNT(*) AS count FROM seed_inspiration_attempts
                WHERE project_id=%s AND status='succeeded'""",
            (PROJECT_ID,),
        )
    readiness = await SeedService(
        SeedRepository(),
        transaction_factory=None,
        connection_factory=connection,
    ).get_selected(PROJECT_ID)
    counter_lines = Path(
        os.environ["BROWSER_FAKE_COUNTER_PATH"]
    ).read_text(encoding="utf-8").splitlines()
    assert selected["selection_revision"] == 3
    assert revisions["count"] == 3
    assert contract["selection_revision"] == 1
    assert selected["seed_id"] == contract["seed_id"]
    assert readiness.contract_ready is False
    assert readiness.reasons == ("selected_seed_drift",)
    assert seeds == {"active_count": 2, "revision_count": 2}
    assert snapshots == {"count": 2, "source_count": 2}
    assert qidian["revision"] == 4 and qidian["enabled"] == 0
    assert qidian["last_snapshot_id"] is not None
    assert qidian["public_error_code"] == "MARKET_TRANSPORT_FAILED"
    assert analyses["count"] == 1
    assert inspiration["count"] == 1
    assert counter_lines.count("fake_market_adapter_calls") == 1
    assert counter_lines.count("fake_market_analysis_calls") == 1
    assert counter_lines.count("fake_seed_gateway_calls") == 1
    assert counter_lines.count("downstream_fixtures") == 1
    assert counter_lines.count("forbidden_outbound_httpx_calls") == 0
    assert database_identity == {"database_name": expected_database}
    print("selection_revision=3")
    print("market_snapshots=2")
    print("seed_revisions=2")
    print("selection_revisions=3")
    print("dependency_graph=fake_only")
    print("disposable_database_identity=verified")

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
    throw new Error('Phase 2B browser requires the exact formal spec path')
  }
  return [...FORMAL_SPECS]
}


export function resolveCommandLineSpecs(argumentsList) {
  if (!Array.isArray(argumentsList)) {
    throw new TypeError('Phase 2B browser CLI arguments must be an array')
  }
  if (argumentsList.length !== 0) {
    throw new Error('Phase 2B browser runner does not accept spec paths')
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
    throw new Error('Phase 2B owned root is not a real directory')
  }
  if (
    !path.basename(root).startsWith(OWNED_ROOT_PREFIX)
    || normalizedPathIdentity(path.dirname(realpathSync(root)))
      !== normalizedPathIdentity(realpathSync(os.tmpdir()))
  ) {
    throw new Error('Phase 2B owned root is outside its temporary namespace')
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
  const capturedAt = Date.now()
  const qidianPath = path.join(filesRoot, 'qidian-public-snapshot.json')
  const qqPath = path.join(filesRoot, 'qq-public-snapshot.json')
  const counterPath = path.join(filesRoot, 'gateway-counters.json')
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
  return { root, filesRoot, qidianPath, qqPath, counterPath }
}


function childOptions(cwd, env) {
  return { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] }
}


export function buildEnvironments(
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
    BROWSER_TEST_DATABASE: databaseName,
    M2_BROWSER_RUN_NONCE: nonce,
    MARKET_SCHEDULER_ENABLED: 'false',
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    BROWSER_PRIVATE_PROVIDER_URL: PRIVATE_PROVIDER_URL,
    BROWSER_MODEL_SENTINEL: MODEL_SENTINEL,
    BROWSER_TRANSCRIPT_SENTINEL: TRANSCRIPT_SENTINEL,
    BROWSER_FAKE_COUNTER_PATH: roots.counterPath,
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
    BROWSER_ARTIFACT_ROOT: path.join(roots.root, 'phase2b-test-results'),
    BROWSER_QIDIAN_SNAPSHOT_PATH: roots.qidianPath,
    BROWSER_QQ_SNAPSHOT_PATH: roots.qqPath,
    BROWSER_PROJECT_ID: PROJECT_ID,
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
  return { prepare, backend, vite, browser, sensitiveController }
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


async function runOneSpec({
  spec,
  environment,
  databaseNameFactory,
  ownedRootFactory,
  portReservationFactory,
  deadlines,
}) {
  let databaseName
  let environments
  let sensitiveValues = []
  return runPhase2BLifecycle({
    async body(lifecycle) {
      databaseName = databaseNameFactory()
      assertDatabaseName(databaseName)
      const ownedRoot = lifecycle.setRoot(ownedRootFactory())
      const roots = prepareOwnedFiles(ownedRoot)
      const backendReservation = lifecycle.registerReservation(
        await portReservationFactory(),
      )
      const viteReservation = lifecycle.registerReservation(
        await portReservationFactory(),
      )
      if (
        !Number.isInteger(backendReservation?.port)
        || !Number.isInteger(viteReservation?.port)
        || backendReservation.port === viteReservation.port
        || typeof backendReservation.release !== 'function'
        || typeof viteReservation.release !== 'function'
      ) throw new Error('Phase 2B runner received invalid port reservations')

      const nonce = randomUUID()
      const backendUrl = `http://127.0.0.1:${backendReservation.port}`
      const viteUrl = `http://127.0.0.1:${viteReservation.port}`
      environments = buildEnvironments(
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
          label: 'Phase 2B fixture preparation', sensitiveValues,
          timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs,
        },
      )

      await lifecycle.releaseReservation(backendReservation)
      const backend = lifecycle.registerServer(startOwnedServer(
        python,
        ['-c', BACKEND_SOURCE, String(backendReservation.port)],
        childOptions(repositoryRoot, environments.backend),
        { label: 'backend', sensitiveValues },
      ))
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
      await waitForOwnedServer(vite, `${viteUrl}/__m2-browser-owner`, {
        expectedNonce: nonce,
        timeoutMs: deadlines.healthMs,
      })

      await runBoundedOwnedCommand(
        process.execPath,
        [
          playwrightCli, 'test', spec, '--config',
          'playwright.phase2b.config.ts',
        ],
        childOptions(frontendRoot, environments.browser),
        {
          label: 'Phase 2B browser test', sensitiveValues,
          timeoutMs: deadlines.browserMs, stopTimeoutMs: deadlines.stopMs,
          states: [backend, vite],
        },
      )
      await runBoundedOwnedCommand(
        python,
        ['-c', VERIFICATION_SOURCE],
        childOptions(repositoryRoot, environments.backend),
        {
          label: 'Phase 2B database evidence', sensitiveValues,
          timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs,
          states: [backend, vite],
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


export async function runPhase2B({
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
  for (const value of Object.values(normalizedDeadlines)) {
    if (!Number.isFinite(value) || value <= 0) {
      throw new TypeError('Phase 2B deadlines must be positive finite numbers')
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
    console.error('Phase 2B browser runner does not accept spec paths.')
    process.exitCode = 2
  }
  if (specs) {
    runPhase2B({ specs }).then(
      status => { process.exitCode = status },
      () => {
        console.error('Phase 2B browser runner failed.')
        process.exitCode = 1
      },
    )
  }
}
