/**
 * 章节摘要 Prompt
 */

export function buildSummarySystemPrompt() {
  return `你是一位专业编辑，擅长为长篇小说撰写章节摘要。

你的摘要需要做到：
- 简洁准确地概括本章核心内容。
- 标注重要的情节推进点。
- 标注角色状态变化。
- 标注新出现的人物、设定、伏笔。
- 不要评价好坏，只记录事实。`
}

export function buildSummaryPrompt(chapterContent, chapterNum) {
  return `请为以下章节生成摘要。

## 第 ${chapterNum} 章正文
---
${chapterContent}
---

请输出 JSON 格式：

\`\`\`json
{
  "summary": "章节摘要（150字以内）",
  "keyEvents": ["关键事件1", "关键事件2"],
  "characterChanges": [
    {
      "character": "角色名",
      "change": "发生了什么变化"
    }
  ],
  "newElements": {
    "characters": ["新出场角色"],
    "settings": ["新揭示的设定"],
    "plotThreads": ["新埋设或推进的伏笔"]
  },
  "emotionalTone": "本章情感基调",
  "pacingNote": "节奏说明（快/慢/过渡）"
}
\`\`\``
}

export function buildSummaryRepairPrompt(rawText) {
  return `请把下面内容修复为合法 JSON。

要求：
- 只输出 JSON，不要 Markdown、解释或代码块。
- 不新增剧情，不扩写正文，只修复字段和标点。
- 字段固定为：
{
  "summary": "50字以内章节摘要",
  "keyEvents": ["关键事件"],
  "characterChanges": [{"character": "角色名", "change": "状态变化"}],
  "newElements": {
    "characters": [],
    "settings": [],
    "plotThreads": []
  },
  "emotionalTone": "情感基调",
  "pacingNote": "节奏说明"
}
- 如果原内容不完整，保留能确定的信息，缺失字段用空数组或空字符串。

待修复内容：
---
${rawText}
---`
}
