import fs from 'node:fs/promises'
import fsSync from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  validateProductionSchemaAdapterPayload,
} from './run_production_schema_adapter_phase2_5.mjs'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const ROOT_DIR = path.resolve(__dirname, '..')
const OUT_DIR = path.join(__dirname, 'realistic-flow-qa')
const SIM_DIR = path.join(__dirname, 'idempotent-migration-inspector-phase2-6')
const SIM_PATH = path.join(SIM_DIR, 'schema-simulator.json')
const OUT_JSON = path.join(OUT_DIR, 'idempotent-migration-inspector-phase2-6.json')
const OUT_REPORT = path.join(OUT_DIR, 'idempotent-migration-inspector-phase2-6-report.md')
const MIGRATION_PATH = path.join(ROOT_DIR, 'backend', 'migrations', '20260705_state_provenance_phase1_2.sql')
const ROLLBACK_PATH = path.join(ROOT_DIR, 'backend', 'migrations', '20260705_state_provenance_phase1_2_rollback.sql')
const PHASE25_JSON = path.join(OUT_DIR, 'production-schema-adapter-phase2-5.json')

const PRODUCTION_DIFF_FILES = [
  path.join(ROOT_DIR, 'backend', 'migrations', '20260705_state_provenance_phase1_2.sql'),
  path.join(ROOT_DIR, 'backend', 'migrations', '20260705_state_provenance_phase1_2_rollback.sql'),
  path.join(ROOT_DIR, 'backend', 'routers', 'project_state.py'),
  path.join(ROOT_DIR, 'frontend', 'src', 'views', 'WriterView.vue'),
  path.join(ROOT_DIR, 'frontend', 'src', 'api', 'db', 'client.js'),
]
const CREATED_AUDIT_TABLES = new Set(['finalization_markers', 'project_health_checks'])

function readText(filePath) {
  return fsSync.readFileSync(filePath, 'utf8')
}

function normalizeDefinition(value) {
  return String(value || '')
    .replace(/`/g, '')
    .replace(/\s+/g, ' ')
    .replace(/\s*,\s*/g, ', ')
    .trim()
    .toLowerCase()
}

function splitTopLevelLines(body) {
  const lines = []
  let current = ''
  let depth = 0
  for (const rawLine of body.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) continue
    for (const char of line) {
      if (char === '(') depth += 1
      if (char === ')') depth = Math.max(0, depth - 1)
    }
    current = current ? `${current} ${line}` : line
    if (depth === 0 && /,$/.test(line)) {
      lines.push(current.replace(/,$/, '').trim())
      current = ''
    }
  }
  if (current) lines.push(current.replace(/,$/, '').trim())
  return lines
}

export function inspectMigrationOperations(sqlText = readText(MIGRATION_PATH)) {
  const operations = []
  const alterMatches = [...sqlText.matchAll(/ALTER TABLE\s+([a-z_]+)([\s\S]*?);/gi)]
  for (const match of alterMatches) {
    const table = match[1]
    const columnClauses = match[2].split(/,\s*(?=ADD COLUMN\b)/i)
    for (const clause of columnClauses) {
      const column = clause.match(/ADD COLUMN\s+([a-z_]+)\s+([\s\S]*)/i)
      if (!column) continue
      const sourceSql = compact(clause, 1000)
      operations.push({
        type: 'add_column',
        table,
        column: column[1],
        key: `${table}.${column[1]}`,
        definition: normalizeDefinition(`${column[1]} ${column[2]}`),
        sourceSql,
        destructive: false,
      })
    }
  }

  const createIndexMatches = [...sqlText.matchAll(/CREATE\s+(UNIQUE\s+)?INDEX\s+([a-z_]+)\s+ON\s+([a-z_]+)\s*\(([^)]+)\);/gi)]
  for (const match of createIndexMatches) {
    const unique = Boolean(match[1])
    const index = match[2]
    const table = match[3]
    operations.push({
      type: unique ? 'create_unique_index' : 'create_index',
      table,
      index,
      key: index,
      definition: normalizeDefinition(`${unique ? 'UNIQUE ' : ''}INDEX ${index} ON ${table} (${match[4]})`),
      sourceSql: match[0],
      destructive: false,
    })
  }

  const createTableMatches = [...sqlText.matchAll(/CREATE TABLE IF NOT EXISTS\s+([a-z_]+)\s*\(([\s\S]*?)\)\s*ENGINE=/gi)]
  for (const match of createTableMatches) {
    const table = match[1]
    const body = match[2]
    operations.push({
      type: 'create_table',
      table,
      key: table,
      definition: normalizeDefinition(`CREATE TABLE ${table}`),
      sourceSql: match[0],
      destructive: false,
    })
    for (const line of splitTopLevelLines(body)) {
      if (/^(UNIQUE\s+KEY|INDEX|KEY)\b/i.test(line)) {
        const index = line.match(/(?:UNIQUE\s+KEY|INDEX|KEY)\s+([a-z_]+)/i)?.[1]
        if (index) {
          operations.push({
            type: /UNIQUE/i.test(line) ? 'create_unique_index' : 'create_index',
            table,
            index,
            key: `${table}.${index}`,
            definition: normalizeDefinition(line),
            sourceSql: line,
            destructive: false,
          })
        }
      } else if (/^(CONSTRAINT|CHECK)\b/i.test(line)) {
        const constraint = line.match(/CONSTRAINT\s+([a-z_]+)/i)?.[1] || `${table}_check_${operations.length}`
        operations.push({
          type: 'add_constraint',
          table,
          constraint,
          key: `${table}.${constraint}`,
          definition: normalizeDefinition(line),
          sourceSql: line,
          destructive: false,
        })
      } else {
        const column = line.match(/^([a-z_]+)\s+/i)?.[1]
        if (column) {
          operations.push({
            type: 'add_column',
            table,
            column,
            key: `${table}.${column}`,
            definition: normalizeDefinition(line),
            sourceSql: line,
            destructive: false,
          })
          if (/\bPRIMARY\s+KEY\b/i.test(line)) {
            operations.push({
              type: 'add_constraint',
              table,
              constraint: 'primary_key',
              key: `${table}.primary_key`,
              definition: normalizeDefinition(line),
              sourceSql: line,
              destructive: false,
            })
          }
        }
      }
    }
  }
  return dedupeOperations(operations)
}

function dedupeOperations(operations) {
  const seen = new Set()
  const result = []
  for (const operation of operations) {
    const key = `${operation.type}:${operation.key}`
    if (seen.has(key)) continue
    seen.add(key)
    result.push(operation)
  }
  return result
}

function createEmptySchema() {
  return {
    tables: {},
  }
}

function ensureTable(schema, table) {
  if (!schema.tables[table]) {
    schema.tables[table] = { definition: '', columns: {}, indexes: {}, constraints: {} }
  }
  schema.tables[table].columns = normalizeObjectMap(schema.tables[table].columns)
  schema.tables[table].indexes = normalizeObjectMap(schema.tables[table].indexes)
  schema.tables[table].constraints = normalizeObjectMap(schema.tables[table].constraints)
  return schema.tables[table]
}

function normalizeObjectMap(value) {
  if (Array.isArray(value)) {
    return Object.fromEntries(value.map(name => [name, { definition: '' }]))
  }
  return value || {}
}

function getExistingObject(schema, operation) {
  const table = schema.tables[operation.table]
  if (operation.type === 'create_table') return table ? { definition: table.definition || '' } : null
  if (!table) return null
  table.columns = normalizeObjectMap(table.columns)
  table.indexes = normalizeObjectMap(table.indexes)
  table.constraints = normalizeObjectMap(table.constraints)
  if (operation.type === 'add_column') return table.columns[operation.column] || null
  if (operation.type === 'create_index' || operation.type === 'create_unique_index') return table.indexes[operation.index] || null
  if (operation.type === 'add_constraint') return table.constraints[operation.constraint] || null
  return null
}

function inspectExistingObject(schema, operation) {
  const existing = getExistingObject(schema, operation)
  if (!existing) return { exists: false, matches: false, reason: 'missing' }
  if (operation.definition && !existing.definition) {
    return {
      exists: true,
      matches: false,
      reason: 'missing_existing_definition',
      existingDefinition: '',
      expectedDefinition: operation.definition,
    }
  }
  if (!operation.definition) return { exists: true, matches: true, reason: '' }
  const existingDefinition = normalizeDefinition(existing.definition)
  if (existingDefinition !== operation.definition) {
    return {
      exists: true,
      matches: false,
      reason: 'definition_mismatch',
      existingDefinition,
      expectedDefinition: operation.definition,
    }
  }
  return { exists: true, matches: true, reason: '' }
}

function applyOperation(schema, operation) {
  const table = ensureTable(schema, operation.table)
  if (operation.type === 'create_table') {
    if (!table.definition) table.definition = operation.definition || ''
    return
  }
  if (operation.type === 'add_column' && !table.columns[operation.column]) {
    table.columns[operation.column] = { definition: operation.definition || '', sourceSql: operation.sourceSql }
  }
  if ((operation.type === 'create_index' || operation.type === 'create_unique_index') && !table.indexes[operation.index]) {
    table.indexes[operation.index] = { definition: operation.definition || '', sourceSql: operation.sourceSql }
  }
  if (operation.type === 'add_constraint' && !table.constraints[operation.constraint]) {
    table.constraints[operation.constraint] = { definition: operation.definition || '', sourceSql: operation.sourceSql }
  }
}

export function buildPlan(operations, schema, label) {
  const working = JSON.parse(JSON.stringify(schema))
  const planItems = operations.map(operation => {
    const existing = inspectExistingObject(working, operation)
    const action = existing.exists
      ? existing.matches ? 'skip_existing' : 'needs_manual_review'
      : 'apply'
    if (action === 'apply') applyOperation(working, operation)
    return {
      action,
      type: operation.type,
      table: operation.table,
      column: operation.column || '',
      index: operation.index || '',
      constraint: operation.constraint || '',
      key: operation.key,
      needsManualReview: action === 'needs_manual_review',
      reason: action === 'needs_manual_review' ? existing.reason : '',
      expectedDefinition: action === 'needs_manual_review' ? existing.expectedDefinition : '',
      existingDefinition: action === 'needs_manual_review' ? existing.existingDefinition : '',
      destructive: false,
      sourceSql: compact(operation.sourceSql, 260),
    }
  })
  const applyCount = planItems.filter(item => item.action === 'apply').length
  const skipExistingCount = planItems.filter(item => item.action === 'skip_existing').length
  const needsManualReviewCount = planItems.filter(item => item.action === 'needs_manual_review').length
  return {
    label,
    applyCount,
    skipExistingCount,
    needsManualReviewCount,
    duplicateApplyCount: detectDuplicateApplies(planItems),
    destructiveApplyCount: planItems.filter(item => item.destructive).length,
    planItems,
    resultingSchema: working,
  }
}

function detectDuplicateApplies(planItems) {
  const applied = new Set()
  let duplicates = 0
  for (const item of planItems) {
    if (item.action !== 'apply') continue
    if (applied.has(item.key)) duplicates += 1
    applied.add(item.key)
  }
  return duplicates
}

export function schemaWithFirstNOperations(operations, count) {
  const schema = createEmptySchema()
  for (const operation of operations.slice(0, count)) applyOperation(schema, operation)
  return schema
}

function rollbackPlan(operations = inspectMigrationOperations(), rollbackSql = readText(ROLLBACK_PATH)) {
  const items = []
  for (const match of rollbackSql.matchAll(/DROP TABLE IF EXISTS\s+([a-z_]+);/gi)) {
    items.push({
      action: 'drop_created_table',
      key: match[1],
      table: match[1],
      sourceSql: match[0],
      requiresBackupApproval: true,
      destructive: true,
    })
  }
  const dropTables = new Set(items.filter(item => item.action === 'drop_created_table').map(item => item.table))
  const irreversibleOperations = operations.filter(operation => !dropTables.has(operation.table))
  if (irreversibleOperations.length) {
    items.push({
      action: 'backup_restore_required',
      key: 'existing_table_provenance_alters',
      sourceSql: 'Rollback draft intentionally leaves existing-table provenance columns/indexes in place; real recovery requires verified backup/restore or a separate reviewed down migration.',
      requiresBackupApproval: true,
      destructive: false,
      affectedOperationCount: irreversibleOperations.length,
    })
  }
  const tableRollbackAvailable = items.some(item => item.key === 'finalization_markers') &&
    items.some(item => item.key === 'project_health_checks')
  const fullRollbackAvailable = tableRollbackAvailable && irreversibleOperations.length === 0
  return {
    planAvailable: tableRollbackAvailable,
    tableRollbackAvailable,
    fullRollbackAvailable,
    requiresBackupRestoreForIrreversibleAlter: irreversibleOperations.length > 0,
    irreversibleOperationCount: irreversibleOperations.length,
    executedAgainstRealDb: false,
    items,
  }
}

function backupPreflight(input = {}) {
  const mode = input.mode || 'real_apply'
  const hasBackup = Boolean(input.backupPlan?.snapshotId && input.backupPlan?.restoreProcedure)
  const hasVerifiedRestore = Boolean(input.backupPlan?.restoreVerified)
  const hasTargetIdentity = Boolean(input.target?.environment && input.target?.databaseName && input.target?.hostFingerprint)
  const hasDryRun = Boolean(input.dryRunDiff?.inspectorPlanId && input.dryRunDiff?.operationCount >= 0)
  const hasTableRollback = Boolean(input.rollbackPlan?.tableRollbackAvailable)
  const hasRecoveryForIrreversibleAlter = Boolean(input.rollbackPlan?.fullRollbackAvailable) ||
    (Boolean(input.rollbackPlan?.requiresBackupRestoreForIrreversibleAlter) && hasVerifiedRestore)
  const disposableAllowed = mode === 'disposable_dry_run' &&
    input.target?.environment === 'disposable' &&
    hasTargetIdentity &&
    hasDryRun &&
    input.explicitApproval === true
  const realApplyAllowed = mode === 'real_apply' &&
    hasBackup &&
    hasVerifiedRestore &&
    hasTargetIdentity &&
    hasDryRun &&
    hasTableRollback &&
    hasRecoveryForIrreversibleAlter &&
    input.explicitApproval === true
  const allowed = disposableAllowed || realApplyAllowed
  const blockedReason = allowed ? ''
    : !hasBackup && mode === 'real_apply' ? 'backup_restore_plan_required'
      : mode === 'real_apply' && !hasVerifiedRestore ? 'backup_restore_verification_required'
        : mode === 'real_apply' && !hasTableRollback ? 'rollback_plan_required'
          : mode === 'real_apply' && !hasRecoveryForIrreversibleAlter ? 'backup_restore_required_for_irreversible_alter'
            : 'backup_restore_plan_required'
  return {
    mode,
    allowed,
    blocked: !allowed,
    blockedReason,
    realDbDsnPresent: Boolean(input.realDbDsn),
  }
}

function loadPhase25Regression() {
  const payload = JSON.parse(readText(PHASE25_JSON))
  validateProductionSchemaAdapterPayload(payload)
  return {
    finalizationMarkersClosed: payload.summary.finalizationMarkersClosed,
    projectHealthChecksClosed: payload.summary.projectHealthChecksClosed,
    durableReadinessWired: Boolean(payload.adapters.frontend.hasReadinessDurableMarkerLoad && payload.adapters.frontend.hasContextDurableMarkerInjection),
    healthArtifactsStayOutOfCreativeContext: payload.summary.creativeBoundaryClean,
    migrationIdempotenceReady: payload.summary.migrationIdempotenceReady,
  }
}

function boundaryScan() {
  const hits = []
  const patterns = [
    ['issueIds', /#98|第98|#99|第99|#50|第50/g],
    ['longformBrowser', /LongformBrowser/g],
    ['realDbDsn', /DATABASE_URL|REAL_DB|PROD_DB|mysql:\/\/|postgres:\/\/|sqlite:\/\//g],
  ]
  for (const filePath of PRODUCTION_DIFF_FILES) {
    const text = readText(filePath)
    for (const [category, pattern] of patterns) {
      pattern.lastIndex = 0
      if (pattern.test(text)) hits.push({ category, file: filePath })
    }
  }
  return {
    productionHardcodedIssueIds: hits.some(hit => hit.category === 'issueIds'),
    longformBrowserInProductionDiff: hits.some(hit => hit.category === 'longformBrowser'),
    realDbDsnInPhase26: hits.some(hit => hit.category === 'realDbDsn'),
    hits,
  }
}

async function writeSimulatorArtifact(payload) {
  await fs.mkdir(SIM_DIR, { recursive: true })
  await fs.writeFile(SIM_PATH, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
}

function buildSummary(plans, rollback, backupGate, phase25Regression, boundary) {
  return {
    inspectorPlanIdempotent: plans.freshSchema.duplicateApplyCount === 0 &&
      plans.freshSchema.needsManualReviewCount === 0 &&
      plans.partialSchema.duplicateApplyCount === 0 &&
      plans.partialSchema.needsManualReviewCount === 0 &&
      plans.fullSchema.needsManualReviewCount === 0 &&
      plans.fullSchema.applyCount === 0 &&
      plans.fullSchema.duplicateApplyCount === 0,
    realApplyExecuted: false,
    backupGateBlocksUnsafeApply: backupGate.unsafeApplyBlocked,
    rollbackPlanAvailable: rollback.planAvailable,
    phase25SchemaAdapterStillClosed: phase25Regression.finalizationMarkersClosed &&
      phase25Regression.projectHealthChecksClosed &&
      phase25Regression.durableReadinessWired &&
      phase25Regression.healthArtifactsStayOutOfCreativeContext,
    boundaryClean: !boundary.productionHardcodedIssueIds &&
      !boundary.longformBrowserInProductionDiff &&
      !boundary.realDbDsnInPhase26,
  }
}

export async function runIdempotentMigrationInspectorGate() {
  const operations = inspectMigrationOperations()
  const freshSchema = createEmptySchema()
  const partialSchema = schemaWithFirstNOperations(operations, Math.floor(operations.length / 2))
  const fullSchema = schemaWithFirstNOperations(operations, operations.length)
  const plans = {
    freshSchema: buildPlan(operations, freshSchema, 'fresh_schema'),
    partialSchema: buildPlan(operations, partialSchema, 'partial_schema'),
    fullSchema: buildPlan(operations, fullSchema, 'full_schema'),
  }
  const rollback = rollbackPlan(operations)
  const unsafeGate = backupPreflight({})
  const disposableGate = backupPreflight({
    mode: 'disposable_dry_run',
    target: { environment: 'disposable', databaseName: 'schema-simulator', hostFingerprint: 'tmp-only' },
    dryRunDiff: { inspectorPlanId: 'phase2-6-disposable-plan', operationCount: operations.length },
    explicitApproval: true,
  })
  const realApplyWithoutRestoreGate = backupPreflight({
    mode: 'real_apply',
    backupPlan: { snapshotId: 'disposable-backup-plan', restoreProcedure: 'restore from verified backup before migration retry' },
    target: { environment: 'production-preflight-placeholder', databaseName: 'target-identity-required', hostFingerprint: 'not-connected' },
    dryRunDiff: { inspectorPlanId: 'phase2-6-disposable-plan', operationCount: operations.length },
    rollbackPlan: rollback,
    explicitApproval: true,
  })
  const backupGate = {
    unsafeApplyBlocked: unsafeGate.blocked,
    safeApplyAllowed: false,
    disposableDryRunAllowed: disposableGate.allowed,
    realApplyWithoutRestoreBlocked: realApplyWithoutRestoreGate.blocked,
    blockedReason: unsafeGate.blockedReason,
    realDbDsnPresent: unsafeGate.realDbDsnPresent ||
      disposableGate.realDbDsnPresent ||
      realApplyWithoutRestoreGate.realDbDsnPresent,
  }
  const phase25Regression = loadPhase25Regression()
  const boundary = boundaryScan()
  const summary = buildSummary(plans, rollback, backupGate, phase25Regression, boundary)
  const simulatorPayload = {
    schemaVersion: 'idempotent-migration-schema-simulator-phase2-6-v1',
    syntheticOnly: true,
    realDbConnection: false,
    operationCount: operations.length,
    plans,
  }
  await writeSimulatorArtifact(simulatorPayload)

  return {
    schemaVersion: 'idempotent-migration-inspector-phase2-6-v1',
    status: 'completed',
    timestamp: new Date().toISOString(),
    boundary: {
      realApplyExecuted: false,
      touchesRealDb: false,
      usesRealProject: false,
      startsService: false,
    },
    simulator: {
      strategy: 'in-memory-schema-simulator-plus-json-artifact',
      path: SIM_PATH,
      syntheticOnly: true,
      realDbConnection: false,
    },
    operations: {
      total: operations.length,
      keys: operations.map(operation => operation.key),
      items: operations,
    },
    plans,
    rollback,
    backupGate,
    phase25Regression,
    boundaryScan: boundary,
    summary,
  }
}

export function validateIdempotentMigrationPayload(payload = {}) {
  if (payload.schemaVersion !== 'idempotent-migration-inspector-phase2-6-v1') {
    throw new Error('Invalid Phase 2.6 idempotent migration inspector schemaVersion')
  }
  if (payload.status !== 'completed') return true
  if (payload.boundary?.realApplyExecuted !== false) throw new Error('realApplyExecuted must be false')
  if (payload.boundary?.touchesRealDb !== false) throw new Error('touchesRealDb must be false')
  if (!String(payload.simulator?.path || '').includes('tmp')) throw new Error('simulator artifact must be under tmp')
  if (payload.operations?.total < 40) throw new Error('migration operation coverage too small')
  if (payload.operations?.total !== payload.operations?.items?.length) throw new Error('operation item count mismatch')
  if (payload.operations?.total !== payload.operations?.keys?.length) throw new Error('operation key count mismatch')
  for (const key of ['finalization_markers.primary_key', 'project_health_checks.primary_key']) {
    if (!payload.operations.keys.includes(key)) throw new Error(`missing inline primary key operation ${key}`)
  }
  for (const key of ['freshSchema', 'partialSchema', 'fullSchema']) {
    const plan = payload.plans?.[key]
    if (!plan) throw new Error(`missing plan ${key}`)
    if (plan.duplicateApplyCount !== 0) throw new Error(`${key} must not duplicate apply`)
    if (plan.destructiveApplyCount !== 0) throw new Error(`${key} must not contain destructive apply`)
  }
  if (payload.plans.fullSchema.applyCount !== 0) throw new Error('fully migrated schema must not apply')
  if (payload.plans.fullSchema.needsManualReviewCount !== 0) throw new Error('fully migrated schema must not require manual review')
  if (payload.rollback?.tableRollbackAvailable !== true) throw new Error('table rollback must be available')
  if (payload.rollback?.fullRollbackAvailable !== false) throw new Error('full rollback must stay false without existing-table down migration')
  if (payload.rollback?.requiresBackupRestoreForIrreversibleAlter !== true) {
    throw new Error('irreversible existing-table alters must require backup/restore')
  }
  if (payload.backupGate?.safeApplyAllowed !== false) throw new Error('real safe apply must not be allowed in Phase 2.6')
  if (payload.backupGate?.disposableDryRunAllowed !== true) throw new Error('disposable dry-run should be allowed')
  if (payload.backupGate?.realApplyWithoutRestoreBlocked !== true) throw new Error('real apply without restore verification must be blocked')
  const expectedSummary = buildSummary(payload.plans, payload.rollback, payload.backupGate, payload.phase25Regression, payload.boundaryScan)
  for (const [key, expected] of Object.entries(expectedSummary)) {
    if (payload.summary?.[key] !== expected) throw new Error(`summary.${key} mismatch`)
  }
  if (!payload.summary.inspectorPlanIdempotent) throw new Error('inspector plan must be idempotent')
  if (!payload.summary.backupGateBlocksUnsafeApply) throw new Error('backup gate must block unsafe apply')
  if (!payload.summary.rollbackPlanAvailable) throw new Error('rollback plan must be available')
  if (!payload.summary.phase25SchemaAdapterStillClosed) throw new Error('Phase 2.5 schema adapter evidence regressed')
  return true
}

export function buildIdempotentMigrationReport(payload) {
  validateIdempotentMigrationPayload(payload)
  const lines = [
    '# Idempotent Migration Inspector Phase 2.6 Report',
    '',
    'Status: completed schema-inspector/disposable dry-run. This is not a real DB migration, real project cleanup, clean regression, canary, or live chapter run.',
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
    `inspector.inspectorPlanIdempotent=${payload.summary.inspectorPlanIdempotent}`,
    `boundary.realApplyExecuted=${payload.summary.realApplyExecuted}`,
    `backupGate.unsafeApplyBlocked=${payload.summary.backupGateBlocksUnsafeApply}`,
    `rollback.planAvailable=${payload.summary.rollbackPlanAvailable}`,
    `phase25.schemaAdapterStillClosed=${payload.summary.phase25SchemaAdapterStillClosed}`,
    `boundary.boundaryClean=${payload.summary.boundaryClean}`,
    '',
    '## Operation Coverage',
    `operations.total=${payload.operations.total}`,
    `operations.includesFinalizationMarkers=${payload.operations.keys.includes('finalization_markers')}`,
    `operations.includesProjectHealthChecks=${payload.operations.keys.includes('project_health_checks')}`,
    `operations.includesChapterVersionsProvenance=${payload.operations.keys.includes('chapter_versions.provenance')}`,
    '',
    '## Schema Simulation Plans',
    '| scenario | apply | skip_existing | needs_manual_review | duplicate_apply | destructive_apply |',
    '| --- | --- | --- | --- | --- | --- |',
    ...Object.entries(payload.plans).map(([key, plan]) =>
      `| ${key} | ${plan.applyCount} | ${plan.skipExistingCount} | ${plan.needsManualReviewCount} | ${plan.duplicateApplyCount} | ${plan.destructiveApplyCount} |`
    ),
    '',
    '## Backup / Recovery Gate',
    `backupGate.safeApplyAllowed=${payload.backupGate.safeApplyAllowed}`,
    `backupGate.disposableDryRunAllowed=${payload.backupGate.disposableDryRunAllowed}`,
    `backupGate.realApplyWithoutRestoreBlocked=${payload.backupGate.realApplyWithoutRestoreBlocked}`,
    `backupGate.blockedReason=${payload.backupGate.blockedReason}`,
    `backupGate.realDbDsnPresent=${payload.backupGate.realDbDsnPresent}`,
    '',
    '## Rollback Plan',
    `rollback.executedAgainstRealDb=${payload.rollback.executedAgainstRealDb}`,
    `rollback.tableRollbackAvailable=${payload.rollback.tableRollbackAvailable}`,
    `rollback.fullRollbackAvailable=${payload.rollback.fullRollbackAvailable}`,
    `rollback.requiresBackupRestoreForIrreversibleAlter=${payload.rollback.requiresBackupRestoreForIrreversibleAlter}`,
    `rollback.irreversibleOperationCount=${payload.rollback.irreversibleOperationCount}`,
    `rollback.items=${payload.rollback.items.map(item => `${item.action}:${item.key}`).join(',')}`,
    '',
    '## Phase 2.5 Regression',
    `phase25.finalizationMarkersClosed=${payload.phase25Regression.finalizationMarkersClosed}`,
    `phase25.projectHealthChecksClosed=${payload.phase25Regression.projectHealthChecksClosed}`,
    `phase25.durableReadinessWired=${payload.phase25Regression.durableReadinessWired}`,
    `phase25.healthArtifactsStayOutOfCreativeContext=${payload.phase25Regression.healthArtifactsStayOutOfCreativeContext}`,
    `phase25.migrationIdempotenceReady=${payload.phase25Regression.migrationIdempotenceReady}`,
    '',
    '## Temp Artifact Policy',
    '- Keep Phase 2.3 / Phase 2.5 / Phase 2.6 temp stores through this audit if reviewers need reproducible evidence.',
    '- Before production merge, choose one policy: retain under explicit QA fixture path, add generated temp-store ignore, or remove after JSON/report evidence is accepted.',
    '- These artifacts are synthetic only and must not be treated as production project data.',
    '',
    '## Remaining Risks',
    '- Real DB migration execution remains untested.',
    '- Real project cleanup/quarantine/purge remains unrun.',
    '- Real clean project regression and live canary remain unrun.',
    '- The inspector is a deterministic contract over parsed DDL and mock metadata; real apply still requires backup/restore approval, verified restore rehearsal, target DB identity review, and dry-run diff approval.',
    '- Table rollback is available for Phase 2.5 audit tables, but full rollback is not available for existing-table ALTER/INDEX operations; those require backup/restore or a separate reviewed down migration.',
    '- Durable-marker retry/recovery UX remains a live-before-rollout product item from Phase 2.5.',
    '',
    '## Go / No-Go Before Real Clean Project Regression',
    '- Go only after inspector plan, backup/recovery preflight, fresh review, and temp artifact policy are accepted.',
    '- No-go if any real DB migration/cleanup is attempted without backup, verified restore path, target DB identity, dry-run diff, rollback/down-plan, and explicit approval.',
    '- No-go if persisted health-check rows or finalization markers are mapped into `stateAuthority` facts or creative prompt content.',
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

export function assertIdempotentMigrationReportMatchesJson(reportText, payload) {
  validateIdempotentMigrationPayload(payload)
  const report = String(reportText || '')
  const checks = {
    'inspector.inspectorPlanIdempotent': payload.summary.inspectorPlanIdempotent,
    'boundary.realApplyExecuted': payload.summary.realApplyExecuted,
    'backupGate.unsafeApplyBlocked': payload.summary.backupGateBlocksUnsafeApply,
    'rollback.planAvailable': payload.summary.rollbackPlanAvailable,
    'phase25.schemaAdapterStillClosed': payload.summary.phase25SchemaAdapterStillClosed,
    'boundary.boundaryClean': payload.summary.boundaryClean,
    'operations.total': payload.operations.total,
    'operations.includesFinalizationMarkers': payload.operations.keys.includes('finalization_markers'),
    'operations.includesProjectHealthChecks': payload.operations.keys.includes('project_health_checks'),
    'operations.includesChapterVersionsProvenance': payload.operations.keys.includes('chapter_versions.provenance'),
    'backupGate.safeApplyAllowed': payload.backupGate.safeApplyAllowed,
    'backupGate.disposableDryRunAllowed': payload.backupGate.disposableDryRunAllowed,
    'backupGate.realApplyWithoutRestoreBlocked': payload.backupGate.realApplyWithoutRestoreBlocked,
    'backupGate.blockedReason': payload.backupGate.blockedReason,
    'backupGate.realDbDsnPresent': payload.backupGate.realDbDsnPresent,
    'rollback.executedAgainstRealDb': payload.rollback.executedAgainstRealDb,
    'rollback.tableRollbackAvailable': payload.rollback.tableRollbackAvailable,
    'rollback.fullRollbackAvailable': payload.rollback.fullRollbackAvailable,
    'rollback.requiresBackupRestoreForIrreversibleAlter': payload.rollback.requiresBackupRestoreForIrreversibleAlter,
    'rollback.irreversibleOperationCount': payload.rollback.irreversibleOperationCount,
    'phase25.finalizationMarkersClosed': payload.phase25Regression.finalizationMarkersClosed,
    'phase25.projectHealthChecksClosed': payload.phase25Regression.projectHealthChecksClosed,
    'phase25.durableReadinessWired': payload.phase25Regression.durableReadinessWired,
    'phase25.healthArtifactsStayOutOfCreativeContext': payload.phase25Regression.healthArtifactsStayOutOfCreativeContext,
    'phase25.migrationIdempotenceReady': payload.phase25Regression.migrationIdempotenceReady,
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
  for (const [key, plan] of Object.entries(payload.plans)) {
    const row = findSingleMarkdownRow(report, key)
    const cells = parseMarkdownRow(row)
    assertMarkdownCells(cells, [
      key,
      plan.applyCount,
      plan.skipExistingCount,
      plan.needsManualReviewCount,
      plan.duplicateApplyCount,
      plan.destructiveApplyCount,
    ], `plan.${key}`)
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

function compact(value, limit = 200) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit)}...` : text
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

function assertMarkdownCells(cells, expectedValues, label) {
  if (cells.length !== expectedValues.length) {
    throw new Error(`Report/JSON mismatch for ${label}: expected ${expectedValues.length} cells, got ${cells.length}`)
  }
  expectedValues.forEach((expected, index) => {
    if (cells[index] !== String(expected)) {
      throw new Error(`Report/JSON mismatch for ${label}[${index}]: ${cells[index]} expected ${expected}`)
    }
  })
}

async function main() {
  const payload = await runIdempotentMigrationInspectorGate()
  const report = buildIdempotentMigrationReport(payload)
  assertIdempotentMigrationReportMatchesJson(report, payload)
  await fs.mkdir(OUT_DIR, { recursive: true })
  await fs.writeFile(OUT_JSON, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
  await fs.writeFile(OUT_REPORT, report, 'utf8')
  console.log(`idempotent migration inspector phase2.6 wrote ${OUT_JSON} and ${OUT_REPORT}`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  main().catch(error => {
    console.error(error)
    process.exit(1)
  })
}
