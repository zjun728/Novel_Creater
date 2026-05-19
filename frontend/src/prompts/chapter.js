/**
 * 章节生成 Prompt
 */

function hasText(value) {
  return value !== undefined && value !== null && String(value).trim() !== ''
}

function formatList(items) {
  if (!Array.isArray(items)) return hasText(items) ? String(items) : ''
  return items.filter(hasText).map(item => `- ${item}`).join('\n')
}

function formatChapterGoal(goal) {
  if (!goal) return ''
  if (typeof goal === 'string') return goal

  const lines = []
  if (goal.title) lines.push(`- 标题/阶段：${goal.title}`)
  if (goal.goal) lines.push(`- 本章要完成：${goal.goal}`)
  if (goal.conflict) lines.push(`- 核心冲突：${goal.conflict}`)
  if (goal.turn) lines.push(`- 转折：${goal.turn}`)
  if (goal.emotionalBeat) lines.push(`- 情绪节拍：${goal.emotionalBeat}`)
  return lines.join('\n')
}

function formatNearOutline(outline) {
  if (!Array.isArray(outline)) return hasText(outline) ? String(outline) : ''
  return outline.map(o => {
    const parts = [
      o.title,
      o.goal,
      o.conflict ? `冲突：${o.conflict}` : '',
      o.turn ? `转折：${o.turn}` : '',
      o.emotionalBeat ? `情绪：${o.emotionalBeat}` : ''
    ].filter(hasText)
    return `- 第${o.chapterNum || '?'}章：${parts.join('；')}`
  }).join('\n')
}

function formatCharacters(characters) {
  if (!Array.isArray(characters)) return hasText(characters) ? String(characters) : ''

  return characters.map(c => {
    const hardState = c.hardState || {}
    const softState = c.softState || {}
    const lines = [`### ${c.name || '未命名角色'}（${c.role || '配角'}）`]
    if (c.personality) lines.push(`- 性格：${c.personality}`)
    if (c.desire) lines.push(`- 欲望：${c.desire}`)
    if (c.fear) lines.push(`- 恐惧：${c.fear}`)
    if (c.location || hardState.location) lines.push(`- 当前位置：${c.location || hardState.location}`)
    if (c.physicalStatus || hardState.physicalStatus) lines.push(`- 身体状态：${c.physicalStatus || hardState.physicalStatus}`)
    if (c.emotion || softState.emotion) lines.push(`- 当前情绪：${c.emotion || softState.emotion}`)
    if (c.currentDesire || softState.currentDesire) lines.push(`- 当前欲望：${c.currentDesire || softState.currentDesire}`)
    return lines.join('\n')
  }).join('\n\n')
}

function formatPlotThreads(threads) {
  if (!Array.isArray(threads)) return hasText(threads) ? String(threads) : ''
  return threads
    .filter(t => t.status === 'planted' || t.status === 'developing')
    .map(t => `- ${t.title}：${t.content}（状态：${t.status}）`)
    .join('\n')
}

function formatChapterBeatPlan(plan) {
  if (!plan) return ''
  if (typeof plan === 'string') return plan.trim()
  if (Array.isArray(plan)) {
    return plan
      .filter(hasText)
      .map((beat, index) => {
        if (typeof beat === 'string') return `${index + 1}. ${beat}`
        const label = beat.type || beat.label || `节拍 ${index + 1}`
        const content = beat.content || beat.description || beat.goal || ''
        const turn = beat.turn ? ` 转折：${beat.turn}` : ''
        return `${index + 1}. [${label}] ${content}${turn}`
      })
      .join('\n')
  }
  return JSON.stringify(plan, null, 2)
}

function formatSeedContext(seed) {
  if (!seed) return ''
  if (typeof seed === 'string') return seed.trim()

  const lines = []
  if (seed.genre) lines.push(`- 题材：${seed.genre}`)
  if (seed.logline) lines.push(`- 一句话：${seed.logline}`)
  if (seed.protagonist) lines.push(`- 主角：${seed.protagonist}`)
  if (seed.desire) lines.push(`- 主角欲望：${seed.desire}`)
  if (seed.coreConflict) lines.push(`- 核心冲突：${seed.coreConflict}`)
  if (seed.worldPressure) lines.push(`- 世界压力：${seed.worldPressure}`)
  if (seed.openingHook) lines.push(`- 开局钩子：${seed.openingHook}`)
  if (seed.styleTarget) lines.push(`- 风格目标：${seed.styleTarget}`)
  if (seed.differentiation) lines.push(`- 差异化：${seed.differentiation}`)
  return lines.join('\n')
}

function formatSequenceRules(rules) {
  if (!rules) return ''
  if (typeof rules === 'string') return rules.trim()
  if (!Array.isArray(rules)) return JSON.stringify(rules, null, 2)
  return rules.filter(hasText).map(rule => `- ${rule}`).join('\n')
}

function formatVolumeStage(stage) {
  if (!stage) return ''
  if (typeof stage === 'string') return stage.trim()

  const lines = [
    `- 当前分卷：${stage.title || '未命名'}（${stage.chapterRange || '章节范围未定'}）`,
    stage.targetWords ? `- 目标字数：${stage.targetWords}` : '',
    stage.status ? `- 状态：${stage.status}` : '',
    stage.coreGoal ? `- 分卷目标：${stage.coreGoal}` : '',
    stage.mainConflict ? `- 分卷核心冲突：${stage.mainConflict}` : '',
    stage.keyCharacters?.length ? `- 分卷关键人物：${stage.keyCharacters.join('、')}` : '',
    stage.currentSummary ? `- 当前阶段短摘要：${stage.currentSummary}` : '',
    stage.stageSummary ? `- 阶段总结：${stage.stageSummary}` : '',
    stage.completedBeats?.length ? `- 已完成节点：${stage.completedBeats.map(formatStageItem).join('；')}` : '',
    stage.openQuestions?.length ? `- 未解问题：${stage.openQuestions.map(formatStageItem).join('；')}` : '',
    stage.characterChanges?.length ? `- 人物变化：${stage.characterChanges.map(formatStageItem).join('；')}` : '',
    stage.settingChanges?.length ? `- 设定变化：${stage.settingChanges.map(formatStageItem).join('；')}` : '',
    stage.foreshadowingState?.length ? `- 伏笔状态：${stage.foreshadowingState.map(formatStageItem).join('；')}` : '',
    stage.handoffToNext?.length ? `- 接力点：${stage.handoffToNext.map(formatStageItem).join('；')}` : '',
    stage.continuityNotes?.length ? `- 连续性约束：${stage.continuityNotes.map(formatStageItem).join('；')}` : '',
    stage.auditAssessment ? `- 最近分卷审稿：${stage.auditAssessment}` : '',
    stage.auditIssues?.length ? `- 审稿待处理：${stage.auditIssues.map(formatStageItem).join('；')}` : '',
    stage.previousVolumeSummaries?.length
      ? `- 前卷摘要：${stage.previousVolumeSummaries.map(item => `${item.title || item.range}：${item.summary}`).join('；')}`
      : ''
  ].filter(hasText)

  return lines.join('\n')
}

function formatStageItem(item) {
  if (typeof item === 'string') return item
  if (!item || typeof item !== 'object') return ''
  return [
    item.name || item.title || item.label || '',
    item.state ? `状态=${item.state}` : '',
    item.change ? `变化=${item.change}` : '',
    item.description || '',
    item.suggestion ? `建议=${item.suggestion}` : '',
    item.note ? `说明=${item.note}` : '',
    item.nextUse ? `接力=${item.nextUse}` : ''
  ].filter(hasText).join('，')
}

export function cleanGeneratedChapterText(text) {
  if (!text) return ''

  return String(text)
    .replace(/^\s*```(?:markdown|md|text|txt)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .split('\n')
    .filter((line, index) => {
      const trimmed = line.trim()
      if (index === 0 && /^#{1,6}\s+/.test(trimmed)) return false
      if (/^第\s*\d+\s*章[：:、\s]/.test(trimmed)) return false
      if (/^(以下是|下面是|正文如下|候选稿|章节正文)[：:]/.test(trimmed)) return false
      return true
    })
    .join('\n')
    .replace(/\n{4,}/g, '\n\n\n')
    .trim()
}

export function cleanChapterBeatPlanText(text) {
  if (!text) return ''
  return String(text)
    .replace(/^\s*```(?:markdown|md|text|txt)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .trim()
}

export function buildChapterSystemPrompt() {
  return `你是一位专业小说作者，擅长长篇叙事。你的任务是撰写小说章节正文。

创作原则：
- 严格遵守已确认的世界规则和角色状态。
- 在给定框架内发挥创造力，但不要推翻已有事实。
- 人物行为要符合其性格、欲望和当前状态。
- 对话要有各自的声音，不要所有人说一样的话。
- 场景要有画面感，但不要过度描写。
- 每章要有推进感：情节、人物或悬念至少推进一项。

输出要求：
- 只输出小说正文，不输出标题、Markdown 标题、提纲、解释、创作说明或“以下是正文”等提示语。
- 第一行必须直接进入正文叙事。
- 正文必须从本章小纲第一个节拍，或本章时间线最早的可写场景开始。
- 不得用后续会议结论、追查结果、角色受伤或死亡后的余波、任务奖励、事后复盘作为开头。
- 如果是第一章，必须从主角初始处境或创作种子的开局钩子开始，不要先写背景结论或势力反应。
- 按自然时间顺序写场景，不要把结尾、设定说明、系统提示或任务奖励插入到开头。
- 不要用项目符号、编号列表、元注释或作者旁白来代替正文。
- 如果需要出现系统提示、任务面板、弹窗等内容，必须作为小说世界内角色实际看到或听到的内容自然写入。`
}

export function buildChapterPrompt(context) {
  const parts = []

  const bible = context.bible || {}
  const premise = bible.premise || context.premise
  const styleBible = bible.styleBible || context.styleBible
  const worldRules = bible.worldRules || context.worldRules
  const forbiddenDirections = bible.forbiddenDirections || context.forbiddenDirections

  if (premise) parts.push(`## 作品定位\n${premise}`)
  if (styleBible) parts.push(`## 风格要求\n${styleBible}`)
  if (worldRules) parts.push(`## 世界规则（不可违背）\n${worldRules}`)
  if (context.settingLibrary) parts.push(`## 设定库（不可违背）\n${context.settingLibrary}`)
  if (context.recentSettingChanges) parts.push(`## 最近设定变化\n${context.recentSettingChanges}`)
  if (forbiddenDirections?.length) parts.push(`## 禁止方向\n${formatList(forbiddenDirections)}`)

  const seedInfo = formatSeedContext(context.seed)
  if (seedInfo) parts.push(`## 创作种子\n${seedInfo}`)

  if (context.openingAnchor) {
    parts.push(`## 开局锚点（第一章优先执行）\n${context.openingAnchor}`)
  }

  const sequenceRules = formatSequenceRules(context.sequenceRules)
  if (sequenceRules) parts.push(`## 顺序控制（必须遵守）\n${sequenceRules}`)

  const volumeStage = formatVolumeStage(context.volumeStage)
  if (volumeStage) parts.push(`## 分卷阶段上下文（必须承接）\n${volumeStage}`)

  const chapterGoal = formatChapterGoal(context.chapterGoal)
  if (chapterGoal) parts.push(`## 本章目标\n${chapterGoal}`)

  const nearOutline = formatNearOutline(context.nearOutline)
  if (nearOutline) parts.push(`## 近景大纲\n${nearOutline}`)

  if (context.currentVolume) {
    const volume = context.currentVolume
    parts.push(`## 当前卷\n- 标题：${volume.title || '无'}\n- 目标：${volume.goal || '无'}\n- 主要冲突：${volume.mainConflict || '无'}`)
  }

  if (context.recentSummaries?.length) {
    parts.push(`## 前情摘要\n${context.recentSummaries.map(s => `- 第${s.chapterNum}章：${s.summary}`).join('\n')}`)
  }

  if (context.recentFacts) {
    parts.push(`## 已确认事实\n${context.recentFacts}`)
  }

  const characters = formatCharacters(context.characters)
  if (characters) parts.push(`## 角色状态\n${characters}`)

  const plotThreads = formatPlotThreads(context.plotThreads)
  if (plotThreads) parts.push(`## 进行中的伏笔\n${plotThreads}`)

  if (context.relationships) {
    parts.push(`## 角色关系\n${context.relationships}`)
  }

  if (context.currentDraft) {
    parts.push(`## 当前草稿（请在此基础上续写或改写）\n${context.currentDraft}`)
  }

  const beatPlan = formatChapterBeatPlan(context.beatPlan)
  if (beatPlan) {
    parts.push(`## 已确认本章小纲（优先执行）
${beatPlan}

执行要求：
- 请按小纲的自然顺序展开成正文。
- 第一段正文必须对应小纲第 1 条，不要先写第 2 条之后的结果或余波。
- 禁止把后续会议、追查余波、伤亡结论、任务奖励提前到开头。
- 小纲是方向，不是模板；允许补充过渡、细节、对白和合理的意外，但不要推翻关键节点。
- 不要把小纲条目、编号或分析文字写进正文。`)
  }

  parts.push(`## 写作任务
请撰写第 ${context.chapterNum || '?'} 章正文。
${context.instruction ? `特别要求：${context.instruction}\n` : ''}如果没有可见小纲，请先在心中按自然时间顺序排好本章场景，但不要输出小纲。
请直接输出正文，不要输出标题和解释。`)

  return parts.join('\n\n')
}

export function buildChapterBeatSystemPrompt() {
  return `你是一位长篇小说主笔兼章节策划，擅长在正式写正文前设计可执行的章前小纲。

你的任务是生成“本章剧情节拍”，不是写正文。

规划原则：
- 小纲必须服务长篇连载：本章要有开场牵引、冲突升级、信息释放、情绪变化和结尾钩子。
- 严格遵守创作圣经、世界规则、角色状态和已确认事实。
- 第一条节拍必须是正文第一幕，是读者真正看到的开场场景，不是背景说明、后续会议、结果总结或事后追查。
- 保留想象力：只锁定关键节点，不要把每一句对白、每个动作都规定死。
- 给正文生成留出发挥空间，但不能让大模型随意跑偏。

输出要求：
- 只输出章前小纲，不输出小说正文。
- 使用清晰的 Markdown 文本，便于用户编辑。
- 小纲节拍控制在 5-8 条，每条用一句话说明“发生什么”和“为什么推动故事”。
- 不要输出 JSON，不要输出解释性废话。`
}

export function buildChapterBeatPrompt(context) {
  const planningContext = buildChapterPrompt({ ...context, instruction: '' })
    .replace(/## 写作任务[\s\S]*$/m, '')
    .trim()

  return `${planningContext}

## 规划任务
请为第 ${context.chapterNum || '?'} 章生成“正式写作前确认的小纲”。

请按以下格式输出：

### 本章核心目的
- 用一句话说明本章必须完成的剧情推进。

### 本章节拍
1. [开场牵引] ...
2. [目标浮现] ...
3. [冲突升级] ...
4. [信息释放] ...
5. [人物选择] ...
6. [转折/代价] ...
7. [结尾钩子] ...

### 写作约束
- 需要遵守的角色、设定、伏笔或禁忌。

### 可发散空间
- 正文生成时可以自由发挥的细节、场景、对白或意外。

要求：
- 节拍必须按自然时间顺序排列。
- 第一条必须是正文第一幕，不要从后续会议、事后追查、伤亡结果或已经发生后的复盘开始。
- 如果这是第 1 章，第一条必须来自开局锚点、创作种子或主角初始处境。
- 每个节拍都要能转化为正文场景，不要写抽象口号。
- 不要把结尾反转放到开头。
- 除非用户明确要求，不要把倒叙、插叙或闪回作为第一幕。
- 不要写小说正文。`
}

/**
 * 章节续写 prompt
 */
export function buildContinuePrompt(currentContent, instruction, context = {}) {
  const volumeStage = formatVolumeStage(context.volumeStage)
  const constraints = [
    context.styleBible ? `风格要求：${context.styleBible}` : '',
    context.settingLibrary ? `设定库：\n${context.settingLibrary}` : '',
    context.recentSettingChanges ? `最近设定变化：\n${context.recentSettingChanges}` : '',
    volumeStage ? `分卷阶段上下文：\n${volumeStage}` : '',
    context.recentFacts ? `已确认事实：\n${context.recentFacts}` : ''
  ].filter(hasText).join('\n\n')

  return `${constraints ? `## 写作上下文\n${constraints}\n\n` : ''}以下是小说的当前内容：

---
${currentContent}
---

请从最后一句自然续写。${instruction ? `\n续写方向：${instruction}` : ''}

要求：
- 只输出续写正文，不要输出标题、说明或提纲。
- 保持一致的风格和人物声音。
- 承接当前分卷目标、阶段总结、人物状态和已确认事实。
- 向前推进情节或深化人物。
- 不要重复已有内容。
- 续写长度：800-2000 字。`
}

/**
 * 多候选版本 prompt
 */
export function buildMultiVariantPrompt(context) {
  const basePrompt = buildChapterPrompt(context)
  return `${basePrompt}

请生成 3 个不同方向的版本：

1. **稳妥推进版**：按照大纲自然推进，风格稳健。
2. **强冲突版**：加强矛盾和冲突，节奏更快，张力更强。
3. **意外转向版**：在合理范围内引入意外发展，制造惊喜。

每个版本输出为一个独立章节正文，使用版本名称作为分隔标题。`
}

/**
 * 扩写 prompt
 */
export function buildExpandPrompt(selectedText, context = {}) {
  const volumeStage = formatVolumeStage(context.volumeStage)
  return `请扩写以下段落，丰富细节、心理描写和场景氛围：

${volumeStage ? `## 分卷阶段上下文\n${volumeStage}\n` : ''}
${context.styleBible ? `## 风格要求\n${context.styleBible}\n` : ''}

---
${selectedText}
---

扩写要求：
- 只输出扩写后的正文。
- 保持原有人物性格和对话风格。
- 可以增加内心独白、环境描写、动作细节。
- 扩写后长度约为原来的 2-3 倍。
- 不要让扩写后的文字变得冗长拖沓。`
}

/**
 * 压缩 prompt
 */
export function buildCompressPrompt(selectedText) {
  return `请压缩以下段落，保留核心情节和关键对话，删除冗余描写：
---
${selectedText}
---

压缩要求：
- 只输出压缩后的正文。
- 保留情节推进的关键节点。
- 保留重要对话和人物反应。
- 压缩后长度约为原来的一半。`
}

/**
 * 多模型融合 prompt
 */
export function buildFusionPrompt(fragments, context) {
  const fragmentText = fragments.map((f, i) =>
    `### 候选 ${i + 1}（来源：${f.label || `模型 ${i + 1}`}）\n\n${f.content}`
  ).join('\n\n---\n\n')

  return `请将以下多个 AI 生成的章节候选版本融合成一个最佳版本。
${fragmentText}

融合要求：
- 只输出融合后的正文，不要输出标题或解释。
- 提取每个候选中最精彩的情节走向和描写。
- 保持统一的叙事风格和人物声音。
- 解决候选之间的冲突和矛盾。
- 确保情节连贯，过渡自然。
- 融合后的长度应接近原候选的平均长度。
- 不要添加与候选中完全无关的新情节。
${context.chapterNum ? `这是第 ${context.chapterNum} 章。` : ''}

请直接输出融合后的完整章节正文。`
}
