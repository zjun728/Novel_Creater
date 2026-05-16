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
