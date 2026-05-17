export const styleTrialPresets = [
  {
    id: 'fast-web',
    name: '快节奏爽文',
    description: '强钩子、短段落、冲突密集，强调追读和即时反馈。'
  },
  {
    id: 'cold-restraint',
    name: '冷峻克制',
    description: '少解释、强画面、心理内压，适合悬疑、权谋和压迫感题材。'
  },
  {
    id: 'light-irony',
    name: '轻松吐槽',
    description: '口语化、反差感、角色自带幽默，适合轻喜剧和系统流。'
  },
  {
    id: 'literary-texture',
    name: '文学质感',
    description: '句式更讲究，重氛围和隐喻，牺牲部分速度换取质地。'
  },
  {
    id: 'suspense-pressure',
    name: '悬疑压迫',
    description: '信息递进克制，制造不安和谜面，适合阴谋、诡秘、悬疑。'
  },
  {
    id: 'epic-group',
    name: '群像史诗',
    description: '视野更开阔，人物关系和时代压力并重，适合长线大叙事。'
  }
]

export function buildStyleTrialSystemPrompt() {
  return `你是一位长篇小说风格总监和试写编辑。

你的任务不是评价哪个风格高级，而是帮助作者找到最适合该小说长期写作的叙事风格。

原则：
- 同一个创作种子，不同风格必须写同一个开局场景，便于横向比较。
- 不要照搬用户示例文本的内容、句子、人物或设定，只提取风格特征。
- 试写片段必须是原创正文。
- 评价要诚实，指出长期写作风险。
- 不要输出 Markdown，严格输出 JSON。`
}

export function buildStyleTrialUserPrompt(seed, options = {}) {
  const selectedPresets = styleTrialPresets
    .filter(p => (options.presetIds || []).includes(p.id))
    .map(p => `- ${p.name}：${p.description}`)
    .join('\n')

  return `请基于以下小说种子，生成风格试写对比。

## 小说种子
题材：${seed.genre || '未指定'}
一句话：${seed.logline || '未指定'}
主角：${seed.protagonist || '未指定'}
主角欲望：${seed.desire || '未指定'}
核心矛盾：${seed.coreConflict || '未指定'}
世界压力：${seed.worldPressure || '未指定'}
开局钩子：${seed.openingHook || '未指定'}
情绪价值：${seed.emotionalPromise || '未指定'}
差异化：${seed.differentiation || '未指定'}

## 需要对比的默认风格
${selectedPresets || '无'}

${options.sampleText ? `## 用户提供的风格示例
示例名称：${options.sampleName || '自定义参考风格'}
示例文本：
${options.sampleText}

请先分析示例的风格指纹，再加入一个“${options.sampleName || '自定义参考风格'}版”试写。` : ''}

## 输出要求
请返回 JSON 对象：

{
  "sampleAnalysis": {
    "fingerprint": ["如果用户提供了示例，列出 5-8 条风格指纹；否则为空数组"],
    "usableAdvice": "这种参考风格可借鉴之处",
    "risk": "长期模仿这种风格的风险"
  },
  "trials": [
    {
      "id": "英文或拼音短 id",
      "name": "风格名称",
      "positioning": "这版风格的定位",
      "styleFingerprint": ["5-8 条风格指纹"],
      "excerpt": "800-1200 字原创试写片段，只写正文，不要标题",
      "suitabilityScore": 1-10,
      "continuationStability": 1-10,
      "imaginationSpace": 1-10,
      "risks": ["长期写作风险 1", "风险 2"],
      "recommendation": "是否推荐作为主风格，以及理由"
    }
  ]
}

评分含义：
- suitabilityScore：与题材、主角、卖点的适配度。
- continuationStability：AI 后续能否稳定保持该风格。
- imaginationSpace：是否保留足够发散空间，而不是一眼看到头。

试写要求：
- 每个 excerpt 都写同一个开局场景。
- 只写小说正文，不输出解释、标题、列表。
- 不要照搬用户示例里的具体句子和内容。`
}
