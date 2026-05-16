export function buildPacingSystemPrompt() {
  return `你是一位专业的小说编辑和叙事节奏分析师。你的任务是将章节内容分段，分析每段的张力和节奏。`
}

export function buildPacingPrompt(text) {
  return `请分析以下小说章节的叙事节奏，将章节分为 5-10 个段落，评估每个段落的张力值：

---
${text}
---

输出 JSON 格式：

\`\`\`json
{
  "segments": [
    {"label": "段落标签", "tension": 5, "note": "简要说明"}
  ],
  "climaxAt": 0.7,
  "turningPoints": [{"at": 0.3, "label": "转折说明"}],
  "overallRhythm": "紧凑/舒缓/起伏/平稳",
  "avgTension": 5.5,
  "suggestions": ["节奏建议1", "节奏建议2"]
}
\`\`\`

说明：
- tension: 1-10，1=最舒缓，10=最高张力
- climaxAt: 高潮位置比例（0-1），例如 0.7 表示在章节 70% 处
- turningPoints.at: 转折点发生位置比例（0-1）
- overallRhythm: 整体节奏评价
- suggestions: 节奏改进建议（可为空数组）`
}
