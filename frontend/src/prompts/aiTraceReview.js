import { AI_TRACE_ISSUE_TYPES } from '../quality/writingQualityStandard.js'
import { buildChapterAuditQualityRubric } from '../quality/writingQualityPrompt.js'

export const AI_TRACE_REVIEW_DECISIONS = [
  'ignore',
  'local_window_revision',
  'paragraph_polish',
  'outline_replan',
  'full_regenerate'
]

function safeJson(value) {
  return JSON.stringify(value ?? null, null, 2)
}

function filterAiTraceIssues(issues = []) {
  if (!Array.isArray(issues)) return []
  const directTypes = new Set([
    ...AI_TRACE_ISSUE_TYPES,
    'ai_tone',
    'quality',
    'pacing',
    'human_motivation',
    'emotional_logic'
  ])
  return issues.filter(issue => directTypes.has(issue?.type))
}

export function buildAiTraceReviewSystemPrompt() {
  return `你是一位小说质量二审编辑，负责做“AI 痕迹二审 / 人味反证审查”。

你的任务不是从头评估全章，也不要直接改正文。你只判断一审提出的 AI 风格相关问题是否成立，以及应该用什么修订路径处理。

判断原则：
- 单一句式、单个短句、单个意象不能直接判定为 AI 腔；必须结合读者代入、情绪呈现、信息释放、角色功能性和节奏呼吸综合判断。
- 如果问题是当前题材或写作指纹允许的风格，要给出 ignore。
- 如果只是局部表达机械，优先 local_window_revision。
- 如果整段都解释感太重但剧情没错，用 paragraph_polish。
- 如果问题来自小纲设计，例如反派交底、假两难、场景没有摩擦，用 outline_replan。
- 只有整章结构性机械、人物动机和信息释放同时失效时，才建议 full_regenerate。
- 输出只允许合法 JSON，不要 Markdown、解释前缀或正文修订稿。`
}

export function buildAiTraceReviewPrompt({ chapterNum, chapterContent, issues = [], context = {} } = {}) {
  const aiIssues = filterAiTraceIssues(issues)
  return `请对第 ${chapterNum || '?'} 章的一审 AI 风格相关问题做二审。

## 写作指纹
${context.writingFingerprint || context.styleStandardBrief || context.styleBible || '未提供'}

## 本章小纲/场景设计
${context.beatPlan || '未提供'}

## 待二审问题
${safeJson(aiIssues)}

## 章节正文
---
${chapterContent || ''}
---

${buildChapterAuditQualityRubric()}

## 处理决策
只能使用以下 decision：
${AI_TRACE_REVIEW_DECISIONS.map(item => `- ${item}`).join('\n')}

请输出 JSON：
{
  "reviews": [
    {
      "issueIndex": 0,
      "originalIssueIndex": 0,
      "decision": "ignore|local_window_revision|paragraph_polish|outline_replan|full_regenerate",
      "confidence": 0.0,
      "sourceLevel": "sentence|paragraph|scene_plan|chapter_structure",
      "repairScope": "none|phrase|sentence|paragraph|scene|chapter",
      "evidence": "为什么该问题成立或不成立",
      "counterEvidence": "如果应忽略，说明反证；否则说明为什么仍需处理",
      "nextAction": "给用户看的下一步建议"
    }
  ],
  "overallDecision": "ignore|local_window_revision|paragraph_polish|outline_replan|full_regenerate",
  "summary": "100 字以内总结"
}`
}
