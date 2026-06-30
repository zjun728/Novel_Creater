import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

function ensureParentDir(filePath) {
  const dir = path.dirname(filePath)
  if (dir && dir !== '.') mkdirSync(dir, { recursive: true })
}

function defaultFormatCompletedStageIds(stages = []) {
  if (!Array.isArray(stages) || !stages.length) return '无'
  return stages
    .map(stage => {
      if (stage && typeof stage === 'object') return stage.id || stage.stageId || ''
      return stage || ''
    })
    .filter(Boolean)
    .join(',') || '无'
}

function listOrEmpty(value) {
  return Array.isArray(value) ? value : []
}

function jsonBlock(value) {
  return '```json\n' + JSON.stringify(value, null, 2) + '\n```'
}

export function buildLiveReportMarkdown({
  report,
  phaseTarget,
  formatCompletedStageIds = defaultFormatCompletedStageIds
} = {}) {
  if (!report || typeof report !== 'object') throw new Error('writeLiveReport requires a report object')

  const aiProxy = report.aiProxy || {}
  const modelBinding = report.modelBinding || {}
  const planningHierarchy = report.planningHierarchy || {}
  const settingInitialization = report.settingInitialization || {}
  const volumePlanning = report.volumePlanning || {}
  const storyBlockGranularity = report.storyBlockGranularity || {}
  const acceptance = report.acceptance || {}
  const project = report.project || {}
  const serviceCleanupDiagnostics = report.serviceCleanupDiagnostics || {}
  const storyBlockSummaries = listOrEmpty(report.storyBlockSummaries)
  const qualityWarnings = listOrEmpty(report.qualityWarnings)
  const qualityBacklog = listOrEmpty(report.qualityBacklog)
  const beatPlanQualityRebuilds = listOrEmpty(report.beatPlanQualityRebuilds)
  const chapterReports = listOrEmpty(report.chapterReports)

  const lines = [
    '# 240 万字长篇真实浏览器第一阶段报告',
    '',
    `- mode: ${report.mode}`,
    `- createdCleanProject: ${report.createdCleanProject}`,
    `- usesArchivedReports: ${report.usesArchivedReports}`,
    `- 项目: ${project.name} (${project.id || '未创建'})`,
    `- 完成章节: ${acceptance.completedChapters}/${phaseTarget}`,
    `- 通过: ${acceptance.passed}`,
    `- 原因: ${acceptance.reason || '进行中'}`,
    `- serviceCleanupDiagnostics: killed=${serviceCleanupDiagnostics.killedPids?.length || 0}, skipped=${serviceCleanupDiagnostics.skippedStalePids?.length || 0}, pending=${serviceCleanupDiagnostics.pending === true}`,
    '',
    '## AI 代理',
    `- aiProxyUsed: ${aiProxy.aiProxyUsed}`,
    `- providerId: ${aiProxy.providerId || '未记录'}`,
    `- providerName: ${aiProxy.providerName || '未记录'}`,
    `- modelName: ${aiProxy.modelName || '未记录'}`,
    `- browserConsoleCorsErrors: ${aiProxy.browserConsoleCorsErrors}`,
    `- backendAiRequests: ${aiProxy.backendAiRequests}`,
    `- browserProviderChatCompletions: ${listOrEmpty(aiProxy.providerChatCompletionUrls).length}`,
    '```json',
    JSON.stringify(listOrEmpty(aiProxy.realRequestStages).slice(-30), null, 2),
    '```',
    '',
    '## 模型继承',
    `- hasBinding: ${modelBinding.status?.hasBinding ?? false}`,
    `- inherited: ${modelBinding.status?.inherited ?? false}`,
    `- inheritedFrom: ${modelBinding.status?.inheritedFromProjectTitle || '无'}`,
    `- 设置页显示继承来源: ${modelBinding.settingsPageShowsInheritance}`,
    `- expectedProviderName: ${modelBinding.expectedProviderName}`,
    `- expectedModelName: ${modelBinding.expectedModelName}`,
    `- expectedProviderId: ${modelBinding.expectedProviderId || '未指定'}`,
    `- 期望模型匹配: ${modelBinding.inheritedProviderMatched}`,
    `- actualProviderModelMatched: ${modelBinding.actualProviderModelMatched}`,
    `- deepseek-v4-pro 兜底: ${modelBinding.usedDeepseekV4ProFallback}`,
    '```json',
    JSON.stringify(listOrEmpty(modelBinding.taskProviders), null, 2),
    '```',
    '',
    '## 规划层级',
    `- 章节管理页检查: ${planningHierarchy.projectChaptersPageChecked}`,
    `- 旧主链路文案残留: ${listOrEmpty(planningHierarchy.legacyTextFound).join(', ') || '无'}`,
    '',
    '## 步骤',
    ...listOrEmpty(report.stepsCompleted).map(step => `- ${step}`),
    '',
    '## 设定初始化',
    `- 分组进度可见: ${settingInitialization.groupedProgressVisible}`,
    `- 待确认候选: ${settingInitialization.pendingCandidatesCreated}`,
    `- 已确认候选: ${settingInitialization.acceptedCandidates}`,
    `- 失败分组: ${listOrEmpty(settingInitialization.failedGroups).join(', ') || '无'}`,
    '',
    '## 分卷规划',
    `- 已生成: ${volumePlanning.generated}`,
    `- 占位文本风险: ${listOrEmpty(volumePlanning.placeholderWarnings).length}`,
    volumePlanning.diagnostics
      ? jsonBlock(volumePlanning.diagnostics)
      : '- 诊断: 无',
    '',
    '## 章节',
    ...chapterReports.map(ch => `- 第 ${ch.chapterNum} 章《${ch.title || '未命名'}》 ${ch.wordCount || 0} 字，wordPolicy=${ch.wordCountPolicyStatus || '未记录'}，titleValid=${ch.titleQuality?.titleValid ?? '未记录'}，titleReason=${ch.titleQuality?.titleInvalidReason || '无'}，block=${ch.storyBlockId || '缺失'} stage=${ch.blockStageId || '缺失'}，stagePurpose=${ch.blockStageSnapshot?.stagePurpose || '未记录'}，上一章回看=${ch.previousStoryBlockReviewDecision || '无'}，上一章stageContinues=${ch.previousStoryBlockStageContinues ?? '无'}，review=${ch.storyBlockReviewDecision || '未记录'}，postFinalizeWaitPassed=${ch.postFinalizeWaitPassed ?? false}，postFinalizeFailed=${ch.postFinalizeFailed ?? false}，markerClearedAt=${ch.finalizationMarkerClearedAt || '未记录'}，stageContinues=${ch.storyBlockStageContinues} ${ch.storyBlockStageContinueReason || ''}，stageDepth=${ch.stageContinuationDepth ?? 0}，settlement=${ch.settlementDecision || '无'}，completedStages=${formatCompletedStageIds(ch.currentBlockCompletedStages)}`),
    '',
    '## 故事块摘要',
    `- blocksCreated: ${storyBlockGranularity.blocksCreated}`,
    `- averageChaptersPerBlock: ${storyBlockGranularity.averageChaptersPerBlock}`,
    `- singleChapterBlockCount: ${storyBlockGranularity.singleChapterBlockCount}`,
    `- consecutiveSingleChapterBlocks: ${storyBlockGranularity.consecutiveSingleChapterBlocks}`,
    `- storyBlockGranularityWarning: ${storyBlockGranularity.storyBlockGranularityWarning || '无'}`,
    `- storyBlockGranularityQualityHold: ${storyBlockGranularity.storyBlockGranularityQualityHold || '无'}`,
    `- storyBlockStalledWarning: ${storyBlockGranularity.storyBlockStalledWarning || '无'}`,
    `- activeBlockRemainingStages: ${listOrEmpty(storyBlockGranularity.activeBlockRemainingStages).length}`,
    ...(storyBlockSummaries.length
      ? storyBlockSummaries.map(block => `- ${block.id} ${block.status} 覆盖章节=${block.coveredChapterCount} executed=${block.executedStageCount} completed=${block.completedStageCount}/${block.stageCount} closedUnexecuted=${block.closedUnexecutedStageCount} invalidated=${block.invalidatedStageCount} 剩余阶段=${block.remainingStageCount} blockCloseReasonType=${block.blockCloseReasonType || '无'} earlyCloseAllowed=${block.earlyCloseAllowed ?? '无'} 单章完成=${block.singleChapterCompletedWholeBlock} completionEvidence=${block.completionEvidence || '无'} singleChapterBlockReason=${block.singleChapterBlockReason || '无'}`)
      : ['无']),
    '```json',
    JSON.stringify(storyBlockGranularity, null, 2),
    '```',
    '',
    '## 质量观察',
    ...(qualityWarnings.length
      ? qualityWarnings.map(item => `- ${item.code}: ${item.message}`)
      : ['无']),
    '',
    '## 质量 Backlog',
    ...(qualityBacklog.length
      ? qualityBacklog.map(item => `- ${item.code}: ${item.message}`)
      : ['无']),
    '',
    '## 小纲质量重建',
    ...(beatPlanQualityRebuilds.length
      ? beatPlanQualityRebuilds.map(item => `- 第 ${item.chapterNum} 章第 ${item.retry} 次：${item.message}`)
      : ['无']),
    '',
    '## 阻断',
    report.blocker ? jsonBlock(report.blocker) : '无'
  ]

  return lines.join('\n')
}

export function writeLiveReport({
  report,
  jsonPath,
  mdPath,
  phaseTarget,
  formatCompletedStageIds = defaultFormatCompletedStageIds
} = {}) {
  if (!jsonPath || !mdPath) throw new Error('writeLiveReport requires jsonPath and mdPath')
  ensureParentDir(jsonPath)
  ensureParentDir(mdPath)
  writeFileSync(jsonPath, JSON.stringify(report, null, 2), 'utf8')
  writeFileSync(mdPath, buildLiveReportMarkdown({ report, phaseTarget, formatCompletedStageIds }), 'utf8')
  return { jsonPath, mdPath }
}
