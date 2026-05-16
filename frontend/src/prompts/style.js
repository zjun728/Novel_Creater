/**
 * 风格相关 Prompt
 */

export function buildStyleSystemPrompt() {
  return `你是一位专业文学编辑，擅长分析和指导小说风格。

你可以帮助作者：
- 分析现有文字的风格特征。
- 提出风格统一或多样化建议。
- 将文字改写为特定风格。
- 检查风格偏移。`
}

export function buildStyleAnalysisPrompt(text) {
  return `请分析以下文字的写作风格：

---
${text}
---

输出 JSON 格式：

\`\`\`json
{
  "styleFeatures": {
    "sentenceLength": "短句/中句/长句/混合",
    "rhythm": "快/慢/中等/多变",
    "vocabulary": "口语化/书面化/文学化/混合",
    "tone": "严肃/轻松/黑暗/温暖/客观/主观",
    "dialogueRatio": "对话占比估计",
    "descriptionDensity": "描写密度（低/中/高）",
    "innerMonologueUsage": "内心独白使用（无/少/中/多）"
  },
  "strengths": ["风格优点1", "风格优点2"],
  "weaknesses": ["可改进处1"],
  "comparables": ["类似风格的知名作品"],
  "styleConsistencyScore": 8
}
\`\`\``
}
