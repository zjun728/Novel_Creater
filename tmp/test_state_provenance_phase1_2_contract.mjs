import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  auditProvenanceWritePaths,
  buildFinalizationProvenance,
  normalizeStateProvenance,
  withStateProvenance
} from '../frontend/src/utils/stateProvenance.js'
import {
  checkProjectStateHealth,
  rebuildStateProjectionFromFinals
} from '../frontend/src/utils/projectHealthCheck.js'
import {
  createFinalizationProtocol,
  finalizationProtocolToMarker,
  transitionFinalizationProtocol
} from '../frontend/src/utils/finalizationProtocol.js'

const FINAL_FACT = '第97章定稿正文确认白玉钥匙仍在林逐掌心，剩余一次。'
const FAILED_ENTITY = '第98失败候选污染实体'
const EMPTY_EVENT = '空章却声称赵青已经离开渭水'
const FUTURE_SECRET = '第100章才揭示祖母是真正门主'
const CONFLICTING_PLAN = '第97章小纲曾计划白玉钥匙被赵青夺走'

const finalProvenance = buildFinalizationProvenance({
  sourceChapterNum: 97,
  sourceVersionId: 'v97-final',
  runId: 'run-final-97',
  finalizationId: 'fin-97'
})
assert.deepEqual(finalProvenance, {
  sourceChapterNum: 97,
  sourceVersionId: 'v97-final',
  runId: 'run-final-97',
  finalizationId: 'fin-97',
  commitStatus: 'final'
})
assert.equal(
  normalizeStateProvenance({ sourceChapterNum: '98', sourceVersionId: 'v98-failed', commitStatus: 'failed' }).sourceChapterNum,
  98
)
assert.equal(
  withStateProvenance({ content: FINAL_FACT }, finalProvenance).provenance.commitStatus,
  'final'
)

const writePathAudit = auditProvenanceWritePaths()
for (const requiredPath of [
  'chapter_versions',
  'canon_facts',
  'setting_change_events',
  'setting_entities',
  'setting_relations',
  'project_volumes.stage_summary_report',
  'chapter_beat_plans'
]) {
  const row = writePathAudit.find(item => item.path === requiredPath)
  assert.ok(row, `write-path audit should include ${requiredPath}`)
  assert.notEqual(row.status, 'silent_unknown', `${requiredPath} must not be silently unknown`)
}

const pollutedSnapshot = {
  novelStore: {
    bible: {
      forbiddenDirections: [`guard-only: ${FUTURE_SECRET}`]
    },
    outline: {
      nearChapters: [
        { chapterNum: 99, title: '镜裂之后', goal: '林逐确认白玉钥匙状态。' },
        { chapterNum: 100, title: '门主', goal: FUTURE_SECRET }
      ]
    },
    characters: [],
    plotThreads: [],
    canonFacts: [
      withStateProvenance({
        id: 'fact-final-97',
        status: 'accepted',
        chapterNum: 97,
        factType: '道具',
        content: FINAL_FACT
      }, finalProvenance),
      {
        id: 'fact-half-provenance',
        status: 'accepted',
        chapterNum: 96,
        factType: 'legacy',
        content: '半 provenance 旧事实只能 degraded。',
        provenance: { sourceChapterNum: 96, sourceVersionId: 'legacy-v96' }
      }
    ]
  },
  settingStore: {
    entities: [
      withStateProvenance({
        id: 'failed-entity',
        entityType: 'item',
        name: FAILED_ENTITY,
        status: 'active',
        summary: '失败候选生成的 active entity。',
        profile: { owner: '赵青' }
      }, {
        sourceChapterNum: 98,
        sourceVersionId: 'v98-failed',
        runId: 'run-98-failed',
        commitStatus: 'failed'
      }),
      {
        id: 'legacy-entity',
        entityType: 'item',
        name: '白玉钥匙',
        status: 'active',
        summary: '旧记录缺 provenance，需要 warning。',
        profile: { owner: '林逐' }
      }
    ],
    relations: [],
    changeEvents: [
      withStateProvenance({
        id: 'empty-event',
        status: 'accepted',
        chapterNum: 98,
        entityName: '赵青',
        entityType: 'character',
        changeType: 'update_entity',
        fieldPath: 'profile.location',
        newValue: EMPTY_EVENT
      }, {
        sourceChapterNum: 98,
        sourceVersionId: 'v98-empty',
        commitStatus: 'empty_chapter'
      })
    ]
  },
  volumeStore: {
    volumes: [
      withStateProvenance({
        id: 'failed-stage',
        title: '失败阶段',
        startChapter: 90,
        endChapter: 120,
        status: 'active',
        coreGoal: '失败 stage 不得进入 projection。',
        stageSummaryReport: { compactSummary: '失败 stage summary 污染。' }
      }, {
        sourceChapterNum: 98,
        sourceVersionId: 'v98-failed',
        commitStatus: 'failed'
      })
    ]
  },
  contextOptions: {
    chapters: [
      { chapterNum: 96, status: 'final', finalVersionId: 'v96-final', wordCount: 5300 },
      { chapterNum: 97, status: 'final', finalVersionId: 'v97-final', wordCount: 5400 },
      { chapterNum: 98, status: 'drafting', finalVersionId: null, wordCount: 0 }
    ],
    chapterVersions: [
      { id: 'v96-final', chapterNum: 96, versionType: 'final', content: '第96章定稿。' },
      { id: 'v97-final', chapterNum: 97, versionType: 'final', content: FINAL_FACT },
      { id: 'v98-failed', chapterNum: 98, versionType: 'ai_candidate', content: '失败候选正文。' }
    ],
    savedBeatPlans: [
      withStateProvenance({
        chapterNum: 97,
        content: CONFLICTING_PLAN
      }, {
        sourceChapterNum: 97,
        sourceVersionId: 'beat-97',
        commitStatus: 'plan_only'
      })
    ],
    finalizationMarkers: [
      {
        chapterNum: 98,
        sourceVersionId: 'v98-final',
        finalizationId: 'fin-98',
        commitStatus: 'failed_after_chapter_commit'
      }
    ]
  }
}

const health = checkProjectStateHealth(pollutedSnapshot, { chapterNum: 99 })
const blockingCodes = new Set(health.issues.filter(issue => issue.severity === 'block').map(issue => issue.code))
const warningCodes = new Set(health.issues.filter(issue => issue.severity !== 'block').map(issue => issue.code))
assert.equal(health.blocked, true)
assert.ok(blockingCodes.has('untrusted_source'))
assert.ok(blockingCodes.has('empty_chapter_authority'))
assert.ok(blockingCodes.has('untrusted_stage_snapshot'))
assert.ok(blockingCodes.has('finalization_pending'))
assert.ok(warningCodes.has('unknown_provenance'))
assert.ok(warningCodes.has('prompt_facing_degraded_context'))
assert.ok(warningCodes.has('saved_beat_plan_conflict'))
assert.doesNotMatch(JSON.stringify(health.creativeContext), new RegExp(FUTURE_SECRET))
assert.doesNotMatch(JSON.stringify(health.creativeContext), new RegExp(CONFLICTING_PLAN))
assert.doesNotMatch(JSON.stringify(health.creativeContext), new RegExp(FAILED_ENTITY))
assert.doesNotMatch(JSON.stringify(health.creativeContext), new RegExp(EMPTY_EVENT))

const projection = rebuildStateProjectionFromFinals(pollutedSnapshot, { chapterNum: 99 })
assert.match(JSON.stringify(projection.stateAuthority.finalChapters), /v97-final/)
assert.match(JSON.stringify(projection.stateAuthority.canonFacts), new RegExp(FINAL_FACT))
assert.doesNotMatch(JSON.stringify(projection), /失败候选正文/)
assert.doesNotMatch(JSON.stringify(projection), new RegExp(CONFLICTING_PLAN))
assert.match(JSON.stringify(projection.rejectedProjectionSources), /plan_only/)

const reportBackedStageHealth = checkProjectStateHealth({
  novelStore: {
    bible: {},
    outline: {
      nearChapters: [
        { chapterNum: 99, title: 'stage report provenance', goal: '验证 stage report provenance。' }
      ]
    },
    canonFacts: [],
    characters: [],
    plotThreads: []
  },
  settingStore: { entities: [], relations: [], changeEvents: [] },
  volumeStore: {
    volumes: [
      {
        id: 'report-backed-stage',
        title: '报告支撑阶段',
        startChapter: 90,
        endChapter: 120,
        status: 'active',
        coreGoal: '从 stageSummaryReport.snapshotProvenance 解释 active stage。',
        stageSummaryReport: {
          compactSummary: '第97章后 stage 已结算。',
          snapshotProvenance: finalProvenance
        }
      }
    ]
  },
  contextOptions: {
    chapters: pollutedSnapshot.contextOptions.chapters,
    chapterVersions: pollutedSnapshot.contextOptions.chapterVersions
  }
}, { chapterNum: 99 })
assert.equal(
  reportBackedStageHealth.contextPack.stateAuthority.activeStoryBlock.sourceExplanation.sourceType,
  'final_state'
)

let protocol = createFinalizationProtocol({
  chapterNum: 98,
  sourceVersionId: 'v98-final',
  runId: 'run-98',
  finalizationId: 'fin-98'
})
assert.equal(protocol.commitStatus, 'staged')
protocol = transitionFinalizationProtocol(protocol, { type: 'validated' })
assert.equal(protocol.commitStatus, 'validated')
assert.equal(finalizationProtocolToMarker(protocol).commitStatus, 'validated')
protocol = transitionFinalizationProtocol(protocol, { type: 'failed_after_chapter_commit', reason: 'setting extraction failed' })
assert.equal(protocol.commitStatus, 'failed_after_chapter_commit')
assert.equal(finalizationProtocolToMarker(protocol).commitStatus, 'failed_after_chapter_commit')

let cleanProtocol = createFinalizationProtocol({
  chapterNum: 99,
  sourceVersionId: 'v99-final',
  finalizationId: 'fin-99'
})
cleanProtocol = transitionFinalizationProtocol(cleanProtocol, { type: 'validated' })
cleanProtocol = transitionFinalizationProtocol(cleanProtocol, { type: 'committed' })
assert.equal(cleanProtocol.commitStatus, 'committed')
assert.equal(finalizationProtocolToMarker(cleanProtocol), null)

const writerStoreSource = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const memoryStoreSource = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')
const settingStoreSource = readFileSync('frontend/src/stores/settingStore.js', 'utf8')
const writerViewSource = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const backendProvenanceSource = readFileSync('backend/routers/provenance_support.py', 'utf8')
const backendNovelSource = readFileSync('backend/routers/novel.py', 'utf8')
const backendHelpersSource = readFileSync('backend/routers/helpers.py', 'utf8')
const migrationSource = readFileSync('backend/migrations/20260705_state_provenance_phase1_2.sql', 'utf8')

assert.match(writerStoreSource, /withStateProvenance/)
assert.match(writerStoreSource, /saveChapterBeatPlan\(projectId, chapterNum, content, metadata = \{\}\)/)
assert.match(writerStoreSource, /buildFinalizationProvenance/)
assert.match(memoryStoreSource, /buildFinalizationProvenance/)
assert.match(memoryStoreSource, /processChapterFinalization\(projectId, chapterContent, chapterNum, options = \{\}\)/)
assert.match(memoryStoreSource, /withStateProvenance/)
assert.match(settingStoreSource, /preserveProvenancePayload/)
assert.match(backendProvenanceSource, /persist_provenance_if_columns/)
assert.match(backendProvenanceSource, /SHOW COLUMNS FROM/)
assert.match(backendProvenanceSource, /_has_meaningful_provenance/)
assert.match(backendProvenanceSource, /if not _has_meaningful_provenance\(payload\) and not _has_meaningful_provenance\(fallback_payload\):/)
assert.match(backendProvenanceSource, /_pick_non_empty/)
assert.match(backendNovelSource, /PROVENANCE_INPUT_KEYS/)
assert.match(backendNovelSource, /if k in PROVENANCE_INPUT_KEYS: continue/)
assert.match(backendNovelSource, /if not sets:\s*\n\s*await persist_provenance_if_columns\("canon_facts", fid, data\)/)
assert.match(backendHelpersSource, /'provenance'/)
assert.match(writerViewSource, /memoryStore\.processChapterFinalization\(projectId\.value,\s*version\.content,\s*num,\s*\{[\s\S]*runId:\s*finalizationRun\.runId[\s\S]*finalizationId:\s*finalizationRun\.finalizationId[\s\S]*\}\)/)
assert.match(writerViewSource, /sourceVersionId:\s*retryVersionId,[\s\S]*runId:\s*finalizationRun\.runId,[\s\S]*finalizationId:\s*finalizationRun\.finalizationId/)
assert.match(migrationSource, /ALTER TABLE canon_facts/)
assert.match(migrationSource, /ALTER TABLE setting_change_events/)
assert.match(migrationSource, /ALTER TABLE chapter_beat_plans/)
assert.match(migrationSource, /commit_status/)

console.log('state provenance phase1.2 contract tests passed')
