import {
  buildChapterPrompt,
  buildChapterSystemPrompt,
  formatDraftContinuityText
} from './chapter.js'
import { formatActiveWritingStandardLowDoseForPrompt } from '../data/writingStyleStandards.js'
import { buildGenerationQualityBrief } from '../quality/writingQualityPrompt.js'
import { storyBlockSnapshotBrief } from '../utils/storyBlockSnapshot.js'

export function buildHumanityDraftBrief() {
  return `## 故事性与人物血肉轻量提示
- 用大白话讲清楚故事，别为了高级感绕远。
- 情绪靠动作、选择、停顿、隐瞒、误会露出来。
- 对话不要每问必答，可以打岔、遮掩、嘴硬、说半句。
- 设定先写行动和后果：尝试、出事、付代价、旁人反应，主角再总结一点点。
- 若上文连续由追捕/撤离推动，本章优先让主角通过主动布局、关系对峙、代价后果或规则观察推进剧情；不要只靠追兵逼近和换地点制造推进。
- 每章至少让一个人物关系或主角选择发生小变化。`
}

export function buildDraftSystemPrompt() {
  return `你是一位长篇小说正文生成作者。

职责边界：
- 你负责写小说正文，不输出质量报告、规则清单、小纲或解释。
- 你以已确认设定、状态账本、上一章结尾和本章小纲为边界。
- 你应按写作指纹自然执行，而不是逐条打卡。
- 你应优先执行 Scene Execution Card 和 Narrative Voice Contract；它们只约束当前场戏和表达方式，不能覆盖事实或阶段边界。
- 你要写可见场景：对白交锋、行动选择、情绪转折、表情语气、环境压力和后果。
- 不要把写作标准、质量规则或自检过程写进正文。

${buildGenerationQualityBrief()}`
}

export function buildDraftPrompt(context = {}) {
  const blockSnapshot = storyBlockSnapshotBrief(context.blockStageSnapshot || {})
  const formalStandardLowDosePrompt = formatActiveWritingStandardLowDoseForPrompt(context.activeWritingStandards || [], context)
  const fingerprint = context.writingFingerprint ||
    (context.narrativeVoiceContract
      ? '以 Narrative Voice Contract 的表达约束为准；风格只影响写法，不改变事实和阶段边界。'
      : (formalStandardLowDosePrompt ? context.styleBible : context.styleStandardBrief)) ||
    context.styleBible ||
    '按本书已确认风格执行。'
  const chapterPromptContext = formalStandardLowDosePrompt
    ? {
        ...context,
        styleStandardBrief: '',
        styleMethodBrief: context.styleBible ? `本书风格：${context.styleBible}` : ''
      }
    : context
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
    buildHumanityDraftBrief(),
    formalStandardLowDosePrompt,
    buildChapterPrompt({ ...chapterPromptContext, includeGenerationQualityBrief: false }),
    '请直接输出正文，不要输出标题、审稿报告、解释、小纲或 Markdown 结构。'
  ].filter(Boolean).join('\n\n')
}
