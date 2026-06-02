import { formatProseRhythmAnalysis } from '../utils/proseRhythmGuard.js'

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

function formatRecentChapterEndings(endings) {
  if (!endings) return ''
  if (typeof endings === 'string') return endings.trim()
  if (!Array.isArray(endings)) return JSON.stringify(endings, null, 2)

  return endings
    .map((item, index) => {
      if (typeof item === 'string') return `- 最近第 ${index + 1} 段结尾：${item.trim()}`
      const chapterNum = item.chapterNum || item.chapter_num || item.num || '?'
      const ending = item.ending || item.content || item.text || item.summary || ''
      return hasText(ending) ? `- 第 ${chapterNum} 章结尾：${String(ending).trim()}` : ''
    })
    .filter(hasText)
    .join('\n')
}

function formatWordTarget(target) {
  if (!target?.target) return ''
  return [
    `- 建议围绕约 ${target.target} 字设计场景密度，优先落在 ${target.min}-${target.max} 字；这是写作节奏参考，不是硬性截断线。`,
    `- 质量优先级高于机械字数：不得为了压字数省略关键动作、情绪转折、人物反应、因果交代或章节钩子。`,
    `- 如果内容自然超量，先判断是否把两章容量塞进了一章；能拆则在自然断点把支线、解释、余波或下一轮冲突留到下一章。`,
    `- 如果明显超量，请减少支线、旁白、重复描写或低效对白；不要压掉关键动作、人物反应和因果交代。`,
    `- 如果当前章核心动作无法安全拆分，可以略高于建议范围；但应减少重复描写、低效对白、纯旁白解释和无效支线。`,
    `- 硬边界参考：尽量不要低于 ${target.hardMin} 字，也不要超过 ${target.hardMax} 字；越界时优先调整场景容量，而不是强行草草收尾或灌水。`
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

  const isOpeningMetaLine = (line) => {
    const trimmed = line.trim()
    if (!trimmed) return true
    const withoutMarkdown = trimmed.replace(/^#{1,6}\s*/, '').trim()
    if (/^(以下是|下面是|正文如下|候选稿|章节正文)[：:]/.test(withoutMarkdown)) return true
    if (/^(?:正文|章节正文|候选正文)\s*[：:]\s*$/.test(withoutMarkdown)) return true
    return /^第\s*[\d一二三四五六七八九十百千万零〇两]+\s*章(?:\s*[：:、.\-—·]\s*.*|\s+\S{1,16})?$/.test(withoutMarkdown)
  }

  const lines = String(text)
    .replace(/^\s*```(?:markdown|md|text|txt)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .split('\n')

  let hasProseStarted = false
  return lines
    .filter(line => {
      const trimmed = line.trim()
      if (!hasProseStarted && isOpeningMetaLine(line)) return false
      if (trimmed) hasProseStarted = true
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
  if (/^[\u4e00-\u9fa5]{1,4}(?:在|被|把|将|让|向|从|给|对|随|带|进入|走进|回到|离开|看见|发现|听见|醒来)/.test(title)) return ''
  if (/[，。！？；：、,.!?;:]/.test(title)) return ''
  if (Array.from(title).length < 2 || Array.from(title).length > 10) return ''
  return title
}

export function buildChapterTitleSystemPrompt() {
  return `你是一位长篇小说编辑，擅长给网文连载章节命名。

命名原则：
- 章名要贴合本章核心动作、情绪或悬念。
- 章名是小说目录里的标题，不是剧情摘要，不要直接截取正文句子。
- 不要写成“主角名 + 在/被/把/进入/发现 + 地点或动作”的流水句。
- 不要剧透后续章节，不要泄露尚未揭开的终局真相。
- 不要使用泛泛的“风暴将至”“新的开始”等空标题。
- 标题应有画面感或钩子，但不要夸张营销腔。

输出要求：
- 只输出章名，不输出“第几章”、解释、引号、书名号、Markdown 或备选列表。
- 章名控制在 2-10 个汉字之间，优先使用名词短语、意象短语或悬念短语。`
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
  return `你是一位专业小说作者，擅长小说章节正文和长篇连载。

核心职责：
- 把已确认的世界规则、设定库、角色状态、上一章结尾和本章小纲当作创作边界。
- 在边界内写出具体场景：人物要行动、观察、误判、选择，并承担后果。
- 设定、真相和规则尽量通过证据、物件反应、行动失败、关系变化或付出代价自然显露。
- 对话要符合角色身份和关系，不要让所有人说成同一种声音。
- 可以补充细节、对白、过渡和合理意外，但不能无解释推翻已有事实。
- 写作标准是气质和方法，不是逐条打卡；明显模板句式和节奏问题会在生成后单独审稿或润色。

输出要求：
- 只输出小说正文，不输出标题、Markdown 标题、提纲、解释、创作说明或“以下是正文”等提示语。
- 不要输出“# 第N章”“第N章”“第十二章 章名”这类章节标题；章节标题由系统另行生成。
- 第一行直接进入正文叙事。
- 正文从本章小纲第一个节拍，或本章时间线最早的可写场景开始。
- 如果是第一章，从主角初始处境或创作种子的开局钩子开始。
- 按自然时间和因果顺序写场景，不要把结尾、设定说明、系统提示或任务奖励插入到开头。
- 系统提示、任务面板、弹窗等内容只能作为小说世界内角色实际看到或听到的内容出现。`
}

export function buildChapterPrompt(context) {
  const parts = []

  const bible = context.bible || {}
  const premise = bible.premise || context.premise
  const styleBible = bible.styleBible || context.styleBible
  const styleMethodBrief = context.styleMethodBrief || ''
  const styleStandardBrief = context.styleStandardBrief || bible.styleStandardBrief
  const worldRules = bible.worldRules || context.worldRules

  if (context.creativeBoundary) {
    parts.push(`## 本章创作边界摘要\n${context.creativeBoundary}`)
  } else {
    const boundaryLines = [
      premise ? `作品方向：${premise}` : '',
      worldRules ? `世界硬边界：${worldRules}` : ''
    ].filter(hasText)
    if (boundaryLines.length) parts.push(`## 本章创作边界摘要\n${boundaryLines.join('\n')}`)
  }

  const styleHints = [styleMethodBrief, !styleMethodBrief ? styleBible : '', !styleMethodBrief ? styleStandardBrief : '']
    .filter(hasText)
    .join('\n\n')
  if (styleHints) parts.push(`## 写作气质\n${styleHints}`)

  if (context.settingLibrary) parts.push(`## 关键设定边界\n${context.settingLibrary}`)
  if (context.recentSettingChanges) parts.push(`## 最近设定变化\n${context.recentSettingChanges}`)
  if (context.softCorrectionAims) parts.push(`## 软过渡提醒\n${context.softCorrectionAims}`)

  if (context.stateLedger) parts.push(`## 章节状态账本（硬状态优先）\n${context.stateLedger}`)

  const seedInfo = formatSeedContext(context.seed)
  if (seedInfo) parts.push(`## 创作种子\n${seedInfo}`)

  if (context.openingAnchor) {
    parts.push(`## 开局锚点（第一章优先执行）\n${context.openingAnchor}`)
  }

  const sequenceRules = formatSequenceRules(context.sequenceRules)
  if (sequenceRules) parts.push(`## 顺序控制\n${sequenceRules}`)

  const wordTarget = formatWordTarget(context.wordTarget)
  if (wordTarget) parts.push(`## 本章字数节奏（质量优先）\n${wordTarget}`)

  if (context.previousChapterEnding) {
    parts.push(`## 上一章结尾原文（下一章必须承接）
${context.previousChapterEnding}

承接要求：
- 如果这是第 2 章或后续章节，第一幕必须自然承接上一章结尾的情绪、危险、动作或悬念。
- 不要无提示地跳到全新地点、全新时间或无关日常；如必须转场，第一段要先完成上一章钩子的即时回应。
- 上一章结尾如果明显是未完成句、动作中断或危机未落地，本章开头必须先补足这个动作或危机，再进入本章小纲后续节拍。`)
  }

  const recentChapterEndings = formatRecentChapterEndings(context.recentChapterEndings)
  if (recentChapterEndings) {
    parts.push(`## 最近章节结尾（避免重复模板）
${recentChapterEndings}

结尾反复规避：
- 本章结尾不得复用最近章节的动作、意象或句式，不要连续用“抬头、转身、闭眼、握拳、走进黑暗、沉入黑暗、看天色、状态总结、内心独白收束”等模板。
- 结尾优先落在具体动作未完成、关系变化、物件状态、误判代价、选择余波或下一章问题上，不要只做抽象总结。
- 如果本章必须安静收束，也要换成具体的人物行为、物件细节或未被说出口的关系变化。`)
  }

  const volumeStage = formatVolumeStage(context.volumeStage)
  if (volumeStage) parts.push(`## 分卷阶段参考\n${volumeStage}`)

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

  parts.push(`## 硬连续性边界（不可违背）
- 承接上一章留下的动作、危险、承诺、伤势、物品状态和情绪余波。
- 新出现的关键线索、道具、钱款、身份、法器、能力或情报，要有来源、交接、发现过程或代价。
- 角色重大选择要来自当前欲望、压力、误判、利益牵引或关系变化。
- 使用伏笔或回收线索时，要来自此前信息、误导解除或本章先行证据。
- 如果剧情需要改变既有状态，在正文中写清因果，后续会进入设定或记忆提取。`)

  const beatPlan = formatChapterBeatPlan(context.beatPlan)
  if (beatPlan) {
    parts.push(`## 已确认本章小纲（优先执行）
${beatPlan}

执行要求：
- 按小纲的自然时间和因果顺序展开成正文。
- 第一幕对应小纲第一个可写场景，不先写后续结论、余波或复盘。
- 小纲是方向，不是模板；可以补充过渡、细节、对白和合理意外。
- 核心因果、人物目标和本章必须完成的剧情推进不能丢。
- 不要把小纲条目、编号或分析文字写进正文。`)
  }

  parts.push(`## 写作质量方向
- 先让人物在场景里行动、观察、犹豫、误判和付出代价，再让读者从结果中理解设定。
- 本章聚焦一个最关键的人物压力：他想要什么、怕失去什么、为什么此刻必须选择。
- 信息释放尽量落在证据、失败尝试、道具反应、关系变化或行动后果上。
- 信息揭示方式优先靠证据、动作失败、物件反应和人物选择，不要集中解释设定。
- 人性变化不能写成开关；情绪、信任、恐惧、爱恨和立场变化要有迟疑、残留习惯、反复或自我辩解。
- 配角自主性要留一点：关键配角可以有自己的小目标、口头习惯、误判或生活痕迹，不只负责解释和推动剧情。
- 可以保留少量生活痕迹、口头习惯、迟疑和沉默，让人物不像只为剧情服务。
- 输出前静默自检：结尾模板、工具人、信息倾倒和段首重复点名如果明显出现，先在正文内部自然调整。
- 这些是写作方向，不是检查清单；自然叙事优先，生成后会另行审稿和润色。`)

  parts.push(`## 写作任务
请撰写第 ${context.chapterNum || '?'} 章正文。
${context.instruction ? `特别要求：${context.instruction}\n` : ''}如果没有可见小纲，请先在心中按自然时间顺序排好本章场景，但不要输出小纲。
请直接输出正文，不要输出标题、Markdown 标题、“# 第N章”“第N章”和解释。`)

  return parts.join('\n\n')
}

export function buildProseRhythmRepairSystemPrompt() {
  return `你是长篇小说正文节奏修订编辑。任务是修正文稿中过密的短句独立段落、机械化“不是X，是Y”句式、段首重复点名和碎片化分镜感。
硬性原则：
- 只做句式节奏和段落组织修订，不要新增剧情、人物、道具、设定、结论或伏笔。
- 保留原文事件顺序、人物选择、因果关系、对白含义、结尾钩子和已确认设定。
- 常规叙事段落应自然合并为 2-5 句，包含动作因果、感官连续、人物观察和情绪余波。
- 短句可以保留，但只能用于局部爆点、恐惧、断裂、反转或停顿；不要连续一行一句。
- 去掉高频 AI 腔：减少“不是X，是Y/而是Y”“某种”“像是又像是”等模板句。
- 降低段首重复点名：不要连续多段都以同一个主角姓名开头；能承接时改用动作、物件、环境、感官、对白、心理余波或代词起段，必要时才点名。
- 输出完整正文，不要输出修改说明、标题、Markdown 小纲或 JSON。`
}

export function buildProseRhythmRepairPrompt({ chapterNum, content, analysis, beatPlan, context } = {}) {
  const report = formatProseRhythmAnalysis(analysis)
  const contextHints = [
    context?.styleBible ? `风格要求：${context.styleBible}` : '',
    context?.styleStandardBrief ? `题材/风格标准：\n${context.styleStandardBrief}` : '',
    context?.stateLedger ? `章节状态账本：\n${context.stateLedger}` : '',
    beatPlan ? `本章小纲：\n${formatChapterBeatPlan(beatPlan)}` : ''
  ].filter(hasText).join('\n\n')

  return `请对第 ${chapterNum || '?'} 章正文做一次“句式节奏修订”。

## 当前节奏问题
${report || '检测到连续短句或 AI 腔句式偏多。'}

## 修订目标
- 保留全部剧情事实，不要新增剧情，不要删掉关键动作、选择、代价和结尾钩子。
- 把连续短句独立段落合并为自然叙事段落；常规推进段落尽量 2-5 句。
- 允许保留少量短句作为局部节奏点，但不要形成连续短句堆叠。
- 把机械句式改为具体动作、感官、物象、对白停顿或人物反应。
- 调整段首重复点名：避免多段连续或高频使用同一个角色姓名起段，改用动作承接、物件状态、环境变化、感官细节、对白或代词起段；不要因此改变视角归属。
- 修订后长度应接近原文，允许轻微浮动，不要大幅扩写或压缩。
- 只输出修订后的完整正文，不要输出解释。

${contextHints ? `## 参考约束\n${contextHints}\n\n` : ''}## 待修订正文
${content || ''}`
}

export function buildChapterBeatSystemPrompt() {
  return `你是一位长篇小说章节策划，负责在正式写正文前设计可执行的小纲。

你的任务是规划本章路线，不是写正文，也不是审稿。

规划原则：
- 小纲只锁定关键场景、冲突、信息释放和结尾钩子。
- 已确认事实、角色状态、上一章结尾和世界规则是边界。
- 第一条节拍必须是读者真正看到的开场场景。
- 给正文保留对白、细节、动作和临场发挥空间。

输出要求：
- 只输出章前小纲，不输出小说正文。
- 使用清晰 Markdown，便于用户编辑。
- 小纲总长度控制在 700-1100 字，节拍控制在 4-6 条。
- 不输出 JSON，不输出解释性废话。`
}

export function buildChapterBeatPrompt(context) {
  const parts = []
  const bible = context.bible || {}
  const premise = bible.premise || context.premise
  const styleBible = bible.styleBible || context.styleBible
  const styleStandardBrief = context.styleStandardBrief || bible.styleStandardBrief
  const worldRules = bible.worldRules || context.worldRules
  const forbiddenDirections = bible.forbiddenDirections || context.forbiddenDirections

  if (premise) parts.push(`## 作品定位\n${premise}`)
  if (styleBible || styleStandardBrief) {
    parts.push(`## 写作气质参考\n${[styleBible, styleStandardBrief].filter(hasText).join('\n\n')}`)
  }
  if (worldRules) parts.push(`## 世界规则（硬边界）\n${worldRules}`)
  if (context.settingLibrary) parts.push(`## 设定库摘要（硬边界）\n${context.settingLibrary}`)
  if (context.stateLedger) parts.push(`## 章节状态账本（硬边界）\n${context.stateLedger}`)

  if (context.previousChapterEnding) {
    parts.push(`## 上一章结尾（本章开场要承接）\n${context.previousChapterEnding}`)
  }

  const chapterGoal = formatChapterGoal(context.chapterGoal)
  if (chapterGoal) parts.push(`## 本章目标\n${chapterGoal}`)

  const nearOutline = formatNearOutline(context.nearOutline)
  if (nearOutline) parts.push(`## 近景滚动规划（参考，不要逐条照抄）\n${nearOutline}`)

  const volumeStage = formatVolumeStage(context.volumeStage)
  if (volumeStage) parts.push(`## 分卷阶段上下文\n${volumeStage}`)

  if (context.recentSummaries?.length) {
    parts.push(`## 前情摘要\n${context.recentSummaries.map(s => `- 第${s.chapterNum}章：${s.summary}`).join('\n')}`)
  }

  if (context.recentFacts) parts.push(`## 已确认事实\n${context.recentFacts}`)
  if (context.activeCorrectionTasks) parts.push(`## 未完成纠偏提醒（只处理会影响本章的硬问题）\n${context.activeCorrectionTasks}`)
  if (forbiddenDirections?.length) parts.push(`## 禁止方向\n${formatList(forbiddenDirections)}`)

  return `${parts.join('\n\n')}

## 规划任务
请为第 ${context.chapterNum || '?'} 章生成“正式写作前确认的小纲”。

${context.wordTarget?.target ? `本章按约 ${context.wordTarget.target} 字体量设计，优先服务 ${context.wordTarget.min}-${context.wordTarget.max} 字正文；不要规划成两章内容，把后续冲突或余波留到下一章。` : ''}

请按以下格式输出：

### 本章一句话目标
- 本章要让读者看到什么变化：

### 必须承接
- 上一章留下的动作、情绪、危险、物件或关系：
- 本章不能写错的硬状态：

### 本章节拍
1. [开场牵引] ...
2. [目标浮现] ...
3. [冲突升级] ...
4. [信息释放或误判解除] ...
5. [人物选择/转折代价] ...
6. [可选：余波或钩子] ...

### 暂不解决
- 本章只露出、不解释透的秘密或矛盾：

### 可发散空间
- 正文生成时可以自由发挥的细节、场景、对白或意外。

### 结尾钩子
- 结尾形态：动作未完成 / 关系变化 / 物件状态改变 / 误判代价 / 下一章问题（任选其一，不要抽象总结）
- 本章结尾落点：
- 留给下一章的具体动作、关系变化、物件状态或问题：

要求：
- 节拍按自然时间和因果顺序排列。
- 第一条是正文第一幕，不要从后续会议、事后追查、伤亡结果或已经发生后的复盘开始。
- 如果这是第 1 章，第一条必须来自开局锚点、创作种子或主角初始处境。
- 每个节拍都要能转化为正文场景，不要写抽象口号。
- 每个关键节拍写清“发生什么”和“为什么推动故事”。
- 小纲只锁定关键路线，不规定具体句子和全部动作。
- 小纲总长度控制在 700-1100 字。
- 节拍控制在 4-6 条。
- 本章结尾应是自然小钩子，可以留下动作、关系、物件或问题，不要写成抽象总结。
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
    context.styleStandardBrief ? `题材/风格标准：\n${context.styleStandardBrief}` : '',
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
${context.styleStandardBrief ? `## 题材/风格标准\n${context.styleStandardBrief}\n` : ''}

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
