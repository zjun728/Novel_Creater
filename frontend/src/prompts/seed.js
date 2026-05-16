/**
 * 创作种子生成 Prompt
 */
export function buildSeedSystemPrompt() {
  return `你是一位资深小说编辑和创意策划。你的任务是帮助作者从模糊想法中提炼出有生命力的小说种子。

核心原则：
- 不要给出套路化、模板化的建议。
- 每个种子必须有独特的差异化理由。
- 优先考虑人物欲望和世界压力的对抗。
- 开局钩子必须具体，能在 500 字内抓住读者。
- 不要写"他决定改变一切"这类空泛描述。

输出格式严格使用 JSON。`
}

export function buildSeedUserPrompt(input) {
  return `根据以下信息，生成 3-5 个原创小说种子。

用户输入：${input.idea || '无具体想法，请自由发挥'}

${input.genre ? `偏好题材：${input.genre}` : ''}
${input.stylePreference ? `偏好风格：${input.stylePreference}` : ''}
${input.forbidden ? `不想写的方向：${input.forbidden}` : ''}

每个种子请包含以下字段，用 JSON 数组返回：

\`\`\`json
[
  {
    "title": "作品暂定名",
    "genre": "题材类型",
    "logline": "一句话故事（30字以内）",
    "protagonist": "主角简介（含身份、性格亮点）",
    "desire": "主角核心欲望",
    "coreConflict": "核心矛盾",
    "worldPressure": "世界施加的压力",
    "openingHook": "开局钩子（200-400字具体场景）",
    "emotionalPromise": "主要情绪价值（爽感、悬念、共鸣、治愈等）",
    "differentiation": "差异化理由（与同类作品的区别）",
    "styleTarget": "风格目标（如：快节奏爽文、慢热文学、黑暗现实、轻松日常）",
    "riskNotes": "风险提示（可能的坑）"
  }
]
\`\`\`

要求：
1. 每个种子必须有明确不同的卖点，不是同一主题的微调。
2. 如果用户提供了题材偏好，以此为基础做差异化；如果没有，提供不同题材的选项。
3. 开局钩子要具体到场景、动作、对话，不要概括。
4. 差异化理由要实话实说，不要吹嘘。
5. 风险提示要诚实。`
}
