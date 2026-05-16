/**
 * 大纲规划 Prompt
 */

export function buildOutlineSystemPrompt() {
  return `你是一位小说结构设计师。你帮助作者规划长篇小说的滚动大纲。

核心原则：
- 远景模糊，近景清晰。
- 不要规划全书 500 章的详细大纲。
- 远景只保留主题、压力和可能结局。
- 中景规划当前卷的冲突和阶段目标。
- 近景只规划未来 3-10 章的具体目标。

你可能提出的不是"正确大纲"，而是"可能路线"。作者有最终决定权。`
}

export function buildOutlinePrompt(context) {
  return `请为以下小说生成三层滚动大纲。

## 创作信息
${context.seedInfo || ''}
${context.bibleInfo || ''}
${context.currentChapterNum ? `当前进度：第 ${context.currentChapterNum} 章` : '尚未开始创作'}

## 已确认的角色
${context.characters?.length ? context.characters.map(c => `- ${c.name}（${c.role}）：${c.personality || ''}`).join('\n') : '无'}

## 已确认的伏笔
${context.plotThreads?.length ? context.plotThreads.filter(t => t.status === 'planted').map(t => `- ${t.title}`).join('\n') : '无'}

请输出 JSON 格式：

\`\`\`json
{
  "farVision": {
    "theme": "作品主题",
    "finalPressure": "最终命运压力",
    "possibleEndings": ["可能结局1", "可能结局2", "可能结局3"],
    "unresolvedBigQuestions": ["大问题1"]
  },
  "currentVolume": {
    "title": "当前卷标题",
    "goal": "本卷目标",
    "mainConflict": "主要矛盾",
    "emotionalArc": "情感弧线",
    "expectedChapterRange": [1, 60]
  },
  "nearChapters": [
    {
      "chapterNum": 1,
      "title": "章节标题",
      "goal": "本章目标",
      "conflict": "核心冲突",
      "turn": "转折点",
      "emotionalBeat": "情感节拍",
      "requiredFacts": ["必须包含的事实"],
      "optionalSurprises": ["可选的意外发展"]
    }
  ]
}
\`\`\`

要求：
- nearChapters 只需规划未来 3-5 章的具体内容。
- 远景保持模糊但有方向感。
- 不要写 500 章的规划。`
}
