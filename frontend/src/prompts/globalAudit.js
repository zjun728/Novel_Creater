export function buildGlobalAuditSystemPrompt() {
  return `你是一位长篇小说总审稿编辑，负责判断一个项目是否能继续稳定写成长篇。

审稿原则：
- 关注项目级结构风险，不做逐句润色。
- 优先检查主线承诺、人物弧光、设定一致性、伏笔容量、节奏结构、读者期待兑现。
- 区分“必须修”的硬问题和“可以优化”的软建议。
- 如果用户指定了章节范围，只审查该范围内的推进质量，同时说明它对全书后续的影响。
- 给出可执行的下一步，不要只写抽象评价。
- 必须输出合法 JSON，不要附加解释。`
}

export function buildGlobalAuditPrompt(context) {
  return `请基于以下资料，对当前小说项目做一次${context.auditScopeLabel || '全局'}审稿。

## 审稿范围
- 范围：${context.auditScopeLabel || '全书'}
- 起始章节：${context.auditStartChapter || '不限'}
- 结束章节：${context.auditEndChapter || '不限'}

## 项目基础
- 项目：${context.projectTitle || '未命名项目'}
- 题材：${context.genre || '未填写'}
- 目标字数：${context.targetWords || 0}
- 目标章节：${context.targetChapters || 0}
- 当前章节：${context.currentChapterNum || 0}
- 简介：${context.description || '暂无'}

## 创作种子
${context.seedSummary || '暂无'}

## 创作圣经
${context.bibleSummary || '暂无'}

## 分卷规划与阶段总结
${context.volumeSummary || '暂无'}

## 章节进展
${context.chapterSummary || '暂无'}

## 设定库摘要
${context.settingSummary || '暂无'}

## 已确认 Canon 事实
${context.factSummary || '暂无'}

## 伏笔状态
${context.threadSummary || '暂无'}

## 最近设定变更
${context.settingChangeSummary || '暂无'}

请输出 JSON：
\`\`\`json
{
  "overallVerdict": "项目当前总体判断，100-200字",
  "healthScore": 0,
  "continueRecommendation": "continue|revise_first|pause_and_replan",
  "mainlineReview": {
    "status": "stable|drifting|unclear",
    "comment": "主线承诺是否清晰、是否还能支撑长篇",
    "actions": ["行动建议"]
  },
  "characterReview": {
    "status": "stable|thin|conflicted",
    "comment": "主角、关键人物弧光和关系是否可持续",
    "actions": ["行动建议"]
  },
  "settingReview": {
    "status": "stable|missing|contradictory",
    "comment": "世界观、规则、势力、地理、能力体系是否稳定",
    "actions": ["行动建议"]
  },
  "foreshadowingReview": {
    "status": "healthy|overloaded|underused",
    "comment": "伏笔数量和状态是否可控",
    "actions": ["行动建议"]
  },
  "pacingReview": {
    "status": "healthy|slow|rushed|uneven",
    "comment": "节奏、章节推进和分卷落点是否合理",
    "actions": ["行动建议"]
  },
  "readerPromiseReview": {
    "status": "clear|weak|misaligned",
    "comment": "读者最期待的爽点、情绪价值和差异化是否兑现",
    "actions": ["行动建议"]
  },
  "criticalIssues": [
    {
      "severity": "critical|major|minor",
      "type": "mainline|character|setting|foreshadowing|pacing|market|continuity",
      "description": "问题描述",
      "impact": "如果不处理会造成什么影响",
      "suggestion": "建议如何修"
    }
  ],
  "nextActions": ["接下来最应该做的 3-8 件事"],
  "safeToWriteNext": true
}
\`\`\``
}

export function buildGlobalAuditRepairPrompt(rawText) {
  return `下面是一段小说项目审稿结果，但可能不是合法 JSON、混入 Markdown，或在输出中出现多余文字。

请只提取并修复为合法 JSON，不要解释，不要 Markdown。字段结构固定如下，缺失字段请用简短中文补齐；criticalIssues 和 nextActions 可以为空数组：
{
  "overallVerdict": "",
  "healthScore": 0,
  "continueRecommendation": "continue",
  "mainlineReview": { "status": "stable", "comment": "", "actions": [] },
  "characterReview": { "status": "stable", "comment": "", "actions": [] },
  "settingReview": { "status": "stable", "comment": "", "actions": [] },
  "foreshadowingReview": { "status": "healthy", "comment": "", "actions": [] },
  "pacingReview": { "status": "healthy", "comment": "", "actions": [] },
  "readerPromiseReview": { "status": "clear", "comment": "", "actions": [] },
  "criticalIssues": [],
  "nextActions": [],
  "safeToWriteNext": true
}

原始内容：
${rawText}`
}

export function buildCompactGlobalAuditPrompt(context, rawText = '') {
  return `请对当前小说项目重新输出一份“精简但完整”的${context.auditScopeLabel || '全局'}审稿 JSON。

规则：
- 只输出合法 JSON，不要 Markdown，不要解释。
- 所有 comment 控制在 80 字以内。
- actions 每项控制在 30 字以内，每组最多 3 项。
- criticalIssues 最多 5 条，nextActions 最多 5 条。
- 如果资料不足，也要输出完整结构，并把 safeToWriteNext 设为合理布尔值。

项目：${context.projectTitle || '未命名项目'}
题材：${context.genre || '未填写'}
目标：${context.targetWords || 0}字 / ${context.targetChapters || 0}章
范围：${context.auditScopeLabel || '全书'}，${context.auditStartChapter || '不限'}-${context.auditEndChapter || '不限'}章

种子摘要：
${context.seedSummary || '暂无'}

圣经摘要：
${context.bibleSummary || '暂无'}

章节进展：
${context.chapterSummary || '暂无'}

设定库摘要：
${context.settingSummary || '暂无'}

Canon 事实：
${context.factSummary || '暂无'}

最近设定变更：
${context.settingChangeSummary || '暂无'}

前一次可见输出：
${rawText || '暂无'}

请严格输出：
{
  "overallVerdict": "",
  "healthScore": 0,
  "continueRecommendation": "continue|revise_first|pause_and_replan",
  "mainlineReview": { "status": "stable|drifting|unclear", "comment": "", "actions": [] },
  "characterReview": { "status": "stable|thin|conflicted", "comment": "", "actions": [] },
  "settingReview": { "status": "stable|missing|contradictory", "comment": "", "actions": [] },
  "foreshadowingReview": { "status": "healthy|overloaded|underused", "comment": "", "actions": [] },
  "pacingReview": { "status": "healthy|slow|rushed|uneven", "comment": "", "actions": [] },
  "readerPromiseReview": { "status": "clear|weak|misaligned", "comment": "", "actions": [] },
  "criticalIssues": [
    { "severity": "critical|major|minor", "type": "mainline|character|setting|foreshadowing|pacing|market|continuity", "description": "", "impact": "", "suggestion": "" }
  ],
  "nextActions": [],
  "safeToWriteNext": true
}`
}
