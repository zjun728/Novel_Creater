import {
  buildChapterPrompt,
  buildChapterSystemPrompt
} from './chapter.js'
import { formatAiTraceRulesForGeneration } from '../qualityRules/aiTraceRules.js'

export function buildDraftSystemPrompt() {
  return `你是一位长篇小说正文生成作者。

职责边界：
- 你负责写小说正文，不输出质量报告、规则清单、小纲或解释。
- 你必须遵守已确认设定、状态账本、上一章结尾和本章小纲。
- 你应按写作指纹自然执行，而不是逐条打卡。

${formatAiTraceRulesForGeneration()}`
}

export function buildDraftPrompt(context = {}) {
  const fingerprint = context.writingFingerprint || context.styleStandardBrief || context.styleBible || '按本书已确认风格执行。'
  const continuity = context.continuityConstraints || [
    context.previousChapterEnding ? `上一章结尾：${context.previousChapterEnding}` : '',
    context.stateLedger ? `状态账本：${context.stateLedger}` : '',
    context.settingLibrary ? `设定库摘要：${context.settingLibrary}` : ''
  ].filter(Boolean).join('\n')

  return [
    `## 写作指纹\n${fingerprint}`,
    `## 连续性硬约束\n${continuity || '无额外硬约束，但不得推翻已确认事实。'}`,
    buildChapterPrompt(context),
    '请直接输出正文，不要输出标题、审稿报告、解释、小纲或 Markdown 结构。'
  ].join('\n\n')
}
