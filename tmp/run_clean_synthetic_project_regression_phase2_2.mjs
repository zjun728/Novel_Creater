import fs from 'node:fs/promises'
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
  withStateProvenance,
} from '../frontend/src/utils/stateProvenance.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const OUT_DIR = path.join(__dirname, 'realistic-flow-qa')
const OUT_JSON = path.join(OUT_DIR, 'clean-synthetic-project-regression-phase2-2.json')
const OUT_REPORT = path.join(OUT_DIR, 'clean-synthetic-project-regression-phase2-2-report.md')

const CURRENT_CHAPTER = 15
const FUTURE_SECRET = '霜塔城主其实是南线内应'
const FINAL_FACT_TEXT = '第14章定稿确认霜火罗盘仍在叶珩手中，指针只剩一次转向。'
const BEAT_CONFLICT_TEXT = '旧 beat plan 计划沈翎已经夺走霜火罗盘。'

function finalProvenance(chapterNum, suffix = '') {
  return {
    sourceChapterNum: chapterNum,
    sourceVersionId: `v${chapterNum}-final${suffix}`,
    runId: `run-final-${chapterNum}${suffix}`,
    finalizationId: `fin-${chapterNum}${suffix}`,
    commitStatus: 'final',
  }
}

function planProvenance(chapterNum, suffix = '') {
  return {
    sourceChapterNum: chapterNum,
    sourceVersionId: `beat-${chapterNum}${suffix}`,
    runId: `run-beat-${chapterNum}${suffix}`,
    finalizationId: '',
    commitStatus: 'plan_only',
  }
}

function makeFinalLedger() {
  const chapters = []
  const chapterVersions = []
  for (let chapterNum = 1; chapterNum <= 14; chapterNum += 1) {
    const sourceVersionId = `v${chapterNum}-final`
    const content = [
      `第${chapterNum}章定稿正文：叶珩与沈翎推进霜河围城线。`,
      chapterNum === 8 ? '第8章定稿确认灰桥盟约仍由沈翎保管。' : '',
      chapterNum === 11 ? '第11章定稿确认北桥将在三日内坍塌。' : '',
      chapterNum === 14 ? FINAL_FACT_TEXT : '',
    ].filter(Boolean).join('\n')
    chapters.push({
      chapterNum,
      status: 'final',
      finalVersionId: sourceVersionId,
      wordCount: 4200 + chapterNum,
      summary: `第${chapterNum}章 final ledger summary`,
      finalizationId: `fin-${chapterNum}`,
    })
    chapterVersions.push({
      id: sourceVersionId,
      chapterNum,
      versionType: 'final',
      content,
    })
  }
  return { chapters, chapterVersions }
}

function makeStages() {
  return [
    {
      id: 'stage-1-ash-gate',
      storyBlockId: 'block-1',
      title: 'Block 1 / Stage 1: Ash Gate',
      startChapter: 1,
      endChapter: 5,
      status: 'settled',
      coreGoal: '叶珩获得霜火罗盘，理解它只能指向一次。',
      mainConflict: '叶珩 vs 失控城防',
      stageSummaryReport: {
        compactSummary: '灰门线完成，罗盘首次进入定稿事实。',
        completedBeats: ['叶珩拿到霜火罗盘。'],
        openQuestions: ['罗盘最后一次转向该给谁。'],
        snapshotProvenance: finalProvenance(5),
      },
    },
    {
      id: 'stage-2-bridge-oath',
      storyBlockId: 'block-1',
      title: 'Block 1 / Stage 2: Bridge Oath',
      startChapter: 6,
      endChapter: 10,
      status: 'settled',
      coreGoal: '沈翎守住灰桥盟约，但代价开始外溢。',
      mainConflict: '沈翎 vs 灰桥叛徒',
      stageSummaryReport: {
        compactSummary: '灰桥盟约被保存，叶珩仍欠沈翎一次解释。',
        completedBeats: ['沈翎保住盟约原件。'],
        openQuestions: ['沈翎是否会继续信任叶珩。'],
        snapshotProvenance: finalProvenance(10),
      },
    },
    {
      id: 'stage-3-siege-choice',
      storyBlockId: 'block-2',
      title: 'Block 2 / Stage 3: Siege Choice',
      startChapter: 11,
      endChapter: 16,
      status: 'active',
      coreGoal: '叶珩必须在北桥坍塌前逼沈翎交出城防暗号。',
      mainConflict: '叶珩 vs 沈翎',
      stageSummaryReport: {
        compactSummary: '第14章后，叶珩掌握霜火罗盘，沈翎握有城防暗号。',
        completedBeats: ['北桥即将坍塌。', '霜火罗盘仍在叶珩手中。'],
        openQuestions: ['沈翎为什么拒绝交出暗号。'],
        handoffToNext: ['第15章停在沈翎承认暗号位置，但不能揭露霜塔城主身份。'],
        continuityNotes: ['罗盘只剩一次转向。'],
        snapshotProvenance: finalProvenance(14),
      },
    },
  ].map(stage => withStateProvenance(stage, stage.stageSummaryReport.snapshotProvenance))
}

function makeBaseSnapshot() {
  const ledger = makeFinalLedger()
  const stages = makeStages()
  return {
    chapterNum: CURRENT_CHAPTER,
    novelStore: {
      bible: {
        styleBible: '短场景必须有压力、对白交锋、情绪转折、表情语气、短内心和环境压力。',
      },
      outline: {
        nearChapters: [
          {
            chapterNum: 15,
            title: '北桥坍塌前夜',
            goal: '让叶珩在北桥坍塌前逼沈翎承认城防暗号藏在霜河钟楼。',
            conflict: '叶珩 vs 沈翎',
            emotionalTurn: '叶珩从怀疑沈翎背叛，转为意识到她在替整座城拖延撤离时间。',
            turn: '叶珩从怀疑沈翎背叛，转为意识到她在替整座城拖延撤离时间。',
            emotionalBeat: '叶珩从怀疑沈翎背叛，转为意识到她在替整座城拖延撤离时间。',
            handoff: '沈翎只承认暗号在霜河钟楼，不能揭露霜塔城主身份。',
            doNotResolveYet: ['不能揭露霜塔城主身份。'],
          },
          {
            chapterNum: 16,
            title: '霜塔内应',
            goal: `后续 guard-only roadmap：${FUTURE_SECRET}。`,
            conflict: '叶珩 vs 霜塔城主',
            turn: FUTURE_SECRET,
            handoff: '第16章以后才进入城主内应线。',
          },
        ],
      },
      canonFacts: [
        withStateProvenance({
          id: 'fact-14-compass',
          status: 'accepted',
          chapterNum: 14,
          factType: 'artifact',
          content: FINAL_FACT_TEXT,
        }, finalProvenance(14)),
        withStateProvenance({
          id: 'fact-11-bridge',
          status: 'accepted',
          chapterNum: 11,
          factType: 'stage',
          content: '第11章定稿确认北桥会在三日内坍塌。',
        }, finalProvenance(11)),
        withStateProvenance({
          id: 'fact-10-oath',
          status: 'accepted',
          chapterNum: 10,
          factType: 'relationship',
          content: '第10章定稿确认沈翎仍欠叶珩一次说明。',
        }, finalProvenance(10)),
      ],
      characters: [
        withStateProvenance({
          id: 'char-ye-heng',
          name: '叶珩',
          status: 'active',
          summary: '叶珩持有霜火罗盘，急于救下北桥居民。',
          profile: { currentGoal: '逼沈翎交出城防暗号。' },
        }, finalProvenance(14)),
        withStateProvenance({
          id: 'char-shen-ling',
          name: '沈翎',
          status: 'active',
          summary: '沈翎握有城防暗号，但拒绝公开城主身份。',
          profile: { currentGoal: '拖到撤离完成。' },
        }, finalProvenance(14)),
      ],
      plotThreads: [
        withStateProvenance({
          id: 'thread-north-bridge',
          title: '北桥坍塌线',
          status: 'active',
          summary: '北桥坍塌倒计时推动叶珩与沈翎正面冲突。',
        }, finalProvenance(14)),
      ],
    },
    settingStore: {
      entities: [
        withStateProvenance({
          id: 'entity-compass',
          entityType: 'artifact',
          name: '霜火罗盘',
          status: 'active',
          summary: '罗盘仍在叶珩手中，只剩一次转向。',
          profile: { owner: '叶珩', usesLeft: 1 },
        }, finalProvenance(14)),
        withStateProvenance({
          id: 'entity-clocktower',
          entityType: 'place',
          name: '霜河钟楼',
          status: 'active',
          summary: '沈翎知道城防暗号藏在钟楼铜钟背面。',
        }, finalProvenance(13)),
      ],
      relations: [
        withStateProvenance({
          id: 'rel-ye-shen',
          status: 'active',
          sourceEntityId: 'char-ye-heng',
          sourceEntityName: '叶珩',
          targetEntityId: 'char-shen-ling',
          targetEntityName: '沈翎',
          relationType: '互相怀疑但必须合作',
          summary: '北桥危机迫使两人短暂合作。',
        }, finalProvenance(14)),
      ],
      changeEvents: [
        withStateProvenance({
          id: 'event-compass-owner',
          status: 'accepted',
          chapterNum: 14,
          entityName: '霜火罗盘',
          changeType: 'update_entity',
          fieldPath: 'profile.owner',
          newValue: '叶珩',
        }, finalProvenance(14)),
      ],
    },
    volumeStore: {
      volumes: stages,
    },
    contextOptions: {
      chapters: ledger.chapters,
      chapterVersions: ledger.chapterVersions,
      savedBeatPlans: [
        withStateProvenance({
          chapterNum: 14,
          content: BEAT_CONFLICT_TEXT,
        }, planProvenance(14)),
      ],
      finalizationMarkers: [],
      narrativeVoiceContract: {
        styleBible: ['短场景必须有压力、对白交锋、情绪转折、表情语气、短内心和环境压力。'],
      },
    },
  }
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function replaceChapterWithEmpty(snapshot, chapterNum) {
  const chapter = snapshot.contextOptions.chapters.find(item => item.chapterNum === chapterNum)
  if (chapter) {
    chapter.status = 'drafting'
    chapter.finalVersionId = null
    chapter.wordCount = 0
  }
  const version = snapshot.contextOptions.chapterVersions.find(item => item.chapterNum === chapterNum)
  if (version) {
    version.versionType = 'ai_candidate'
    version.content = ''
  }
}

function makePollutedSnapshot(baseSnapshot) {
  const snapshot = clone(baseSnapshot)
  replaceChapterWithEmpty(snapshot, 12)
  snapshot.settingStore.entities.push(
    withStateProvenance({
      id: 'polluted-failed-entity',
      entityType: 'artifact',
      name: '失败候选霜塔密钥',
      status: 'active',
      summary: '失败候选声称霜塔密钥已经交给叶珩。',
    }, {
      sourceChapterNum: 14,
      sourceVersionId: 'v14-failed-candidate',
      runId: 'run-failed-14',
      finalizationId: '',
      commitStatus: 'failed',
    }),
    withStateProvenance({
      id: 'polluted-empty-entity',
      entityType: 'character',
      name: '空章污染守钟人',
      status: 'active',
      summary: '空章却 accepted 的 active entity。',
    }, {
      sourceChapterNum: 12,
      sourceVersionId: 'v12-empty',
      runId: 'run-empty-12',
      finalizationId: 'fin-empty-12',
      commitStatus: 'final',
    }),
    withStateProvenance({
      id: 'polluted-unfinalized-entity',
      entityType: 'state',
      name: '未定稿暗号状态',
      status: 'active',
      summary: '未定稿状态不应进入权威。',
    }, {
      sourceChapterNum: 14,
      sourceVersionId: 'v14-unfinalized',
      runId: 'run-unfinalized-14',
      finalizationId: '',
      commitStatus: 'unfinalized',
    }),
  )
  snapshot.settingStore.changeEvents.push(
    withStateProvenance({
      id: 'polluted-empty-event',
      status: 'accepted',
      chapterNum: 12,
      entityName: '空章污染守钟人',
      changeType: 'update_entity',
      fieldPath: 'profile.location',
      newValue: '空章声称守钟人已经离城。',
    }, {
      sourceChapterNum: 12,
      sourceVersionId: 'v12-empty',
      runId: 'run-empty-12',
      finalizationId: 'fin-empty-12',
      commitStatus: 'empty_chapter',
    }),
  )
  snapshot.novelStore.outline.nearChapters[0].goal = `错误泄漏：${FUTURE_SECRET}，并让叶珩提前确认。`
  snapshot.contextOptions.finalizationMarkers.push({
    chapterNum: 14,
    sourceVersionId: 'v14-final',
    runId: 'run-half-14',
    finalizationId: 'fin-half-14',
    commitStatus: 'failed_after_chapter_commit',
    reason: 'setting settlement failed after chapter commit',
  })
  return snapshot
}

export function buildCleanSyntheticProjectFixture() {
  const baseSnapshot = makeBaseSnapshot()
  return {
    schemaVersion: 'clean-synthetic-project-fixture-phase2-2-v1',
    chapterNum: CURRENT_CHAPTER,
    finalFactText: FINAL_FACT_TEXT,
    storyBlocks: [
      { id: 'block-1', title: 'Ash Gate Arc', chapterRange: '1-10' },
      { id: 'block-2', title: 'Mirror Siege Arc', chapterRange: '11-18' },
    ],
    stages: baseSnapshot.volumeStore.volumes.map(stage => ({
      id: stage.id,
      storyBlockId: stage.storyBlockId,
      title: stage.title,
      startChapter: stage.startChapter,
      endChapter: stage.endChapter,
      status: stage.status,
    })),
    ledger: {
      chapters: baseSnapshot.contextOptions.chapters,
      chapterVersions: baseSnapshot.contextOptions.chapterVersions,
    },
    savedBeatPlan: {
      conflictWithFinalFact: BEAT_CONFLICT_TEXT,
      authority: 'plan_evidence_only',
    },
    guardOnly: {
      futureRoadmapSecret: FUTURE_SECRET,
      futureChapterNum: 16,
    },
    pollutionVariants: {
      failedCandidateSettingEntity: 'polluted-failed-entity',
      emptyChapterAcceptedEntity: 'polluted-empty-entity',
      unfinalizedActiveState: 'polluted-unfinalized-entity',
      savedBeatConflict: BEAT_CONFLICT_TEXT,
      futureRoadmapLeak: FUTURE_SECRET,
      halfSuccessFinalizationMarker: 'fin-half-14',
    },
    snapshots: {
      healthy: baseSnapshot,
      polluted: makePollutedSnapshot(baseSnapshot),
    },
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

function textContainsAny(text, values) {
  const source = String(text || '')
  return values.some(value => String(value || '').trim() && source.includes(String(value)))
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
    creativeBoundaryEvidence: {
      creativeBoundary: health.creativeContext.creativeBoundary,
      stateLedger: health.creativeContext.stateLedger,
      settingLibrary: health.creativeContext.settingLibrary,
    },
    contextPack: {
      stateAuthorityFacts: health.contextPack.stateAuthority.canonFacts.length,
      guardFutureRoadmapCount: health.contextPack.guardSnapshot.futureRoadmap.length,
      creativeFactCount: health.creativeContext.stateAuthority.canonFacts.length,
    },
    sceneCard: {
      hasConflict: Boolean(sceneCard.conflictPair && sceneCard.conflictPair.includes('叶珩')),
      hasEmotionalTurn: Boolean(sceneCard.emotionalTurn && sceneCard.emotionalTurn.includes('转为')),
      hasStopPoint: Boolean(sceneCard.stopPoint),
      trustedFactCount: Array.isArray(sceneCard.allowedFacts) ? sceneCard.allowedFacts.length : 0,
      stopPoint: sceneCard.stopPoint || '',
      allowedFacts: (sceneCard.allowedFacts || []).map(fact => fact.text || ''),
    },
  }
}

function evaluatePolluted(snapshot) {
  const health = checkProjectStateHealth(snapshot, { chapterNum: CURRENT_CHAPTER })
  const issues = summarizeIssues(health.issues || [])
  const blockingIssues = issues.filter(issue => issue.severity === 'block')
  return {
    ready: !health.blocked,
    healthBlocked: health.blocked,
    issueCodes: uniqueCodes(issues),
    blockingIssues,
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
    authorityFact: projection.stateAuthority.canonFacts.map(fact => fact.content || fact.summary || '').join('\n'),
    rejectedPlanReasons: projection.rejectedProjectionSources
      .filter(item => item.sourceType === 'chapter_beat_plan')
      .map(item => item.reason),
  }
}

function evaluateStageHandoff(snapshot) {
  const health = checkProjectStateHealth(snapshot, { chapterNum: CURRENT_CHAPTER })
  const projection = rebuildStateProjectionFromFinals(snapshot, { chapterNum: CURRENT_CHAPTER })
  const active = health.contextPack.stateAuthority.activeStoryBlock || {}
  const projectionText = JSON.stringify(projection)
  return {
    activeStage: active.title || '',
    sourceType: active.sourceExplanation?.sourceType || '',
    canRebuildFromFinalFacts: Boolean(active.sourceExplanation?.canRebuildFromFinalFacts),
    rebuildHint: active.rebuildHint || '',
    rebuildFinalChapterCount: projection.stateAuthority.finalChapters.length,
    usesFailedCandidate: projectionText.includes('failed') && projectionText.includes('候选正文'),
  }
}

function evaluateFinalizationHalfSuccess(snapshot) {
  const health = checkProjectStateHealth(snapshot, { chapterNum: CURRENT_CHAPTER })
  const marker = snapshot.contextOptions.finalizationMarkers[0] || {}
  return {
    ready: !health.blocked,
    marker: {
      sourceChapterNum: Number(marker.chapterNum || 0),
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
  const sceneCard = health.creativeContext.sceneExecutionCard || {}
  const scenePrompt = [
    formatSceneExecutionCardForPrompt(sceneCard),
    formatNarrativeVoiceContractForPrompt(voice),
  ].join('\n\n')
  const sampleScene = [
    '雨水顺着北桥裂缝往下坠，桥下的霜河像一条被拧紧的铁索。',
    '叶珩把霜火罗盘按在石栏上：“暗号在钟楼，对不对。”',
    '沈翎的声音发哑：“你再逼一句，北桥上这些人就少一刻撤离。”',
    '“你不是背叛，”他盯着她发白的唇，忽然明白，“你是在替他们拖时间。”',
    '她偏开眼：“霜河钟楼。铜钟背面。只到这里。”',
  ].join('\n')
  const quality = evaluateLiteraryQuality(sampleScene, { prompt: scenePrompt })
  const promptQuality = evaluatePromptQuality(scenePrompt)
  return {
    voiceScope: voice.scope || '',
    voiceLintOk: Boolean(voice.lint?.ok),
    scenePromptContainsFutureRoadmap: scenePrompt.includes(fixture.guardOnly.futureRoadmapSecret),
    scenePromptContainsGuardSnapshot: /guardSnapshot|roadmap|futureRoadmap/u.test(scenePrompt),
    qualityPassed: quality.passed,
    qualityScore: quality.score,
    qualityIssueCodes: quality.issues.map(issue => issue.code),
    promptQualityPassed: promptQuality.passed,
    promptIssueCodes: promptQuality.issues.map(issue => issue.code),
    factOrStageOverridePresent: Boolean(voice.factOverrides || voice.stageBoundary || voice.worldRules || voice.guardSnapshot),
  }
}

function buildSummary(results) {
  return {
    healthyReady: Boolean(results.healthyCleanProject.ready),
    pollutedBlocked: Boolean(results.pollutedProject.healthBlocked),
    guardLeaksToCreativeContext: results.healthyCleanProject.creativeContextContainsFutureRoadmap ? 1 : 0,
    savedBeatConflictResolved: Boolean(results.savedBeatConflict.finalFactWins),
    stageHandoffFromFinalState: results.stageHandoff.sourceType === 'final_state',
    finalizationHalfSuccessBlocked: !results.finalizationHalfSuccess.ready &&
      results.finalizationHalfSuccess.blockingIssueCodes.includes('finalization_pending'),
    narrativeVoiceSafe: Boolean(results.narrativeVoice.voiceLintOk) &&
      Boolean(results.narrativeVoice.qualityPassed) &&
      !results.narrativeVoice.scenePromptContainsFutureRoadmap &&
      !results.narrativeVoice.factOrStageOverridePresent,
  }
}

export function runCleanSyntheticProjectRegression() {
  const fixture = buildCleanSyntheticProjectFixture()
  const healthySnapshot = fixture.snapshots.healthy
  const pollutedSnapshot = fixture.snapshots.polluted
  const results = {
    healthyCleanProject: evaluateHealthy(healthySnapshot, fixture),
    pollutedProject: evaluatePolluted(pollutedSnapshot),
    savedBeatConflict: evaluateBeatConflict(healthySnapshot, fixture),
    stageHandoff: evaluateStageHandoff(healthySnapshot),
    finalizationHalfSuccess: evaluateFinalizationHalfSuccess(pollutedSnapshot),
    narrativeVoice: evaluateNarrativeVoice(healthySnapshot, fixture),
  }
  return {
    schemaVersion: 'clean-synthetic-project-regression-phase2-2-v1',
    status: 'completed',
    mode: 'deterministic-no-live',
    timestamp: new Date().toISOString(),
    scope: 'No-live synthetic readiness only; not a real project migration, cleanup, clean canary, or live chapter generation.',
    fixtureCoverage: {
      storyBlocks: fixture.storyBlocks.length,
      stages: fixture.stages.length,
      finalChapters: fixture.ledger.chapters.length,
      chapterRange: `${fixture.ledger.chapters[0].chapterNum}-${fixture.ledger.chapters.at(-1).chapterNum}`,
      hasSavedBeatConflict: Boolean(fixture.savedBeatPlan.conflictWithFinalFact),
      hasGuardOnlyFutureRoadmap: Boolean(fixture.guardOnly.futureRoadmapSecret),
      pollutionVariants: Object.keys(fixture.pollutionVariants),
    },
    summary: buildSummary(results),
    results,
  }
}

export function validateCleanSyntheticRegressionPayload(payload = {}) {
  if (payload.schemaVersion !== 'clean-synthetic-project-regression-phase2-2-v1') {
    throw new Error('Invalid Phase 2.2 clean synthetic regression schemaVersion')
  }
  if (payload.status !== 'completed') return true
  const expectedCoverage = {
    storyBlocks: 2,
    stages: 3,
    hasSavedBeatConflict: true,
    hasGuardOnlyFutureRoadmap: true,
  }
  for (const [key, expected] of Object.entries(expectedCoverage)) {
    if (payload.fixtureCoverage?.[key] !== expected) throw new Error(`fixtureCoverage.${key} mismatch`)
  }
  if (payload.fixtureCoverage.finalChapters < 12 || payload.fixtureCoverage.finalChapters > 20) {
    throw new Error('fixtureCoverage.finalChapters must be 12-20')
  }
  const results = payload.results || {}
  for (const key of [
    'healthyCleanProject',
    'pollutedProject',
    'savedBeatConflict',
    'stageHandoff',
    'finalizationHalfSuccess',
    'narrativeVoice',
  ]) {
    if (!results[key]) throw new Error(`Missing result ${key}`)
  }
  const expectedSummary = buildSummary(results)
  for (const [key, expected] of Object.entries(expectedSummary)) {
    if (payload.summary?.[key] !== expected) throw new Error(`summary.${key} mismatch`)
  }
  if (!results.healthyCleanProject.ready) throw new Error('healthyCleanProject must be ready')
  if (!results.pollutedProject.healthBlocked) throw new Error('pollutedProject must be blocked')
  if (results.healthyCleanProject.creativeContextContainsFutureRoadmap) {
    throw new Error('healthy creative context leaked future roadmap')
  }
  if (!results.savedBeatConflict.finalFactWins) throw new Error('saved beat conflict must resolve to final fact')
  if (results.stageHandoff.sourceType !== 'final_state') throw new Error('stage handoff must come from final_state')
  if (results.finalizationHalfSuccess.ready) throw new Error('half-success finalization must block readiness')
  return true
}

function issueText(values = []) {
  return values?.length ? values.join(',') : 'none'
}

export function buildCleanSyntheticProjectReport(payload) {
  validateCleanSyntheticRegressionPayload(payload)
  const lines = [
    '# Clean Synthetic Project Regression Phase 2.2 Report',
    '',
    'Status: completed deterministic no-live synthetic readiness regression.',
    '',
    '## Scope Guard',
    '- No-live synthetic readiness only; this is not a real project migration, real cleanup, clean canary, or live chapter generation.',
    '- Did not start backend/frontend dev server, runner, or page.goto.',
    '- Did not run formal chapter generation/finalization chain.',
    '- Did not write real DB data or execute migrations/cleanup.',
    '- Did not restore LongformBrowser or run #98/#99/#50.',
    '- Did not save model output as project正文、小纲、beat plan, or DB state.',
    '- Did not enter Phase 3 provider/model adapter work.',
    '',
    '## Fixture Coverage',
    `fixtureStoryBlocks=${payload.fixtureCoverage.storyBlocks}`,
    `fixtureStages=${payload.fixtureCoverage.stages}`,
    `fixtureFinalChapters=${payload.fixtureCoverage.finalChapters}`,
    `fixtureChapterRange=${payload.fixtureCoverage.chapterRange}`,
    `fixtureHasSavedBeatConflict=${payload.fixtureCoverage.hasSavedBeatConflict}`,
    `fixtureHasGuardOnlyFutureRoadmap=${payload.fixtureCoverage.hasGuardOnlyFutureRoadmap}`,
    `fixturePollutionVariants=${payload.fixtureCoverage.pollutionVariants.join(',')}`,
    '',
    '## Summary',
    `healthyReady=${payload.summary.healthyReady}`,
    `pollutedBlocked=${payload.summary.pollutedBlocked}`,
    `newPromptEquivalentGuardLeaks=${payload.summary.guardLeaksToCreativeContext}`,
    `savedBeatConflictResolved=${payload.summary.savedBeatConflictResolved}`,
    `stageHandoffFromFinalState=${payload.summary.stageHandoffFromFinalState}`,
    `finalizationHalfSuccessBlocked=${payload.summary.finalizationHalfSuccessBlocked}`,
    `narrativeVoiceSafe=${payload.summary.narrativeVoiceSafe}`,
    '',
    '## Scenario Results',
    '| scenario | evidence |',
    '| --- | --- |',
    `| healthy | healthy.ready=${payload.results.healthyCleanProject.ready}; healthBlocked=${payload.results.healthyCleanProject.healthBlocked}; creativeContextContainsFutureRoadmap=${payload.results.healthyCleanProject.creativeContextContainsFutureRoadmap}; trustedFactCount=${payload.results.healthyCleanProject.sceneCard.trustedFactCount}; hasConflict=${payload.results.healthyCleanProject.sceneCard.hasConflict}; hasEmotionalTurn=${payload.results.healthyCleanProject.sceneCard.hasEmotionalTurn}; hasStopPoint=${payload.results.healthyCleanProject.sceneCard.hasStopPoint} |`,
    `| polluted | polluted.ready=${payload.results.pollutedProject.ready}; healthBlocked=${payload.results.pollutedProject.healthBlocked}; issueCodes=${issueText(payload.results.pollutedProject.issueCodes)}; blockingIssueCount=${payload.results.pollutedProject.blockingIssues.length} |`,
    `| savedBeatConflict | finalFactWins=${payload.results.savedBeatConflict.finalFactWins}; beatPlanAuthority=${payload.results.savedBeatConflict.beatPlanAuthority}; creativeContextContainsConflictingBeat=${payload.results.savedBeatConflict.creativeContextContainsConflictingBeat}; rejectedPlanReasons=${issueText(payload.results.savedBeatConflict.rejectedPlanReasons)} |`,
    `| stageHandoff | activeStage=${payload.results.stageHandoff.activeStage}; sourceType=${payload.results.stageHandoff.sourceType}; canRebuildFromFinalFacts=${payload.results.stageHandoff.canRebuildFromFinalFacts}; usesFailedCandidate=${payload.results.stageHandoff.usesFailedCandidate}; rebuildFinalChapterCount=${payload.results.stageHandoff.rebuildFinalChapterCount} |`,
    `| finalization | ready=${payload.results.finalizationHalfSuccess.ready}; markerStatus=${payload.results.finalizationHalfSuccess.marker.commitStatus}; markerSourceChapter=${payload.results.finalizationHalfSuccess.marker.sourceChapterNum}; blockingIssueCodes=${issueText(payload.results.finalizationHalfSuccess.blockingIssueCodes)} |`,
    `| narrative | voiceScope=${payload.results.narrativeVoice.voiceScope}; voiceLintOk=${payload.results.narrativeVoice.voiceLintOk}; scenePromptContainsFutureRoadmap=${payload.results.narrativeVoice.scenePromptContainsFutureRoadmap}; scenePromptContainsGuardSnapshot=${payload.results.narrativeVoice.scenePromptContainsGuardSnapshot}; narrative.qualityPassed=${payload.results.narrativeVoice.qualityPassed}; promptQualityPassed=${payload.results.narrativeVoice.promptQualityPassed}; factOrStageOverridePresent=${payload.results.narrativeVoice.factOrStageOverridePresent} |`,
    '',
    '## Evidence Contract',
    '- JSON/report alignment is strict: summary lines, fixture coverage lines, scenario rows, and key-value cells are parsed and compared; stale+correct duplicates are rejected.',
    '- Future-roadmap isolation is deterministic string evidence over this synthetic fixture; this does not claim full semantic leak detection.',
    '- Saved beat plans remain plan evidence; final facts win in state projection and creative context.',
    '',
    '## Remaining Risks',
    '- Real DB migrations remain unexecuted.',
    '- Real project cleanup and legacy data repair have not been performed.',
    '- Clean project regression and live canary have not been run.',
    '- This synthetic fixture is not production data and must not be treated as a real project.',
    '',
    '## Review',
    payload.review
      ? `Fresh review subthread=${payload.review.threadId}; critical=${payload.review.critical}; important=${payload.review.important}; conclusion=${payload.review.conclusion}`
      : 'Fresh review pending.',
  ]
  if (Array.isArray(payload.verification?.commands) && payload.verification.commands.length) {
    lines.push('', '## Verification')
    for (const command of payload.verification.commands) {
      lines.push(`- ${command.command}: ${command.result}`)
    }
  }
  return `${lines.join('\n')}\n`
}

export function assertCleanSyntheticReportMatchesJson(reportText, payload) {
  validateCleanSyntheticRegressionPayload(payload)
  if (payload.status !== 'completed') return true
  const report = String(reportText || '')
  const lineChecks = {
    fixtureStoryBlocks: payload.fixtureCoverage.storyBlocks,
    fixtureStages: payload.fixtureCoverage.stages,
    fixtureFinalChapters: payload.fixtureCoverage.finalChapters,
    fixtureChapterRange: payload.fixtureCoverage.chapterRange,
    fixtureHasSavedBeatConflict: payload.fixtureCoverage.hasSavedBeatConflict,
    fixtureHasGuardOnlyFutureRoadmap: payload.fixtureCoverage.hasGuardOnlyFutureRoadmap,
    fixturePollutionVariants: payload.fixtureCoverage.pollutionVariants.join(','),
    healthyReady: payload.summary.healthyReady,
    pollutedBlocked: payload.summary.pollutedBlocked,
    newPromptEquivalentGuardLeaks: payload.summary.guardLeaksToCreativeContext,
    savedBeatConflictResolved: payload.summary.savedBeatConflictResolved,
    stageHandoffFromFinalState: payload.summary.stageHandoffFromFinalState,
    finalizationHalfSuccessBlocked: payload.summary.finalizationHalfSuccessBlocked,
    narrativeVoiceSafe: payload.summary.narrativeVoiceSafe,
  }
  for (const [key, expected] of Object.entries(lineChecks)) {
    const actual = extractSingleLineValue(report, key)
    if (actual !== String(expected)) {
      const alias = key === 'newPromptEquivalentGuardLeaks' ? 'guardLeaksToCreativeContext' : key
      throw new Error(`Report/JSON mismatch for ${alias}: ${actual} expected ${expected}`)
    }
  }
  const rows = {
    healthy: {
      'healthy.ready': payload.results.healthyCleanProject.ready,
      healthBlocked: payload.results.healthyCleanProject.healthBlocked,
      creativeContextContainsFutureRoadmap: payload.results.healthyCleanProject.creativeContextContainsFutureRoadmap,
      trustedFactCount: payload.results.healthyCleanProject.sceneCard.trustedFactCount,
      hasConflict: payload.results.healthyCleanProject.sceneCard.hasConflict,
      hasEmotionalTurn: payload.results.healthyCleanProject.sceneCard.hasEmotionalTurn,
      hasStopPoint: payload.results.healthyCleanProject.sceneCard.hasStopPoint,
    },
    polluted: {
      'polluted.ready': payload.results.pollutedProject.ready,
      healthBlocked: payload.results.pollutedProject.healthBlocked,
      issueCodes: issueText(payload.results.pollutedProject.issueCodes),
      blockingIssueCount: payload.results.pollutedProject.blockingIssues.length,
    },
    savedBeatConflict: {
      finalFactWins: payload.results.savedBeatConflict.finalFactWins,
      beatPlanAuthority: payload.results.savedBeatConflict.beatPlanAuthority,
      creativeContextContainsConflictingBeat: payload.results.savedBeatConflict.creativeContextContainsConflictingBeat,
      rejectedPlanReasons: issueText(payload.results.savedBeatConflict.rejectedPlanReasons),
    },
    stageHandoff: {
      activeStage: payload.results.stageHandoff.activeStage,
      sourceType: payload.results.stageHandoff.sourceType,
      canRebuildFromFinalFacts: payload.results.stageHandoff.canRebuildFromFinalFacts,
      usesFailedCandidate: payload.results.stageHandoff.usesFailedCandidate,
      rebuildFinalChapterCount: payload.results.stageHandoff.rebuildFinalChapterCount,
    },
    finalization: {
      ready: payload.results.finalizationHalfSuccess.ready,
      markerStatus: payload.results.finalizationHalfSuccess.marker.commitStatus,
      markerSourceChapter: payload.results.finalizationHalfSuccess.marker.sourceChapterNum,
      blockingIssueCodes: issueText(payload.results.finalizationHalfSuccess.blockingIssueCodes),
    },
    narrative: {
      voiceScope: payload.results.narrativeVoice.voiceScope,
      voiceLintOk: payload.results.narrativeVoice.voiceLintOk,
      scenePromptContainsFutureRoadmap: payload.results.narrativeVoice.scenePromptContainsFutureRoadmap,
      scenePromptContainsGuardSnapshot: payload.results.narrativeVoice.scenePromptContainsGuardSnapshot,
      'narrative.qualityPassed': payload.results.narrativeVoice.qualityPassed,
      promptQualityPassed: payload.results.narrativeVoice.promptQualityPassed,
      factOrStageOverridePresent: payload.results.narrativeVoice.factOrStageOverridePresent,
    },
  }
  for (const [label, expectedValues] of Object.entries(rows)) {
    const row = findSingleMarkdownRow(report, label)
    const cells = parseMarkdownRow(row)
    if (cells.length !== 2 || cells[0] !== label) {
      throw new Error(`Report/JSON mismatch for ${label} row`)
    }
    assertKeyValueCell(cells[1], expectedValues, label)
  }
  return true
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function extractSingleLineValue(report, key) {
  const pattern = new RegExp(`^${escapeRegExp(key)}=(.*)$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) {
    throw new Error(`Report/JSON mismatch for ${key}: appears ${matches.length} times`)
  }
  return matches[0][1].trim()
}

function findSingleMarkdownRow(report, firstCell) {
  const pattern = new RegExp(`^\\| ${escapeRegExp(firstCell)} \\|.*$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) {
    throw new Error(`Report/JSON mismatch for row ${firstCell}: appears ${matches.length} times`)
  }
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
  const payload = runCleanSyntheticProjectRegression()
  const report = buildCleanSyntheticProjectReport(payload)
  assertCleanSyntheticReportMatchesJson(report, payload)
  await fs.mkdir(OUT_DIR, { recursive: true })
  await fs.writeFile(OUT_JSON, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
  await fs.writeFile(OUT_REPORT, report, 'utf8')
  console.log(`clean synthetic phase2.2 regression wrote ${OUT_JSON} and ${OUT_REPORT}`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  main().catch(error => {
    console.error(error)
    process.exit(1)
  })
}
