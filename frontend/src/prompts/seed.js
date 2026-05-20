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

输出格式必须是合法 JSON：
- 只输出 JSON，不要输出 Markdown 代码块。
- 顶层对象必须只有一个字段 "seeds"。
- "seeds" 必须是数组。
- 字符串内部不要写未转义换行，长文本用中文句号连接。
- 不要在 JSON 前后添加解释、编号、标题或结语。
- 每个种子对象必须保留 endingAnchor 字段；内容可以为空字符串，但不要省略字段。`
}

export function buildSeedUserPrompt(input) {
  return `根据以下信息，生成 1-3 个原创小说种子。

用户输入：${input.idea || '无具体想法，请自由发挥'}

${input.genre ? `偏好题材：${input.genre}` : ''}
${input.stylePreference ? `偏好风格：${input.stylePreference}` : ''}
${input.forbidden ? `不想写的方向：${input.forbidden}` : ''}

每个种子请包含以下字段，用 JSON 对象返回，顶层固定为 "seeds"：

{
  "seeds": [
    {
      "title": "作品暂定名",
      "genre": "题材类型",
      "logline": "一句话故事（30字以内）",
      "protagonist": "主角简介（含身份、性格亮点）",
      "desire": "主角核心欲望",
      "coreConflict": "核心矛盾",
      "worldPressure": "世界施加的压力",
      "openingHook": "开局钩子（120-220字具体场景）",
      "emotionalPromise": "主要情绪价值（爽感、悬念、共鸣、治愈等）",
      "differentiation": "差异化理由（与同类作品的区别）",
      "styleTarget": "风格目标（如：快节奏爽文、慢热文学、黑暗现实、轻松日常）",
      "riskNotes": "风险提示（可能的坑）",
      "endingAnchor": "结局锚点（故事最终抵达的画面、情绪收束或主题归宿；不需要剧透全部细节）"
    }
  ]
}

要求：
1. 每个种子必须有明确不同的卖点，不是同一主题的微调。
2. 如果用户提供了题材偏好，以此为基础做差异化；如果没有，提供不同题材的选项。
3. 开局钩子要具体到场景、动作、对话，不要概括。
4. 差异化理由要实话实说，不要吹嘘。
5. 风险提示要诚实。
6. 每个字段控制在 300 字以内，避免输出过长导致 JSON 被截断。
7. 结局锚点不是强制剧情大纲，但必须保留字段；能判断时写出终局画面、情绪收束或主题归宿，无法判断时填空字符串。
8. 最终回复只能是上面结构的合法 JSON。`
}

export function buildSeedRepairPrompt(rawText) {
  return `下面是一段 AI 已经生成过的小说种子内容，但格式可能不是合法 JSON，也可能是 Markdown/编号列表/中文标签。请把其中已有的种子内容结构化，不要解释。

允许做的事：
- 从原文中提取标题、题材、主角、开局钩子等字段。
- 原文有明确信息但字段名不同，可以归并到最接近的字段。
- 不要编造原文没有的新方向，不要新增本地样本。
- 每个种子对象必须保留 endingAnchor 字段；原文没有结局锚点时填空字符串。

请严格输出合法 JSON 对象，顶层只有 "seeds" 字段：
{
  "seeds": [
    {
      "title": "",
      "genre": "",
      "logline": "",
      "protagonist": "",
      "desire": "",
      "coreConflict": "",
      "worldPressure": "",
      "openingHook": "",
      "emotionalPromise": "",
      "differentiation": "",
      "styleTarget": "",
      "riskNotes": "",
      "endingAnchor": ""
    }
  ]
}

原始内容：
${rawText}`
}
