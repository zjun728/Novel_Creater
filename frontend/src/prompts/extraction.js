/**
 * Canon 事实提取 Prompt
 */

export function buildExtractionSystemPrompt() {
  return `你是一位专业编辑，负责从小说章节中提取需要记录的事实信息。

你的任务是客观提取，不做主观判断。提取的信息将用于后续章节的一致性检查。

输出类型包括：
- 世界观事实（规则、地理、历史、社会结构）
- 角色事实（身份、关系、能力、过去经历）
- 情节事实（已发生的重要事件、时间节点）
- 关系事实（角色之间的关系变化）
- 伏笔事实（新埋设的伏笔、已有伏笔的推进或回收）`
}

export function buildExtractionPrompt(chapterContent, chapterNum, existingFacts) {
  return `请从以下章节中提取需要记录的事实。

## 第 ${chapterNum} 章正文
---
${chapterContent}
---

${existingFacts?.length ? `## 已有事实（供参考，避免重复）\n${existingFacts.map(f => `- [${f.factType}] ${f.content}`).join('\n')}` : ''}

请输出 JSON 数组格式，每个事实包含：

\`\`\`json
[
  {
    "factType": "world|character|plot|relationship|timeline|style",
    "content": "事实描述",
    "relatedCharacters": ["关联角色名"],
    "relatedPlotThreads": ["关联伏笔标题"],
    "evidence": "原文依据（引用关键原文）",
    "confidence": 0.8
  }
]
\`\`\`

要求：
1. 只提取会在后续章节中产生影响的事实。
2. 不要提取临时性信息（如"今天下雨了"除非影响情节）。
3. 对于角色状态变化，标注变化前后对比。
4. confidence 表示你对该事实判断的信心（0-1）。
5. 如果某事实与已有事实矛盾，额外标注 conflictWithExisting。`
}
