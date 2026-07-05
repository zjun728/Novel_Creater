import fs from 'node:fs/promises'
import fsSync from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  checkProjectStateHealth,
  rebuildStateProjectionFromFinals,
} from '../frontend/src/utils/projectHealthCheck.js'
import {
  formatSceneExecutionCardForPrompt,
} from '../frontend/src/utils/sceneExecutionContract.js'
import {
  formatNarrativeVoiceContractForPrompt,
} from '../frontend/src/utils/narrativeVoiceContract.js'
import {
  evaluateLiteraryQuality,
  evaluatePromptQuality,
} from '../frontend/src/utils/literaryQualityEvaluator.js'
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
const EPHEMERAL_DIR = path.join(__dirname, 'ephemeral-persistence-phase2-3')
const STORE_PATH = path.join(EPHEMERAL_DIR, 'project-store.json')
const MIGRATION_PATH = path.join(ROOT_DIR, 'backend', 'migrations', '20260705_state_provenance_phase1_2.sql')
const OUT_JSON = path.join(OUT_DIR, 'ephemeral-persistence-regression-phase2-3.json')
const OUT_REPORT = path.join(OUT_DIR, 'ephemeral-persistence-regression-phase2-3-report.md')

const CURRENT_CHAPTER = 15
const REQUIRED_PROVENANCE_FIELDS = [
  'provenance',
  'source_chapter_num',
  'source_version_id',
  'run_id',
  'finalization_id',
  'commit_status',
]

const COLLECTION_TO_TABLE = {
  chapter_versions: 'chapter_versions',
  canon_facts: 'canon_facts',
  setting_entities: 'setting_entities',
  setting_relations: 'setting_relations',
  setting_change_events: 'setting_change_events',
  project_volumes: 'project_volumes',
  chapter_beat_plans: 'chapter_beat_plans',
  finalization_markers: 'finalization_markers',
  project_health_checks: 'project_health_checks',
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function provenanceForRecord(collection, record = {}) {
  const fallback = {}
  if (collection === 'chapter_versions') {
    fallback.sourceChapterNum = record.chapterNum ?? record.chapter_num
    fallback.sourceVersionId = record.id || record.versionId || ''
    fallback.runId = `run-final-${record.chapterNum ?? record.chapter_num ?? 'unknown'}`
    fallback.finalizationId = `fin-${record.chapterNum ?? record.chapter_num ?? 'unknown'}`
    fallback.commitStatus = String(record.versionType || record.version_type || '').toLowerCase() === 'final' ? 'final' : 'candidate'
  } else if (collection === 'finalization_markers') {
    fallback.sourceChapterNum = record.chapterNum ?? record.chapter_num
    fallback.sourceVersionId = record.sourceVersionId || record.source_version_id || ''
    fallback.runId = record.runId || record.run_id || ''
    fallback.finalizationId = record.finalizationId || record.finalization_id || ''
    fallback.commitStatus = record.commitStatus || record.commit_status || record.status || 'pending'
  } else if (collection === 'project_health_checks') {
    fallback.sourceChapterNum = CURRENT_CHAPTER
    fallback.sourceVersionId = `${record.projectId || 'project'}-health-${CURRENT_CHAPTER}`
    fallback.runId = `${record.projectId || 'project'}-health-run`
    fallback.finalizationId = ''
    fallback.commitStatus = 'dry_run'
  }
  const normalized = normalizeStateProvenance(record, fallback)
  return withStateProvenance(record, normalized)
}

function normalizeCollectionRecords(collection, records = []) {
  return (records || []).map(record => provenanceForRecord(collection, record))
}

function snapshotToCollections(snapshot, projectId, variant) {
  return {
    projectId,
    variant,
    metadata: {
      syntheticOnly: true,
      realDbConnection: false,
      chapterNum: snapshot.chapterNum,
      bible: snapshot.novelStore?.bible || {},
      outline: snapshot.novelStore?.outline || {},
      contextOptions: {
        narrativeVoiceContract: snapshot.contextOptions?.narrativeVoiceContract || {},
      },
    },
    collections: {
      chapters: clone(snapshot.contextOptions?.chapters || []),
      chapter_versions: normalizeCollectionRecords('chapter_versions', snapshot.contextOptions?.chapterVersions || []),
      canon_facts: normalizeCollectionRecords('canon_facts', snapshot.novelStore?.canonFacts || []),
      characters: normalizeCollectionRecords('characters', snapshot.novelStore?.characters || []),
      plot_threads: normalizeCollectionRecords('plot_threads', snapshot.novelStore?.plotThreads || []),
      setting_entities: normalizeCollectionRecords('setting_entities', snapshot.settingStore?.entities || []),
      setting_relations: normalizeCollectionRecords('setting_relations', snapshot.settingStore?.relations || []),
      setting_change_events: normalizeCollectionRecords('setting_change_events', snapshot.settingStore?.changeEvents || []),
      project_volumes: normalizeCollectionRecords('project_volumes', snapshot.volumeStore?.volumes || []),
      chapter_beat_plans: normalizeCollectionRecords('chapter_beat_plans', snapshot.contextOptions?.savedBeatPlans || []),
      finalization_markers: normalizeCollectionRecords('finalization_markers', snapshot.contextOptions?.finalizationMarkers || []),
      project_health_checks: [],
    },
  }
}

function collectionsToSnapshot(project) {
  const collections = project.collections || {}
  const metadata = project.metadata || {}
  return {
    chapterNum: metadata.chapterNum || CURRENT_CHAPTER,
    novelStore: {
      bible: metadata.bible || {},
      outline: metadata.outline || {},
      canonFacts: collections.canon_facts || [],
      characters: collections.characters || [],
      plotThreads: collections.plot_threads || [],
    },
    settingStore: {
      entities: collections.setting_entities || [],
      relations: collections.setting_relations || [],
      changeEvents: collections.setting_change_events || [],
    },
    volumeStore: {
      volumes: collections.project_volumes || [],
    },
    contextOptions: {
      chapters: collections.chapters || [],
      chapterVersions: collections.chapter_versions || [],
      savedBeatPlans: collections.chapter_beat_plans || [],
      finalizationMarkers: collections.finalization_markers || [],
      narrativeVoiceContract: metadata.contextOptions?.narrativeVoiceContract || {},
    },
  }
}

function hasCompleteProvenance(record = {}) {
  const provenance = record.provenance || {}
  return Boolean(
    provenance.sourceChapterNum &&
    provenance.sourceVersionId &&
    (provenance.runId || provenance.finalizationId) &&
    provenance.commitStatus
  )
}

function writeReadCoverageForStore(store, readStore) {
  const rows = []
  for (const collection of [
    'chapter_versions',
    'canon_facts',
    'setting_entities',
    'setting_relations',
    'setting_change_events',
    'project_volumes',
    'chapter_beat_plans',
    'finalization_markers',
    'project_health_checks',
  ]) {
    const writtenRecords = Object.values(store.projects).flatMap(project => project.collections?.[collection] || [])
    const readRecords = Object.values(readStore.projects).flatMap(project => project.collections?.[collection] || [])
    rows.push({
      collection,
      wrote: writtenRecords.length,
      read: readRecords.length,
      provenanceComplete: readRecords.length > 0 && readRecords.every(hasCompleteProvenance),
      readStrategy: COLLECTION_TO_TABLE[collection] || collection,
    })
  }
  return rows
}

function parseMigrationDryRun() {
  const sql = fsSync.readFileSync(MIGRATION_PATH, 'utf8')
  const tableMatches = [...sql.matchAll(/ALTER TABLE\s+([a-z_]+)([\s\S]*?);/g)]
  const tables = tableMatches.map(match => {
    const table = match[1]
    const body = match[2]
    const columns = [...body.matchAll(/ADD COLUMN\s+([a-z_]+)/g)].map(columnMatch => columnMatch[1])
    return {
      table,
      provenanceFields: REQUIRED_PROVENANCE_FIELDS.filter(field => columns.includes(field)),
      hasAllProvenanceFields: REQUIRED_PROVENANCE_FIELDS.every(field => columns.includes(field)),
    }
  })
  const ephemeralCollections = [
    'finalization_markers',
    'project_health_checks',
  ].map(collection => ({
    collection,
    hasAllProvenanceFields: true,
    strategy: 'ephemeral-json-store-normalized-provenance',
  }))
  return {
    mode: 'migration-sql-parse-dry-run-plus-json-store-schema',
    migrationPath: MIGRATION_PATH,
    executedAgainstRealDb: false,
    notExecutedReason: 'Migration draft is MySQL-oriented and explicitly marked dry-run; Phase 2.3 parses it and validates an isolated JSON store schema instead of connecting to any real DB.',
    tables,
    adapterGaps: [
      {
        collection: 'finalization_markers',
        reason: 'No production migration table in current draft; represented in ephemeral store and ContextPack contextOptions.finalizationMarkers.',
        minimalFix: 'Add a durable finalization marker table or project-level finalization journal before real migration.',
      },
      {
        collection: 'project_health_checks',
        reason: 'Health checks are computed dry-run artifacts, not migrated production state.',
        minimalFix: 'If persistent health audit is desired, add a project_health_checks table with provenance columns.',
      },
    ],
    ephemeralCollections,
  }
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

function uniqueCodes(issues = []) {
  return [...new Set(issues.map(issue => issue.code).filter(Boolean))]
}

function evaluateHealthy(snapshot, fixture) {
  const health = checkProjectStateHealth(snapshot, { chapterNum: CURRENT_CHAPTER })
  const creativeContextText = JSON.stringify(health.creativeContext)
  const sceneCard = health.creativeContext.sceneExecutionCard || {}
  return {
    ready: !health.blocked,
    healthBlocked: health.blocked,
    warningIssueCodes: uniqueCodes((health.issues || []).filter(issue => issue.severity !== 'block')),
    creativeContextContainsFutureRoadmap: creativeContextText.includes(fixture.guardOnly.futureRoadmapSecret),
    sceneCard: {
      hasConflict: Boolean(sceneCard.conflictPair && sceneCard.conflictPair.includes('叶珩')),
      hasEmotionalTurn: Boolean(sceneCard.emotionalTurn && sceneCard.emotionalTurn.includes('转为')),
      hasStopPoint: Boolean(sceneCard.stopPoint),
      trustedFactCount: Array.isArray(sceneCard.allowedFacts) ? sceneCard.allowedFacts.length : 0,
      stopPoint: sceneCard.stopPoint || '',
    },
  }
}

function evaluatePolluted(snapshot) {
  const health = checkProjectStateHealth(snapshot, { chapterNum: CURRENT_CHAPTER })
  const issues = summarizeIssues(health.issues || [])
  return {
    ready: !health.blocked,
    healthBlocked: health.blocked,
    issueCodes: uniqueCodes(issues),
    blockingIssues: issues.filter(issue => issue.severity === 'block'),
    warningIssues: issues.filter(issue => issue.severity !== 'block'),
  }
}

function evaluateBeatConflict(snapshot, fixture) {
  const projection = rebuildStateProjectionFromFinals(snapshot, { chapterNum: CURRENT_CHAPTER })
  const health = checkProjectStateHealth(snapshot, { chapterNum: CURRENT_CHAPTER })
  const authorityText = JSON.stringify(projection.stateAuthority)
  const creativeText = JSON.stringify(health.creativeContext)
  return {
    finalFactWins: authorityText.includes(fixture.finalFactText) &&
      !authorityText.includes(fixture.savedBeatPlan.conflictWithFinalFact),
    beatPlanAuthority: fixture.savedBeatPlan.authority,
    creativeContextContainsConflictingBeat: creativeText.includes(fixture.savedBeatPlan.conflictWithFinalFact),
    rejectedProjectionSources: projection.rejectedProjectionSources.length,
  }
}

function evaluateStageHandoff(snapshot) {
  const health = checkProjectStateHealth(snapshot, { chapterNum: CURRENT_CHAPTER })
  const projection = rebuildStateProjectionFromFinals(snapshot, { chapterNum: CURRENT_CHAPTER })
  const active = health.contextPack.stateAuthority.activeStoryBlock || {}
  return {
    activeStage: active.title || '',
    sourceType: active.sourceExplanation?.sourceType || '',
    canRebuildFromFinalFacts: Boolean(active.sourceExplanation?.canRebuildFromFinalFacts),
    usesFailedCandidate: JSON.stringify(projection).includes('失败候选'),
    rebuildFinalChapterCount: projection.stateAuthority.finalChapters.length,
  }
}

function evaluateFinalizationHalfSuccess(snapshot) {
  const health = checkProjectStateHealth(snapshot, { chapterNum: CURRENT_CHAPTER })
  const marker = snapshot.contextOptions.finalizationMarkers[0] || {}
  return {
    ready: !health.blocked,
    marker: {
      sourceChapterNum: Number(marker.chapterNum || marker.sourceChapterNum || 0),
      sourceVersionId: marker.sourceVersionId || '',
      runId: marker.runId || '',
      finalizationId: marker.finalizationId || '',
      commitStatus: marker.commitStatus || '',
    },
    blockingIssueCodes: uniqueCodes((health.issues || []).filter(issue => issue.severity === 'block')),
  }
}

function evaluateNarrativeVoice(snapshot, fixture) {
  const health = checkProjectStateHealth(snapshot, { chapterNum: CURRENT_CHAPTER })
  const voice = health.creativeContext.narrativeVoiceContract || {}
  const scenePrompt = [
    formatSceneExecutionCardForPrompt(health.creativeContext.sceneExecutionCard || {}),
    formatNarrativeVoiceContractForPrompt(voice),
  ].join('\n\n')
  const sampleScene = [
    '雨水顺着北桥裂缝往下坠，桥下的霜河像一条被拧紧的铁索。',
    '叶珩把霜火罗盘按在石栏上：“别装，暗号到底在不在钟楼？说清楚。”',
    '沈翎的声音发哑：“不是你想的那样。你再逼一句，北桥上这些人就少一刻撤离。”',
    '他盯着她发白的唇，忽然明白，她不是背叛，是在替他们拖时间。',
    '她偏开眼：“霜河钟楼。铜钟背面。只到这里。”',
  ].join('\n')
  const quality = evaluateLiteraryQuality(sampleScene, { prompt: scenePrompt })
  const promptQuality = evaluatePromptQuality(scenePrompt)
  return {
    voiceScope: voice.scope || '',
    voiceLintOk: Boolean(voice.lint?.ok),
    scenePromptContainsFutureRoadmap: scenePrompt.includes(fixture.guardOnly.futureRoadmapSecret),
    factOrStageOverridePresent: Boolean(voice.factOverrides || voice.stageBoundary || voice.worldRules || voice.guardSnapshot),
    qualityPassed: quality.passed,
    qualityScore: quality.score,
    qualityIssueCodes: quality.issues.map(issue => issue.code),
    promptQualityPassed: promptQuality.passed,
    promptIssueCodes: promptQuality.issues.map(issue => issue.code),
  }
}

function buildCleanupDryRun(pollutedSnapshot) {
  const health = checkProjectStateHealth(pollutedSnapshot, { chapterNum: CURRENT_CHAPTER })
  const projection = rebuildStateProjectionFromFinals(pollutedSnapshot, { chapterNum: CURRENT_CHAPTER })
  const proposedActions = summarizeIssues(health.issues || [])
    .filter(issue => issue.severity === 'block')
    .map(issue => ({
      action: issue.code === 'finalization_pending' ? 'hold_generation' : 'quarantine',
      code: issue.code,
      targetType: issue.targetType,
      target: issue.target,
      sourceChapterNum: issue.sourceChapterNum,
      sourceVersionId: issue.sourceVersionId,
      runId: issue.runId,
      finalizationId: issue.finalizationId,
    }))
  return {
    mode: 'dry-run-only',
    writesRealData: false,
    proposedActions,
    projectionRebuild: {
      finalChapters: projection.stateAuthority.finalChapters.length,
      rejectedProjectionSources: projection.rejectedProjectionSources.length,
    },
  }
}

function buildSummary(results) {
  return {
    healthyReady: results.healthy.ready,
    pollutedBlocked: results.polluted.healthBlocked,
    savedBeatConflictResolved: results.savedBeatConflict.finalFactWins,
    stageHandoffFromFinalState: results.stageHandoff.sourceType === 'final_state',
    finalizationHalfSuccessBlocked: !results.finalizationHalfSuccess.ready &&
      results.finalizationHalfSuccess.blockingIssueCodes.includes('finalization_pending'),
    narrativeVoiceSafe: results.narrativeVoice.voiceScope === 'expression_only' &&
      results.narrativeVoice.voiceLintOk &&
      results.narrativeVoice.qualityPassed &&
      !results.narrativeVoice.scenePromptContainsFutureRoadmap &&
      !results.narrativeVoice.factOrStageOverridePresent,
  }
}

async function writeStore(store) {
  await fs.mkdir(EPHEMERAL_DIR, { recursive: true })
  await fs.writeFile(STORE_PATH, `${JSON.stringify(store, null, 2)}\n`, 'utf8')
}

async function readStore() {
  return JSON.parse(await fs.readFile(STORE_PATH, 'utf8'))
}

function addHealthCheckRecord(store, projectId, health) {
  const project = store.projects[projectId]
  const record = provenanceForRecord('project_health_checks', {
    id: `${projectId}-health-${CURRENT_CHAPTER}`,
    projectId,
    chapterNum: CURRENT_CHAPTER,
    blocked: health.blocked,
    issueCodes: uniqueCodes(health.issues || []),
  })
  project.collections.project_health_checks.push(record)
}

export async function runEphemeralPersistenceRegression() {
  const fixture = buildCleanSyntheticProjectFixture()
  const store = {
    schemaVersion: 'ephemeral-project-store-phase2-3-v1',
    metadata: {
      syntheticOnly: true,
      realDbConnection: false,
      createdFor: 'Phase 2.3 ephemeral persistence dry-run',
    },
    projects: {
      'ephemeral-clean': snapshotToCollections(fixture.snapshots.healthy, 'ephemeral-clean', 'healthy'),
      'ephemeral-polluted': snapshotToCollections(fixture.snapshots.polluted, 'ephemeral-polluted', 'polluted'),
    },
  }

  const cleanSnapshotBeforeHealth = collectionsToSnapshot(store.projects['ephemeral-clean'])
  const pollutedSnapshotBeforeHealth = collectionsToSnapshot(store.projects['ephemeral-polluted'])
  addHealthCheckRecord(store, 'ephemeral-clean', checkProjectStateHealth(cleanSnapshotBeforeHealth, { chapterNum: CURRENT_CHAPTER }))
  addHealthCheckRecord(store, 'ephemeral-polluted', checkProjectStateHealth(pollutedSnapshotBeforeHealth, { chapterNum: CURRENT_CHAPTER }))

  await writeStore(store)
  const readStoreValue = await readStore()
  const cleanSnapshot = collectionsToSnapshot(readStoreValue.projects['ephemeral-clean'])
  const pollutedSnapshot = collectionsToSnapshot(readStoreValue.projects['ephemeral-polluted'])

  const results = {
    healthy: evaluateHealthy(cleanSnapshot, fixture),
    polluted: evaluatePolluted(pollutedSnapshot),
    savedBeatConflict: evaluateBeatConflict(cleanSnapshot, fixture),
    stageHandoff: evaluateStageHandoff(cleanSnapshot),
    finalizationHalfSuccess: evaluateFinalizationHalfSuccess(pollutedSnapshot),
    narrativeVoice: evaluateNarrativeVoice(cleanSnapshot, fixture),
  }

  return {
    schemaVersion: 'ephemeral-persistence-regression-phase2-3-v1',
    status: 'completed',
    timestamp: new Date().toISOString(),
    persistence: {
      strategy: 'ephemeral-json-store',
      storePath: STORE_PATH,
      touchesRealDb: false,
      isolationReason: 'Store path is under tmp/ephemeral-persistence-phase2-3 and contains synthetic fixture data only; no database driver or production DSN is used.',
    },
    schemaDryRun: parseMigrationDryRun(),
    writeReadCoverage: writeReadCoverageForStore(store, readStoreValue),
    summary: buildSummary(results),
    results,
    cleanupDryRun: buildCleanupDryRun(pollutedSnapshot),
  }
}

export function validateEphemeralPersistencePayload(payload = {}) {
  if (payload.schemaVersion !== 'ephemeral-persistence-regression-phase2-3-v1') {
    throw new Error('Invalid Phase 2.3 ephemeral persistence schemaVersion')
  }
  if (payload.status !== 'completed') return true
  if (payload.persistence?.touchesRealDb !== false) throw new Error('persistence.touchesRealDb must be false')
  if (!String(payload.persistence?.storePath || '').includes('tmp')) throw new Error('storePath must be under tmp')
  for (const table of [
    'chapter_versions',
    'canon_facts',
    'setting_entities',
    'setting_relations',
    'setting_change_events',
    'project_volumes',
    'chapter_beat_plans',
  ]) {
    const row = payload.schemaDryRun?.tables?.find(item => item.table === table)
    if (!row?.hasAllProvenanceFields) throw new Error(`schemaDryRun.${table} missing provenance fields`)
  }
  for (const collection of [
    'chapter_versions',
    'canon_facts',
    'setting_entities',
    'setting_relations',
    'setting_change_events',
    'project_volumes',
    'chapter_beat_plans',
    'finalization_markers',
    'project_health_checks',
  ]) {
    const row = payload.writeReadCoverage?.find(item => item.collection === collection)
    if (!row) throw new Error(`writeReadCoverage missing ${collection}`)
    if (row.wrote <= 0 || row.read <= 0) throw new Error(`writeReadCoverage.${collection} must read/write records`)
    if (!row.provenanceComplete) throw new Error(`writeReadCoverage.${collection} must preserve provenance`)
  }
  const expectedSummary = buildSummary(payload.results || {})
  for (const [key, expected] of Object.entries(expectedSummary)) {
    if (payload.summary?.[key] !== expected) throw new Error(`summary.${key} mismatch`)
  }
  if (!payload.summary.healthyReady) throw new Error('healthy project must be ready after readback')
  if (!payload.summary.pollutedBlocked) throw new Error('polluted project must be blocked after readback')
  if (!payload.summary.savedBeatConflictResolved) throw new Error('saved beat conflict must resolve to final fact after readback')
  if (!payload.summary.stageHandoffFromFinalState) throw new Error('stage handoff must come from final_state after readback')
  if (!payload.summary.finalizationHalfSuccessBlocked) throw new Error('half-success marker must block readiness after readback')
  if (!payload.summary.narrativeVoiceSafe) throw new Error('narrative voice must remain expression-only after readback')
  return true
}

function issueText(values = []) {
  return values?.length ? values.join(',') : 'none'
}

export function buildEphemeralPersistenceReport(payload) {
  validateEphemeralPersistencePayload(payload)
  const lines = [
    '# Ephemeral Persistence Regression Phase 2.3 Report',
    '',
    'Status: completed ephemeral persistence dry-run. 临时环境通过不等于真实项目迁移/清理完成。',
    '',
    '## Scope Guard',
    '- Did not start backend/frontend dev server, runner, or page.goto.',
    '- Did not run formal chapter generation/finalization chain.',
    '- Did not connect to or write a real DB; no real migration/cleanup executed.',
    '- Did not restore LongformBrowser or run #98/#99/#50.',
    '- Did not save model output as project正文、小纲、beat plan, or DB state.',
    '- Did not enter Phase 3 provider/model adapter work or real clean project/live canary.',
    '',
    '## Persistence Strategy',
    `persistence.strategy=${payload.persistence.strategy}`,
    `persistence.storePath=${payload.persistence.storePath}`,
    `persistence.touchesRealDb=${payload.persistence.touchesRealDb}`,
    `persistence.isolationReason=${payload.persistence.isolationReason}`,
    '',
    '## Schema Dry-Run',
    `schema.mode=${payload.schemaDryRun.mode}`,
    `schema.executedAgainstRealDb=${payload.schemaDryRun.executedAgainstRealDb}`,
    `schema.adapterGaps=${payload.schemaDryRun.adapterGaps.map(gap => gap.collection).join(',')}`,
    '',
    '## Write/Read Coverage',
    '| collection | wrote | read | provenanceComplete | strategy |',
    '| --- | --- | --- | --- | --- |',
    ...payload.writeReadCoverage.map(row => `| ${row.collection} | wrote=${row.wrote}; read=${row.read}; provenanceComplete=${row.provenanceComplete}; strategy=${row.readStrategy} |`),
    '',
    '## Summary',
    `ephemeral.healthyReady=${payload.summary.healthyReady}`,
    `ephemeral.pollutedBlocked=${payload.summary.pollutedBlocked}`,
    `ephemeral.savedBeatConflictResolved=${payload.summary.savedBeatConflictResolved}`,
    `ephemeral.stageHandoffFromFinalState=${payload.summary.stageHandoffFromFinalState}`,
    `ephemeral.finalizationHalfSuccessBlocked=${payload.summary.finalizationHalfSuccessBlocked}`,
    `ephemeral.narrativeVoiceSafe=${payload.summary.narrativeVoiceSafe}`,
    '',
    '## Scenario Results',
    '| scenario | evidence |',
    '| --- | --- |',
    `| healthy | ready=${payload.results.healthy.ready}; healthBlocked=${payload.results.healthy.healthBlocked}; creativeContextContainsFutureRoadmap=${payload.results.healthy.creativeContextContainsFutureRoadmap}; trustedFactCount=${payload.results.healthy.sceneCard.trustedFactCount} |`,
    `| polluted | ready=${payload.results.polluted.ready}; healthBlocked=${payload.results.polluted.healthBlocked}; issueCodes=${issueText(payload.results.polluted.issueCodes)}; blockingIssueCount=${payload.results.polluted.blockingIssues.length} |`,
    `| savedBeatConflict | finalFactWins=${payload.results.savedBeatConflict.finalFactWins}; beatPlanAuthority=${payload.results.savedBeatConflict.beatPlanAuthority}; creativeContextContainsConflictingBeat=${payload.results.savedBeatConflict.creativeContextContainsConflictingBeat} |`,
    `| stageHandoff | sourceType=${payload.results.stageHandoff.sourceType}; canRebuildFromFinalFacts=${payload.results.stageHandoff.canRebuildFromFinalFacts}; usesFailedCandidate=${payload.results.stageHandoff.usesFailedCandidate}; rebuildFinalChapterCount=${payload.results.stageHandoff.rebuildFinalChapterCount} |`,
    `| finalization | ready=${payload.results.finalizationHalfSuccess.ready}; markerStatus=${payload.results.finalizationHalfSuccess.marker.commitStatus}; blockingIssueCodes=${issueText(payload.results.finalizationHalfSuccess.blockingIssueCodes)} |`,
    `| narrativeVoice | voiceScope=${payload.results.narrativeVoice.voiceScope}; voiceLintOk=${payload.results.narrativeVoice.voiceLintOk}; scenePromptContainsFutureRoadmap=${payload.results.narrativeVoice.scenePromptContainsFutureRoadmap}; factOrStageOverridePresent=${payload.results.narrativeVoice.factOrStageOverridePresent}; qualityPassed=${payload.results.narrativeVoice.qualityPassed} |`,
    '',
    '## Cleanup / Projection Dry-Run',
    `cleanup.mode=${payload.cleanupDryRun.mode}`,
    `cleanup.writesRealData=${payload.cleanupDryRun.writesRealData}`,
    `cleanup.proposedActions=${payload.cleanupDryRun.proposedActions.map(action => action.action).join(',')}`,
    `cleanup.rejectedProjectionSources=${payload.cleanupDryRun.projectionRebuild.rejectedProjectionSources}`,
    '',
    '## Evidence Contract',
    '- JSON/report alignment parses single-value summary lines, coverage rows, scenario rows, and key-value cells; stale+correct duplicates are rejected.',
    '- Migration SQL is parsed only; no real DB driver, DSN, migration runner, or production database connection is used.',
    '- The temporary JSON store is synthetic and disposable; it is not a real project DB.',
    '',
    '## Remaining Risks',
    '- Real DB migration execution remains untested.',
    '- Real project cleanup/quarantine/purge remains unrun.',
    '- Real clean project regression and live canary remain unrun.',
    '',
    '## Review',
    ...(payload.review
      ? [
          `review.threadId=${payload.review.threadId}`,
          `review.critical=${payload.review.critical}`,
          `review.important=${payload.review.important}`,
          `review.conclusion=${payload.review.conclusion}`,
        ]
      : ['Fresh review pending.']),
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

export function assertEphemeralPersistenceReportMatchesJson(reportText, payload) {
  validateEphemeralPersistencePayload(payload)
  const report = String(reportText || '')
  const lineChecks = {
    'persistence.strategy': payload.persistence.strategy,
    'persistence.storePath': payload.persistence.storePath,
    'persistence.touchesRealDb': payload.persistence.touchesRealDb,
    'schema.mode': payload.schemaDryRun.mode,
    'schema.executedAgainstRealDb': payload.schemaDryRun.executedAgainstRealDb,
    'schema.adapterGaps': payload.schemaDryRun.adapterGaps.map(gap => gap.collection).join(','),
    'ephemeral.healthyReady': payload.summary.healthyReady,
    'ephemeral.pollutedBlocked': payload.summary.pollutedBlocked,
    'ephemeral.savedBeatConflictResolved': payload.summary.savedBeatConflictResolved,
    'ephemeral.stageHandoffFromFinalState': payload.summary.stageHandoffFromFinalState,
    'ephemeral.finalizationHalfSuccessBlocked': payload.summary.finalizationHalfSuccessBlocked,
    'ephemeral.narrativeVoiceSafe': payload.summary.narrativeVoiceSafe,
    'cleanup.mode': payload.cleanupDryRun.mode,
    'cleanup.writesRealData': payload.cleanupDryRun.writesRealData,
    'cleanup.rejectedProjectionSources': payload.cleanupDryRun.projectionRebuild.rejectedProjectionSources,
  }
  if (payload.review) {
    Object.assign(lineChecks, {
      'review.threadId': payload.review.threadId,
      'review.critical': payload.review.critical,
      'review.important': payload.review.important,
      'review.conclusion': payload.review.conclusion,
    })
  }
  if (Array.isArray(payload.verification?.commands) && payload.verification.commands.length) {
    lineChecks['verification.commandCount'] = payload.verification.commands.length
  }
  for (const [key, expected] of Object.entries(lineChecks)) {
    const actual = extractSingleLineValue(report, key)
    const alias = key.replace(/^ephemeral\./, '')
    if (actual !== String(expected)) throw new Error(`Report/JSON mismatch for ${alias}: ${actual} expected ${expected}`)
  }
  if (Array.isArray(payload.verification?.commands) && payload.verification.commands.length) {
    for (const command of payload.verification.commands) {
      const reportRow = findSingleMarkdownRow(report, command.command)
      const cells = parseMarkdownRow(reportRow)
      if (cells.length !== 2) throw new Error(`Report/JSON mismatch for verification ${command.command}`)
      if (cells[1] !== command.result) {
        throw new Error(`Report/JSON mismatch for verification ${command.command}: ${cells[1]} expected ${command.result}`)
      }
    }
  }
  for (const row of payload.writeReadCoverage) {
    const reportRow = findSingleMarkdownRow(report, row.collection)
    const cells = parseMarkdownRow(reportRow)
    if (cells.length !== 2) throw new Error(`Report/JSON mismatch for coverage ${row.collection}`)
    assertKeyValueCell(cells[1], {
      wrote: row.wrote,
      read: row.read,
      provenanceComplete: row.provenanceComplete,
      strategy: row.readStrategy,
    }, `coverage.${row.collection}`)
  }
  const scenarioRows = {
    healthy: {
      ready: payload.results.healthy.ready,
      healthBlocked: payload.results.healthy.healthBlocked,
      creativeContextContainsFutureRoadmap: payload.results.healthy.creativeContextContainsFutureRoadmap,
      trustedFactCount: payload.results.healthy.sceneCard.trustedFactCount,
    },
    polluted: {
      ready: payload.results.polluted.ready,
      healthBlocked: payload.results.polluted.healthBlocked,
      issueCodes: issueText(payload.results.polluted.issueCodes),
      blockingIssueCount: payload.results.polluted.blockingIssues.length,
    },
    savedBeatConflict: {
      finalFactWins: payload.results.savedBeatConflict.finalFactWins,
      beatPlanAuthority: payload.results.savedBeatConflict.beatPlanAuthority,
      creativeContextContainsConflictingBeat: payload.results.savedBeatConflict.creativeContextContainsConflictingBeat,
    },
    stageHandoff: {
      sourceType: payload.results.stageHandoff.sourceType,
      canRebuildFromFinalFacts: payload.results.stageHandoff.canRebuildFromFinalFacts,
      usesFailedCandidate: payload.results.stageHandoff.usesFailedCandidate,
      rebuildFinalChapterCount: payload.results.stageHandoff.rebuildFinalChapterCount,
    },
    finalization: {
      ready: payload.results.finalizationHalfSuccess.ready,
      markerStatus: payload.results.finalizationHalfSuccess.marker.commitStatus,
      blockingIssueCodes: issueText(payload.results.finalizationHalfSuccess.blockingIssueCodes),
    },
    narrativeVoice: {
      voiceScope: payload.results.narrativeVoice.voiceScope,
      voiceLintOk: payload.results.narrativeVoice.voiceLintOk,
      scenePromptContainsFutureRoadmap: payload.results.narrativeVoice.scenePromptContainsFutureRoadmap,
      factOrStageOverridePresent: payload.results.narrativeVoice.factOrStageOverridePresent,
      qualityPassed: payload.results.narrativeVoice.qualityPassed,
    },
  }
  for (const [label, expectedValues] of Object.entries(scenarioRows)) {
    const row = findSingleMarkdownRow(report, label)
    const cells = parseMarkdownRow(row)
    if (cells.length !== 2) throw new Error(`Report/JSON mismatch for scenario ${label}`)
    assertKeyValueCell(cells[1], expectedValues, `scenario.${label}`)
  }
  return true
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
  const pairs = String(cell)
    .split(';')
    .map(part => part.trim())
    .filter(Boolean)
  const actual = new Map()
  for (const pair of pairs) {
    const separator = pair.indexOf('=')
    if (separator < 1) throw new Error(`Report/JSON mismatch for ${label}: malformed token ${pair}`)
    const key = pair.slice(0, separator).trim()
    const value = pair.slice(separator + 1).trim()
    if (actual.has(key)) throw new Error(`Report/JSON mismatch for ${label}.${key}: duplicate key`)
    actual.set(key, value)
  }
  const expectedKeys = Object.keys(expectedValues)
  if (actual.size !== expectedKeys.length) {
    throw new Error(`Report/JSON mismatch for ${label}: expected ${expectedKeys.length} fields, got ${actual.size}`)
  }
  for (const [key, expected] of Object.entries(expectedValues)) {
    if (!actual.has(key)) throw new Error(`Report/JSON mismatch for ${label}.${key}: missing`)
    if (actual.get(key) !== String(expected)) {
      throw new Error(`Report/JSON mismatch for ${label}.${key}: ${actual.get(key)} expected ${expected}`)
    }
  }
}

async function main() {
  const payload = await runEphemeralPersistenceRegression()
  const report = buildEphemeralPersistenceReport(payload)
  assertEphemeralPersistenceReportMatchesJson(report, payload)
  await fs.mkdir(OUT_DIR, { recursive: true })
  await fs.writeFile(OUT_JSON, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
  await fs.writeFile(OUT_REPORT, report, 'utf8')
  console.log(`ephemeral persistence phase2.3 regression wrote ${OUT_JSON} and ${OUT_REPORT}`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  main().catch(error => {
    console.error(error)
    process.exit(1)
  })
}
