export function buildVolumeSummarySystemPrompt() {
  return `你是一位长篇小说的分卷阶段总结编辑，负责把一卷已经写出的内容压缩成后续创作可复用的结构化记忆。

工作原则：
- 只总结已经发生、已经确认或明显需要接力处理的内容，不擅自改写设定。
- 优先沉淀会影响下一卷写作的事实：人物状态、关系变化、势力变化、地理/世界观变化、伏笔推进、未解决问题。
- 输出要能直接作为下一卷 AI 写作上下文使用，避免空泛评价。
- 必须输出合法 JSON，不要附加解释。`
}

export function buildVolumeSummaryPrompt(context) {
  return `请基于以下项目资料，为当前分卷生成“阶段总结”。

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

## 最近一次分卷审稿报告
${context.auditSummary || '暂无'}

请输出 JSON：
\`\`\`json
{
  "stageSummary": "本卷已经完成的剧情推进、阶段结论和当前落点，300-600字",
  "compactSummary": "可放入分卷卡片的一段简短总结，80-160字",
  "completedBeats": ["已经完成的关键剧情节点"],
  "openQuestions": ["下一卷仍需要回答的问题或悬念"],
  "characterChanges": [
    {
      "name": "人物名",
      "change": "本卷结束时的状态、关系、目标或心理变化",
      "nextUse": "下一卷继续使用时要注意什么"
    }
  ],
  "settingChanges": [
    {
      "name": "设定/地点/势力/体系名",
      "change": "本卷确认或改变了什么",
      "evidence": "来自哪类章节或事件"
    }
  ],
  "foreshadowingState": [
    {
      "title": "伏笔或悬念",
      "state": "planted|developing|ready_to_resolve|resolved",
      "note": "当前状态和后续建议"
    }
  ],
  "handoffToNext": ["下一卷开写时必须继承的接力点"],
  "continuityNotes": ["后续不能写错的硬约束"],
  "nextVolumeSeeds": ["可以自然展开到下一卷的剧情种子"]
}
\`\`\``
}
