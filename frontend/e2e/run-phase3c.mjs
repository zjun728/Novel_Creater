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
  assertDatabaseName,
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
import {
  assertNoPrivateEvidenceMarkers,
  runtimeSensitiveValues,
} from './runtime-observer.mjs'


export const FORMAL_SPECS = Object.freeze([
  'phase3c-story-blocks-outlines.spec.ts',
])
export const FORMAL_CONFIG = 'playwright.phase3c.config.ts'
export const FORMAL_SCENARIOS = Object.freeze([
  Object.freeze({ tag: '@manual', mode: 'manual' }),
  Object.freeze({ tag: '@gateway', mode: 'gateway' }),
  Object.freeze({ tag: '@supersession', mode: 'supersession' }),
  Object.freeze({ tag: '@archived', mode: 'archived' }),
  Object.freeze({ tag: '@missing-upstream', mode: 'missing-upstream' }),
  Object.freeze({ tag: '@canon-mismatch', mode: 'canon-mismatch' }),
  Object.freeze({ tag: '@wrong-chapter', mode: 'wrong-chapter' }),
])
const FORMAL_SCENARIO_MODES = new Set(
  FORMAL_SCENARIOS.map(scenario => scenario.mode),
)

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const OWNED_ROOT_PREFIX = 'novel-creator-phase3c-'
const PROJECT_ID = '81000000-0000-0000-0000-000000000001'
const SECRET_SENTINEL = 'phase3c-browser-secret-must-not-leak'
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
export const OWNED_SERVER_LOG_MARKERS = Object.freeze([
  'manifest',
  'Manifest',
  'MANIFEST',
  'inputManifest',
  'InputManifest',
  'INPUT_MANIFEST',
  'rawOutput',
  'RawOutput',
  'RAW_OUTPUT',
  'raw_output',
  'providerOutput',
  'ProviderOutput',
  'PROVIDER_OUTPUT',
  'provider_output',
  'rawProviderOutput',
  'RawProviderOutput',
  'RAW_PROVIDER_OUTPUT',
  'raw_provider_output',
  'rawProvider',
  'RawProvider',
  'RAW_PROVIDER',
  'raw_provider',
])
const DEFAULT_DEADLINES = Object.freeze({
  commandMs: 90_000,
  healthMs: 45_000,
  browserMs: 180_000,
  stopMs: 8_000,
})
const phase3CFailureContexts = new WeakMap()

export const FIXTURE_DOCUMENT_CONTRACT_SOURCE = String.raw`
from backend.domain.bibles import BiblePayload
from backend.domain.contracts import CreationContractPayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import (
    SeedPayload,
    decode_seed_revision,
    seed_revision_document,
)
from backend.tests.support.contract_fakes import SEED_PAYLOAD
from backend.tests.support.story_engine_fakes import option


_BIBLE_DOCUMENT = {
    "premiseAndPromise": (
        "一个被追捕的记录者必须保存真相，并承担公开真相的关系代价。"
    ),
    "worldRules": (
        {
            "id": "world-rule-1",
            "text": "任何超常力量都必须留下可追踪且不可撤销的代价。",
        },
    ),
    "powerOrProgressionSystem": (
        "成长依靠选择、训练和有限资源，不允许无依据跃升。"
    ),
    "protagonist": "主角谨慎、重视证据，并承担自己选择的后果。",
    "coreCast": (
        {
            "id": "cast-1",
            "text": "同伴拥有独立目标，不是主角的功能性附庸。",
        },
    ),
    "factions": (
        {
            "id": "faction-1",
            "text": "地方势力围绕安全、秩序与真相形成竞争。",
        },
    ),
    "longTermConflicts": (
        {
            "id": "conflict-1",
            "text": "保存真相与维持眼前秩序的冲突会逐步升级。",
        },
    ),
    "relationshipDynamics": (
        {
            "id": "relationship-1",
            "text": "信任只能通过共同选择和公开代价逐步建立。",
        },
    ),
    "toneAndNarrativeBoundaries": (
        "保持克制，让人物行动承担情绪和选择的后果。"
    ),
    "continuityGuardrails": (
        {
            "id": "guardrail-1",
            "text": "已经付出的代价不能被无条件撤销。",
        },
    ),
    "openDesignQuestions": (
        {
            "id": "question-1",
            "text": "第一阶段需要决定哪段关系最先承受代价。",
        },
    ),
}


def build_seed_fixture_document(provenance=None):
    payload = SeedPayload.model_validate(SEED_PAYLOAD, strict=True)
    return seed_revision_document(payload, provenance)


def validate_seed_fixture_document(document, expected_hash):
    payload, provenance = decode_seed_revision(document)
    if canonical_hash(payload) != expected_hash:
        raise ValueError("fixture seed hash mismatch")
    canonical = seed_revision_document(payload, provenance)
    if canonical_hash(canonical) != canonical_hash(document):
        raise ValueError("fixture seed document is not canonical")
    return canonical


def build_creation_fixture_document():
    seed = SeedPayload.model_validate(SEED_PAYLOAD, strict=True)
    engine = option(1)
    document = {
        "schemaVersion": "creation-contract-v1",
        "channelProfileKey": "web-fiction",
        "genreProfileKey": "fantasy",
        "qualityCharterVersion": "quality-v1",
        "selectionRevision": 1,
        "selectedSeed": seed,
        "seedRevisionId": "seed-revision-1",
        "seedHash": canonical_hash(seed),
        "selectedEngine": engine,
        "engineOptionId": "engine-option-1",
        "engineHash": canonical_hash(engine),
        "primaryStyleRef": {
            "id": "style-primary",
            "revision": 1,
            "contentHash": "a" * 64,
        },
        "secondaryStyleRef": None,
        "experienceCardRefs": (),
        "corpusSourceRefs": (),
        "targetTotalWords": 200_000,
        "expectedVolumeCount": 5,
        "expectedChapterCount": 80,
        "chapterWordRangePreference": (2_000, 3_000),
        "prohibitedDirections": ("不写无代价升级",),
        "authorNotes": "人物选择优先。",
        "modelBindingRef": None,
    }
    return CreationContractPayload.model_validate(
        document,
        strict=True,
    ).model_dump(mode="json", by_alias=True)


def validate_creation_fixture_document(document, expected_hash):
    if isinstance(document, (bytes, bytearray)):
        document = document.decode("utf-8")
    if isinstance(document, str):
        payload = CreationContractPayload.model_validate_json(
            document,
            strict=True,
        )
    else:
        payload = CreationContractPayload.model_validate_json(
            canonical_json(document),
            strict=True,
        )
    canonical = payload.model_dump(mode="json", by_alias=True)
    if canonical_hash(canonical) != expected_hash:
        raise ValueError("fixture creation contract hash mismatch")
    return canonical


def build_bible_fixture_document():
    return BiblePayload.model_validate(
        _BIBLE_DOCUMENT,
        strict=True,
    ).model_dump(mode="json", by_alias=True)


def validate_bible_fixture_document(document):
    if isinstance(document, (bytes, bytearray)):
        document = document.decode("utf-8")
    if not isinstance(document, str):
        document = canonical_json(document)
    return BiblePayload.model_validate_json(
        document,
        strict=True,
    ).model_dump(mode="json", by_alias=True)
`

export const MYSQL8_VERSION_PROOF_SOURCE = String.raw`
import re

def assert_mysql_8_version(row):
    assert isinstance(row, dict)
    version = row.get("version")
    assert isinstance(version, str)
    assert "mariadb" not in version.lower()
    assert re.fullmatch(r"8\.[0-9]+\.[0-9]+(?:[-+].*)?", version)
`

const FIXTURE_SOURCE = FIXTURE_DOCUMENT_CONTRACT_SOURCE + MYSQL8_VERSION_PROOF_SOURCE + String.raw`
import asyncio
import os
from contextlib import asynccontextmanager

from backend.database import close_pool, connection, transaction
from backend.repositories.contracts import ContractRepository
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.planning import PlanningRepository
from backend.services.chapter_outlines import (
    ChapterOutlineService,
    ConfirmChapterOutlineDraft,
    CreateChapterOutlineDraft,
    SaveChapterOutlineDraft,
)
from backend.services.bibles import BIBLE_POLICY_VERSION
from backend.services.contracts import ConfirmContracts, ContractService, SaveContractDraft
from backend.services.planning import (
    ConfirmPlanningDraft,
    CreatePlanningDraft,
    PlanningService,
    SavePlanningDraft,
)
from backend.services.projections import build_projection_bundle
from backend.tests.integration.test_contract_drafts import PROJECT, SEED_REV, _bootstrap, _draft
from backend.tests.integration.test_chapter_outline_lifecycle import _editable_outline
from backend.tests.integration.test_planning_aggregate_lifecycle import _payload
from backend.tests.integration.test_project_archive import _insert_confirmed_bible

NOW = 2_020_000_000_000

async def main():
    async with connection() as session:
        version = await session.fetchone("SELECT VERSION() AS version")
        assert_mysql_8_version(version)
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        assert selected == {"database_name": os.environ["MYSQL_DB"]}
        facts = await _bootstrap(session)
        seed_document = build_seed_fixture_document()
        seed_document = validate_seed_fixture_document(
            seed_document,
            facts["seed_hash"],
        )
        await session.execute(
            """UPDATE creative_seed_revisions
                  SET payload_json=%s
                WHERE id=%s AND project_id=%s""",
            (canonical_json(seed_document), SEED_REV, PROJECT),
        )

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
            "phase3c-contract-confirm",
            saved_contract.draft_version,
            saved_contract.content_hash,
        )
    )
    bible_content = build_bible_fixture_document()
    bible_content = validate_bible_fixture_document(bible_content)
    bundle = build_projection_bundle(0, ())
    async with transaction() as session:
        creation_row = await session.fetchone(
            """SELECT content_json
                 FROM creation_contracts
                WHERE project_id=%s AND id=%s""",
            (PROJECT, confirmed.creation_contract_id),
        )
        assert creation_row is not None
        creation_content = validate_creation_fixture_document(
            creation_row["content_json"],
            confirmed.creation_hash,
        )
        assert creation_content
        await _insert_confirmed_bible(
            session,
            confirmed,
            bible_id="93000000-0000-0000-0001-000000000001",
            now=NOW,
            content=bible_content,
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
                       'phase3c-bootstrap','bootstrap',NULL,%s,%s)""",
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

    scenario = os.environ["BROWSER_SCENARIO_MODE"]
    confirmed_planning = None
    if scenario not in {"manual", "missing-upstream"}:
        planning = PlanningService(
            PlanningRepository(),
            transaction_factory=transaction,
            id_factory=identifiers.__next__,
            clock=lambda: NOW + 1,
        )
        draft = await planning.create_draft(
            CreatePlanningDraft(PROJECT, "phase3c-ready-draft")
        )
        saved = await planning.save_draft(
            SavePlanningDraft(
                PROJECT,
                draft.draft_id,
                draft.draft_revision,
                draft.content_hash,
                _payload("作者保存的第一卷"),
                "phase3c-ready-draft-save",
            )
        )
        confirmed_planning = await planning.confirm_draft(
            ConfirmPlanningDraft(
                PROJECT,
                saved.draft_id,
                saved.draft_revision,
                saved.content_hash,
                f"phase3c-{scenario}-planning-r1",
            )
        )

    if scenario in {"supersession", "archived", "wrong-chapter"}:
        outline_ids = iter(
            f"94000000-0000-0000-0000-{number:012d}"
            for number in range(1, 100)
        )
        outlines = ChapterOutlineService(
            ChapterOutlineRepository(),
            ChapterSessionRepository(),
            transaction_factory=transaction,
            id_factory=outline_ids.__next__,
            clock=lambda: NOW + 2,
        )
        outline_draft = await outlines.create_draft(
            CreateChapterOutlineDraft(PROJECT, 1)
        )
        outline_saved = await outlines.save_draft(
            SaveChapterOutlineDraft(
                PROJECT,
                1,
                outline_draft.draft_id,
                outline_draft.draft_revision,
                outline_draft.content_hash,
                _editable_outline(confirmed_planning.content),
            )
        )
        await outlines.confirm_draft(
            ConfirmChapterOutlineDraft(
                PROJECT,
                1,
                outline_saved.draft_id,
                outline_saved.draft_revision,
                outline_saved.content_hash,
                0,
                f"phase3c-{scenario}-outline-r1",
            )
        )

    async with transaction() as session:
        if scenario == "archived":
            await session.execute(
                "UPDATE projects SET archived_at=%s WHERE id=%s",
                (NOW + 3, PROJECT),
            )
        if scenario == "canon-mismatch":
            await session.execute(
                """UPDATE projection_heads
                      SET projection_revision_number=1
                    WHERE project_id=%s""",
                (PROJECT,),
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

export const BACKEND_SOURCE = String.raw`
import os
import sys
from urllib.parse import urlsplit

import httpx
import uvicorn

PROVIDER_BASE_URL = os.environ["BROWSER_PROVIDER_BASE_URL"]
OUTBOUND_LEDGER_PATH = os.environ["BROWSER_OUTBOUND_LEDGER_PATH"]
ALLOW_PROVIDER = os.environ["BROWSER_ALLOW_PROVIDER"] == "1"

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

    async def aclose(self):
        return await self.inner.aclose()

    def build_request(self, *args, **kwargs):
        return self.inner.build_request(*args, **kwargs)

    def guard(self, method, url):
        parsed = urlsplit(str(url))
        allowed = (
            ALLOW_PROVIDER
            and str(method).upper() == "POST"
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
        with open(OUTBOUND_LEDGER_PATH, "a", encoding="utf-8") as ledger:
            ledger.write("allowed-local-provider\n")

    async def request(self, method, url, *args, **kwargs):
        self.guard(method, url)
        return await self.inner.request(method, url, *args, **kwargs)

    async def send(self, request, *args, **kwargs):
        self.guard(request.method, request.url)
        return await self.inner.send(request, *args, **kwargs)

    def stream(self, method, url, *args, **kwargs):
        self.guard(method, url)
        return self.inner.stream(method, url, *args, **kwargs)

    async def get(self, url, *args, **kwargs):
        return await self.request("GET", url, *args, **kwargs)

    async def options(self, url, *args, **kwargs):
        return await self.request("OPTIONS", url, *args, **kwargs)

    async def head(self, url, *args, **kwargs):
        return await self.request("HEAD", url, *args, **kwargs)

    async def post(self, url, *args, **kwargs):
        return await self.request("POST", url, *args, **kwargs)

    async def put(self, url, *args, **kwargs):
        return await self.request("PUT", url, *args, **kwargs)

    async def patch(self, url, *args, **kwargs):
        return await self.request("PATCH", url, *args, **kwargs)

    async def delete(self, url, *args, **kwargs):
        return await self.request("DELETE", url, *args, **kwargs)

httpx.AsyncClient = GuardedAsyncClient

from backend.main import app
uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(sys.argv[1]),
    log_level="warning",
)
`

export const TRANSPARENT_FAULT_PROXY_SOURCE = String.raw`
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
let faultUpstreamDrained = !inject
const afterFaultUpstreamDrain = []

function markFaultUpstreamDrained() {
  if (faultUpstreamDrained) return
  faultUpstreamDrained = true
  for (const deliver of afterFaultUpstreamDrain.splice(0)) deliver()
}

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

function waitForGatewayEntry(response, targetState) {
  const deadline = Date.now() + 5_000
  const check = () => {
    if (targetState.terminal || response.writableEnded) return
    if (existsSync(enteredPath)) {
      if (!injected) {
        injected = true
        targetState.injected = true
        targetState.terminal = true
        fixedUnknown(response)
        if (targetState.upstreamFinalized) markFaultUpstreamDrained()
      }
      return
    }
    if (Date.now() >= deadline) {
      if (!response.headersSent) {
        targetState.terminal = true
        const body = Buffer.from('owned provider did not start')
        response.writeHead(504, {
          'content-type': 'text/plain; charset=utf-8',
          'content-length': String(body.length),
          'access-control-allow-origin': browserOrigin,
          'vary': 'Origin',
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
    '/api/projects/' + projectId + '/chapter-outlines/'
  )
  const target = inject
    && !injected
    && incoming.method === 'POST'
    && incoming.url.startsWith(generationPrefix)
    && incoming.url.includes('/drafts/')
    && incoming.url.endsWith('/generate')
  const pendingLookup = (
    incoming.method === 'GET'
    && incoming.url.startsWith(
      '/api/projects/' + projectId
        + '/chapter-outlines/operations/by-key/',
    )
  )
  const gatePendingLookup = pendingLookup && injected
  const targetState = {
    terminal: false,
    upstreamFailed: false,
    upstreamFinalized: false,
    injected: false,
  }
  const finalizeUpstream = outcome => {
    if (!target || targetState.upstreamFinalized) return
    targetState.upstreamFinalized = true
    const ledgerEntry = Number.isInteger(outcome.statusCode)
      ? 'upstream-generation-status=' + String(outcome.statusCode) + '\n'
      : 'upstream-generation-error=' + outcome.errorKind + '\n'
    appendFileSync(upstreamLedgerPath, ledgerEntry, 'utf8')
    if (targetState.injected) markFaultUpstreamDrained()
  }
  const upstream = http.request({
    host: '127.0.0.1',
    port: upstreamPort,
    method: incoming.method,
    path: incoming.url,
    headers: { ...incoming.headers, host: '127.0.0.1:' + upstreamPort },
  }, upstreamResponse => {
    const upstreamSucceeded = (
      upstreamResponse.statusCode >= 200
      && upstreamResponse.statusCode < 300
    )
    if (target) {
      upstreamResponse.once('end', () => finalizeUpstream({
        statusCode: upstreamResponse.statusCode,
      }))
      upstreamResponse.once('aborted', () => finalizeUpstream({
        errorKind: 'aborted',
      }))
      upstreamResponse.once('error', () => finalizeUpstream({
        errorKind: 'transport',
      }))
      if (
        !upstreamSucceeded
        && !targetState.injected
        && !response.headersSent
        && !response.writableEnded
      ) {
        targetState.upstreamFailed = true
        targetState.terminal = true
        response.writeHead(upstreamResponse.statusCode, upstreamResponse.headers)
        upstreamResponse.pipe(response)
      } else {
        upstreamResponse.resume()
      }
      return
    }
    if (!gatePendingLookup) {
      response.writeHead(upstreamResponse.statusCode, upstreamResponse.headers)
      upstreamResponse.pipe(response)
      return
    }
    const chunks = []
    upstreamResponse.on('data', chunk => chunks.push(chunk))
    upstreamResponse.on('end', () => {
      const body = Buffer.concat(chunks)
      const deliver = () => {
        if (response.writableEnded || response.destroyed) return
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
            if (faultUpstreamDrained) deliver()
            else afterFaultUpstreamDrain.push(deliver)
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
    if (target) {
      targetState.upstreamFailed = true
      finalizeUpstream({ errorKind: 'transport' })
    }
    targetState.terminal = true
    if (!response.headersSent && !response.writableEnded) {
      const body = Buffer.from('upstream unavailable')
      response.writeHead(502, {
        'content-type': 'text/plain; charset=utf-8',
        'content-length': String(body.length),
      })
      response.end(body)
    } else if (!response.writableEnded) {
      response.destroy()
    }
  })
  incoming.pipe(upstream)
  if (target) waitForGatewayEntry(response, targetState)
}).listen(port, '127.0.0.1')
`

export const DENY_PROXY_SOURCE = String.raw`
const http = require('node:http')
const { appendFileSync } = require('node:fs')

const port = Number(process.argv[2])
const nonce = process.env.M2_BROWSER_RUN_NONCE
const ledgerPath = process.env.BROWSER_DENY_PROXY_LEDGER_PATH

const server = http.createServer((request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    response.writeHead(200, { 'content-type': 'application/json' })
    response.end(JSON.stringify({ browserRunNonce: nonce }))
    return
  }
  appendFileSync(ledgerPath, 'http-denied\n', 'utf8')
  response.writeHead(502, {
    connection: 'close',
    'content-type': 'text/plain; charset=utf-8',
  })
  response.end('outbound request denied')
})

server.on('connect', (_request, socket) => {
  appendFileSync(ledgerPath, 'connect-denied\n', 'utf8')
  socket.end(
    'HTTP/1.1 502 Bad Gateway\r\n'
      + 'Connection: close\r\n'
      + 'Content-Length: 0\r\n'
      + '\r\n',
  )
})

server.listen(port, '127.0.0.1')
`

export const FAKE_PLANNING_OUTLINE_GATEWAY_SOURCE = String.raw`
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

function normalizedPrivateKey(value) {
  const normalized = value.toLowerCase().replace(/[^a-z0-9]/gu, '')
  return (
    normalized === 'provenance'
    || normalized === 'apikey'
    || normalized === 'authorization'
    || normalized === 'password'
    || normalized === 'dsn'
    || normalized.includes('corpus')
  )
}

function containsPrivateKey(value) {
  if (Array.isArray(value)) return value.some(containsPrivateKey)
  if (value === null || typeof value !== 'object') return false
  return Object.entries(value).some(
    ([key, child]) => normalizedPrivateKey(key) || containsPrivateKey(child),
  )
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
      const manifest = evidence.manifest
      const manifestText = JSON.stringify(manifest)
      const publicBasis = (
        manifest.schema_version === 'chapter-outline-generation-v1'
        && Number.isInteger(manifest.chapter_number)
        && manifest.volume?.id
        && manifest.story_block?.id
        && Array.isArray(manifest.allowed_stages)
        && manifest.allowed_stages.length > 0
        && Array.isArray(manifest.allowed_scene_tasks)
        && manifest.allowed_scene_tasks.length > 0
      )
      if (
        !publicBasis
        || manifestText.includes(expectedSecret)
        || containsPrivateKey(manifest)
      ) {
        reject(response)
        return
      }
      const ref = node => ({
        id: node.id,
        revision: node.revision,
        contentHash: node.contentHash || node.content_hash,
      })
      const output = {
        schemaVersion: 'chapter-outline-draft-v1',
        volumeRef: ref(manifest.volume),
        storyBlockRef: ref(manifest.story_block),
        stageRefs: manifest.allowed_stages.map(ref),
        sceneTaskRefs: manifest.allowed_scene_tasks.map(ref),
        chapterGoal: 'AI 精确小纲：趁换岗空隙穿过封锁线。',
        expectedCharacters: ['主角', '同伴'],
        continuation: ['承接被困局面'],
        plannedTasks: ['观察换岗', '验证缺口'],
        scenes: ['废弃驿站侦察', '封锁线夜行'],
        forbiddenEarlyEvents: ['不可提前揭示内应'],
      }
      appendFileSync(counterPath, 'outline-generation\n', 'utf8')
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

const VERIFICATION_SOURCE = MYSQL8_VERSION_PROOF_SOURCE + String.raw`
import asyncio
import os
from backend.database import close_pool, connection

async def main():
    async with connection() as session:
        version = await session.fetchone("SELECT VERSION() AS version")
        assert_mysql_8_version(version)
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        assert selected == {"database_name": os.environ["MYSQL_DB"]}
        project_id = os.environ["BROWSER_PROJECT_ID"]
        project = await session.fetchone(
            "SELECT archived_at FROM projects WHERE id=%s",
            (project_id,),
        )
        assert project is not None
        pending = await session.fetchone(
            """SELECT COUNT(*) AS total
                 FROM chapter_outline_generation_attempts
                WHERE project_id=%s AND status='pending'""",
            (project_id,),
        )
        assert pending == {"total": 0}

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

function buildCleanupEnvironment(environment, databaseName) {
  return {
    ...allowlistedBaseEnvironment(environment),
    TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST,
    TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: environment.TEST_MYSQL_USER,
    TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    BROWSER_TEST_DATABASE: databaseName,
  }
}


function createRoots(ownedRoot) {
  const artifactRoot = path.join(ownedRoot, 'artifacts')
  const counterPath = path.join(ownedRoot, 'gateway-counter.log')
  const outboundLedgerPath = path.join(ownedRoot, 'outbound-ledger.log')
  const gatewayEnteredPath = path.join(ownedRoot, 'gateway-entered.signal')
  const gatewayReleasePath = path.join(ownedRoot, 'gateway-release.signal')
  const upstreamLedgerPath = path.join(ownedRoot, 'upstream-response.log')
  const denyProxyLedgerPath = path.join(ownedRoot, 'deny-proxy.log')
  const viteConfigPath = path.join(ownedRoot, 'vite.config.mjs')
  const fixturePath = path.join(ownedRoot, 'fixture.py')
  const backendPath = path.join(ownedRoot, 'backend.py')
  const gatewayPath = path.join(ownedRoot, 'gateway.cjs')
  const proxyPath = path.join(ownedRoot, 'proxy.cjs')
  const denyProxyPath = path.join(ownedRoot, 'deny-proxy.cjs')
  const browserResultPath = path.join(ownedRoot, 'browser-result.json')
  mkdirSync(artifactRoot)
  writeFileSync(counterPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(outboundLedgerPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(upstreamLedgerPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(denyProxyLedgerPath, '', { encoding: 'utf8', flag: 'wx' })
  writeFileSync(fixturePath, FIXTURE_SOURCE, { encoding: 'utf8', flag: 'wx' })
  writeFileSync(backendPath, BACKEND_SOURCE, { encoding: 'utf8', flag: 'wx' })
  writeFileSync(gatewayPath, FAKE_PLANNING_OUTLINE_GATEWAY_SOURCE, {
    encoding: 'utf8',
    flag: 'wx',
  })
  writeFileSync(proxyPath, TRANSPARENT_FAULT_PROXY_SOURCE, {
    encoding: 'utf8',
    flag: 'wx',
  })
  writeFileSync(denyProxyPath, DENY_PROXY_SOURCE, {
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
    denyProxyLedgerPath,
    viteConfigPath,
    fixturePath,
    backendPath,
    gatewayPath,
    proxyPath,
    denyProxyPath,
    browserResultPath,
  }
}


function buildEnvironments(
  environment,
  databaseName,
  backendUrl,
  browserApiUrl,
  viteUrl,
  denyProxyUrl,
  gatewayUrl,
  nonce,
  roots,
  scenario,
  cleanupEnvironment,
) {
  const base = allowlistedBaseEnvironment(environment)
  const prepare = cleanupEnvironment
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
    BROWSER_ALLOW_PROVIDER: scenario.mode === 'gateway' ? '1' : '0',
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
    BROWSER_ALLOWED_ORIGINS: JSON.stringify([viteUrl, browserApiUrl]),
    BROWSER_DENY_PROXY_URL: denyProxyUrl,
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
  const denyProxy = {
    ...base,
    M2_BROWSER_RUN_NONCE: nonce,
    BROWSER_DENY_PROXY_LEDGER_PATH: roots.denyProxyLedgerPath,
  }
  return { prepare, backend, vite, browser, gateway, denyProxy }
}


export function validateSpecs(specs) {
  if (
    !Array.isArray(specs)
    || specs.length !== FORMAL_SPECS.length
    || specs.some((spec, index) => spec !== FORMAL_SPECS[index])
  ) {
    throw new Error('Phase 3C requires its one exact formal browser spec')
  }
  return [...FORMAL_SPECS]
}


export function resolveCommandLineSpecs(argumentsList) {
  if (!Array.isArray(argumentsList) || argumentsList.length !== 0) {
    throw new Error('Phase 3C browser runner does not accept spec paths')
  }
  return [...FORMAL_SPECS]
}


function resolveScenarios(value) {
  if (value == null || value === '') return [...FORMAL_SCENARIOS]
  const scenario = formalScenarioForTag(value)
  if (!scenario) throw new Error('PHASE3C_GREP must select one exact formal scenario')
  return [scenario]
}

function formalScenarioForTag(value) {
  return FORMAL_SCENARIOS.find(item => item.tag === value) || null
}


function assertExactGatewayLedger(value, scenario) {
  const entries = String(value).split(/\r?\n/u).filter(Boolean)
  const expected = scenario.mode === 'gateway' ? ['outline-generation'] : []
  assertDeepEqual(entries, expected, 'fake Planning/Outline gateway call ledger')
}


function assertDeepEqual(actual, expected, label) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${label} did not match its closed contract`)
  }
}


function assertBackendOutboundLedger(value, scenario) {
  const entries = String(value).split(/\r?\n/u).filter(Boolean)
  const expected = scenario.mode === 'gateway'
    ? ['allowed-local-provider']
    : []
  assertDeepEqual(entries, expected, 'backend HTTPX outbound ledger')
}

export function assertDenyProxyLedger(value, {
  expectedHttpCount = 0,
  expectedConnectCount = 0,
} = {}) {
  if (
    !Number.isInteger(expectedHttpCount)
    || expectedHttpCount < 0
    || !Number.isInteger(expectedConnectCount)
    || expectedConnectCount < 0
  ) {
    throw new TypeError('deny proxy ledger expectation is invalid')
  }
  const entries = String(value).split(/\r?\n/u).filter(Boolean)
  if (entries.some(entry => !['http-denied', 'connect-denied'].includes(entry))) {
    throw new Error('deny proxy ledger did not match its closed contract')
  }
  const deniedHttpCount = entries.filter(entry => entry === 'http-denied').length
  const deniedConnectCount = entries.filter(entry => entry === 'connect-denied').length
  if (
    deniedHttpCount !== expectedHttpCount
    || deniedConnectCount !== expectedConnectCount
  ) {
    throw new Error('deny proxy ledger did not match its closed contract')
  }
  return {
    deniedHttpCount,
    deniedConnectCount,
    liveWebsiteAccessCount: 0,
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


export function assertBrowserNetworkAudit(value) {
  let report
  try {
    report = JSON.parse(String(value))
  } catch {
    throw new Error('browser network audit evidence is invalid')
  }
  const tests = (report?.suites || []).flatMap(suite => suite?.specs || [])
    .flatMap(spec => spec?.tests || [])
  const annotations = tests.flatMap(item => item?.annotations || [])
    .filter(item => item?.type === 'network-audit')
  if (annotations.length !== 1) {
    throw new Error('browser network audit evidence is invalid')
  }
  let audit
  try {
    audit = JSON.parse(String(annotations[0].description))
  } catch {
    throw new Error('browser network audit evidence is invalid')
  }
  const exactKeys = [
    'httpRequestCount',
    'allowedRequestCount',
    'forbiddenRequestCount',
    'forbiddenResponseCount',
  ]
  if (
    !audit
    || typeof audit !== 'object'
    || Array.isArray(audit)
    || JSON.stringify(Object.keys(audit).sort()) !== JSON.stringify([...exactKeys].sort())
    || exactKeys.some(key => !Number.isInteger(audit[key]) || audit[key] < 0)
    || audit.httpRequestCount <= 0
    || audit.httpRequestCount
      !== audit.allowedRequestCount + audit.forbiddenRequestCount
    || audit.forbiddenRequestCount !== 0
    || audit.forbiddenResponseCount !== 0
  ) {
    throw new Error('browser network audit evidence is invalid')
  }
  return Object.freeze({ ...audit })
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
      else throw new Error('Phase 3C artifact root contains a non-regular entry')
    }
  }
  visit(root)
  return files
}


export function assertArtifactEvidenceSafe(
  artifactRoot,
  sensitiveValues,
  extraFiles = [],
) {
  const markers = [...sensitiveValues, ...FORBIDDEN_EVIDENCE_MARKERS]
  for (const fileName of [
    ...listFilesRecursively(artifactRoot),
    ...extraFiles,
  ]) {
    const bytes = readFileSync(fileName)
    const text = bytes.toString('utf8')
    try {
      assertNoPrivateEvidenceMarkers([text])
    } catch {
      throw new Error('Phase 3C artifact contains forbidden evidence')
    }
    for (const marker of markers) {
      if (
        typeof marker === 'string'
        && marker
        && text.toLowerCase().includes(marker.toLowerCase())
      ) {
        throw new Error('Phase 3C artifact contains forbidden evidence')
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
  return new Error(`Phase 3C browser test failed: ${detail.slice(0, 2000)}`, {
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


export function attachPhase3CFailureContext(error, {
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
    scenario: FORMAL_SCENARIO_MODES.has(scenario) ? scenario : null,
    ownedRoot: root,
    artifactRoot: ownedDiagnosticPath(root, artifactRoot),
    resultPath: ownedDiagnosticPath(root, resultPath),
    sensitiveValues: Object.freeze(
      sensitiveValues.filter(value => typeof value === 'string' && value),
    ),
  })
  phase3CFailureContexts.set(error, context)
  return error
}


function collectFailureContexts(error, contexts = [], visited = new Set()) {
  if (!error || (typeof error !== 'object' && typeof error !== 'function')) {
    return contexts
  }
  if (visited.has(error)) return contexts
  visited.add(error)
  const context = phase3CFailureContexts.get(error)
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


export function formatPhase3CCommandFailure(error, {
  environment = process.env,
} = {}) {
  const contexts = collectFailureContexts(error)
  const failures = collectLeafFailures(error)
  const configuredScenario = formalScenarioForTag(environment.PHASE3C_GREP)?.mode
  const scenario = contexts.find(context => context.scenario)?.scenario
    || configuredScenario
    || 'unknown'
  const lines = [
    'Phase 3C browser runner failed.',
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


export async function runPhase3CCommandLine({
  specs,
  environment = process.env,
  runPhase3CImpl = runPhase3C,
  writeError = message => console.error(message),
}) {
  try {
    return await runPhase3CImpl({ specs, environment })
  } catch (error) {
    writeError(formatPhase3CCommandFailure(error, { environment }))
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
    throw new AggregateError(errors, 'Phase 3C root validation and removal failed')
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
  cleanupCommandImpl = runBoundedOwnedCommand,
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
  let browserNetworkAudit = null
  let denyProxyAudit = null
  const databaseName = databaseNameFactory()
  assertDatabaseName(databaseName)
  const cleanupEnvironment = buildCleanupEnvironment(environment, databaseName)
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
        const denyProxyReservation = lifecycle.registerReservation(
          await portReservationFactory(),
        )
        const viteReservation = lifecycle.registerReservation(
          await portReservationFactory(),
        )
        ports.push(
          gatewayReservation.port,
          backendReservation.port,
          proxyReservation.port,
          denyProxyReservation.port,
          viteReservation.port,
        )
        if (new Set(ports).size !== 5) {
          throw new Error('Phase 3C runner received duplicate owned ports')
        }
        const gatewayUrl = `http://127.0.0.1:${gatewayReservation.port}/v1`
        const backendUrl = `http://127.0.0.1:${backendReservation.port}`
        const browserApiUrl = `http://127.0.0.1:${proxyReservation.port}`
        const denyProxyUrl = `http://127.0.0.1:${denyProxyReservation.port}`
        const viteUrl = `http://127.0.0.1:${viteReservation.port}`
        environments = buildEnvironments(
          environment,
          databaseName,
          backendUrl,
          browserApiUrl,
          viteUrl,
          denyProxyUrl,
          gatewayUrl,
          nonce,
          roots,
          scenario,
          cleanupEnvironment,
        )
        sensitiveValues = [
          ...runtimeSensitiveValues(environments.browser),
          ...FORBIDDEN_EVIDENCE_MARKERS,
          ...OWNED_SERVER_LOG_MARKERS,
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
            label: 'Phase 3C fixture preparation',
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
          { label: 'fake Planning/Outline gateway', sensitiveValues },
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

        await lifecycle.releaseReservation(denyProxyReservation)
        const denyProxy = lifecycle.registerServer(startOwnedServer(
          process.execPath,
          [roots.denyProxyPath, String(denyProxyReservation.port)],
          childOptions(repositoryRoot, environments.denyProxy),
          { label: 'fake outbound deny proxy', sensitiveValues },
        ))
        activeServers.push(denyProxy)
        await waitForOwnedServer(denyProxy, `${denyProxyUrl}/health`, {
          expectedNonce: nonce,
          timeoutMs: deadlines.healthMs,
        })

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
              label: 'Phase 3C browser test',
              sensitiveValues,
              timeoutMs: deadlines.browserMs,
              stopTimeoutMs: deadlines.stopMs,
              states: activeServers,
            },
          )
        } catch (error) {
          throw browserFailure(error, roots.browserResultPath, sensitiveValues)
        }
        browserNetworkAudit = assertBrowserNetworkAudit(
          readFileSync(roots.browserResultPath, 'utf8'),
        )
        denyProxyAudit = assertDenyProxyLedger(
          readFileSync(roots.denyProxyLedgerPath, 'utf8'),
        )
        assertBackendOutboundLedger(
          readFileSync(roots.outboundLedgerPath, 'utf8'),
          scenario,
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
            label: 'Phase 3C database evidence',
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
        await cleanupCommandImpl(
          environment.PYTHON || 'python',
          [
            '-m',
            'backend.scripts.prepare_product_shell_browser_db',
            '--database',
            database,
            '--drop',
          ],
          childOptions(repositoryRoot, cleanupEnvironment),
          {
            label: 'database cleanup',
            sensitiveValues,
            timeoutMs: deadlines.commandMs,
            stopTimeoutMs: deadlines.stopMs,
          },
        )
        databaseCleaned = 1
        await cleanupCommandImpl(
          environment.PYTHON || 'python',
          ['-c', VERIFY_DATABASE_ABSENT_SOURCE],
          childOptions(repositoryRoot, cleanupEnvironment),
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
    attachPhase3CFailureContext(error, {
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
    || browserNetworkAudit === null
    || browserNetworkAudit.forbiddenRequestCount !== 0
    || browserNetworkAudit.forbiddenResponseCount !== 0
    || denyProxyAudit === null
    || denyProxyAudit.deniedHttpCount !== 0
    || denyProxyAudit.deniedConnectCount !== 0
    || denyProxyAudit.liveWebsiteAccessCount !== 0
  ) {
    const error = new AggregateError([], 'Phase 3C resource accounting failed')
    attachPhase3CFailureContext(error, {
      scenario: scenario.mode,
      ownedRoot: ownedRootPath,
      artifactRoot: roots?.artifactRoot,
      resultPath: roots?.browserResultPath,
      sensitiveValues: [...sensitiveValues, databaseName],
    })
    throw error
  }
  console.log(
    `Phase3C ${scenario.mode}: browser assertions passed; `
      + `DB created=${databaseCreated} cleaned=${databaseCleaned} `
      + `remaining=${databaseRemaining}; process=0 port=0 temp=0 cache=0; `
      + 'real provider calls = 0; product DB reads/writes = 0/0; '
      + `browser HTTP allowed=${String(browserNetworkAudit.allowedRequestCount)} `
      + `forbidden=${String(browserNetworkAudit.forbiddenRequestCount)}; `
      + `deny proxy HTTP=${String(denyProxyAudit.deniedHttpCount)} `
      + `CONNECT=${String(denyProxyAudit.deniedConnectCount)}; `
      + `live website access = ${String(denyProxyAudit.liveWebsiteAccessCount)}`,
  )
}


export async function runPhase3C({
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
  const scenarios = resolveScenarios(environment.PHASE3C_GREP)
  const normalizedDeadlines = { ...DEFAULT_DEADLINES, ...deadlines }
  if (Object.values(normalizedDeadlines).some(value => (
    !Number.isFinite(value) || value <= 0
  ))) {
    throw new TypeError('Phase 3C deadlines must be positive finite numbers')
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
    console.error('Phase 3C browser runner does not accept spec paths.')
    process.exitCode = 2
  }
  if (specs) {
    runPhase3CCommandLine({ specs }).then(status => {
      process.exitCode = status
    })
  }
}
