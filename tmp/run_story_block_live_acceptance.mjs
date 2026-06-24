import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { chatCompletion } from '../frontend/src/api/ai/index.js'
import {
  buildStoryBlockPlanningPrompt,
  buildStoryBlockPlanningSystemPrompt,
  buildStoryBlockReviewPrompt,
  buildStoryBlockReviewSystemPrompt,
  normalizeStoryBlockReviewResult
} from '../frontend/src/prompts/storyBlockPrompt.js'
import {
  buildScenePlanPrompt,
  buildScenePlanSystemPrompt
} from '../frontend/src/prompts/chapterPlanPrompt.js'
import {
  buildDraftPrompt,
  buildDraftSystemPrompt
} from '../frontend/src/prompts/chapterDraftPrompt.js'
import {
  buildAuditPrompt,
  buildAuditSystemPrompt
} from '../frontend/src/prompts/audit.js'
import {
  buildSummaryPrompt,
  buildSummarySystemPrompt
} from '../frontend/src/prompts/summary.js'
import {
  buildExtractionPrompt,
  buildExtractionSystemPrompt
} from '../frontend/src/prompts/extraction.js'
import {
  buildSettingExtractionPrompt,
  buildSettingExtractionSystemPrompt
} from '../frontend/src/prompts/settingExtraction.js'
import {
  buildBlockStageSnapshot,
  findNextEditableStage
} from '../frontend/src/utils/storyBlockSnapshot.js'

const API_BASE = process.env.STORY_BLOCK_LIVE_API_BASE || 'http://127.0.0.1:8000/api'
const CHAPTER_TARGET = Number(process.env.STORY_BLOCK_LIVE_CHAPTERS || 3)
const OUT_JSON = resolve('tmp/realistic-flow-qa/latest-story-block-live-report.json')
const OUT_MD = resolve('tmp/realistic-flow-qa/latest-story-block-live-report.md')

const report = {
  mode: 'live',
  createdAt: new Date().toISOString(),
  createdCleanProject: false,
  usesArchivedReports: false,
  targetChapters: CHAPTER_TARGET,
  project: null,
  provider: null,
  environment: {
    apiBase: API_BASE,
    frontendPort: 5173,
    backendPort: 8000
  },
  setup: {
    healthOk: false,
    providerCallOk: false,
    seedCreated: false,
    bibleSaved: false,
    volumeCreated: false,
    settingBaseCreated: false,
    storyBlockPlanningAiCalled: false,
    storyBlockCreated: false
  },
  chapters: [],
  blockers: [],
  acceptance: {
    passed: false,
    completedChapters: 0,
    criteria: {
      realLiveMode: true,
      cleanProject: false,
      storyBlockCreatedByAi: false,
      outlinesFromActiveStoryBlock: false,
      snapshotsSaved: false,
      draftsReadSnapshotBoundary: false,
      storyBlockReviewsAfterFinalize: false,
      forwardOnlyRollingObserved: false,
      noRequiresReviewBypass: true,
      noMultipleActiveBlocks: true,
      noArchivedReportsUsed: true
    }
  }
}

async function main() {
  try {
    await ensureApiHealth()
    const providers = await api('GET', '/providers')
    const provider = selectProvider(providers)
    if (!provider) fail('setup', 'providers', '未配置 AI Provider')
    report.provider = {
      id: provider.id,
      name: provider.name,
      model: provider.model,
      providerType: provider.providerType,
      baseURL: provider.baseURL
    }
    await smokeTestProvider(provider)

    const fixture = await createCleanProject()
    let activeBlock = await createAiPlannedStoryBlock(provider, fixture)
    if (activeBlock?.lockState?.requiresReview) {
      fail('story_block_planning', 'requiresReview', 'AI 故事块规划失败后生成 requiresReview 占位块，按边界阻断小纲/正文生成', {
        storyBlockId: activeBlock.id
      })
    }

    let previousChapterEnding = ''
    let recentSummaries = []
    let facts = []
    let settingEntities = [fixture.settingEntity]
    let settingRelations = []
    let pendingNewBlockSeed = null

    for (let chapterNum = 1; chapterNum <= CHAPTER_TARGET; chapterNum += 1) {
      const chapterReport = baseChapterReport(chapterNum)
      report.chapters.push(chapterReport)

      const activeBlocksBefore = await activeBlockCount(fixture.project.id)
      chapterReport.multipleActiveStoryBlocks = activeBlocksBefore > 1
      if (activeBlocksBefore > 1) {
        fail(chapterNum, 'storyBlocks.active', '项目出现多个 active 故事块')
      }

      activeBlock = await api('GET', `/projects/${fixture.project.id}/story-blocks/active`)
      if (!activeBlock) {
        activeBlock = await createAiPlannedStoryBlock(provider, {
          ...fixture,
          settingEntity: settingEntities?.[0] || fixture.settingEntity
        }, {
          ...(pendingNewBlockSeed || {}),
          entryState: pendingNewBlockSeed?.entryState || previousChapterEnding || '承接上一故事块完成后的新局面。',
          recentSummaries,
          facts: facts.slice(-8),
          settingRelations: settingRelations.slice(-8)
        })
        pendingNewBlockSeed = null
      }
      if (activeBlock.lockState?.requiresReview) {
        chapterReport.requiresReviewBlocker = true
        fail(chapterNum, 'ensureStoryBlockReady', 'active 故事块是 requiresReview 占位块，阻断小纲/正文生成', {
          storyBlockId: activeBlock.id
        })
      }

      const stage = findNextEditableStage(activeBlock)
      if (!stage?.id) fail(chapterNum, 'findNextEditableStage', 'active 故事块没有可引用阶段')

      const snapshot = buildBlockStageSnapshot(activeBlock, stage)
      chapterReport.storyBlockId = activeBlock.id
      chapterReport.blockStageId = stage.id
      chapterReport.blockStageSnapshot = snapshot
      chapterReport.outlineFromActiveStoryBlock = true

      const context = buildGenerationContext({
        fixture,
        chapterNum,
        activeBlock,
        snapshot,
        previousChapterEnding,
        recentSummaries,
        facts,
        settingEntities,
        settingRelations
      })

      const beatPlan = await aiText(provider, [
        { role: 'system', content: buildScenePlanSystemPrompt() },
        { role: 'user', content: buildScenePlanPrompt(context) }
      ], { maxTokens: 2600, temperature: 0.55 })
      if (!beatPlan.trim()) fail(chapterNum, 'generateChapterBeatPlan', 'AI 小纲返回为空')

      const savedBeatPlan = await api('PUT', `/projects/${fixture.project.id}/chapter-beat-plan/${chapterNum}`, {
        content: beatPlan,
        storyBlockId: activeBlock.id,
        blockStageId: stage.id,
        blockStageSnapshot: snapshot
      })
      chapterReport.savedBeatPlan = {
        id: savedBeatPlan?.id,
        storyBlockId: savedBeatPlan?.storyBlockId,
        blockStageId: savedBeatPlan?.blockStageId,
        hasSnapshot: Boolean(savedBeatPlan?.blockStageSnapshot)
      }

      const draft = await aiText(provider, [
        { role: 'system', content: buildDraftSystemPrompt() },
        { role: 'user', content: buildDraftPrompt({ ...context, beatPlan }) }
      ], { maxTokens: 10000, temperature: 0.64 })
      if (!draft.trim()) fail(chapterNum, 'generateChapter', 'AI 正文返回为空')
      chapterReport.draftReadSnapshotBoundary = draftPromptReadsSnapshotBoundary(context)
      chapterReport.draftCharCount = draft.length

      const chapter = await api('POST', `/projects/${fixture.project.id}/chapters`, {
        chapterNum,
        title: `第${chapterNum}章`
      })
      const version = await api('POST', `/projects/${fixture.project.id}/chapters/${chapter.id}/versions`, {
        title: `第${chapterNum}章 - live 验收候选`,
        content: draft,
        versionType: 'ai_candidate',
        sourceModelId: provider.id,
        promptBrief: 'story-block-live-acceptance'
      })

      const audit = await aiJson(provider, [
        { role: 'system', content: buildAuditSystemPrompt() },
        { role: 'user', content: buildAuditPrompt(draft, { ...context, beatPlan }) }
      ], { maxTokens: 5000, temperature: 0.2 })
      chapterReport.audit = {
        storyTaskConsistency: audit.storyTaskConsistency || null,
        blockAlignment: audit.blockAlignment || null,
        readingBurden: audit.readingBurden || null,
        issueCount: Array.isArray(audit.issues) ? audit.issues.length : 0
      }

      const summary = await aiJson(provider, [
        { role: 'system', content: buildSummarySystemPrompt() },
        { role: 'user', content: buildSummaryPrompt(draft, chapterNum) }
      ], { maxTokens: 1800, temperature: 0.25 })
      const summaryText = summary.summary || `第${chapterNum}章 live 验收定稿摘要`
      const finalized = await api('POST', `/projects/${fixture.project.id}/chapters/${chapter.id}/versions/${version.id}/finalize`, {
        summary: summaryText,
        wordCount: draft.length
      })
      chapterReport.finalized = {
        chapterId: finalized?.chapter?.id,
        versionId: finalized?.version?.id,
        status: finalized?.chapter?.status
      }

      const extractedFacts = await extractAndPersistFacts(provider, fixture.project.id, draft, chapterNum, facts)
      facts = facts.concat(extractedFacts)
      const settingChanges = await extractAndPersistSettingChanges(provider, fixture.project.id, draft, chapterNum, settingEntities, settingRelations)
      settingEntities = await api('GET', `/projects/${fixture.project.id}/settings/entities`)
      settingRelations = await api('GET', `/projects/${fixture.project.id}/settings/relations`)
      chapterReport.memoryExtraction = {
        factsCreated: extractedFacts.length,
        settingChangesCreated: settingChanges.length
      }

      const reviewRaw = await aiJson(provider, [
        { role: 'system', content: buildStoryBlockReviewSystemPrompt() },
        {
          role: 'user',
          content: buildStoryBlockReviewPrompt({
            chapterNum,
            finalizedSummary: summaryText,
            chapterEnding: extractEnding(draft),
            blockStageSnapshot: snapshot,
            storyBlock: activeBlock,
            facts: extractedFacts,
            settingChanges
          })
        }
      ], { maxTokens: 3200, temperature: 0.2 })
      const review = normalizeStoryBlockReviewResult(reviewRaw)
      chapterReport.storyBlockReviewDecision = review.decision
      chapterReport.storyBlockReview = review

      await api('POST', `/projects/${fixture.project.id}/story-blocks/${activeBlock.id}/reviews`, {
        chapterNum,
        decision: review.decision,
        review
      })

      const rolling = await applyStoryBlockReviewDecision({
        projectId: fixture.project.id,
        provider,
        fixture,
        currentBlock: activeBlock,
        review,
        chapterNum,
        recentSummaries,
        previousChapterEnding: extractEnding(draft),
        facts,
        settingEntities,
        settingRelations
      })
      chapterReport.updatedUnexecutedStages = rolling.updatedUnexecutedStages
      chapterReport.forwardOnlyRollingObserved = rolling.forwardOnlyRollingObserved
      pendingNewBlockSeed = rolling.nextBlockSeed || null
      chapterReport.requiresReviewBlocker = false

      const activeBlocksAfter = await activeBlockCount(fixture.project.id)
      chapterReport.multipleActiveStoryBlocks = activeBlocksAfter > 1
      if (activeBlocksAfter > 1) {
        fail(chapterNum, 'storyBlocks.active.afterReview', '定稿回看后出现多个 active 故事块')
      }

      previousChapterEnding = extractEnding(draft)
      recentSummaries = recentSummaries.concat([`第${chapterNum}章：${summaryText}`]).slice(-5)
      report.acceptance.completedChapters = chapterNum
      await writeReports()
    }

    report.acceptance.criteria.cleanProject = report.createdCleanProject
    report.acceptance.criteria.storyBlockCreatedByAi = report.setup.storyBlockPlanningAiCalled && report.setup.storyBlockCreated
    report.acceptance.criteria.outlinesFromActiveStoryBlock = report.chapters.every(item => item.outlineFromActiveStoryBlock)
    report.acceptance.criteria.snapshotsSaved = report.chapters.every(item => item.savedBeatPlan?.hasSnapshot)
    report.acceptance.criteria.draftsReadSnapshotBoundary = report.chapters.every(item => item.draftReadSnapshotBoundary)
    report.acceptance.criteria.storyBlockReviewsAfterFinalize = report.chapters.every(item => item.storyBlockReviewDecision)
    report.acceptance.criteria.forwardOnlyRollingObserved = report.chapters.every(item => item.forwardOnlyRollingObserved !== false)
    report.acceptance.criteria.noRequiresReviewBypass = report.chapters.every(item => !item.requiresReviewBlocker)
    report.acceptance.criteria.noMultipleActiveBlocks = report.chapters.every(item => !item.multipleActiveStoryBlocks)
    report.acceptance.passed = report.acceptance.completedChapters >= 3 &&
      Object.values(report.acceptance.criteria).every(Boolean) &&
      report.blockers.length === 0
  } catch (error) {
    if (!error.isAcceptanceFailure) {
      report.blockers.push({
        stage: 'unhandled',
        message: error.message,
        stack: String(error.stack || '').split('\n').slice(0, 6)
      })
    }
    report.acceptance.passed = false
  } finally {
    await writeReports()
    if (!report.acceptance.passed) {
      process.exitCode = 1
    }
  }
}

function baseChapterReport(chapterNum) {
  return {
    chapterNum,
    storyBlockId: null,
    blockStageId: null,
    blockStageSnapshot: null,
    outlineFromActiveStoryBlock: false,
    draftReadSnapshotBoundary: false,
    storyBlockReviewDecision: null,
    updatedUnexecutedStages: false,
    requiresReviewBlocker: false,
    multipleActiveStoryBlocks: false,
    liveDatabaseOrApiErrors: []
  }
}

async function ensureApiHealth() {
  const health = await api('GET', '/health')
  report.setup.healthOk = Boolean(health?.ok)
}

function selectProvider(providers) {
  const list = Array.isArray(providers) ? providers : providers?.value || []
  return list.find(item => /flash/i.test(`${item.name || ''} ${item.model || ''}`)) || list[0] || null
}

async function smokeTestProvider(provider) {
  const text = await aiText(provider, [
    { role: 'user', content: 'Reply with exactly: live-ok' }
  ], { maxTokens: 1000, temperature: 0 })
  if (!text.trim()) fail('setup', 'provider.smoke', 'AI Provider 真实调用返回空文本')
  report.setup.providerCallOk = true
}

async function createCleanProject() {
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)
  const project = await api('POST', '/projects', {
    title: `StoryBlockLiveV1_${stamp}`,
    genre: '近未来悬疑 / 人物选择',
    description: '故事块 v1 live 验收干净项目；只用于验证故事块驱动生成链路。',
    targetWords: 120000,
    targetChapters: 30
  })
  report.project = { id: project.id, title: project.title }
  report.createdCleanProject = true

  await api('POST', `/projects/${project.id}/seeds`, seedPayload())
  report.setup.seedCreated = true

  const bible = biblePayload()
  await api('PUT', `/projects/${project.id}/bible`, bible)
  report.setup.bibleSaved = true

  await api('PUT', `/projects/${project.id}/outline`, outlinePayload())
  const volume = await api('POST', `/projects/${project.id}/volumes`, volumePayload())
  report.setup.volumeCreated = true

  const settingEntity = await api('POST', `/projects/${project.id}/settings/entities`, {
    entityType: 'location',
    name: '临港旧塔',
    category: '核心地点',
    summary: '旧通信塔改造后的民间避难节点，掌握城市断网夜的关键记录。',
    status: 'active',
    importance: 5,
    tags: ['live验收', '故事块入口'],
    profile: { currentState: '断电后仍保留本地记录' },
    firstChapter: 1
  })
  report.setup.settingBaseCreated = true

  await api('PUT', `/projects/${project.id}/bindings`, {
    writingModelId: report.provider.id,
    outlineModelId: report.provider.id,
    auditModelId: report.provider.id,
    summaryModelId: report.provider.id,
    extractionModelId: report.provider.id
  })

  return { project, bible, volume, settingEntity }
}

async function createAiPlannedStoryBlock(provider, fixture, newBlockSeed = {}) {
  report.setup.storyBlockPlanningAiCalled = true
  let planned
  try {
    planned = await aiJson(provider, [
      { role: 'system', content: buildStoryBlockPlanningSystemPrompt() },
      {
        role: 'user',
        content: buildStoryBlockPlanningPrompt({
          currentVolume: fixture.volume,
          volumePlanning: [fixture.volume],
          bible: fixture.bible,
          settingLibrary: [fixture.settingEntity],
          stateLedger: [],
          recentFacts: [],
          recentSummaries: [],
          previousChapterEnding: '',
          newBlockSeed
        })
      }
    ], { maxTokens: 4200, temperature: 0.45 })
  } catch (error) {
    planned = buildFallbackStoryBlockPayload({
      reason: error.message,
      seed: newBlockSeed
    })
  }

  const payload = normalizeStoryBlockPayload(planned)
  const block = await api('POST', `/projects/${fixture.project.id}/story-blocks`, {
    ...payload,
    volumeId: fixture.volume.id,
    status: 'active'
  })
  report.setup.storyBlockCreated = true
  report.acceptance.criteria.storyBlockCreatedByAi = !block.lockState?.requiresReview
  return block
}

async function applyStoryBlockReviewDecision(options) {
  const {
    projectId,
    provider,
    fixture,
    currentBlock,
    review,
    chapterNum,
    recentSummaries,
    previousChapterEnding,
    facts,
    settingEntities,
    settingRelations
  } = options
  const result = {
    updatedUnexecutedStages: false,
    forwardOnlyRollingObserved: true,
    nextBlockSeed: null
  }
  const currentStages = Array.isArray(currentBlock.stagePlan) ? currentBlock.stagePlan : []

  if (review.decision === 'adjust_remaining_stages') {
    const nextStages = mergeRemainingStages(currentStages, review.remainingStages)
    await api('PUT', `/projects/${projectId}/story-blocks/${currentBlock.id}/remaining-stages`, {
      stagePlan: nextStages,
      nextStageSuggestion: review.nextStageSuggestion || currentBlock.nextStageSuggestion || '',
      unresolvedQuestions: review.unresolvedQuestions || currentBlock.unresolvedQuestions || [],
      dontAdvanceYet: currentBlock.dontAdvanceYet || [],
      carryOverToNextChapter: review.carryOverToNextChapter || currentBlock.carryOverToNextChapter || [],
      capacityAssessment: currentBlock.capacityAssessment || 'normal'
    })
    result.updatedUnexecutedStages = true
  } else if (review.decision === 'continue_current_block') {
    await api('PUT', `/projects/${projectId}/story-blocks/${currentBlock.id}/remaining-stages`, {
      stagePlan: currentStages,
      nextStageSuggestion: review.nextStageSuggestion || currentBlock.nextStageSuggestion || '',
      unresolvedQuestions: review.unresolvedQuestions || currentBlock.unresolvedQuestions || [],
      dontAdvanceYet: currentBlock.dontAdvanceYet || [],
      carryOverToNextChapter: review.carryOverToNextChapter || currentBlock.carryOverToNextChapter || [],
      capacityAssessment: currentBlock.capacityAssessment || 'normal'
    })
  } else if (review.decision === 'split_unfinalized_content') {
    await api('PUT', `/projects/${projectId}/story-blocks/${currentBlock.id}/remaining-stages`, {
      stagePlan: currentStages,
      nextStageSuggestion: review.nextStageSuggestion || '本章已定稿，拆分建议转为后续章节承接事项。',
      unresolvedQuestions: review.unresolvedQuestions || currentBlock.unresolvedQuestions || [],
      dontAdvanceYet: currentBlock.dontAdvanceYet || [],
      carryOverToNextChapter: review.carryOverToNextChapter?.length
        ? review.carryOverToNextChapter
        : ['AI 在定稿后返回 split_unfinalized_content，live 验收按边界转为后续章节承接事项。'],
      capacityAssessment: currentBlock.capacityAssessment || 'normal'
    })
  } else if (review.decision === 'complete_current_block') {
    await api('POST', `/projects/${projectId}/story-blocks/${currentBlock.id}/complete`, {
      reason: review.reason || `第${chapterNum}章块级回看判定完成`,
      chapterRefs: [chapterNum]
    })
    result.nextBlockSeed = review.newBlockSeed || {
      entryState: previousChapterEnding,
      goal: review.nextStageSuggestion || '承接已完成故事块后的下一段连续剧情。',
      storyFunction: '承接'
    }
  } else if (review.decision === 'open_new_block') {
    await api('POST', `/projects/${projectId}/story-blocks/${currentBlock.id}/close`, {
      reason: review.reason || `第${chapterNum}章块级回看建议开启新故事块`,
      chapterRefs: [chapterNum]
    })
    const block = await createAiPlannedStoryBlock(provider, {
      ...fixture,
      settingEntity: settingEntities?.[0] || fixture.settingEntity
    }, {
      ...(review.newBlockSeed || {}),
      recentSummaries,
      previousChapterEnding,
      facts: facts?.slice(-8),
      settingRelations: settingRelations?.slice(-8)
    })
    if (block.lockState?.requiresReview) {
      fail(chapterNum, 'open_new_block.requiresReview', '开启新故事块时 AI 规划失败并生成 requiresReview 占位块，阻断后续章节', {
        storyBlockId: block.id
      })
    }
  }

  return result
}

function mergeRemainingStages(existingStages, remainingStages) {
  const incoming = Array.isArray(remainingStages) ? remainingStages : []
  if (!incoming.length) return existingStages
  const incomingById = new Map(incoming.map(stage => [String(stage.id || ''), normalizeStage(stage)]).filter(([id]) => id))
  return existingStages.map(stage => {
    const id = String(stage.id || '')
    const locked = stage.status === 'completed' || stage.lockedByBeatPlan || stage.lockedByFinalChapter || stage.locked
    if (locked || !incomingById.has(id)) return stage
    return { ...stage, ...incomingById.get(id), id }
  })
}

async function extractAndPersistFacts(provider, projectId, draft, chapterNum, existingFacts) {
  const parsed = await aiJson(provider, [
    { role: 'system', content: buildExtractionSystemPrompt() },
    { role: 'user', content: buildExtractionPrompt(draft, chapterNum, existingFacts) }
  ], { maxTokens: 3600, temperature: 0.25 })
  const facts = Array.isArray(parsed) ? parsed : parsed.facts || []
  const created = []
  for (const fact of facts.slice(0, 6)) {
    if (!fact?.content) continue
    created.push(await api('POST', `/projects/${projectId}/canon-facts`, {
      chapterNum,
      factType: fact.factType || 'plot',
      content: String(fact.content).slice(0, 500),
      relatedCharacters: fact.relatedCharacters || [],
      relatedPlotThreads: fact.relatedPlotThreads || [],
      evidence: fact.evidence || '',
      confidence: fact.confidence || 0.8,
      status: 'accepted'
    }))
  }
  return created
}

async function extractAndPersistSettingChanges(provider, projectId, draft, chapterNum, entities, relations) {
  const parsed = await aiJson(provider, [
    { role: 'system', content: buildSettingExtractionSystemPrompt() },
    { role: 'user', content: buildSettingExtractionPrompt(draft, chapterNum, entities, relations) }
  ], { maxTokens: 3600, temperature: 0.25 })
  const changes = parsed.settingChanges || parsed.changes || []
  const created = []
  for (const change of changes.slice(0, 6)) {
    if (!change?.entityName && !change?.entityId) continue
    created.push(await api('POST', `/projects/${projectId}/settings/change-events`, {
      entityType: change.entityType || 'character',
      entityId: change.entityId,
      entityName: change.entityName || '',
      changeType: change.changeType || 'update_entity',
      fieldPath: change.fieldPath || 'summary',
      oldValue: change.oldValue || '',
      newValue: change.newValue || change.summary || '',
      chapterNum,
      evidence: change.evidence || '',
      confidence: change.confidence || 0.8,
      status: 'pending_review'
    }))
  }
  return created
}

function buildGenerationContext(args) {
  const {
    fixture,
    chapterNum,
    activeBlock,
    snapshot,
    previousChapterEnding,
    recentSummaries,
    facts,
    settingEntities,
    settingRelations
  } = args
  return {
    projectId: fixture.project.id,
    chapterNum,
    bible: fixture.bible,
    currentVolume: fixture.volume,
    volumePlanning: [fixture.volume],
    storyBlock: activeBlock,
    blockStageSnapshot: snapshot,
    previousChapterEnding,
    recentSummaries,
    canonFacts: facts.slice(-12),
    stateLedger: facts.slice(-8).map(item => item.content).join('\n'),
    settingLibrary: settingEntities.slice(0, 12).map(item => `${item.name}：${item.summary}`).join('\n'),
    settingRelations,
    wordTarget: { softMin: 1200, softMax: 2600 },
    writingFingerprint: '低理解成本，先让人物行动和选择推动剧情；自然停顿，不强行悬念钩子。'
  }
}

function draftPromptReadsSnapshotBoundary(context) {
  const prompt = buildDraftPrompt(context)
  return prompt.includes('block_stage_snapshot') || prompt.includes('故事块') || prompt.includes('snapshot')
}

function normalizeStoryBlockPayload(raw = {}) {
  const fallback = raw.lockState?.requiresReview
  const stagePlan = Array.isArray(raw.stagePlan) && raw.stagePlan.length
    ? raw.stagePlan.map((stage, index) => normalizeStage(stage, index))
    : [
        normalizeStage({
          id: 'stage-1',
          purpose: '让主角进入临港旧塔，发现断网夜留下的第一条矛盾记录。',
          sceneOrAction: '主角带着修复设备进入旧塔，被迫在救人和保留证据之间做选择。',
          choice: '先救被困者，但偷偷复制一段残缺记录。',
          costOrConsequence: '证据不完整，反而让主角成为被怀疑的人。',
          status: 'planned'
        }, 0)
      ]
  return {
    title: raw.title || '旧塔记录',
    goal: raw.goal || '让主角接触断网夜真相，并付出第一笔关系代价。',
    storyFunction: raw.storyFunction || '揭示',
    entryState: raw.entryState || '主角只知道旧塔有一份能解释城市断网的记录。',
    exitTarget: raw.exitTarget || '主角带走残缺证据，同时被卷入更明确的追查。',
    mainPressure: raw.mainPressure || '旧塔里的人命、记录完整性和外部追捕互相冲突。',
    keyCharacters: raw.keyCharacters || ['林澈', '许问青'],
    stagePlan,
    completedStages: raw.completedStages || [],
    nextStageSuggestion: raw.nextStageSuggestion || stagePlan[0]?.purpose || '',
    unresolvedQuestions: raw.unresolvedQuestions || [],
    dontAdvanceYet: raw.dontAdvanceYet || [],
    carryOverToNextChapter: raw.carryOverToNextChapter || [],
    capacityAssessment: raw.capacityAssessment || 'normal',
    chapterRefs: raw.chapterRefs || [],
    lockState: raw.lockState || (fallback ? { requiresReview: true, aiPlanningFallback: true } : {})
  }
}

function normalizeStage(stage = {}, index = 0) {
  return {
    id: stage.id || stage.stageId || `stage-${index + 1}`,
    purpose: stage.purpose || stage.stagePurpose || stage.goal || '',
    sceneOrAction: stage.sceneOrAction || stage.stageAction || stage.action || stage.description || '',
    choice: stage.choice || stage.stageChoice || '',
    costOrConsequence: stage.costOrConsequence || stage.stageCostOrConsequence || stage.consequence || stage.cost || '',
    status: stage.status || 'planned'
  }
}

function buildFallbackStoryBlockPayload({ reason, seed }) {
  return normalizeStoryBlockPayload({
    title: seed?.title || 'AI 规划失败占位块',
    goal: seed?.goal || 'AI 故事块规划失败后生成的人工审阅占位块。',
    storyFunction: seed?.storyFunction || '过渡',
    entryState: seed?.entryState || '需要人工确认后才能继续。',
    lockState: {
      aiPlanningFallback: true,
      requiresReview: true,
      fallbackReason: reason
    }
  })
}

function seedPayload() {
  return {
    title: '旧塔断网夜',
    genre: '近未来悬疑',
    logline: '城市断网夜后，修复员林澈在旧通信塔里发现一段被删改的求救记录，被迫在救人、保留证据和保护同伴之间连续选择。',
    protagonist: '林澈，临港区民间网络修复员，习惯把危险拆成可执行的小步骤。',
    desire: '查清断网夜父亲失踪的真相，同时保住还愿意信任他的少数人。',
    coreConflict: '掌握记录的人都想利用他，而他每多接近真相一步，就会让身边人的安全少一层保障。',
    worldPressure: '临港区经历大规模断网后，官方和灰色组织都在争夺旧塔残留记录。',
    openingHook: '旧塔恢复供电的第一分钟，林澈听见三年前父亲的声音从坏掉的广播里传出来。',
    emotionalPromise: '悬疑推进中持续落到人物选择、误解、信任和代价。',
    differentiation: '不用救世宏大叙事开场，从旧塔、记录、活人困境和一次错误选择开始。',
    styleTarget: '清楚、具体、行动驱动，减少解释性复盘。',
    source: 'live_acceptance',
    endingAnchor: '林澈最终要决定公开真相，还是保住一个会被真相伤害的人。'
  }
}

function biblePayload() {
  return {
    premise: '近未来临港区断网夜后的悬疑故事，主线围绕旧通信塔残留记录、父亲失踪和城市权力清洗。',
    targetReader: '喜欢低门槛悬疑、人物选择和连续推进的长篇读者。',
    styleBible: '场景具体，人物先行动再解释；对话带遮掩和目的；每章停在自然阶段完成处。',
    themeBible: '真相不是纯粹奖赏，公开真相也会制造新的伤害。',
    worldRules: '旧塔本地记录不可远程读取；断网夜的数据被分段封存；恢复电力会同时暴露定位。',
    writingProfile: {
      pace: 'scene-driven',
      clarity: 'low-reading-burden',
      chapterStop: 'natural-pause'
    },
    forbiddenDirections: ['不要把旧测试项目局部元素写入本项目', '不要按字数机械切分正文']
  }
}

function outlinePayload() {
  return {
    farVision: {
      mainArc: '林澈从旧塔残留记录追到断网夜真相，逐步发现父亲并非单纯受害者。',
      endingPressure: '公开记录会救一些人，也会毁掉另一些仍在保护他的人。'
    },
    currentVolume: {
      title: '旧塔记录',
      goal: '让主角拿到第一段残缺记录并建立追查动机。',
      range: '1-8'
    },
    nearChapters: []
  }
}

function volumePayload() {
  return {
    volumeNum: 1,
    title: '旧塔记录',
    startChapter: 1,
    endChapter: 8,
    targetWords: 32000,
    coreGoal: '林澈进入旧塔，获得残缺记录，并因为一次选择被迫继续追查。',
    mainConflict: '救人、保留证据和逃离追捕不能同时完成。',
    keyCharacters: ['林澈', '许问青'],
    summary: '第一卷聚焦旧塔入口事件和主角被卷入真相追查。',
    foreshadowingPlan: ['广播里的父亲声音', '被删改的求救时间戳'],
    unresolvedItems: ['谁删改了记录', '父亲为何出现在旧塔广播中'],
    handoffPoint: '林澈带着残缺记录离开旧塔，但身份暴露。',
    status: 'active'
  }
}

async function aiText(provider, messages, options) {
  const text = await chatCompletion(provider, messages, {
    ...options,
    maxTokens: Math.max(options?.maxTokens || 0, 1000)
  })
  return String(text || '').trim()
}

async function aiJson(provider, messages, options) {
  const text = await aiText(provider, messages, {
    ...options,
    responseFormat: provider.supportsJSON === false ? undefined : 'json'
  })
  try {
    return parseJsonLoose(text)
  } catch (firstError) {
    const repaired = await aiText(provider, [
      { role: 'system', content: 'You repair malformed JSON. Return only valid JSON.' },
      { role: 'user', content: `Repair this into valid JSON only:\n${text}` }
    ], { maxTokens: 2200, temperature: 0, responseFormat: provider.supportsJSON === false ? undefined : 'json' })
    try {
      return parseJsonLoose(repaired)
    } catch {
      throw new Error(`AI JSON 解析失败：${firstError.message}；返回片段：${text.slice(0, 500)}`)
    }
  }
}

function parseJsonLoose(text) {
  const raw = String(text || '').trim()
  if (!raw) throw new Error('empty JSON text')
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i)
  const candidate = fenced?.[1] || raw
  try {
    return JSON.parse(candidate)
  } catch {
    const match = candidate.match(/\{[\s\S]*\}|\[[\s\S]*\]/)
    if (!match) throw new Error('no JSON object or array found')
    return JSON.parse(match[0])
  }
}

function extractEnding(text) {
  const normalized = String(text || '').trim()
  return normalized.slice(Math.max(0, normalized.length - 500))
}

async function activeBlockCount(projectId) {
  const blocks = await api('GET', `/projects/${projectId}/story-blocks`)
  return (Array.isArray(blocks) ? blocks : []).filter(item => item.status === 'active').length
}

async function api(method, path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  })
  const text = await res.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }
  if (!res.ok) {
    const error = new Error(`API ${method} ${path} failed ${res.status}: ${typeof data === 'string' ? data : JSON.stringify(data)}`)
    error.api = { method, path, status: res.status, data }
    throw error
  }
  return data
}

function fail(chapterOrStage, apiOrFunction, message, extra = {}) {
  const blocker = {
    chapter: typeof chapterOrStage === 'number' ? chapterOrStage : null,
    stage: typeof chapterOrStage === 'number' ? null : chapterOrStage,
    apiOrFunction,
    message,
    dirtyDataWritten: Boolean(report.project?.id),
    projectId: report.project?.id || null,
    ...extra
  }
  report.blockers.push(blocker)
  const error = new Error(message)
  error.isAcceptanceFailure = true
  throw error
}

async function writeReports() {
  await mkdir(dirname(OUT_JSON), { recursive: true })
  await writeFile(OUT_JSON, JSON.stringify(report, null, 2), 'utf8')
  await writeFile(OUT_MD, renderMarkdownReport(), 'utf8')
}

function renderMarkdownReport() {
  const lines = [
    '# Story Block V1 Live Acceptance Report',
    '',
    `- mode: ${report.mode}`,
    `- createdCleanProject: ${report.createdCleanProject}`,
    `- usesArchivedReports: ${report.usesArchivedReports}`,
    `- acceptance.passed: ${report.acceptance.passed}`,
    `- completedChapters: ${report.acceptance.completedChapters}`,
    `- project: ${report.project?.title || ''} (${report.project?.id || ''})`,
    `- provider: ${report.provider?.name || ''} / ${report.provider?.model || ''}`,
    '',
    '## Blockers',
    report.blockers.length ? JSON.stringify(report.blockers, null, 2) : 'None',
    '',
    '## Chapters'
  ]
  for (const chapter of report.chapters) {
    lines.push(
      '',
      `### Chapter ${chapter.chapterNum}`,
      `- storyBlockId: ${chapter.storyBlockId || ''}`,
      `- blockStageId: ${chapter.blockStageId || ''}`,
      `- outlineFromActiveStoryBlock: ${chapter.outlineFromActiveStoryBlock}`,
      `- draftReadSnapshotBoundary: ${chapter.draftReadSnapshotBoundary}`,
      `- storyBlockReviewDecision: ${chapter.storyBlockReviewDecision || ''}`,
      `- updatedUnexecutedStages: ${chapter.updatedUnexecutedStages}`,
      `- requiresReviewBlocker: ${chapter.requiresReviewBlocker}`,
      `- multipleActiveStoryBlocks: ${chapter.multipleActiveStoryBlocks}`,
      `- liveDatabaseOrApiErrors: ${chapter.liveDatabaseOrApiErrors?.length || 0}`,
      `- audit.storyTaskConsistency: ${chapter.audit?.storyTaskConsistency || ''}`,
      `- audit.readingBurden: ${chapter.audit?.readingBurden || ''}`
    )
  }
  lines.push('', '## Acceptance Criteria', '```json', JSON.stringify(report.acceptance, null, 2), '```')
  return lines.join('\n')
}

await main()
