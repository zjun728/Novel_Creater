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

function formatWordTarget(target) {
  if (!target?.target) return ''
  return [
    `- 本章目标约 ${target.target} 字，优先控制在 ${target.min}-${target.max} 字。`,
    `- 如内容接近 ${target.hardMax} 字，必须主动收束场景，把未展开内容留作下一章钩子，不要继续新增场景或扩写设定。`,
    `- 字数护栏服务章节节奏，不是机械截断；不得为了压字数省略关键动作、情绪转折或因果交代。`,
    `- 如果内容自然超量，优先减少支线、旁白、重复描写或低效对白，而不是草草结尾。`,
    `- 硬边界参考：尽量不要低于 ${target.hardMin} 字，也不要超过 ${target.hardMax} 字（最多上下浮动 20%）。`
  ].join('\n')
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

const MULTI_VARIANT_LABELS = ['稳妥推进版', '强冲突版', '意外转向版']

function normalizeVariantLabel(label, index = 0) {
  const text = String(label || '').replace(/[《》【】[\]（）()#*：:\-—\s]/g, '')
  if (/稳妥|稳健|保守|自然推进/.test(text)) return '稳妥推进版'
  if (/强冲突|冲突|张力|加速|压迫/.test(text)) return '强冲突版'
  if (/意外|转向|惊喜|反转/.test(text)) return '意外转向版'
  return MULTI_VARIANT_LABELS[index] || `候选 ${index + 1}`
}

function cleanVariantContent(content) {
  return cleanGeneratedChapterText(
    String(content || '')
      .replace(/^\s*<<<END_VARIANT>>>\s*/i, '')
      .replace(/\s*<<<END_VARIANT>>>\s*$/i, '')
      .replace(/^\s*(?:正文|章节正文|候选正文)\s*[：:]\s*/i, '')
      .trim()
  )
}

function extractMarkerVariants(text) {
  const variants = []
  const markerRegex = /<<<VARIANT\s*[:：]\s*([^>\n]+?)\s*>>>\s*([\s\S]*?)(?=<<<VARIANT\s*[:：]|$)/gi
  let match = markerRegex.exec(text)
  while (match) {
    const content = cleanVariantContent(match[2])
    if (content) {
      variants.push({
        label: normalizeVariantLabel(match[1], variants.length),
        content
      })
    }
    match = markerRegex.exec(text)
  }
  return variants
}

function extractHeadingVariants(text) {
  const lines = String(text || '').split(/\r?\n/)
  const boundaries = []

  lines.forEach((line, index) => {
    const trimmed = line.trim()
    if (!trimmed || trimmed.length > 80) return

    const named = trimmed.match(/^(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*\*)?(?:[【\[(（《]?\s*)?(?:候选\s*)?(?:版本|方案|稿件)?\s*(?:一|二|三|1|2|3|A|B|C)?\s*[】\])）》、.．:：\-\s]*(稳妥推进版?|稳健推进版?|保守推进版?|自然推进版?|强冲突版?|冲突加强版?|张力加强版?|意外转向版?|惊喜转向版?|反转版?)(?:\*\*)?\s*(?:[：:\-—]\s*)?$/i)
    if (named) {
      boundaries.push({ lineIndex: index, label: named[1] })
      return
    }

    const numbered = trimmed.match(/^(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*\*)?(?:候选\s*)?(?:版本|方案|稿件)\s*(一|二|三|1|2|3|A|B|C)\s*(?:\*\*)?\s*[：:、.．\-\s]*(.*)$/i)
    if (numbered) {
      boundaries.push({ lineIndex: index, label: numbered[2] || numbered[1] })
    }
  })

  if (boundaries.length < 2) return []

  return boundaries.map((boundary, index) => {
    const next = boundaries[index + 1]
    const content = cleanVariantContent(lines.slice(boundary.lineIndex + 1, next?.lineIndex ?? lines.length).join('\n'))
    return {
      label: normalizeVariantLabel(boundary.label, index),
      content
    }
  }).filter(variant => variant.content)
}

function extractRuleSeparatedVariants(text) {
  const parts = String(text || '')
    .split(/\n\s*(?:-{3,}|={3,}|_{3,}|※{3,})\s*\n/g)
    .map(cleanVariantContent)
    .filter(content => content.length > 80)

  if (parts.length < 3) return []
  return parts.slice(0, 3).map((content, index) => ({
    label: MULTI_VARIANT_LABELS[index],
    content
  }))
}

export function parseMultiVariantText(text) {
  if (!text) return []

  const raw = String(text)
    .replace(/^\s*```(?:markdown|md|text|txt)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .trim()

  const parsed = [
    extractMarkerVariants(raw),
    extractHeadingVariants(raw),
    extractRuleSeparatedVariants(raw)
  ].find(list => list.length >= 2)

  if (parsed?.length) {
    const seen = new Set()
    return parsed.filter(variant => {
      const key = `${variant.label}::${variant.content.slice(0, 120)}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    }).slice(0, 3)
  }

  const fallback = cleanVariantContent(raw)
  return fallback ? [{ label: '候选', content: fallback }] : []
}

export function cleanChapterBeatPlanText(text) {
  if (!text) return ''
  return String(text)
    .replace(/^\s*```(?:markdown|md|text|txt)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .trim()
}

export function isDefaultChapterTitle(title, chapterNum) {
  const text = String(title || '').trim()
  if (!text || text === '未命名') return true
  const num = String(chapterNum || '').trim()
  if (!num) return /^第\s*\d+\s*章$/.test(text)
  return new RegExp(`^第\\s*${num}\\s*章$`).test(text)
}

export function formatChapterDisplayTitle(chapter = {}, options = {}) {
  const chapterNum = chapter.chapterNum || chapter.chapter_num || options.chapterNum || ''
  const numberTitle = chapterNum ? `第 ${chapterNum} 章` : '未命名章节'
  const title = String(chapter.title || '').trim()
  if (!title || isDefaultChapterTitle(title, chapterNum)) return numberTitle
  if (options.includeNumber === false) return title
  return `${numberTitle} · ${title}`
}

export function cleanGeneratedChapterTitle(text) {
  if (!text) return ''
  const title = String(text)
    .replace(/^\s*```(?:markdown|md|text|txt)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .find(Boolean)
    ?.replace(/^#{1,6}\s*/, '')
    .replace(/^(?:章名|标题|章节标题)\s*[：:]\s*/i, '')
    .replace(/^第\s*[\d一二三四五六七八九十百千万零〇两]+\s*章\s*[：:、，.\-—]?\s*/, '')
    .replace(/^[《“"「『【\[]+/, '')
    .replace(/[》”"」』】\]]+$/, '')
    .replace(/[。！？!?,，；;：:、\s]+$/g, '')
    .trim()

  if (!title) return ''
  if (/^(?:第\s*[\d一二三四五六七八九十百千万零〇两]+\s*章|无题|未命名)$/.test(title)) return ''
  if (Array.from(title).length < 2 || Array.from(title).length > 14) return ''
  return title
}

export function buildChapterTitleSystemPrompt() {
  return `你是一位长篇小说编辑，擅长给网文连载章节命名。

命名原则：
- 章名要贴合本章核心动作、情绪或悬念。
- 不要剧透后续章节，不要泄露尚未揭开的终局真相。
- 不要使用泛泛的“风暴将至”“新的开始”等空标题。
- 标题应有画面感或钩子，但不要夸张营销腔。

输出要求：
- 只输出章名，不输出“第几章”、解释、引号、书名号、Markdown 或备选列表。
- 章名控制在 2-14 个汉字之间。`
}

export function buildChapterTitlePrompt(context = {}) {
  const parts = [
    `请为第 ${context.chapterNum || '?'} 章生成一个默认章名。`
  ]

  const chapterGoal = formatChapterGoal(context.chapterGoal)
  if (chapterGoal) parts.push(`## 本章目标\n${chapterGoal}`)

  const beatPlan = formatChapterBeatPlan(context.beatPlan)
  if (beatPlan) parts.push(`## 本章小纲\n${beatPlan}`)

  const content = String(context.content || '').trim()
  if (content) {
    parts.push(`## 本章正文节选\n${content.slice(0, 1800)}`)
  }

  parts.push('请只输出一个章名。')
  return parts.join('\n\n')
}

export function buildChapterSystemPrompt() {
  return `你是一位专业小说作者，擅长长篇叙事。你的任务是撰写小说章节正文。

创作原则：
- 严格遵守已确认的世界规则和角色状态。
- 在给定框架内发挥创造力，但不要推翻已有事实；可以制造反转，但必须以角色认知有限、隐藏真相揭示或误导解除的方式自然成立。
- 人物行为要符合其性格、欲望和当前状态。
- 每个重要场景都要有“人性动机”：人物想得到什么、害怕失去什么、为什么不能直接说出口、做出选择要付出什么代价，以及事件结束后的情绪残留。
- 不要把人物写成推动剧情或解释设定的工具人；外部事件必须通过人物的欲望、恐惧、羞耻、亏欠、依赖、嫉妒、爱恨或自尊产生代入感。
- 对话要有各自的声音，不要所有人说一样的话。
- 场景要有画面感，但不要过度描写。
- 每章要有推进感：情节、人物或悬念至少推进一项。
- 设定、小纲和上下文是创作边界，不是写作模板；允许补充场景、对白、细节和意外，但不能无解释破坏既有因果。
- 新增关键人物、势力、地点、物品或能力时，要让其在正文中有清晰作用，便于后续提取到设定库。
- 降低 AI 腔硬约束：非对白叙述中尽量不要使用“不是X，而是Y”“不是X，是Y”结构；整章最多 2 次，超过就必须改写。
- 禁止连续使用套路化反差句：包括“不是……而是……”“不是……是……”“像是……又像是……”“某种……”“仿佛有什么东西……”“终于意识到……”等。
- 如果需要表达反差、压迫、心理变化，优先用具体动作、感官细节、物象变化、对白停顿或人物反应来呈现，不要用解释性判断句反复总结。

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
  if (context.activeCorrectionTasks) parts.push(`## 未完成纠偏任务（写作时优先避免继续扩大问题）\n${context.activeCorrectionTasks}`)
  if (forbiddenDirections?.length) parts.push(`## 禁止方向\n${formatList(forbiddenDirections)}`)

  const seedInfo = formatSeedContext(context.seed)
  if (seedInfo) parts.push(`## 创作种子\n${seedInfo}`)

  if (context.openingAnchor) {
    parts.push(`## 开局锚点（第一章优先执行）\n${context.openingAnchor}`)
  }

  const sequenceRules = formatSequenceRules(context.sequenceRules)
  if (sequenceRules) parts.push(`## 顺序控制（必须遵守）\n${sequenceRules}`)

  const wordTarget = formatWordTarget(context.wordTarget)
  if (wordTarget) parts.push(`## 本章字数节奏（尽量遵守）\n${wordTarget}`)

  if (context.previousChapterEnding) {
    parts.push(`## 上一章结尾原文（下一章必须承接）
${context.previousChapterEnding}

承接要求：
- 如果这是第 2 章或后续章节，第一幕必须自然承接上一章结尾的情绪、危险、动作或悬念。
- 不要无提示地跳到全新地点、全新时间或无关日常；如必须转场，第一段要先完成上一章钩子的即时回应。
- 上一章结尾如果明显是未完成句、动作中断或危机未落地，本章开头必须先补足这个动作或危机，再进入本章小纲后续节拍。`)
  }

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
- 允许把小纲写得更有想象力，但核心因果、人物目标和本章必须完成的剧情推进不能丢。
- 不要把小纲条目、编号或分析文字写进正文。`)
  }

  parts.push(`## 人物代入感要求（必须执行）
- 本章至少要让一个关键人物的内在动机变得可感：他想得到什么，害怕失去什么，为什么不能直接说出口。
- 重要选择不能只因为“剧情需要”，必须让读者看见欲望、恐惧、误判、遮掩或自尊在推动选择。
- 每个关键冲突都要有代价：失去某个关系、暴露弱点、承担误解、欠下人情、伤害别人或改变自我认知。
- 情绪不要只用形容词说明，要通过动作、停顿、回避、细节选择、对白失控或沉默表现。
- 场景结束时应留下情绪残留：愤怒未消、羞耻被压住、依赖被否认、信任裂开、希望变重等，让下一章有心理惯性。
- 爽点要来自“人物在压力下做出选择”，不是只靠外部开挂、信息堆叠或华丽句子。`)

  parts.push(`## 写作任务
请撰写第 ${context.chapterNum || '?'} 章正文。
${context.instruction ? `特别要求：${context.instruction}\n` : ''}如果没有可见小纲，请先在心中按自然时间顺序排好本章场景，但不要输出小纲。
请直接输出正文，不要输出标题和解释。

## 输出前静默自检
在最终输出前，请在心中快速检查并自行修正以下问题，但不要输出检查过程：
- 开头是否自然承接上一章结尾或本章小纲第一条。
- 是否完成了本章小纲的核心节点，同时保留合理发挥空间。
- 是否无解释推翻了创作圣经、设定库、角色状态或已确认事实。
- 新增人物、势力、地点、物品、能力是否有明确叙事作用。
- 是否把结论、余波、任务奖励、系统说明或后续复盘提前到了开头。
- 是否明显超过本章建议字数范围；如果超过，请减少支线、旁白、重复描写或低效对白，保留关键动作、情绪转折、因果交代和章节钩子。
- 是否出现高频 AI 腔句式，如“不是……而是……”“不是……是……”“像是……又像是……”“某种……”。非对白叙述中“不是X，是/而是Y”整章最多 2 次；如果超过，请必须改成具体动作、感官、物象、对白停顿或人物反应。
- 这一章是否能回答：关键人物想得到什么、害怕失去什么、为什么不能直说、这个选择要付出什么代价、结束后留下什么情绪残留。`)

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
- 小纲必须包含人物动机层：关键人物的欲望、恐惧、遮掩、选择、代价和情绪残留至少要落到 2-3 个节拍中。

输出要求：
- 只输出章前小纲，不输出小说正文。
- 使用清晰的 Markdown 文本，便于用户编辑。
- 小纲节拍控制在 5-8 条，每条用一句话说明“发生什么”和“为什么推动故事”。
- 不要输出 JSON，不要输出解释性废话。
- 输出前先在心中自检并修正小纲，不要把自检过程写出来。`
}

export function buildChapterBeatPrompt(context) {
  const planningContext = buildChapterPrompt({ ...context, instruction: '' })
    .replace(/## 写作任务[\s\S]*$/m, '')
    .trim()

  return `${planningContext}

## 规划任务
请为第 ${context.chapterNum || '?'} 章生成“正式写作前确认的小纲”。

${context.wordTarget?.target ? `本章按约 ${context.wordTarget.target} 字体量设计，优先服务 ${context.wordTarget.min}-${context.wordTarget.max} 字正文。小纲节拍应控制在一章可完成的范围内，不要规划成两章内容；如果剧情自然超量，应减少支线节拍，把后续冲突或余波留到下一章。` : ''}

请按以下格式输出：

### 本章核心目的
- 用一句话说明本章必须完成的剧情推进。

### 人物动机层
- 本章关键人物想得到什么：
- 本章关键人物害怕失去什么：
- 他为什么不能直接说出口：
- 本章选择需要付出的代价：
- 本章结束后的情绪残留：

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
- 每个关键节拍至少说明一个“人物为什么这样做”的动机，不要只写事件发生。
- 不要把结尾反转放到开头。
- 除非用户明确要求，不要把倒叙、插叙或闪回作为第一幕。
- 不要写小说正文。

## 小纲输出前静默自检
请在最终输出小纲前，先在心中检查并自行修正以下问题，但不要输出检查过程：
- 第一条是否自然承接上一章结尾、开局锚点或主角当前处境。
- 节拍是否按自然时间和因果顺序推进，没有把结论、余波、任务奖励或后续复盘提前。
- 是否无解释违背创作圣经、设定库、角色状态、已确认事实或未完成纠偏任务。
- 人物行动是否符合当前欲望、关系和心理状态。
- 是否明确了关键人物的欲望、恐惧、不能直说的原因、选择代价和情绪残留。
- 是否完成本章核心目的，同时给正文生成保留对白、场景细节和合理意外的发挥空间。
- 如果涉及隐藏真相或反转，是否能以角色认知有限、伏笔回收或误导解除自然成立。`
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
    context.activeCorrectionTasks ? `未完成纠偏任务：\n${context.activeCorrectionTasks}` : '',
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
  const labels = Array.isArray(context?.variantLabels) && context.variantLabels.length
    ? context.variantLabels
    : MULTI_VARIANT_LABELS
  const descriptions = {
    稳妥推进版: '按照小纲自然推进，风格稳健，适合作为正文基准稿。',
    强冲突版: '加强矛盾和冲突，节奏更快，张力更强。',
    意外转向版: '在合理范围内引入意外发展，制造惊喜。'
  }
  const variantList = labels
    .map((label, index) => `${index + 1}. **${label}**：${descriptions[label] || '在不违背小纲的前提下提供不同写法。'}`)
    .join('\n')
  const variantBlocks = labels
    .map(label => `<<<VARIANT:${label}>>>\n只写这一版的章节正文，不要写标题、解释或小纲。\n<<<END_VARIANT>>>`)
    .join('\n\n')
  const baselineDraft = hasText(context?.baselineDraft)
    ? `\n\n## 已有基准正文\n下面是用户当前已有的基准正文。新候选应与它形成可比较的差异，不要简单同义改写，也不要无视小纲乱改。\n---\n${context.baselineDraft}\n---`
    : ''

  return `${basePrompt}
${baselineDraft}

请生成 ${labels.length} 个不同方向的候选版本：

${variantList}

输出格式必须严格使用下面的分隔协议：

${variantBlocks}

注意：
- 分隔符必须原样保留，便于系统拆分版本。
- 每个分隔符之间只能放对应版本的小说正文。
- 不要把多个版本混写到同一个正文里。`
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
