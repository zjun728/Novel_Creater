import {
  buildChapterPrompt,
  buildChapterSystemPrompt,
  formatDraftContinuityText
} from './chapter.js'
import { buildGenerationQualityBrief } from '../quality/writingQualityPrompt.js'
import { storyBlockSnapshotBrief } from '../utils/storyBlockSnapshot.js'

export function buildDraftSystemPrompt() {
  return `你是一位长篇小说正文生成作者。

职责边界：
- 你负责写小说正文，不输出质量报告、规则清单、小纲或解释。
- 你以已确认设定、状态账本、上一章结尾和本章小纲为边界。
- 你应按写作指纹自然执行，而不是逐条打卡。

${buildGenerationQualityBrief()}`
}

export function buildDraftPrompt(context = {}) {
  const fingerprint = context.writingFingerprint || context.styleStandardBrief || context.styleBible || '按本书已确认风格执行。'
  const blockSnapshot = storyBlockSnapshotBrief(context.blockStageSnapshot || {})
  const continuity = context.continuityConstraints || [
    context.previousChapterEnding ? `上一章结尾事实：${formatDraftContinuityText(context.previousChapterEnding, 360)}` : '',
    context.stateLedger ? `状态账本：${context.stateLedger}` : '',
    context.settingLibrary ? `设定库摘要：${context.settingLibrary}` : '',
    blockSnapshot ? `故事块阶段快照：\n${blockSnapshot}` : ''
  ].filter(Boolean).join('\n')

  return [
    `## 写作指纹\n${fingerprint}`,
    `## 连续性硬约束\n${continuity || '无额外硬约束，但不得推翻已确认事实。'}`,
    blockSnapshot
      ? `## 故事块执行边界\n本章只执行 block_stage_snapshot 中的当前阶段，不读取后续滚动后的 live stage 来判断历史任务。不要提前写掉后续阶段；如果剧情容量过大，停在自然停顿点，把未写内容顺延到下一章。`
      : '',
    buildChapterPrompt({ ...context, includeGenerationQualityBrief: false }),
    '请直接输出正文，不要输出标题、审稿报告、解释、小纲或 Markdown 结构。'
  ].filter(Boolean).join('\n\n')
}
