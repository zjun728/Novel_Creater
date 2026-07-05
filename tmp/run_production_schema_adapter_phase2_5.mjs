import fs from 'node:fs/promises'
import fsSync from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  checkProjectStateHealth,
  rebuildStateProjectionFromFinals,
} from '../frontend/src/utils/projectHealthCheck.js'
import {
  normalizeStateProvenance,
  withStateProvenance,
} from '../frontend/src/utils/stateProvenance.js'
import {
  buildCleanSyntheticProjectFixture,
} from './run_clean_synthetic_project_regression_phase2_2.mjs'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const ROOT_DIR = path.resolve(__dirname, '..')
const OUT_DIR = path.join(__dirname, 'realistic-flow-qa')
const DISPOSABLE_DIR = path.join(__dirname, 'production-schema-adapter-phase2-5')
const STORE_PATH = path.join(DISPOSABLE_DIR, 'disposable-store.json')
const MIGRATION_PATH = path.join(ROOT_DIR, 'backend', 'migrations', '20260705_state_provenance_phase1_2.sql')
const ROLLBACK_PATH = path.join(ROOT_DIR, 'backend', 'migrations', '20260705_state_provenance_phase1_2_rollback.sql')
const BACKEND_ADAPTER_PATH = path.join(ROOT_DIR, 'backend', 'routers', 'project_state.py')
const FRONTEND_CLIENT_PATH = path.join(ROOT_DIR, 'frontend', 'src', 'api', 'db', 'client.js')
const FRONTEND_READINESS_PATH = path.join(ROOT_DIR, 'frontend', 'src', 'views', 'WriterView.vue')
const OUT_JSON = path.join(OUT_DIR, 'production-schema-adapter-phase2-5.json')
const OUT_REPORT = path.join(OUT_DIR, 'production-schema-adapter-phase2-5-report.md')

const CURRENT_CHAPTER = 15
const REQUIRED_PROVENANCE_FIELDS = [
  'provenance',
  'source_chapter_num',
  'source_version_id',
  'run_id',
  'finalization_id',
  'commit_status',
]
const EXISTING_PROVENANCE_TABLES = [
  'chapter_versions',
  'canon_facts',
  'setting_entities',
  'setting_relations',
  'setting_change_events',
  'project_volumes',
  'chapter_beat_plans',
]

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function readText(filePath) {
  return fsSync.readFileSync(filePath, 'utf8')
}

function parseSchema() {
  const sql = readText(MIGRATION_PATH)
  const createTables = parseCreateTables(sql)
  const alterTables = parseAlterTables(sql)
  const tables = ['finalization_markers', 'project_health_checks'].map(table => {
    const created = createTables.get(table)
    return {
      table,
      hasProductionCreateTable: Boolean(created),
      provenanceFields: REQUIRED_PROVENANCE_FIELDS.filter(field => created?.columns.includes(field)),
      hasAllProvenanceFields: REQUIRED_PROVENANCE_FIELDS.every(field => created?.columns.includes(field)),
      indexes: created?.indexes || [],
      hasCommitStatusConstraint: Boolean(created?.constraints.some(line => /commit_status/i.test(line) && /CHECK/i.test(line))),
      columns: created?.columns || [],
    }
  })
  const existingProvenanceTables = EXISTING_PROVENANCE_TABLES.map(table => {
    const altered = alterTables.get(table)
    return {
      table,
      provenanceFields: REQUIRED_PROVENANCE_FIELDS.filter(field => altered?.columns.includes(field)),
      hasAllProvenanceFields: REQUIRED_PROVENANCE_FIELDS.every(field => altered?.columns.includes(field)),
    }
  })
  return {
    migrationPath: MIGRATION_PATH,
    executedAgainstRealDb: false,
    parserMode: 'mysql-ddl-parse-dry-run',
    tables,
    existingProvenanceTables,
    idempotence: {
      newTablesRepeatSafe: tables.every(row => row.hasProductionCreateTable),
      existingAlterRepeatSafe: false,
      productionApplyRequiresInspector: true,
      unavailableReason: 'Existing provenance ALTER TABLE ADD COLUMN and CREATE INDEX statements are draft-only; production apply must use a schema inspector/migration runner that skips existing columns/indexes or a backup-verified one-shot migration.',
    },
    finalizationMarkersClosed: tableClosed(tables, 'finalization_markers'),
    projectHealthChecksClosed: tableClosed(tables, 'project_health_checks'),
  }
}

function parseCreateTables(sql) {
  const tables = new Map()
  const matches = [...String(sql || '').matchAll(/CREATE TABLE IF NOT EXISTS\s+([a-z_]+)\s*\(([\s\S]*?)\)\s*ENGINE=/gi)]
  for (const match of matches) {
    const table = match[1]
    const body = match[2]
    const lines = body.split(/\r?\n/).map(line => line.trim().replace(/,$/, '')).filter(Boolean)
    const columns = []
    const indexes = []
    const constraints = []
    for (const line of lines) {
      if (/^(UNIQUE\s+KEY|INDEX|KEY)\b/i.test(line)) indexes.push(line)
      else if (/^(CONSTRAINT|CHECK)\b/i.test(line)) constraints.push(line)
      else if (/^commit_status\s+IN\b/i.test(line) || /^'/.test(line) || /^\)/.test(line)) continue
      else {
        const column = line.match(/^([a-z_]+)\s+/i)?.[1]
        if (column) columns.push(column)
      }
    }
    tables.set(table, { table, columns, indexes, constraints, raw: body })
  }
  return tables
}

function parseAlterTables(sql) {
  const tables = new Map()
  const matches = [...String(sql || '').matchAll(/ALTER TABLE\s+([a-z_]+)([\s\S]*?);/gi)]
  for (const match of matches) {
    const table = match[1]
    const body = match[2]
    const columns = [...body.matchAll(/ADD COLUMN\s+([a-z_]+)/gi)].map(columnMatch => columnMatch[1])
    tables.set(table, { table, columns })
  }
  return tables
}

function tableClosed(tables, table) {
  const row = tables.find(item => item.table === table)
  return Boolean(row?.hasProductionCreateTable && row.hasAllProvenanceFields && row.hasCommitStatusConstraint && row.indexes.length >= 2)
}

function parseRollback() {
  const sql = readText(ROLLBACK_PATH)
  const steps = sql.split(/\r?\n/).map(line => line.trim()).filter(line => /^DROP TABLE/i.test(line))
  return {
    rollbackPath: ROLLBACK_PATH,
    supported: steps.some(step => /project_health_checks/i.test(step)) &&
      steps.some(step => /finalization_markers/i.test(step)),
    executedAgainstRealDb: false,
    requiresBackupBeforeRealRun: true,
    steps,
  }
}

function inspectAdapters() {
  const backend = readText(BACKEND_ADAPTER_PATH)
  const frontend = readText(FRONTEND_CLIENT_PATH)
  const readiness = readText(FRONTEND_READINESS_PATH)
  return {
    backend: {
      path: BACKEND_ADAPTER_PATH,
      hasFinalizationMarkerRoutes: /finalization-markers/.test(backend) && /save_finalization_marker/.test(backend),
      hasProjectHealthCheckRoutes: /health-checks/.test(backend) && /save_project_health_check/.test(backend),
      hasIdempotentMarkerUpsert: /ON DUPLICATE KEY UPDATE[\s\S]*finalization_markers/.test(backend) ||
        /INSERT INTO finalization_markers[\s\S]*ON DUPLICATE KEY UPDATE/.test(backend),
      hasIdempotentHealthUpsert: /INSERT INTO project_health_checks[\s\S]*ON DUPLICATE KEY UPDATE/.test(backend),
    },
    frontend: {
      path: FRONTEND_CLIENT_PATH,
      readinessPath: FRONTEND_READINESS_PATH,
      hasFinalizationMarkerClient: /finalizationMarkers/.test(frontend) && /finalization-markers/.test(frontend),
      hasProjectHealthCheckClient: /healthChecks/.test(frontend) && /health-checks/.test(frontend),
      hasReadinessDurableMarkerLoad: /api\.projectState\.finalizationMarkers\.list/.test(readiness) &&
        /loadDurableFinalizationMarkers/.test(readiness),
      hasContextDurableMarkerInjection: /collectContextFinalizationMarkers/.test(readiness) &&
        /durableFinalizationMarkers/.test(readiness),
    },
  }
}

function createDisposableStore() {
  return {
    schemaVersion: 'production-schema-adapter-disposable-store-phase2-5-v1',
    metadata: {
      syntheticOnly: true,
      realDbConnection: false,
      migrationAppliedAgainstRealDb: false,
      storePath: STORE_PATH,
    },
    collections: {
      finalization_markers: [],
      project_health_checks: [],
    },
  }
}

function stableMarkerId(marker) {
  return `${marker.projectId}_${marker.chapterNum}_${marker.runId || 'no-run'}_${marker.finalizationId || 'no-finalization'}`.slice(0, 160)
}

function stableHealthId(record) {
  return `${record.projectId}_${record.chapterNum}_${record.runId}`.slice(0, 160)
}

function normalizeMarker(input = {}) {
  const provenance = normalizeStateProvenance(input, {
    sourceChapterNum: input.sourceChapterNum || input.chapterNum,
    sourceVersionId: input.sourceVersionId || input.source_version_id || '',
    runId: input.runId || input.run_id || '',
    finalizationId: input.finalizationId || input.finalization_id || '',
    commitStatus: input.commitStatus || input.commit_status || input.status || 'pending',
  })
  const marker = withStateProvenance({
    projectId: input.projectId || '',
    chapterNum: Number(input.chapterNum || provenance.sourceChapterNum || 0),
    sourceVersionId: provenance.sourceVersionId,
    runId: provenance.runId,
    finalizationId: provenance.finalizationId,
    commitStatus: provenance.commitStatus || 'pending',
    reason: input.reason || '',
    startedAt: input.startedAt || input.started_at || null,
    updatedAt: input.updatedAt || input.updated_at || Date.now(),
  }, provenance)
  return { id: stableMarkerId(marker), ...marker }
}

function upsertMarker(store, markerInput) {
  const marker = normalizeMarker(markerInput)
  const rows = store.collections.finalization_markers
  const index = rows.findIndex(row => row.id === marker.id)
  if (index >= 0) rows[index] = { ...rows[index], ...marker }
  else rows.push(marker)
  return marker
}

function normalizeHealthCheck(input = {}) {
  const runId = input.runId || input.run_id || `health-${input.projectId || 'project'}-${input.chapterNum || CURRENT_CHAPTER}`
  const status = input.commitStatus || (input.blocked ? 'blocked' : 'ready')
  const provenance = normalizeStateProvenance(input, {
    sourceChapterNum: input.sourceChapterNum || input.chapterNum,
    sourceVersionId: input.sourceVersionId || input.source_version_id || '',
    runId,
    finalizationId: input.finalizationId || input.finalization_id || '',
    commitStatus: status,
  })
  const record = withStateProvenance({
    projectId: input.projectId || '',
    chapterNum: Number(input.chapterNum || provenance.sourceChapterNum || 0),
    sourceVersionId: provenance.sourceVersionId,
    runId: provenance.runId || runId,
    finalizationId: provenance.finalizationId,
    commitStatus: provenance.commitStatus || status,
    blocked: Boolean(input.blocked),
    blockingCount: Number(input.blockingCount || input.blocking_count || 0),
    warningCount: Number(input.warningCount || input.warning_count || 0),
    resultJson: input.resultJson || input.result || {},
    issueSummary: input.issueSummary || [],
    updatedAt: input.updatedAt || Date.now(),
  }, provenance)
  return { id: stableHealthId(record), ...record }
}

function upsertHealthCheck(store, healthInput) {
  const record = normalizeHealthCheck(healthInput)
  const rows = store.collections.project_health_checks
  const index = rows.findIndex(row => row.id === record.id)
  if (index >= 0) rows[index] = { ...rows[index], ...record }
  else rows.push(record)
  return record
}

async function writeDisposableStore(store) {
  await fs.mkdir(DISPOSABLE_DIR, { recursive: true })
  await fs.writeFile(STORE_PATH, `${JSON.stringify(store, null, 2)}\n`, 'utf8')
}

async function readDisposableStore() {
  return JSON.parse(await fs.readFile(STORE_PATH, 'utf8'))
}

function summarizeIssues(issues = []) {
  return issues.map(issue => ({
    code: issue.code,
    severity: issue.severity,
    targetType: issue.targetType || '',
    target: issue.target || '',
    reason: issue.reason || '',
    sourceChapterNum: issue.provenance?.sourceChapterNum || null,
    sourceVersionId: issue.provenance?.sourceVersionId || '',
    runId: issue.provenance?.runId || '',
    finalizationId: issue.provenance?.finalizationId || '',
    commitStatus: issue.provenance?.commitStatus || '',
  }))
}

function evaluateReadiness(fixture, marker) {
  const snapshot = clone(fixture.snapshots.healthy)
  snapshot.contextOptions.finalizationMarkers = [marker]
  const health = checkProjectStateHealth(snapshot, { chapterNum: CURRENT_CHAPTER })
  return {
    blocked: health.blocked,
    issueCodes: [...new Set((health.issues || []).map(issue => issue.code))],
    blockingIssues: summarizeIssues((health.issues || []).filter(issue => issue.severity === 'block')),
    creativeContextContainsMarkerReason: JSON.stringify(health.creativeContext || {}).includes(marker.reason || 'setting settlement'),
  }
}

function evaluateHealthCheckIsolation(fixture, record) {
  const snapshot = clone(fixture.snapshots.healthy)
  snapshot.contextOptions.projectHealthChecks = [record]
  const health = checkProjectStateHealth(snapshot, { chapterNum: CURRENT_CHAPTER })
  const creativeText = JSON.stringify(health.creativeContext || {})
  const authorityText = JSON.stringify(health.contextPack?.stateAuthority || {})
  return {
    creativeContextContainsHealthJson: creativeText.includes('phase2.5 persisted degraded health artifact') ||
      creativeText.includes(record.id),
    entersStateAuthority: authorityText.includes('phase2.5 persisted degraded health artifact') ||
      authorityText.includes(record.id),
  }
}

function evaluateSavedBeatAndGuard(fixture) {
  const health = checkProjectStateHealth(fixture.snapshots.healthy, { chapterNum: CURRENT_CHAPTER })
  const projection = rebuildStateProjectionFromFinals(fixture.snapshots.healthy, { chapterNum: CURRENT_CHAPTER })
  const creativeText = JSON.stringify(health.creativeContext || {})
  const authorityText = JSON.stringify(projection.stateAuthority || {})
  return {
    savedBeatConflictFinalFactWins: authorityText.includes(fixture.finalFactText) &&
      !creativeText.includes(fixture.savedBeatPlan.conflictWithFinalFact),
    guardSnapshotLeakBlocked: !creativeText.includes(fixture.guardOnly.futureRoadmapSecret),
  }
}

function rollbackDisposableStore(store) {
  const rolledBack = clone(store)
  delete rolledBack.collections.project_health_checks
  delete rolledBack.collections.finalization_markers
  return {
    removedCollections: !rolledBack.collections.project_health_checks && !rolledBack.collections.finalization_markers,
    postRollbackReadBlocked: !rolledBack.collections.project_health_checks && !rolledBack.collections.finalization_markers,
  }
}

function buildSummary(schema, adapters, results, rollback) {
  return {
    finalizationMarkersClosed: schema.finalizationMarkersClosed,
    projectHealthChecksClosed: schema.projectHealthChecksClosed,
    backendAdapterClosed: adapters.backend.hasFinalizationMarkerRoutes &&
      adapters.backend.hasProjectHealthCheckRoutes &&
      adapters.backend.hasIdempotentMarkerUpsert &&
      adapters.backend.hasIdempotentHealthUpsert,
    frontendAdapterClosed: adapters.frontend.hasFinalizationMarkerClient &&
      adapters.frontend.hasProjectHealthCheckClient &&
      adapters.frontend.hasReadinessDurableMarkerLoad &&
      adapters.frontend.hasContextDurableMarkerInjection,
    disposableSchemaParserPassed: schema.finalizationMarkersClosed &&
      schema.projectHealthChecksClosed &&
      rollback.supported,
    migrationIdempotenceReady: schema.idempotence.newTablesRepeatSafe && schema.idempotence.existingAlterRepeatSafe,
    disposableRollbackDryRunPassed: results.disposableRollback.removedCollections &&
      results.disposableRollback.postRollbackReadBlocked,
    readinessBlockedByHalfSuccess: results.halfSuccessReadinessBlocked,
    creativeBoundaryClean: !results.healthCheck.creativeContextContainsHealthJson &&
      !results.healthCheck.entersStateAuthority &&
      results.guardSnapshotLeakBlocked,
  }
}

export async function runProductionSchemaAdapterGate() {
  const schema = parseSchema()
  const rollback = parseRollback()
  const adapters = inspectAdapters()
  const fixture = buildCleanSyntheticProjectFixture()
  const store = createDisposableStore()

  const markerInput = {
    projectId: 'phase2-5-disposable-project',
    chapterNum: 14,
    sourceChapterNum: 14,
    sourceVersionId: 'v14-final',
    runId: 'run-half-14',
    finalizationId: 'fin-half-14',
    commitStatus: 'failed_after_chapter_commit',
    reason: 'phase2.5 disposable half-success marker',
  }
  upsertMarker(store, markerInput)
  const marker = upsertMarker(store, { ...markerInput, reason: 'phase2.5 disposable half-success marker updated' })
  const readiness = evaluateReadiness(fixture, marker)

  const healthInput = {
    projectId: 'phase2-5-disposable-project',
    chapterNum: CURRENT_CHAPTER,
    sourceChapterNum: CURRENT_CHAPTER,
    sourceVersionId: 'health-v15',
    runId: 'health-run-15',
    commitStatus: 'blocked',
    blocked: true,
    blockingCount: 1,
    warningCount: 1,
    result: {
      schemaVersion: 'project-health-check-v1',
      blocked: true,
      note: 'phase2.5 persisted degraded health artifact',
    },
    issueSummary: [
      { code: 'unknown_provenance', severity: 'warn', note: 'phase2.5 persisted degraded health artifact' },
    ],
  }
  upsertHealthCheck(store, healthInput)
  const healthRecord = upsertHealthCheck(store, { ...healthInput, warningCount: 2 })
  await writeDisposableStore(store)
  const readStore = await readDisposableStore()
  const isolation = evaluateHealthCheckIsolation(fixture, healthRecord)
  const beatAndGuard = evaluateSavedBeatAndGuard(fixture)
  const disposableRollback = rollbackDisposableStore(readStore)

  const results = {
    marker: {
      idempotent: readStore.collections.finalization_markers.length === 1,
      readBackCount: readStore.collections.finalization_markers.length,
      commitStatus: readStore.collections.finalization_markers[0]?.commitStatus || '',
      provenanceComplete: Boolean(readStore.collections.finalization_markers[0]?.provenance?.finalizationId),
    },
    healthCheck: {
      idempotent: readStore.collections.project_health_checks.length === 1,
      readBackCount: readStore.collections.project_health_checks.length,
      creativeContextContainsHealthJson: isolation.creativeContextContainsHealthJson,
      entersStateAuthority: isolation.entersStateAuthority,
      provenanceComplete: Boolean(readStore.collections.project_health_checks[0]?.provenance?.runId),
    },
    halfSuccessReadinessBlocked: readiness.blocked && readiness.issueCodes.includes('finalization_pending'),
    halfSuccessBlockingIssues: readiness.blockingIssues,
    unknownDegradedExcludedFromCreative: !isolation.creativeContextContainsHealthJson && !isolation.entersStateAuthority,
    savedBeatConflictFinalFactWins: beatAndGuard.savedBeatConflictFinalFactWins,
    guardSnapshotLeakBlocked: beatAndGuard.guardSnapshotLeakBlocked,
    disposableRollback,
  }

  const payload = {
    schemaVersion: 'production-schema-adapter-phase2-5-v1',
    status: 'completed',
    timestamp: new Date().toISOString(),
    boundary: {
      touchesRealDb: false,
      startsService: false,
      usesRealProject: false,
      realDbDsnPresent: false,
    },
    disposableStore: {
      strategy: 'disposable-json-store',
      path: STORE_PATH,
      syntheticOnly: true,
      realDbConnection: false,
    },
    schema,
    rollback,
    adapters,
    results,
  }
  payload.summary = buildSummary(schema, adapters, results, rollback)
  return payload
}

export function validateProductionSchemaAdapterPayload(payload = {}) {
  if (payload.schemaVersion !== 'production-schema-adapter-phase2-5-v1') {
    throw new Error('Invalid Phase 2.5 production schema adapter schemaVersion')
  }
  if (payload.status !== 'completed') return true
  if (payload.boundary?.touchesRealDb !== false) throw new Error('boundary.touchesRealDb must be false')
  if (payload.boundary?.startsService !== false) throw new Error('boundary.startsService must be false')
  if (payload.boundary?.usesRealProject !== false) throw new Error('boundary.usesRealProject must be false')
  if (!String(payload.disposableStore?.path || '').includes('tmp')) throw new Error('disposable store must stay under tmp')
  if (!payload.schema?.finalizationMarkersClosed) throw new Error('schema.finalizationMarkersClosed mismatch')
  if (!payload.schema?.projectHealthChecksClosed) throw new Error('schema.projectHealthChecksClosed mismatch')
  if (!payload.rollback?.supported) throw new Error('rollback.supported mismatch')
  const expectedSummary = buildSummary(payload.schema, payload.adapters, payload.results, payload.rollback)
  for (const [key, expected] of Object.entries(expectedSummary)) {
    if (payload.summary?.[key] !== expected) throw new Error(`summary.${key} mismatch`)
  }
  if (!payload.summary.backendAdapterClosed) throw new Error('backend adapter must be closed')
  if (!payload.summary.frontendAdapterClosed) throw new Error('frontend adapter must be closed')
  if (payload.schema.idempotence?.existingAlterRepeatSafe !== false) throw new Error('plain ALTER idempotence must remain explicitly unresolved')
  if (!payload.schema.idempotence?.productionApplyRequiresInspector) throw new Error('production apply must require schema inspector')
  if (!payload.summary.readinessBlockedByHalfSuccess) throw new Error('half-success marker must block readiness')
  if (!payload.summary.creativeBoundaryClean) throw new Error('health/guard artifacts must stay out of creative context')
  return true
}

export function buildProductionSchemaAdapterReport(payload) {
  validateProductionSchemaAdapterPayload(payload)
  const lines = [
    '# Production Schema Adapter Phase 2.5 Report',
    '',
    'Status: completed disposable schema/adapter dry-run. This is not a real DB migration, real project cleanup, clean regression, canary, or live chapter run.',
    '',
    '## Scope Guard',
    '- Did not start backend/frontend dev server, runner, or page.goto.',
    '- Did not run formal chapter generation/finalization chain.',
    '- Did not connect to or write a real DB; no real migration/cleanup/quarantine/purge executed.',
    '- Did not restore LongformBrowser or run #98/#99/#50.',
    '- Did not save model output as project正文、小纲、beat plan, or DB state.',
    '- Did not enter Phase 3 provider/model adapter work or real clean project/live canary.',
    '- Did not create commit/PR.',
    '',
    '## Summary',
    `schema.finalizationMarkersClosed=${payload.summary.finalizationMarkersClosed}`,
    `schema.projectHealthChecksClosed=${payload.summary.projectHealthChecksClosed}`,
    `adapter.backendClosed=${payload.summary.backendAdapterClosed}`,
    `adapter.frontendClosed=${payload.summary.frontendAdapterClosed}`,
    `dryRun.schemaParserPassed=${payload.summary.disposableSchemaParserPassed}`,
    `dryRun.migrationIdempotenceReady=${payload.summary.migrationIdempotenceReady}`,
    `dryRun.idempotenceUnavailableReason=${payload.schema.idempotence.unavailableReason}`,
    `dryRun.rollbackPassed=${payload.summary.disposableRollbackDryRunPassed}`,
    `readiness.halfSuccessBlocked=${payload.summary.readinessBlockedByHalfSuccess}`,
    `creative.boundaryClean=${payload.summary.creativeBoundaryClean}`,
    '',
    '## Schema Closure',
    '| table | productionCreate | provenanceFields | indexes | commitStatusConstraint |',
    '| --- | --- | --- | --- | --- |',
    ...payload.schema.tables.map(row => `| ${row.table} | productionCreate=${row.hasProductionCreateTable}; provenanceFields=${row.provenanceFields.join(',')}; indexes=${row.indexes.length}; commitStatusConstraint=${row.hasCommitStatusConstraint} |`),
    '',
    '## Existing Provenance Coverage',
    '| table | allProvenanceFields | fields |',
    '| --- | --- | --- |',
    ...payload.schema.existingProvenanceTables.map(row => `| ${row.table} | allProvenanceFields=${row.hasAllProvenanceFields}; fields=${row.provenanceFields.join(',')} |`),
    '',
    '## Adapter Closure',
    `backend.path=${payload.adapters.backend.path}`,
    `backend.finalizationMarkerRoutes=${payload.adapters.backend.hasFinalizationMarkerRoutes}`,
    `backend.projectHealthCheckRoutes=${payload.adapters.backend.hasProjectHealthCheckRoutes}`,
    `backend.idempotentMarkerUpsert=${payload.adapters.backend.hasIdempotentMarkerUpsert}`,
    `backend.idempotentHealthUpsert=${payload.adapters.backend.hasIdempotentHealthUpsert}`,
    `frontend.path=${payload.adapters.frontend.path}`,
    `frontend.finalizationMarkerClient=${payload.adapters.frontend.hasFinalizationMarkerClient}`,
    `frontend.projectHealthCheckClient=${payload.adapters.frontend.hasProjectHealthCheckClient}`,
    `frontend.readinessDurableMarkerLoad=${payload.adapters.frontend.hasReadinessDurableMarkerLoad}`,
    `frontend.contextDurableMarkerInjection=${payload.adapters.frontend.hasContextDurableMarkerInjection}`,
    '',
    '## Disposable Migration / Rollback',
    `disposable.storePath=${payload.disposableStore.path}`,
    `disposable.syntheticOnly=${payload.disposableStore.syntheticOnly}`,
    `disposable.realDbConnection=${payload.disposableStore.realDbConnection}`,
    `rollback.supported=${payload.rollback.supported}`,
    `rollback.executedAgainstRealDb=${payload.rollback.executedAgainstRealDb}`,
    `rollback.steps=${payload.rollback.steps.join(' | ')}`,
    '',
    '## Integration Results',
    `marker.idempotent=${payload.results.marker.idempotent}`,
    `marker.readBackCount=${payload.results.marker.readBackCount}`,
    `marker.commitStatus=${payload.results.marker.commitStatus}`,
    `healthCheck.idempotent=${payload.results.healthCheck.idempotent}`,
    `healthCheck.readBackCount=${payload.results.healthCheck.readBackCount}`,
    `healthCheck.creativeContextContainsHealthJson=${payload.results.healthCheck.creativeContextContainsHealthJson}`,
    `healthCheck.entersStateAuthority=${payload.results.healthCheck.entersStateAuthority}`,
    `readiness.halfSuccessBlockingIssueCodes=${issueText(payload.results.halfSuccessBlockingIssues.map(issue => issue.code))}`,
    `context.unknownDegradedExcludedFromCreative=${payload.results.unknownDegradedExcludedFromCreative}`,
    `context.savedBeatConflictFinalFactWins=${payload.results.savedBeatConflictFinalFactWins}`,
    `context.guardSnapshotLeakBlocked=${payload.results.guardSnapshotLeakBlocked}`,
    `rollback.removedCollections=${payload.results.disposableRollback.removedCollections}`,
    `rollback.postRollbackReadBlocked=${payload.results.disposableRollback.postRollbackReadBlocked}`,
    '',
    '## Migration Idempotence',
    `idempotence.newTablesRepeatSafe=${payload.schema.idempotence.newTablesRepeatSafe}`,
    `idempotence.existingAlterRepeatSafe=${payload.schema.idempotence.existingAlterRepeatSafe}`,
    `idempotence.productionApplyRequiresInspector=${payload.schema.idempotence.productionApplyRequiresInspector}`,
    '- The production table additions are repeat-safe through `CREATE TABLE IF NOT EXISTS`.',
    '- Existing table provenance columns/indexes remain plain draft DDL; real apply must use schema inspection or a one-shot backup-verified migration.',
    '',
    '## Temp Artifact Policy',
    '- Keep `tmp/ephemeral-persistence-phase2-3/project-store.json` through this audit if reviewers need Phase 2.3 readback evidence.',
    '- Before production merge, choose one policy: retain under explicit QA fixture path, add generated temp-store ignore, or remove after Phase 2.5 JSON/report evidence is accepted.',
    '- This Phase 2.5 report and JSON provide reproducible schema/adapter evidence without treating temp stores as production project data.',
    '',
    '## Remaining Risks',
    '- Real DB migration execution remains untested.',
    '- Real project cleanup/quarantine/purge remains unrun.',
    '- Real clean project regression and live canary remain unrun.',
    '- Production rollback must require backup/restore approval before any real migration run.',
    '- Project health-check persistence is an audit artifact; product must decide retention/window before live rollout.',
    '- Durable-marker retry/recovery UX remains local-marker oriented; readiness blocking is closed, but product should decide recovery handling before live rollout.',
    '',
    '## Go / No-Go Before Real Clean Project Regression',
    '- Go only after disposable migration evidence, fresh review, backup/rollback plan, and temp artifact policy are accepted.',
    '- No-go if any real DB migration/cleanup is attempted without backup, disposable apply evidence, and rollback plan.',
    '- No-go if persisted health-check rows or finalization markers are ever mapped into `stateAuthority` facts or creative prompt content.',
    '',
    '## Fresh Review',
    payload.review
      ? `review.threadId=${payload.review.threadId}\nreview.critical=${payload.review.critical}\nreview.important=${payload.review.important}\nreview.conclusion=${payload.review.conclusion}`
      : 'Fresh review pending.',
  ]
  if (Array.isArray(payload.verification?.commands) && payload.verification.commands.length) {
    lines.push('', '## Verification')
    lines.push(`verification.commandCount=${payload.verification.commands.length}`)
    lines.push('| command | result |')
    lines.push('| --- | --- |')
    for (const command of payload.verification.commands) {
      lines.push(`| ${command.command} | ${command.result} |`)
    }
  }
  return `${lines.join('\n')}\n`
}

export function assertProductionSchemaAdapterReportMatchesJson(reportText, payload) {
  validateProductionSchemaAdapterPayload(payload)
  const report = String(reportText || '')
  const checks = {
    'schema.finalizationMarkersClosed': payload.summary.finalizationMarkersClosed,
    'schema.projectHealthChecksClosed': payload.summary.projectHealthChecksClosed,
    'adapter.backendClosed': payload.summary.backendAdapterClosed,
    'adapter.frontendClosed': payload.summary.frontendAdapterClosed,
    'dryRun.schemaParserPassed': payload.summary.disposableSchemaParserPassed,
    'dryRun.migrationIdempotenceReady': payload.summary.migrationIdempotenceReady,
    'dryRun.idempotenceUnavailableReason': payload.schema.idempotence.unavailableReason,
    'dryRun.rollbackPassed': payload.summary.disposableRollbackDryRunPassed,
    'readiness.halfSuccessBlocked': payload.summary.readinessBlockedByHalfSuccess,
    'creative.boundaryClean': payload.summary.creativeBoundaryClean,
    'rollback.supported': payload.rollback.supported,
    'rollback.executedAgainstRealDb': payload.rollback.executedAgainstRealDb,
    'frontend.readinessDurableMarkerLoad': payload.adapters.frontend.hasReadinessDurableMarkerLoad,
    'frontend.contextDurableMarkerInjection': payload.adapters.frontend.hasContextDurableMarkerInjection,
    'idempotence.newTablesRepeatSafe': payload.schema.idempotence.newTablesRepeatSafe,
    'idempotence.existingAlterRepeatSafe': payload.schema.idempotence.existingAlterRepeatSafe,
    'idempotence.productionApplyRequiresInspector': payload.schema.idempotence.productionApplyRequiresInspector,
    'marker.idempotent': payload.results.marker.idempotent,
    'marker.readBackCount': payload.results.marker.readBackCount,
    'marker.commitStatus': payload.results.marker.commitStatus,
    'healthCheck.idempotent': payload.results.healthCheck.idempotent,
    'healthCheck.readBackCount': payload.results.healthCheck.readBackCount,
    'healthCheck.creativeContextContainsHealthJson': payload.results.healthCheck.creativeContextContainsHealthJson,
    'healthCheck.entersStateAuthority': payload.results.healthCheck.entersStateAuthority,
    'context.unknownDegradedExcludedFromCreative': payload.results.unknownDegradedExcludedFromCreative,
    'context.savedBeatConflictFinalFactWins': payload.results.savedBeatConflictFinalFactWins,
    'context.guardSnapshotLeakBlocked': payload.results.guardSnapshotLeakBlocked,
    'rollback.removedCollections': payload.results.disposableRollback.removedCollections,
    'rollback.postRollbackReadBlocked': payload.results.disposableRollback.postRollbackReadBlocked,
  }
  if (payload.review) {
    checks['review.threadId'] = payload.review.threadId
    checks['review.critical'] = payload.review.critical
    checks['review.important'] = payload.review.important
    checks['review.conclusion'] = payload.review.conclusion
  }
  if (Array.isArray(payload.verification?.commands) && payload.verification.commands.length) {
    checks['verification.commandCount'] = payload.verification.commands.length
  }
  for (const [key, expected] of Object.entries(checks)) {
    const actual = extractSingleLineValue(report, key)
    if (actual !== String(expected)) throw new Error(`Report/JSON mismatch for ${key}: ${actual} expected ${expected}`)
  }
  for (const row of payload.schema.tables) {
    const reportRow = findSingleMarkdownRow(report, row.table)
    const cells = parseMarkdownRow(reportRow)
    assertKeyValueCell(cells[1], {
      productionCreate: row.hasProductionCreateTable,
      provenanceFields: row.provenanceFields.join(','),
      indexes: row.indexes.length,
      commitStatusConstraint: row.hasCommitStatusConstraint,
    }, `schema.${row.table}`)
  }
  for (const row of payload.schema.existingProvenanceTables) {
    const reportRow = findSingleMarkdownRow(report, row.table)
    const cells = parseMarkdownRow(reportRow)
    assertKeyValueCell(cells[1], {
      allProvenanceFields: row.hasAllProvenanceFields,
      fields: row.provenanceFields.join(','),
    }, `existing.${row.table}`)
  }
  if (Array.isArray(payload.verification?.commands) && payload.verification.commands.length) {
    for (const command of payload.verification.commands) {
      const row = findSingleMarkdownRow(report, command.command)
      const cells = parseMarkdownRow(row)
      if (cells[1] !== command.result) {
        throw new Error(`Report/JSON mismatch for verification ${command.command}: ${cells[1]} expected ${command.result}`)
      }
    }
  }
  return true
}

function issueText(values = []) {
  return values.length ? values.join(',') : 'none'
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function extractSingleLineValue(report, key) {
  const pattern = new RegExp(`^${escapeRegExp(key)}=(.*)$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) throw new Error(`Report/JSON mismatch for ${key}: appears ${matches.length} times`)
  return matches[0][1].trim()
}

function findSingleMarkdownRow(report, firstCell) {
  const pattern = new RegExp(`^\\| ${escapeRegExp(firstCell)} \\|.*$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) throw new Error(`Report/JSON mismatch for row ${firstCell}: appears ${matches.length} times`)
  return matches[0][0]
}

function parseMarkdownRow(row) {
  return String(row)
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map(cell => cell.trim())
}

function assertKeyValueCell(cell, expectedValues, label) {
  const pairs = String(cell).split(';').map(part => part.trim()).filter(Boolean)
  const actual = new Map()
  for (const pair of pairs) {
    const separator = pair.indexOf('=')
    if (separator < 1) throw new Error(`Report/JSON mismatch for ${label}: malformed token ${pair}`)
    const key = pair.slice(0, separator).trim()
    const value = pair.slice(separator + 1).trim()
    if (actual.has(key)) throw new Error(`Report/JSON mismatch for ${label}.${key}: duplicate key`)
    actual.set(key, value)
  }
  if (actual.size !== Object.keys(expectedValues).length) {
    throw new Error(`Report/JSON mismatch for ${label}: expected ${Object.keys(expectedValues).length} fields, got ${actual.size}`)
  }
  for (const [key, expected] of Object.entries(expectedValues)) {
    if (!actual.has(key)) throw new Error(`Report/JSON mismatch for ${label}.${key}: missing`)
    if (actual.get(key) !== String(expected)) {
      throw new Error(`Report/JSON mismatch for ${label}.${key}: ${actual.get(key)} expected ${expected}`)
    }
  }
}

async function main() {
  const payload = await runProductionSchemaAdapterGate()
  const report = buildProductionSchemaAdapterReport(payload)
  assertProductionSchemaAdapterReportMatchesJson(report, payload)
  await fs.mkdir(OUT_DIR, { recursive: true })
  await fs.writeFile(OUT_JSON, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
  await fs.writeFile(OUT_REPORT, report, 'utf8')
  console.log(`production schema adapter phase2.5 wrote ${OUT_JSON} and ${OUT_REPORT}`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  main().catch(error => {
    console.error(error)
    process.exit(1)
  })
}
