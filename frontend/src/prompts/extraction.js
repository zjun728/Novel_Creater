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
- 伏笔事实（新埋设的伏笔、已有伏笔的推进或回收）
- 硬状态事实（交易次数、剩余寿命、冷却时间、物品价值、时间流速、伤势、位置、持有物、能力等级、债务金额等）`
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
    "threadTags": ["#主角身世线"],
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
5. 如果某事实与已有事实矛盾，额外标注 conflictWithExisting。
6. 硬状态必须优先提取：交易次数、剩余寿命、冷却时间、隐性/显性消耗、物品价值或售价、时间流速、持有物数量、伤势、境界等级、角色当前位置。
7. 凡正文出现“第几次交易/首次/第二次/第三次”“剩余多少寿命/次数”“下次何时可用/冷却多久”“某物价值/稀有度/售价”“不同世界时间比例”，必须保留精确数字和单位。
8. 如果硬状态已变化，用一句短事实写清“谁/什么从何状态变为何状态”，不要只写情绪或氛围。
9. 为每条事实补充 threadTags，用于长篇线索链检索；可用标签示例：#主线推进、#主角身世线、#女主秘密线、#反派阴谋线、#关键道具线、#功法代价线、#势力斗争线、#感情关系线。threadTags 可与 relatedPlotThreads 内容一致或更粗粒度。`
}

export function buildExtractionRepairPrompt(rawText) {
  return `请把下面内容修复为合法 JSON，只输出 JSON，不要解释，不要 Markdown。

目标格式必须是：
{
  "facts": [
    {
      "factType": "world|character|plot|relationship|timeline|style",
      "content": "80字内事实描述",
      "relatedCharacters": ["角色名"],
      "relatedPlotThreads": ["伏笔标题"],
      "threadTags": ["#主角身世线"],
      "evidence": "80字内原文依据",
      "confidence": 0.8
    }
  ]
}

要求：
1. 最多保留 4 条最重要事实。
2. content 和 evidence 必须短，不要长篇复述。
3. 如果原始内容不完整，只保留能确定的完整事实。
4. 若原始内容包含交易次数、剩余寿命、冷却时间、物品价值、时间流速等硬状态，优先保留这些事实。
5. threadTags 是线索链标签，可从 relatedPlotThreads、人物身世、反派阴谋、关键道具、感情关系等信息中归纳。
6. 如果没有可确定事实，输出 {"facts":[]}。

原始内容：
${String(rawText || '').slice(0, 12000)}`
}

export function buildCompactExtractionPrompt(chapterContent, chapterNum, existingFacts = [], rawText = '') {
  const existingBrief = existingFacts.slice(0, 12).map(f => `- [${f.factType || 'plot'}] ${f.content || ''}`).join('\n')
  return `请重新从第 ${chapterNum} 章提取极简记忆事实。

只输出合法 JSON，不要解释，不要 Markdown：
{
  "facts": [
    {
      "factType": "world|character|plot|relationship|timeline|style",
      "content": "80字内事实描述",
      "relatedCharacters": ["角色名"],
      "relatedPlotThreads": ["伏笔标题"],
      "threadTags": ["#主角身世线"],
      "evidence": "80字内原文依据",
      "confidence": 0.8
    }
  ]
}

硬性要求：
1. 最多 4 条事实；宁可少，不要多，但不得漏掉明确出现的硬状态。
2. 只记录会影响后续章节的事实：角色状态、关系变化、世界规则、关键物品、关键事件结果、交易次数、剩余寿命、冷却时间、物品价值、时间流速。
3. 不要记录普通环境描写、临时动作、无后续影响的细节。
4. content/evidence 都必须短，避免输出过长导致 JSON 截断。
5. threadTags 用于长篇线索链检索，例如 #主角身世线、#反派阴谋线、#关键道具线；没有明确线索时可为空数组。
6. 如果没有必要事实，输出 {"facts":[]}。

${existingBrief ? `已有事实参考，避免重复：\n${existingBrief}\n\n` : ''}${rawText ? `上一次模型返回片段：\n${String(rawText).slice(0, 2000)}\n\n` : ''}第 ${chapterNum} 章正文节选：
${String(chapterContent || '').slice(0, 9000)}`
}
