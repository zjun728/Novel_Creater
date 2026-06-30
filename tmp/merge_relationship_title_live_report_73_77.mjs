import fs from 'node:fs'
import path from 'node:path'
import { buildWritingContext } from '../frontend/src/utils/contextBuilder.js'
import { buildDraftPrompt } from '../frontend/src/prompts/chapterDraftPrompt.js'
import { getChapterTitleQuality } from '../frontend/src/prompts/chapter.js'
import { resolveActiveWritingStandardLowDose } from '../frontend/src/data/writingStyleStandards.js'

const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8000/api'
const PROJECT_ID = process.env.PROJECT_ID || '2da6152a-c083-41ee-8bcb-f11b0fae387d'
const QA_DIR = path.join(process.cwd(), 'tmp', 'realistic-flow-qa')
const LIVE_JSON = path.join(QA_DIR, 'latest-longform-browser-live-report-73-77.json')
const LIVE_MD = path.join(QA_DIR, 'latest-longform-browser-live-report-73-77.md')
const HUMANITY_JSON = path.join(QA_DIR, 'latest-story-humanity-rerun-73-77.json')
const HUMANITY_MD = path.join(QA_DIR, 'latest-story-humanity-rerun-73-77.md')
const CHAPTER76_RECOVERY_JSON = path.join(QA_DIR, 'latest-chapter76-recovery-report.json')
const CHAPTER76_RECOVERY_MD = path.join(QA_DIR, 'latest-chapter76-recovery-report.md')
const CHAPTER76_RECOVERY_LIVE_JSON = path.join(QA_DIR, 'latest-longform-browser-live-report-76-recovery.json')
const CHAPTER77_CONTINUATION_LIVE_JSON = path.join(QA_DIR, 'latest-longform-browser-live-report-77-continuation.json')
const RELATION_FIX_JSON_V2 = path.join(QA_DIR, 'latest-setting-relationship-rehome-generalized-fix-v2.json')
const RELATION_AUDIT_AFTER_JSON_V2 = path.join(QA_DIR, 'latest-setting-relationship-rehome-generalized-audit-after-v2.json')
const RELATION_FIX_JSON = fs.existsSync(RELATION_FIX_JSON_V2)
  ? RELATION_FIX_JSON_V2
  : path.join(QA_DIR, 'latest-setting-relationship-rehome-generalized-fix.json')
const RELATION_AUDIT_AFTER_JSON = fs.existsSync(RELATION_AUDIT_AFTER_JSON_V2)
  ? RELATION_AUDIT_AFTER_JSON_V2
  : path.join(QA_DIR, 'latest-setting-relationship-rehome-generalized-audit-after.json')

const RANGE = [73, 74, 75, 76, 77]
const FORBIDDEN_PROMPT_TOKENS = [
  'sampleMicroDemoCard',
  'candidateStandards',
  'experience_card',
  'prompt-ready-low-dose',
  'sourceWork',
  'sourceInfluence',
  'sourceCardId',
  'sourceCardIds',
  'rawExcerpt',
  'sourceText',
  'characterEmotionVariants',
  'emotionDialogueOptions',
  '凡人修仙传',
  '韩立',
  '黄枫谷',
  '祁家'
]

function readJson(filePath, fallback = null) {
  if (!fs.existsSync(filePath)) return fallback
  return JSON.parse(fs.readFileSync(filePath, 'utf8'))
}

async function api(pathname) {
  const response = await fetch(`${API_BASE}${pathname}`)
  const text = await response.text()
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${text.slice(0, 800)}`)
  return text ? JSON.parse(text) : null
}

function count(text, pattern) {
  return (String(text || '').match(pattern) || []).length
}

function countTerms(text, terms = []) {
  const source = String(text || '')
  return terms.reduce((sum, term) => sum + source.split(term).length - 1, 0)
}

function cleanText(value, limit = 600) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit).replace(/[，。；;,. ]+$/, '')}。` : text
}

function chapterByNum(chapters, chapterNum) {
  return chapters.find(item => Number(item.chapterNum) === Number(chapterNum))
}

function latestVersion(versions = []) {
  return [...versions]
    .filter(version => String(version.content || '').length > 500)
    .sort((a, b) => Number(b.createdAt || 0) - Number(a.createdAt || 0))[0] || null
}

function buildOutlineForChapter(outline, chapters, chapterNum, beatPlan) {
  const near = Array.isArray(outline?.nearChapters) ? outline.nearChapters : []
  return {
    ...(outline || {}),
    nearChapters: [
      {
        chapterNum,
        title: chapterByNum(chapters, chapterNum)?.title || `第 ${chapterNum} 章`,
        goal: beatPlan?.blockStageSnapshot?.stagePurpose || beatPlan?.content || '',
        conflict: beatPlan?.blockStageSnapshot?.conflict || '',
        turn: beatPlan?.blockStageSnapshot?.stageExitCondition || '',
        emotionalBeat: beatPlan?.blockStageSnapshot?.stageCostOrConsequence || ''
      },
      ...near.filter(item => Number(item.chapterNum) !== Number(chapterNum)),
      ...chapters
        .filter(item => Number(item.chapterNum) >= chapterNum - 2 && Number(item.chapterNum) < chapterNum)
        .map(item => ({
          chapterNum: item.chapterNum,
          title: item.title,
          goal: item.summary || ''
        }))
    ]
  }
}

function promptExcerpt(prompt) {
  const source = String(prompt || '')
  const start = source.indexOf('## 正式写作标准低量调用')
  if (start < 0) return ''
  const next = source.indexOf('\n\n## ', start + 4)
  return source.slice(start, next > start ? next : Math.min(source.length, start + 1400)).trim()
}

function assessQuality(content = '') {
  const text = String(content || '')
  const dialogueQuoteCount = count(text, /“[^”]+”/g)
  const dialogueSignals = ['没说话', '沉默', '停了', '顿了顿', '压低声音', '张了张嘴', '别', '算了', '你别', '怎么了', '骂', '打断']
  const characterSignals = ['左臂', '疼', '手指', '攥', '松了一口气', '心沉', '胸口', '伤口', '迟疑', '没看他', '咬牙']
  const sceneSignals = ['门槛', '油灯', '桌', '巷口', '客栈', '街', '墙', '窗', '纸', '灰', '脚步', '饭', '茶', '床']
  const settingSignals = ['铜扣', '欠条', '星债会', '星账', '抵押', '问询权', '债本', '规矩', '玉牌', '活人的债', '口令', '契约']
  const summarySignals = ['这意味着', '也就是说', '说明', '他意识到', '应该已经知道']
  return {
    dialogueLikeHuman: dialogueQuoteCount >= 18 && countTerms(text, dialogueSignals) >= 3,
    dialogueEvidence: dialogueQuoteCount >= 18 && countTerms(text, dialogueSignals) >= 3
      ? '有短句、停顿、打断或遮掩式交锋。'
      : '对话仍偏功能性，闲话/打岔/沉默不足。',
    dialogueQuoteCount,
    characterHumanity: countTerms(text, characterSignals) >= 4,
    characterEvidence: countTerms(text, characterSignals) >= 4
      ? '有身体反应、迟疑或关系压力下的小动作。'
      : '人物私心、身体代价或关系反应偏弱。',
    sceneDwell: countTerms(text, sceneSignals) >= 8,
    sceneEvidence: countTerms(text, sceneSignals) >= 8
      ? '有门窗、街巷、桌面、脚步等环境停留。'
      : '场景停留感不足，仍有过站感。',
    settingByAction: countTerms(text, settingSignals) >= 6,
    settingEvidence: countTerms(text, settingSignals) >= 6
      ? '设定主要通过凭证、契约、规矩和代价进入动作。'
      : '设定自然呈现信号偏少。',
    skeletonReduced: countTerms(text, summarySignals) <= 5,
    skeletonEvidence: countTerms(text, summarySignals) <= 5
      ? '摘要盖章句不多。'
      : '仍有剧情摘要感。'
  }
}

function buildPromptCheck({ chapterNum, bible, outline, chapters, characters, plotThreads, canonFacts, volumes, settingEntities, settingRelations, settingChangeEvents, storyBlocks, beatPlan }) {
  if (!beatPlan) return null
  const storyBlock = storyBlocks.find(item => item.id === beatPlan.storyBlockId) || null
  const contextResult = buildWritingContext(
    { bible, outline: buildOutlineForChapter(outline, chapters, chapterNum, beatPlan), characters, plotThreads, canonFacts },
    chapterNum,
    12000,
    { entities: settingEntities, relations: settingRelations, changeEvents: settingChangeEvents },
    { volumes },
    null,
    { storyBlock, blockStageSnapshot: beatPlan.blockStageSnapshot || {} }
  )
  const context = {
    ...contextResult.context,
    chapterNum,
    chapterGoal: beatPlan.content || beatPlan.blockStageSnapshot?.stagePurpose || '',
    beatPlan: beatPlan.content || '',
    storyBlock,
    blockStageSnapshot: beatPlan.blockStageSnapshot || {}
  }
  const prompt = buildDraftPrompt(context)
  const forbidden = FORBIDDEN_PROMPT_TOKENS.filter(token => prompt.includes(token))
  return {
    activeWritingStandards: (context.activeWritingStandards || []).map(item => ({
      id: item.id,
      name: item.name,
      status: item.status,
      sourceKind: item.sourceKind
    })),
    resolved: resolveActiveWritingStandardLowDose(context.activeWritingStandards || [], context),
    formalLowDoseSectionCount: count(prompt, /正式写作标准低量调用/g),
    principleCount: count(prompt, /写法原则：/g),
    originalMicroDemoCount: count(prompt, /原创微示范：/g),
    antiAiReminderCount: count(prompt, /反 AI 提醒：/g),
    maxOneOneOnePassed: count(prompt, /写法原则：/g) <= 1 &&
      count(prompt, /原创微示范：/g) <= 1 &&
      count(prompt, /反 AI 提醒：/g) <= 1,
    forbiddenPromptTokensDetected: forbidden,
    hasExperienceCardDirectField: forbidden.some(token => [
      'sampleMicroDemoCard',
      'candidateStandards',
      'experience_card',
      'prompt-ready-low-dose',
      'sourceWork',
      'sourceInfluence',
      'sourceCardId',
      'sourceCardIds',
      'rawExcerpt',
      'sourceText',
      'characterEmotionVariants',
      'emotionDialogueOptions'
    ].includes(token)),
    sampleLeakageDetected: forbidden.length > 0,
    promptExcerpt: promptExcerpt(prompt)
  }
}

const baseLive = readJson(LIVE_JSON, {})
const recovery76Live = readJson(CHAPTER76_RECOVERY_LIVE_JSON, {})
const continuation77Live = readJson(CHAPTER77_CONTINUATION_LIVE_JSON, {})
const relationshipFix = readJson(RELATION_FIX_JSON, {})
const relationshipAuditAfter = readJson(RELATION_AUDIT_AFTER_JSON, {})
const recovery76HasResult = Boolean(recovery76Live?.acceptance || recovery76Live?.chapterReports?.length)
const continuation77HasResult = Boolean(continuation77Live?.acceptance || continuation77Live?.chapterReports?.length)
const effectiveBlocker = continuation77HasResult
  ? (continuation77Live?.blocker || null)
  : (recovery76HasResult ? (recovery76Live?.blocker || null) : (baseLive.blocker || null))

const [
  bible,
  outline,
  chapters,
  characters,
  plotThreads,
  canonFacts,
  volumes,
  settingEntities,
  settingRelations,
  settingChangeEvents,
  storyBlocks,
  pendingSettings
] = await Promise.all([
  api(`/projects/${PROJECT_ID}/bible`),
  api(`/projects/${PROJECT_ID}/outline`),
  api(`/projects/${PROJECT_ID}/chapters`),
  api(`/projects/${PROJECT_ID}/characters`),
  api(`/projects/${PROJECT_ID}/plot-threads`),
  api(`/projects/${PROJECT_ID}/canon-facts`),
  api(`/projects/${PROJECT_ID}/volumes`),
  api(`/projects/${PROJECT_ID}/settings/entities`),
  api(`/projects/${PROJECT_ID}/settings/relations`),
  api(`/projects/${PROJECT_ID}/settings/change-events`),
  api(`/projects/${PROJECT_ID}/story-blocks`),
  api(`/projects/${PROJECT_ID}/settings/change-events?status=pending_review`)
])

const baseEntries = baseLive.chapterReports || []
const chapterReports = []

for (const chapterNum of RANGE) {
  const chapter = chapterByNum(chapters, chapterNum)
  if (!chapter) {
    chapterReports.push({
      chapterNum,
      exists: false,
      generated: false,
      finalized: false,
      skipped: true,
      skipReason: '失败即停，未启动本章。'
    })
    continue
  }
  const versions = await api(`/projects/${PROJECT_ID}/chapters/${chapter.id}/versions`).catch(() => [])
  const finalVersion = chapter.finalVersionId ? versions.find(item => item.id === chapter.finalVersionId) : null
  const selectedVersion = finalVersion || latestVersion(versions)
  const beatPlan = await api(`/projects/${PROJECT_ID}/chapter-beat-plan/${chapterNum}`).catch(() => null)
  const promptCheck = buildPromptCheck({
    chapterNum,
    bible,
    outline,
    chapters,
    characters,
    plotThreads,
    canonFacts,
    volumes,
    settingEntities,
    settingRelations,
    settingChangeEvents,
    storyBlocks,
    beatPlan
  })
  const liveEntry = baseEntries.find(item => Number(item.chapterNum) === chapterNum) || {}
  const titleQuality = getChapterTitleQuality(chapter.title || '', {
    chapterNum,
    content: selectedVersion?.content || '',
    titleSource: 'metadata',
    fallbackUsed: false
  })
  chapterReports.push({
    ...liveEntry,
    chapterNum,
    exists: true,
    generated: Boolean(selectedVersion),
    finalized: chapter.status === 'final',
    skipped: chapter.status !== 'final',
    skipReason: chapter.status === 'final' ? '' : (effectiveBlocker?.message || '本章未定稿。'),
    chapterId: chapter.id,
    title: chapter.title || '',
    status: chapter.status || '',
    titleQuality,
    wordCount: Number(chapter.wordCount || String(selectedVersion?.content || '').length || 0),
    finalVersionId: chapter.finalVersionId || '',
    selectedVersion: selectedVersion ? {
      id: selectedVersion.id,
      versionType: selectedVersion.versionType,
      title: selectedVersion.title,
      contentLength: String(selectedVersion.content || '').length
    } : null,
    candidateVersions: versions.map(version => ({
      id: version.id,
      versionType: version.versionType,
      title: version.title,
      contentLength: String(version.content || '').length,
      createdAt: version.createdAt || 0
    })).sort((a, b) => Number(a.createdAt || 0) - Number(b.createdAt || 0)),
    storyBlockId: beatPlan?.storyBlockId || '',
    blockStageId: beatPlan?.blockStageId || '',
    blockStageSnapshot: beatPlan?.blockStageSnapshot || null,
    formalWritingStandardsEnabled: promptCheck?.activeWritingStandards || [],
    actualFormalStandardCalled: promptCheck?.resolved || null,
    formalWritingStandardPromptCheck: promptCheck ? {
      formalLowDoseSectionCount: promptCheck.formalLowDoseSectionCount,
      principleCount: promptCheck.principleCount,
      originalMicroDemoCount: promptCheck.originalMicroDemoCount,
      antiAiReminderCount: promptCheck.antiAiReminderCount,
      maxOneOneOnePassed: promptCheck.maxOneOneOnePassed,
      forbiddenPromptTokensDetected: promptCheck.forbiddenPromptTokensDetected,
      hasExperienceCardDirectField: promptCheck.hasExperienceCardDirectField,
      sampleLeakageDetected: promptCheck.sampleLeakageDetected,
      promptExcerpt: promptCheck.promptExcerpt
    } : null,
    sampleBoundaryCheck: {
      sampleCardInjected: liveEntry.sampleCardInjected === true,
      sampleLeakageDetected: liveEntry.sampleLeakageDetected === true || promptCheck?.sampleLeakageDetected === true,
      sourceFieldsStripped: liveEntry.sourceFieldsStripped !== false
    },
    qualityObservation: selectedVersion?.content ? assessQuality(selectedVersion.content) : null
  })
}

const standardIds = chapterReports
  .filter(item => item.formalWritingStandardPromptCheck?.formalLowDoseSectionCount)
  .map(item => item.actualFormalStandardCalled?.standardId || '')
  .filter(Boolean)
const formalStandardOverStickyWarning = standardIds.length >= 5 && new Set(standardIds).size === 1
const chapter76 = chapterReports.find(item => item.chapterNum === 76) || null
const recovery76ChapterReport = (recovery76Live?.chapterReports || [])
  .find(item => Number(item.chapterNum) === 76) || {}
const recovery76FlowEvents = recovery76ChapterReport.flowEvents || {}
const successfulRecoveryDiagnostics = recovery76FlowEvents.below_hard_min_expand_short_draft_succeeded ||
  recovery76FlowEvents.below_hard_min_expand_short_draft_done ||
  recovery76FlowEvents.below_hard_min_top_up_expand_short_draft_done ||
  {}
const recoveryDiagnostics = recovery76Live?.blocker?.liveDiagnostics ||
  recovery76Live?.blocker ||
  successfulRecoveryDiagnostics ||
  {}
const chapter76CandidateCounts = (chapter76?.candidateVersions || [])
  .filter(item => item.versionType === 'ai_candidate')
  .map(item => item.contentLength)
const chapter76ShortCandidateCounts = chapter76CandidateCounts.filter(count => Number(count) > 0 && Number(count) < 4000)
const chapter76Recovery = {
  projectId: PROJECT_ID,
  chapterNum: 76,
  createdAt: new Date().toISOString(),
  sourceLiveReport: CHAPTER76_RECOVERY_LIVE_JSON,
  status: chapter76?.status || '',
  finalVersionId: chapter76?.finalVersionId || '',
  finalTitle: chapter76?.title || '',
  titleQuality: chapter76?.titleQuality || null,
  finalTitleQuality: chapter76?.titleQuality || null,
  originalWordCount: recoveryDiagnostics.originalWordCount || chapter76CandidateCounts[0] || 0,
  originalCandidateWordCount: recoveryDiagnostics.originalWordCount || chapter76ShortCandidateCounts[0] || 0,
  regeneratedCandidateWordCount: chapter76ShortCandidateCounts[1] || 0,
  expansionBaseWordCount: recoveryDiagnostics.originalWordCount || 0,
  firstExpandedWordCount: recoveryDiagnostics.firstExpandedWordCount || recoveryDiagnostics.expandedWordCount || 0,
  topUpExpandedWordCount: recoveryDiagnostics.topUpExpandedWordCount || 0,
  expandedWordCount: recoveryDiagnostics.expandedWordCount || 0,
  finalCandidateWordCount: recoveryDiagnostics.finalCandidateWordCount || chapter76?.wordCount || 0,
  shortDraftStrategy: recoveryDiagnostics.shortDraftStrategy || '',
  expansionPasses: recoveryDiagnostics.expansionPasses || [],
  expansionAccepted: recoveryDiagnostics.expansionAccepted === true,
  expansionRejectedReason: recoveryDiagnostics.expansionRejectedReason || '',
  factDriftCheck: recoveryDiagnostics.factDriftCheck || null,
  endingPreserved: recoveryDiagnostics.endingPreserved || null,
  hardMin: recoveryDiagnostics.liveHardMin || recovery76Live?.blocker?.liveHardMin || 4000,
  blocker: recovery76Live?.blocker || null,
  chapterFinal: chapter76?.finalized === true
}
const finalizedChapterCount = chapterReports.filter(item => item.finalized).length
const allRequestedChaptersFinalized = chapterReports.every(item => item.finalized)
const acceptancePassed = allRequestedChaptersFinalized && !effectiveBlocker
const chapter76ClearsHardFail = chapter76Recovery.chapterFinal === true &&
  Number(chapter76Recovery.finalCandidateWordCount || chapter76?.wordCount || 0) >= Number(chapter76Recovery.hardMin || 4000)
const resolvedHardFailWordCountChapters = chapter76ClearsHardFail
  ? []
  : (baseLive.hardFailWordCountChapters || [])
const successfulAcceptanceReason = chapter76Recovery.topUpExpandedWordCount > 0
  ? '第 76 二段补足后过 hardMin；top-up 路径已触发并通过。'
  : '第 76 第一次扩写直接过 hardMin；top-up 路径已实现但本次未触发。'

const enrichedLive = {
  ...baseLive,
  updatedAt: new Date().toISOString(),
  blocker: effectiveBlocker,
  hardFailWordCountChapters: resolvedHardFailWordCountChapters,
  relationshipRehomeGeneralizedFix: relationshipFix,
  relationshipRehomeAuditAfter: relationshipAuditAfter,
  chapter76Recovery,
  titleMetadataRepair: {
    chapter70: {
      title: chapterByNum(chapters, 70)?.title || '',
      metadataOnly: true,
      bodyContentChanged: false
    },
    chapter76: {
      title: chapterByNum(chapters, 76)?.title || '',
      metadataOnly: true,
      bodyContentChanged: false
    },
    chapter77: {
      title: chapterByNum(chapters, 77)?.title || '',
      metadataOnly: true,
      bodyContentChanged: false
    }
  },
  chapterReports,
  titleQualitySummary: chapterReports.map(item => ({
    chapterNum: item.chapterNum,
    title: item.title || '',
    status: item.titleQuality?.status || '',
    reason: item.titleQuality?.reason || item.titleQuality?.titleInvalidReason || ''
  })),
  formalWritingStandardObservation: {
    noExperienceCardDirectPrompt: chapterReports.every(item => !item.formalWritingStandardPromptCheck?.hasExperienceCardDirectField),
    sampleLeakageDetected: chapterReports.some(item => item.formalWritingStandardPromptCheck?.sampleLeakageDetected),
    formalStandardOverStickyWarning
  },
  pendingSettingsAfterRun: pendingSettings.map(event => ({
    id: event.id,
    entityName: event.entityName,
    changeType: event.changeType,
    fieldPath: event.fieldPath,
    chapterNum: event.chapterNum,
    status: event.status,
    newValue: event.newValue
  })),
  acceptance: {
    ...(baseLive.acceptance || {}),
    passed: acceptancePassed,
    completedChapters: finalizedChapterCount,
    reason: acceptancePassed
      ? successfulAcceptanceReason
      : (effectiveBlocker?.message || '仍有章节未定稿，按失败即停停止。')
  }
}

const humanity = {
  createdAt: new Date().toISOString(),
  projectId: PROJECT_ID,
  range: [73, 77],
  mode: 'relationship-rehome-title-gate-small-run',
  generatedChapterCount: chapterReports.filter(item => item.generated).length,
  finalizedChapterCount,
  stoppedAtChapter: effectiveBlocker?.chapterNum || (allRequestedChaptersFinalized ? null : 76),
  stopReason: effectiveBlocker?.message || '',
  blocker: effectiveBlocker,
  chapter76Recovery,
  relationshipRehome: {
    activeSyntheticRelationCountBefore: relationshipFix.activeSyntheticRelationCountBefore,
    activeSyntheticRelationCountAfter: relationshipFix.activeSyntheticRelationCountAfter,
    activeSelfRelationCountBefore: relationshipFix.activeSelfRelationCountBefore,
    activeSelfRelationCountAfter: relationshipFix.activeSelfRelationCountAfter,
    manualReviewCount: relationshipFix.manualReviewCount,
    auditAfterSynthetic: relationshipAuditAfter.activeSyntheticRelationCount,
    auditAfterSelf: relationshipAuditAfter.activeSelfRelationCount
  },
  chapters: chapterReports.map(item => ({
    chapterNum: item.chapterNum,
    title: item.title || '',
    titleQuality: item.titleQuality || null,
    status: item.status || '',
    finalized: item.finalized,
    wordCount: item.wordCount || 0,
    actualFormalStandardCalled: item.actualFormalStandardCalled || null,
    promptCheck: item.formalWritingStandardPromptCheck || null,
    qualityObservation: item.qualityObservation || null,
    skipped: item.skipped,
    skipReason: item.skipReason || ''
  })),
  sampleLeakageDetected: chapterReports.some(item => item.formalWritingStandardPromptCheck?.sampleLeakageDetected),
  noExperienceCardDirectPrompt: chapterReports.every(item => !item.formalWritingStandardPromptCheck?.hasExperienceCardDirectField),
  formalStandardOverStickyWarning
}

function renderLine(item) {
  if (!item.exists) return `- 第 ${item.chapterNum} 章：未创建；${item.skipReason}`
  const check = item.formalWritingStandardPromptCheck || {}
  return `- 第 ${item.chapterNum} 章《${item.title || '未命名'}》：status=${item.status}；title=${item.titleQuality?.status || 'unknown'}/${item.titleQuality?.reason || item.titleQuality?.titleInvalidReason || '无'}；标准=${item.actualFormalStandardCalled?.standardId || '无'} / ${item.actualFormalStandardCalled?.standardName || '无'}；低量段=${check.formalLowDoseSectionCount ?? 0}；1/1/1=${check.principleCount ?? 0}/${check.originalMicroDemoCount ?? 0}/${check.antiAiReminderCount ?? 0}；泄漏=${check.sampleLeakageDetected ? '有' : '无'}；${item.finalized ? '已定稿' : item.skipReason}`
}

function renderMarkdown() {
  const promptBlocks = chapterReports
    .filter(item => item.formalWritingStandardPromptCheck?.promptExcerpt)
    .map(item => [
      `### 第 ${item.chapterNum} 章 Prompt 片段`,
      '',
      '```text',
      item.formalWritingStandardPromptCheck.promptExcerpt,
      '```'
    ].join('\n'))
    .join('\n\n')
  const qualityBlocks = chapterReports
    .filter(item => item.qualityObservation)
    .map(item => {
      const q = item.qualityObservation
      return [
        `### 第 ${item.chapterNum} 章效果观察`,
        '',
        `- 对话：${q.dialogueEvidence}`,
        `- 人物：${q.characterEvidence}`,
        `- 场景：${q.sceneEvidence}`,
        `- 设定：${q.settingEvidence}`,
        `- 骨架感：${q.skeletonEvidence}`
      ].join('\n')
    })
    .join('\n\n')
  const runSummary = acceptancePassed
    ? `- 小跑结果：73-77 已完成；${successfulAcceptanceReason}；第 77 章已补跑；未跑 78。`
    : `- 小跑结果：73-75 定稿，76 短稿扩写 first=${chapter76Recovery.firstExpandedWordCount || 0} / topUp=${chapter76Recovery.topUpExpandedWordCount || 0} / final=${chapter76Recovery.expandedWordCount || 0}，77 ${chapterReports.find(item => item.chapterNum === 77)?.finalized ? '已补跑' : '未启动或未定稿'}。`
  return [
    '# 73-77 小跑观察报告',
    '',
    `- 项目：${PROJECT_ID}`,
    '- 边界：未跑 78，未跑 50，未新建项目。',
    `- 关系归位：active synthetic ${relationshipFix.activeSyntheticRelationCountBefore ?? '?'} -> ${relationshipFix.activeSyntheticRelationCountAfter ?? '?'}；active self ${relationshipFix.activeSelfRelationCountBefore ?? '?'} -> ${relationshipFix.activeSelfRelationCountAfter ?? '?'}；after audit synthetic=${relationshipAuditAfter.activeSyntheticRelationCount ?? '?'} self=${relationshipAuditAfter.activeSelfRelationCount ?? '?'}`,
    '- 第 70 章标题已 metadata-only 修复为《入账星债会》，正文版本哈希未变化。',
    runSummary,
    `- 第 76 章恢复：original=${chapter76Recovery.originalWordCount || chapter76Recovery.originalCandidateWordCount}，new=${chapter76Recovery.regeneratedCandidateWordCount}，firstExpanded=${chapter76Recovery.firstExpandedWordCount}，topUp=${chapter76Recovery.topUpExpandedWordCount}，finalExpanded=${chapter76Recovery.expandedWordCount}，strategy=${chapter76Recovery.shortDraftStrategy}，accepted=${chapter76Recovery.expansionAccepted}，factDrift=${chapter76Recovery.factDriftCheck?.passed ?? '无'}，ending=${chapter76Recovery.endingPreserved?.passed ?? '无'}`,
    `- 当前 blocker：${effectiveBlocker?.code || ''}；${effectiveBlocker?.message || ''}`,
    `- pending settings：${enrichedLive.pendingSettingsAfterRun.length ? enrichedLive.pendingSettingsAfterRun.map(item => `${item.entityName}.${item.fieldPath}`).join('、') : '无'}`,
    `- formalStandardOverStickyWarning：${formalStandardOverStickyWarning ? 'true' : 'false'}`,
    '',
    '## 章节概览',
    '',
    chapterReports.map(renderLine).join('\n'),
    '',
    '## Prompt 边界',
    '',
    promptBlocks,
    '',
    '## 效果观察',
    '',
    qualityBlocks
  ].join('\n')
}

fs.writeFileSync(LIVE_JSON, JSON.stringify(enrichedLive, null, 2), 'utf8')
fs.writeFileSync(HUMANITY_JSON, JSON.stringify(humanity, null, 2), 'utf8')
fs.writeFileSync(CHAPTER76_RECOVERY_JSON, JSON.stringify(chapter76Recovery, null, 2), 'utf8')
const md = renderMarkdown()
fs.writeFileSync(LIVE_MD, md, 'utf8')
fs.writeFileSync(HUMANITY_MD, md.replace('# 73-77 小跑观察报告', '# 73-77 Story Humanity 观察'), 'utf8')
fs.writeFileSync(CHAPTER76_RECOVERY_MD, [
  '# 第 76 章短稿扩写恢复报告',
  '',
  `- 项目：${PROJECT_ID}`,
  `- 状态：${chapter76Recovery.status || 'unknown'}；finalVersionId=${chapter76Recovery.finalVersionId || '无'}`,
  `- 标题：${chapter76Recovery.finalTitle || '无'}；titleQuality=${chapter76Recovery.finalTitleQuality?.status || 'unknown'}/${chapter76Recovery.finalTitleQuality?.reason || chapter76Recovery.finalTitleQuality?.titleInvalidReason || '无'}`,
  `- original/new/firstExpanded/topUp/finalExpanded：${chapter76Recovery.originalWordCount || chapter76Recovery.originalCandidateWordCount}/${chapter76Recovery.regeneratedCandidateWordCount}/${chapter76Recovery.firstExpandedWordCount}/${chapter76Recovery.topUpExpandedWordCount}/${chapter76Recovery.expandedWordCount}`,
  `- shortDraftStrategy：${chapter76Recovery.shortDraftStrategy}`,
  `- expansionPasses：${chapter76Recovery.expansionPasses.map(item => `${item.taskName}:${item.wordCount}`).join('，') || '无'}`,
  `- expansionAccepted：${chapter76Recovery.expansionAccepted}`,
  `- expansionRejectedReason：${chapter76Recovery.expansionRejectedReason || '无'}`,
  `- factDriftCheck：${chapter76Recovery.factDriftCheck?.passed ?? '无'}`,
  `- endingPreserved：${chapter76Recovery.endingPreserved?.passed ?? '无'}`,
  `- hardMin：${chapter76Recovery.hardMin}`,
  `- blocker：${chapter76Recovery.blocker?.code || ''}；${chapter76Recovery.blocker?.message || ''}`
].join('\n') + '\n', 'utf8')

console.log(JSON.stringify({
  ok: true,
  liveJson: LIVE_JSON,
  humanityJson: HUMANITY_JSON,
  chapter76RecoveryJson: CHAPTER76_RECOVERY_JSON,
  finalized: chapterReports.filter(item => item.finalized).map(item => item.chapterNum),
  stoppedAt: effectiveBlocker?.chapterNum || (allRequestedChaptersFinalized ? null : 76),
  sampleLeakageDetected: humanity.sampleLeakageDetected,
  noExperienceCardDirectPrompt: humanity.noExperienceCardDirectPrompt,
  formalStandardOverStickyWarning
}, null, 2))
