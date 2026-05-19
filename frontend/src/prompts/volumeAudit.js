export function buildVolumeAuditSystemPrompt() {
  return `你是一位长篇小说的分卷总编，负责对某一卷进行阶段审稿。

工作原则：
- 你审的是“这一卷是否成立”，不是只挑单句毛病。
- 优先发现主线推进、人物弧光、设定一致性、伏笔状态和节奏结构的问题。
- 区分真正影响后续写作的硬问题，和可以酌情优化的软建议。
- 输出必须是合法 JSON，不要附加解释。`
}

export function buildVolumeAuditPrompt(context) {
  return `请基于以下项目资料，对当前分卷进行阶段审稿。

## 项目基础
- 项目：${context.projectTitle}
- 题材：${context.projectGenre || '未填写'}
- 当前分卷：${context.volumeTitle}
- 章节范围：第 ${context.startChapter} - ${context.endChapter} 章
- 分卷目标字数：${context.targetWords || 0}

## 创作圣经摘要
${context.bibleSummary || '暂无'}

## 当前分卷目标
${context.volumeGoal || '暂无'}

## 当前分卷核心冲突
${context.volumeConflict || '暂无'}

## 本卷关键人物
${context.keyCharacters?.length ? context.keyCharacters.map(name => `- ${name}`).join('\n') : '暂无'}

## 章节进展
${context.chapterSummaries || '暂无章节摘要'}

## 本卷正文节选
${context.chapterExcerpts || '暂无可用正文节选'}

## 已确认事实（本卷范围）
${context.canonFacts || '暂无'}

## 相关设定
${context.settingSummary || '暂无'}

## 相关关系
${context.relationSummary || '暂无'}

## 相关伏笔
${context.plotSummary || '暂无'}

请输出 JSON：

\`\`\`json
{
  "overallAssessment": "对这一卷当前质量和完成度的总评，120字以内",
  "stageSummary": "这一卷目前已经完成了什么，还缺什么",
  "strengths": ["优点1", "优点2"],
  "issues": [
    {
      "severity": "critical|major|minor|suggestion",
      "type": "plot|character|setting|foreshadowing|pacing|emotion|structure",
      "chapterRefs": [1, 2],
      "description": "问题描述",
      "impact": "对后续创作有什么影响",
      "suggestion": "建议如何处理"
    }
  ],
  "characterArcReview": "人物弧光是否在推进，是否有人掉线或偏轨",
  "settingConsistency": "设定与规则是否稳定，有无潜在错乱",
  "foreshadowingReview": "伏笔埋设/推进/回收状态如何",
  "pacingReview": "这一卷节奏是否失衡，高潮点是否够清楚",
  "nextActionPlan": ["下一步建议1", "下一步建议2", "下一步建议3"],
  "suitableToContinue": true
}
\`\`\``
}
