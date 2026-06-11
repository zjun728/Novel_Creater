import {
  correctionTaskMode,
  isCorrectionTaskActiveForContext,
  isCorrectionTaskBlockingForGeneration
} from './correctionTaskRules.js'
import { formatWritingStyleStandardsForPrompt } from '../data/writingStyleStandards.js'
import { buildChapterStateLedger } from './chapterStateLedger.js'

/**
 * 上下文构建器
 *
 * 根据不同任务类型，按优先级构建 AI 上下文。
 * 不是机械塞入所有资料，而是根据任务和 token 预算选择内容。
 * 低优先级内容在超出预算时会被摘要压缩或直接跳过。
 */

// 粗略 token 估计
export function estimateTokens(text) {
  if (!text) return 0
  if (typeof text !== 'string') text = JSON.stringify(text)
  const chineseChars = (text.match(/[一-鿿]/g) || []).length
  const otherChars = text.length - chineseChars
  return Math.ceil(chineseChars * 0.5 + otherChars * 0.25)
}

function compactText(value, limit = 240) {
  const text = typeof value === 'string' ? value : JSON.stringify(value || '')
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (!normalized) return ''
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized
}

function buildCreativeBoundary({ bible, outline, volumeContext } = {}) {
  const lines = []
  if (bible?.premise) lines.push(`作品方向：${compactText(bible.premise, 220)}`)
  if (bible?.worldRules) lines.push(`世界硬边界：${compactText(bible.worldRules, 260)}`)
  if (volumeContext?.coreGoal || volumeContext?.mainConflict) {
    lines.push(`当前阶段压力：${compactText([volumeContext.coreGoal, volumeContext.mainConflict].filter(Boolean).join('；'), 260)}`)
  } else if (outline?.currentVolume) {
    lines.push(`当前卷压力：${compactText([outline.currentVolume.goal, outline.currentVolume.mainConflict].filter(Boolean).join('；'), 220)}`)
  }
  return lines.join('\n')
}

function buildStyleMethodBrief(styleBible, styleStandardBrief) {
  const style = compactText(styleBible, 220)
  const standard = compactText(styleStandardBrief, 260)
  if (style && standard) return `本书风格：${style}\n写作方法参考：${standard}`
  if (style) return `本书风格：${style}`
  if (standard) return `写作方法参考：${standard}`
  return ''
}

// 默认 token 预算分配
const BUDGETS = {
  writing: 12000,    // 正文生成
  brainstorm: 4000,  // 脑洞发散
  audit: 16000,      // 审稿（需要全文+全量记忆）
  summary: 8000,     // 摘要
  extraction: 8000,  // 事实提取
  outline: 8000,     // 大纲
}

/**
 * 上下文添加器：按优先级填充，超出预算则跳过低优项
 */
class ContextBuilder {
  constructor(maxTokens = 12000) {
    this.maxTokens = maxTokens
    this.context = {}
    this.usedTokens = 0
  }

  /**
   * 尝试添加一个上下文项
   * @param {string} key
   * @param {*} value - 原始值
   * @param {object} options
   * @param {number} options.priority - 优先级 1-10，越低越重要
   * @param {boolean} options.required - 是否必须包含（即使超出预算）
   * @param {number} options.maxTokens - 该项的最大 token 预算
   * @param {function} options.summarize - 超预算时的压缩函数
   */
  add(key, value, options = {}) {
    const { priority = 5, required = false, maxTokens: itemMax, summarize } = options
    if (value == null || value === '' || (Array.isArray(value) && value.length === 0)) return

    let text = typeof value === 'string' ? value : JSON.stringify(value)
    let tokenCost = estimateTokens(text)

    // 如果该项有 token 上限，裁剪
    if (itemMax && tokenCost > itemMax) {
      if (summarize) {
        text = summarize(value, itemMax)
        tokenCost = estimateTokens(text)
      } else {
        text = text.slice(0, Math.floor(itemMax * 2)) // 粗略裁剪
        tokenCost = itemMax
      }
    }

    // 非必须项超出剩余预算时跳过
    if (!required && this.usedTokens + tokenCost > this.maxTokens) {
      return
    }

    this.context[key] = typeof value === 'string' ? text : value
    this.usedTokens += tokenCost
  }

  getContext() {
    return this.context
  }

  getUsedTokens() {
    return this.usedTokens
  }
}

function normalizeThreadLabel(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  return text.startsWith('#') ? text : `#${text.replace(/^#+/, '')}`
}

function normalizeThreadList(value) {
  if (Array.isArray(value)) return value.map(normalizeThreadLabel).filter(Boolean)
  if (typeof value === 'string') return value.split(/\n|；|;|,|，/).map(normalizeThreadLabel).filter(Boolean)
  return []
}

function addThreadKeywordLabels(text, labels) {
  const source = String(text || '')
  if (/身世|血脉|父亲|母亲|家族|来历|真相/.test(source)) labels.add('#主角身世线')
  if (/女主|她|少女|妻|恋|情感|感情|羁绊/.test(source)) labels.add('#女主秘密线')
  if (/反派|阴谋|幕后|组织|追杀|内鬼|背叛/.test(source)) labels.add('#反派阴谋线')
  if (/道具|钥匙|令牌|碎片|法宝|武器|遗物|信物/.test(source)) labels.add('#关键道具线')
  if (/功法|境界|修为|代价|系统|能力|规则/.test(source)) labels.add('#功法代价线')
  if (/宗门|家族|朝堂|势力|盟约|战争|派系/.test(source)) labels.add('#势力斗争线')
}

function collectThreadLabels({ plotThreads = [], nearChapter = null, outline = null, volumeContext = null } = {}) {
  const labels = new Set()
  const activeThreads = (plotThreads || []).filter(thread =>
    ['planted', 'developing', 'active', 'accepted', 'in_progress'].includes(thread?.status || 'developing')
  )

  const planningText = JSON.stringify({
    nearChapter,
    nearChapters: outline?.nearChapters,
    currentVolume: outline?.currentVolume,
    volumeContext
  })

  for (const thread of activeThreads) {
    if (!threadMatchesFocus(thread, { text: planningText })) continue
    const title = thread?.title || thread?.name
    if (title) labels.add(normalizeThreadLabel(title))
    for (const tag of normalizeThreadList(thread?.tags || thread?.threadTags || thread?.relatedPlotThreads)) {
      labels.add(tag)
    }
  }

  addThreadKeywordLabels(planningText, labels)

  return labels
}

function buildContextFocus({ chapterNum, nearChapter, outline, volumeContext, plotThreads = [], settingEntities = [] } = {}) {
  const text = [
    chapterNum ? `chapter:${chapterNum}` : '',
    nearChapter?.title,
    nearChapter?.goal,
    nearChapter?.conflict,
    nearChapter?.turn,
    nearChapter?.emotionalBeat,
    outline?.currentVolume?.title,
    outline?.currentVolume?.goal,
    outline?.currentVolume?.mainConflict,
    volumeContext?.title,
    volumeContext?.coreGoal,
    volumeContext?.mainConflict,
    volumeContext?.currentSummary,
    volumeContext?.stageSummary,
    ...(volumeContext?.keyCharacters || []),
    ...(volumeContext?.completedBeats || []),
    ...(volumeContext?.openQuestions || []),
    ...(volumeContext?.handoffToNext || []),
    ...(volumeContext?.continuityNotes || [])
  ].map(value => typeof value === 'string' ? value : JSON.stringify(value || '')).filter(Boolean).join('\n')

  const keywords = extractFocusKeywords(text)
  const threadLabels = collectThreadLabels({ plotThreads, nearChapter, outline, volumeContext })
  const focus = { text, keywords, threadLabels, entityNames: new Set() }

  for (const entity of settingEntities || []) {
    if ((entity?.status || 'active') !== 'active') continue
    if (!entityMatchesFocus(entity, focus) && !alwaysCarryEntity(entity)) continue
    const aliases = Array.isArray(entity?.aliases) ? entity.aliases : []
    for (const name of [entity?.name, ...aliases]) {
      if (String(name || '').trim()) focus.entityNames.add(String(name).trim())
    }
  }

  return focus
}

function extractFocusKeywords(text) {
  const source = String(text || '')
  const tokens = new Set()
  const matches = source.match(/[#A-Za-z0-9_\u4e00-\u9fa5·-]{2,24}/g) || []
  for (const raw of matches) {
    const token = raw.replace(/^[,，。；;：:\s]+|[,，。；;：:\s]+$/g, '').trim()
    if (token.length < 2) continue
    if (/^(chapter|goal|title|conflict|turn)$/i.test(token)) continue
    tokens.add(token)
  }
  return tokens
}

function focusHasText(focus, value) {
  const text = String(value || '').trim()
  if (!text) return false
  return String(focus?.text || '').includes(text)
}

function textMatchesFocus(text, focus) {
  const source = String(text || '')
  if (!source.trim()) return false
  if (!focus?.text && !focus?.keywords?.size && !focus?.threadLabels?.size && !focus?.entityNames?.size) return true
  if (focus?.entityNames) {
    for (const name of focus.entityNames) {
      if (String(name || '').length >= 2 && source.includes(name)) return true
    }
  }
  if (focus?.keywords) {
    for (const keyword of focus.keywords) {
      if (keyword.length >= 2 && source.includes(keyword)) return true
    }
  }
  if (focus?.threadLabels) {
    for (const label of focus.threadLabels) {
      const clean = String(label || '').replace(/^#/, '')
      if (clean && source.includes(clean)) return true
    }
  }
  return false
}

function entityMatchesFocus(entity, focus) {
  if (!focus?.text && !focus?.keywords?.size) return true
  const profile = entity?.profile || {}
  const aliases = Array.isArray(entity?.aliases) ? entity.aliases : []
  const names = [entity?.name, ...aliases].filter(Boolean)
  if (names.some(name => focusHasText(focus, name))) return true
  if (Array.isArray(entity?.tags) && entity.tags.some(tag => textMatchesFocus(tag, focus))) return true
  const profileText = Object.values(profile).map(value => typeof value === 'string' ? value : JSON.stringify(value || '')).join('\n')
  return textMatchesFocus(profileText, focus)
}

function alwaysCarryEntity(entity) {
  const category = String(entity?.category || '')
  const summary = String(entity?.summary || '')
  const importance = Number(entity?.importance || 0)
  return importance >= 10 && /主角|protagonist|核心/.test(`${category}\n${summary}`)
}

function settingChangeMatchesFocus(event, focus) {
  if (!focus?.text && !focus?.keywords?.size) return true
  const text = [
    event?.entityName,
    event?.targetEntityName,
    event?.fieldPath,
    event?.changeType,
    event?.newValue,
    event?.summary,
    event?.content
  ].filter(Boolean).join('\n')
  return textMatchesFocus(text, focus)
}

function factMatchesFocus(fact, focus) {
  if (!focus?.text && !focus?.keywords?.size && !focus?.threadLabels?.size && !focus?.entityNames?.size) return true
  const factTags = normalizeThreadList(fact?.relatedPlotThreads || fact?.related_plot_threads || fact?.threadTags || fact?.tags)
  if (factTags.length && focus?.threadLabels?.size && factTags.some(tag => focus.threadLabels.has(tag))) return true
  const text = [fact?.content, fact?.summary, fact?.fact, fact?.factType, fact?.fact_type].filter(Boolean).join('\n')
  return textMatchesFocus(text, focus)
}

function threadMatchesFocus(thread, focus) {
  if (!focus?.text && !focus?.keywords?.size && !focus?.threadLabels?.size) return true
  const title = thread?.title || thread?.name || ''
  const tags = normalizeThreadList(thread?.tags || thread?.threadTags || thread?.relatedPlotThreads)
  if (title && focusHasText(focus, title)) return true
  if (tags.some(tag => focus?.threadLabels?.has(tag) || focusHasText(focus, tag.replace(/^#/, '')))) return true
  const text = [title, thread?.content, thread?.summary, thread?.description, ...tags].filter(Boolean).join('\n')
  return textMatchesFocus(text, focus)
}

function summarizeThreadFacts(canonFacts = [], plotThreads = [], options = {}) {
  const labels = options.focus?.threadLabels || collectThreadLabels({
    plotThreads,
    nearChapter: options.nearChapter,
    outline: options.outline,
    volumeContext: options.volumeContext
  })

  const acceptedTaggedFacts = (canonFacts || [])
    .filter(fact => (fact?.status || 'accepted') === 'accepted')
    .map(fact => ({
      fact,
      tags: normalizeThreadList(fact?.relatedPlotThreads || fact?.related_plot_threads || fact?.threadTags || fact?.tags)
    }))
    .filter(item => item.tags.length)

  if (!acceptedTaggedFacts.length) return ''

  let selected = acceptedTaggedFacts.filter(item => {
    if (labels.size && item.tags.some(tag => labels.has(tag))) return true
    return factMatchesFocus(item.fact, options.focus)
  })

  if (!selected.length && !options.focus?.text) {
    selected = acceptedTaggedFacts.slice(-12)
  }

  return selected
    .slice(-24)
    .map(({ fact, tags }) => `${tags.join(' ')} [${fact.factType || fact.fact_type || 'plot'}] ${fact.content || fact.summary || fact.fact || ''}`)
    .filter(Boolean)
    .join('\n')
}

// === 正文生成上下文 ===
export function buildWritingContext(novelStore, chapterNum, maxTokens, settingStore = null, volumeStore = null, correctionTaskStore = null) {
  const builder = new ContextBuilder(maxTokens || BUDGETS.writing)
  const bible = novelStore.bible?.value || novelStore.bible
  const outline = novelStore.outline?.value || novelStore.outline
  const characters = novelStore.characters?.value || novelStore.characters || []
  const plotThreads = novelStore.plotThreads?.value || novelStore.plotThreads || []
  const canonFacts = novelStore.canonFacts?.value || novelStore.canonFacts || []
  const settingEntities = settingStore?.entities?.value || settingStore?.entities || []
  const settingRelations = settingStore?.relations?.value || settingStore?.relations || []
  const settingChangeEvents = settingStore?.changeEvents?.value || settingStore?.changeEvents || []
  const volumes = volumeStore?.volumes?.value || volumeStore?.volumes || []
  const correctionTasks = getContextCorrectionTasks(correctionTaskStore)

  // P1: 本章目标（必须）
  const nearChapter = outline?.nearChapters?.find(n => n.chapterNum === chapterNum)
  if (nearChapter) {
    builder.add('chapterGoal', {
      title: nearChapter.title,
      goal: nearChapter.goal,
      conflict: nearChapter.conflict,
      turn: nearChapter.turn,
      emotionalBeat: nearChapter.emotionalBeat
    }, { priority: 1, required: true })
  }

  // P1.5: 分卷阶段上下文（长篇连续创作的中间锚点）
  const volumeContext = buildVolumeStageContext(volumes, chapterNum)
  const contextFocus = buildContextFocus({ chapterNum, nearChapter, outline, volumeContext, plotThreads, settingEntities })
  const creativeBoundary = buildCreativeBoundary({ bible, outline, volumeContext })
  if (creativeBoundary) {
    builder.add('creativeBoundary', creativeBoundary, { priority: 1, required: true, maxTokens: 650 })
  }

  if (bible?.premise) {
    builder.add('premise', bible.premise, { priority: 3, maxTokens: 300 })
  }

  if (volumeContext) {
    builder.add('volumeStage', volumeContext, { priority: 5, maxTokens: 800 })
  }

  // P2: 当前卷信息
  if (outline?.currentVolume) {
    builder.add('currentVolume', outline.currentVolume, { priority: 5, maxTokens: 500 })
  }

  // P3: 近景大纲
  if (outline?.nearChapters?.length) {
    builder.add('nearOutline', outline.nearChapters.filter(n => n.chapterNum >= chapterNum), { priority: 2, maxTokens: 800 })
  }

  // P4: 世界规则摘要
  if (bible?.worldRules) {
    builder.add('worldRules', bible.worldRules, { priority: 5, maxTokens: 500 })
  }

  // P5: 禁止方向
  if (bible?.forbiddenDirections?.length) {
    builder.add('forbiddenDirections', bible.forbiddenDirections, { priority: 2, maxTokens: 300 })
  }

  // P6: 风格要求
  if (bible?.styleBible) {
    builder.add('styleBible', bible.styleBible, { priority: 5, maxTokens: 320 })
  }

  const styleStandardBrief = formatWritingStyleStandardsForPrompt(bible?.writingProfile)
  const styleMethodBrief = buildStyleMethodBrief(bible?.styleBible, styleStandardBrief)
  if (styleMethodBrief) {
    builder.add('styleMethodBrief', styleMethodBrief, { priority: 3, maxTokens: 420 })
  }
  if (styleStandardBrief) {
    builder.add('styleStandardBrief', styleStandardBrief, { priority: 7, maxTokens: 320 })
  }

  // P6.5: 结构化设定库，优先注入与本章/分卷相关的实体和关系
  const settingLibrary = summarizeSettingLibrary(settingEntities, settingRelations, {
    chapterNum,
    nearChapter,
    volumeContext,
    settingChangeEvents,
    focus: contextFocus
  })
  if (settingLibrary) {
    builder.add('settingLibrary', settingLibrary, { priority: 3, maxTokens: 1900 })
  }

  const recentSettingChanges = summarizeSettingChanges(settingChangeEvents, chapterNum, contextFocus)
  if (recentSettingChanges) {
    builder.add('recentSettingChanges', recentSettingChanges, { priority: 4, maxTokens: 650 })
  }

  const stateLedger = buildChapterStateLedger({
    chapterNum,
    settingEntities,
    settingChangeEvents,
    canonFacts,
    focus: contextFocus
  })
  if (stateLedger) {
    builder.add('stateLedger', stateLedger, { priority: 2, required: true, maxTokens: 1400 })
  }

  const activeCorrectionTasks = summarizeCorrectionTasks(correctionTasks, chapterNum, contextFocus)
  if (activeCorrectionTasks) {
    builder.add('softCorrectionAims', activeCorrectionTasks, { priority: 6, maxTokens: 420 })
  }

  const threadFacts = summarizeThreadFacts(canonFacts, plotThreads, {
    nearChapter,
    outline,
    volumeContext,
    focus: contextFocus
  })
  if (threadFacts) {
    builder.add('threadFacts', threadFacts, { priority: 4, maxTokens: 900 })
  }

  // P7: 主要角色状态
  const keyChars = characters.filter(c =>
    c.role === 'protagonist' || c.role === 'antagonist' ||
    c.hardState?.location || c.softState?.emotion
  )
  if (keyChars.length > 0) {
    const simplified = keyChars.map(c => ({
      name: c.name,
      role: c.role,
      personality: c.personality,
      desire: c.desire,
      fear: c.fear,
      location: c.hardState?.location,
      physicalStatus: c.hardState?.physicalStatus,
      emotion: c.softState?.emotion,
      currentDesire: c.softState?.currentDesire
    }))
    builder.add('characters', simplified, { priority: 4, maxTokens: 1000 })
  }

  // P8: 最近已确认事实
  const recentFacts = summarizeRecentFacts(canonFacts, chapterNum, contextFocus)
  if (recentFacts.length > 0) {
    const summary = recentFacts.map(f => `[${f.factType || f.fact_type || 'fact'}] ${f.content || f.summary || f.fact || ''}`).join('\n')
    builder.add('recentFacts', summary, { priority: 5, maxTokens: 900 })
  }

  // P9: 进行中的伏笔
  const activeThreads = plotThreads
    .filter(t => t.status === 'planted' || t.status === 'developing')
    .filter(t => threadMatchesFocus(t, contextFocus))
  if (activeThreads.length > 0) {
    const threadSummary = activeThreads.map(t => `${t.title}: ${t.content}`).join('\n')
    builder.add('plotThreads', threadSummary, { priority: 6, maxTokens: 800 })
  }

  // P10: 角色关系
  const relationChars = characters.filter(c => c.relationshipNotes)
  if (relationChars.length > 0) {
    const relSummary = relationChars.map(c => `${c.name}: ${c.relationshipNotes}`).join('\n')
    builder.add('relationships', relSummary, { priority: 7, maxTokens: 500 })
  }

  // 额外：传入当前草稿（由调用者提供）
  return {
    context: builder.getContext(),
    usedTokens: builder.getUsedTokens(),
    maxTokens: builder.maxTokens
  }
}

function summarizeSettingLibrary(entities, relations, options = {}) {
  const { chapterNum, nearChapter, volumeContext, settingChangeEvents, focus } = options
  const scoredEntities = (entities || [])
    .filter(e => (e.status || 'active') === 'active')
    .map(entity => ({
      entity,
      relevance: scoreSettingEntity(entity, {
        chapterNum,
        nearChapter,
        volumeContext,
        settingChangeEvents
      })
    }))
    .sort((a, b) => b.relevance - a.relevance || Number(b.entity.importance || 3) - Number(a.entity.importance || 3))

  let activeEntities = scoredEntities
    .filter(item => {
      const hasFocusedContext = Boolean(focus?.keywords?.size || focus?.threadLabels?.size || focus?.entityNames?.size)
      if (!hasFocusedContext) return item.relevance >= 22 || entityMatchesFocus(item.entity, focus) || alwaysCarryEntity(item.entity)
      return entityMatchesFocus(item.entity, focus) || alwaysCarryEntity(item.entity)
    })
    .slice(0, 24)
    .map(item => item.entity)

  if (!activeEntities.length && !(focus?.keywords?.size || focus?.threadLabels?.size || focus?.entityNames?.size)) {
    activeEntities = scoredEntities.slice(0, 12).map(item => item.entity)
  }

  if (!activeEntities.length) return ''

  const entityMap = new Map((entities || []).map(e => [e.id, e]))
  const lines = activeEntities.map(entity => {
    const profile = entity.profile || {}
    const facts = pickProfileFacts(entity.entityType, profile)
    const tags = entity.tags?.length ? `；标签：${entity.tags.join('、')}` : ''
    const aliases = entity.aliases?.length ? `；别名：${entity.aliases.join('、')}` : ''
    return `- [${settingTypeLabel(entity.entityType)}] ${entity.name}${entity.category ? `（${entity.category}）` : ''}：${entity.summary || '无概要'}${facts ? `；${facts}` : ''}${aliases}${tags}`
  })

  const selectedIds = new Set(activeEntities.map(entity => entity.id))
  const relationLines = (relations || [])
    .filter(r => {
      if (r.status === 'archived') return false
      const bothSelected = selectedIds.has(r.sourceEntityId) && selectedIds.has(r.targetEntityId)
      return bothSelected
    })
    .map(relation => ({
      relation,
      relevance: scoreSettingRelation(relation, selectedIds, entityMap)
    }))
    .sort((a, b) => b.relevance - a.relevance)
    .slice(0, 24)
    .map(({ relation: r }) => {
      const source = entityMap.get(r.sourceEntityId)?.name || '未知'
      const target = entityMap.get(r.targetEntityId)?.name || '未知'
      return `- ${source} -> ${r.relationType || '关系'} -> ${target}${r.stance ? `（${r.stance}）` : ''}：${r.summary || '无说明'}`
    })

  return [
    '### 关键实体',
    lines.join('\n'),
    relationLines.length ? `\n### 关键关系\n${relationLines.join('\n')}` : ''
  ].filter(Boolean).join('\n')
}

function scoreSettingEntity(entity, context) {
  const profile = entity.profile || {}
  const chapterNum = Number(context.chapterNum || 0)
  const name = String(entity.name || '').trim()
  const category = String(entity.category || '')
  const summary = String(entity.summary || '')
  const aliases = Array.isArray(entity.aliases) ? entity.aliases : []
  const tags = Array.isArray(entity.tags) ? entity.tags : []
  const searchableNames = [name, ...aliases].filter(Boolean)
  const currentTexts = [
    context.nearChapter?.title,
    context.nearChapter?.goal,
    context.nearChapter?.conflict,
    context.nearChapter?.turn,
    context.nearChapter?.emotionalBeat,
    context.volumeContext?.coreGoal,
    context.volumeContext?.mainConflict,
    context.volumeContext?.currentSummary,
    context.volumeContext?.stageSummary,
    ...(context.volumeContext?.keyCharacters || []),
    ...(context.volumeContext?.completedBeats || []),
    ...(context.volumeContext?.openQuestions || []),
    ...(context.volumeContext?.handoffToNext || []),
    ...(context.volumeContext?.continuityNotes || [])
  ].map(value => typeof value === 'string' ? value : JSON.stringify(value || ''))

  let score = Number(entity.importance || 3) * 2
  if (searchableNames.some(item => containsAny(currentTexts, item))) score += 18
  if ((context.volumeContext?.keyCharacters || []).some(item => item === name || aliases.includes(item))) score += 16

  const firstChapter = Number(entity.firstChapter || 0)
  const lastChapter = Number(entity.lastChapter || 0)
  if (chapterNum && firstChapter && Math.abs(firstChapter - chapterNum) <= 3) score += 6
  if (chapterNum && lastChapter && Math.abs(lastChapter - chapterNum) <= 8) score += 10
  if (chapterNum && firstChapter && firstChapter <= chapterNum && (!lastChapter || lastChapter >= chapterNum - 12)) score += 4

  const recentChanges = (context.settingChangeEvents || [])
    .filter(event => event.status === 'accepted')
    .filter(event => !chapterNum || !event.chapterNum || Number(event.chapterNum) <= chapterNum)
    .filter(event => event.entityId === entity.id || event.entityName === name)
    .sort((a, b) => Number(b.chapterNum || 0) - Number(a.chapterNum || 0))
  if (recentChanges[0]) {
    const distance = chapterNum - Number(recentChanges[0].chapterNum || chapterNum)
    score += distance <= 3 ? 12 : distance <= 10 ? 8 : 4
  }

  if (profile.location && containsAny(currentTexts, profile.location)) score += 8
  if (profile.faction && containsAny(currentTexts, profile.faction)) score += 6
  if (profile.sect && containsAny(currentTexts, profile.sect)) score += 6
  if (profile.owner && containsAny(currentTexts, profile.owner)) score += 6
  if (category && containsAny(currentTexts, category)) score += 3
  if (tags.some(tag => containsAny(currentTexts, tag))) score += 3
  if (summary && searchableNames.some(item => summary.includes(item))) score += 1

  return score
}

function scoreSettingRelation(relation, selectedIds, entityMap) {
  let score = 0
  if (selectedIds.has(relation.sourceEntityId)) score += 8
  if (selectedIds.has(relation.targetEntityId)) score += 8
  if (selectedIds.has(relation.sourceEntityId) && selectedIds.has(relation.targetEntityId)) score += 8
  const sourceImportance = Number(entityMap.get(relation.sourceEntityId)?.importance || 0)
  const targetImportance = Number(entityMap.get(relation.targetEntityId)?.importance || 0)
  score += sourceImportance + targetImportance
  if (relation.status === 'active') score += 2
  return score
}

function containsAny(texts, needle) {
  const value = String(needle || '').trim()
  if (!value) return false
  return (texts || []).some(text => String(text || '').includes(value))
}

function summarizeSettingChanges(events, chapterNum, focus = null) {
  const recent = (events || [])
    .filter(e => e.status === 'accepted')
    .filter(e => !chapterNum || !e.chapterNum || e.chapterNum <= chapterNum)
    .filter(e => settingChangeMatchesFocus(e, focus))
    .sort((a, b) => Number(b.chapterNum || 0) - Number(a.chapterNum || 0))
    .slice(0, 8)

  if (!recent.length) return ''
  return recent.map(e =>
    `- 第${e.chapterNum || '?'}章：${e.entityName || settingTypeLabel(e.entityType)} 的 ${e.fieldPath || e.changeType || '设定'} 变为「${e.newValue || ''}」`
  ).join('\n')
}

function summarizeRecentFacts(canonFacts, chapterNum, focus = null) {
  const accepted = (canonFacts || [])
    .filter(f => (f.status || 'accepted') === 'accepted')
    .filter(f => {
      const factChapter = Number(f.chapterNum || f.chapter_num || 0)
      return !chapterNum || !factChapter || factChapter <= Number(chapterNum)
    })

  let selected = accepted.filter(f => factMatchesFocus(f, focus))
  if (!selected.length && !focus?.text) selected = accepted

  return selected
    .sort((a, b) => Number(b.chapterNum || b.chapter_num || 0) - Number(a.chapterNum || a.chapter_num || 0))
    .slice(0, 12)
}

function buildVolumeStageContext(volumes, chapterNum) {
  if (!volumes?.length) return null
  const current = volumes.find(volume =>
    Number(chapterNum) >= Number(volume.startChapter || 0) &&
    Number(chapterNum) <= Number(volume.endChapter || 0)
  )
  if (!current) return null

  const previousSummaries = volumes
    .filter(volume =>
      Number(volume.endChapter || 0) < Number(current.startChapter || 0) &&
      volume.stageSummaryReport
    )
    .sort((a, b) => Number(b.endChapter || 0) - Number(a.endChapter || 0))
    .slice(0, 2)
    .map(volume => ({
      title: volume.title,
      range: `第${volume.startChapter}-${volume.endChapter}章`,
      summary: volume.stageSummaryReport?.compactSummary || volume.summary || volume.stageSummaryReport?.stageSummary || ''
    }))

  const next = volumes
    .filter(volume => Number(volume.startChapter || 0) > Number(current.endChapter || 0))
    .sort((a, b) => Number(a.startChapter || 0) - Number(b.startChapter || 0))[0]

  const nextVolumePreview = next
    ? {
        title: next.title || `第 ${next.volumeNum || '?'} 卷`,
        range: `第${next.startChapter}-${next.endChapter}章`,
        coreGoal: next.coreGoal || '',
        mainConflict: next.mainConflict || '',
        unresolvedItems: next.unresolvedItems || [],
        handoffPoint: next.handoffPoint || '',
        handoffHint: next.summary || ''
      }
    : null

  const report = current.stageSummaryReport || null
  const audit = current.auditReport || null
  return {
    title: current.title || `第 ${current.volumeNum || '?'} 卷`,
    volumeNum: current.volumeNum,
    chapterRange: `第${current.startChapter}-${current.endChapter}章`,
    targetWords: current.targetWords || 0,
    status: current.status || 'planned',
    coreGoal: current.coreGoal || '',
    mainConflict: current.mainConflict || '',
    keyCharacters: current.keyCharacters || [],
    currentSummary: report?.compactSummary || current.summary || '',
    foreshadowingPlan: current.foreshadowingPlan || [],
    unresolvedItems: current.unresolvedItems || [],
    handoffPoint: current.handoffPoint || '',
    stageSummary: report?.stageSummary || '',
    completedBeats: report?.completedBeats || [],
    openQuestions: report?.openQuestions || [],
    characterChanges: report?.characterChanges || [],
    settingChanges: report?.settingChanges || [],
    foreshadowingState: report?.foreshadowingState || [],
    handoffToNext: report?.handoffToNext || [],
    continuityNotes: report?.continuityNotes || [],
    nextVolumeSeeds: report?.nextVolumeSeeds || [],
    auditAssessment: audit?.overallAssessment || '',
    auditIssues: (audit?.issues || []).slice(0, 6).map(issue => ({
      severity: issue.severity,
      type: issue.type,
      description: issue.description,
      suggestion: issue.suggestion
    })),
    previousVolumeSummaries: previousSummaries,
    nextVolumePreview
  }
}

function summarizeCorrectionTasks(tasks, chapterNum, focus = null) {
  const ranked = (tasks || [])
    .filter(isCorrectionTaskActiveForContext)
    .filter(task => {
      const refs = normalizeChapterRefs(task.chapterRefs)
      if (refs.includes(Number(chapterNum))) return true
      if (refs.length) return false
      return task.sourceType === 'global_audit' && correctionTaskMatchesFocus(task, focus)
    })
    .filter(isCorrectionTaskHighPriorityForWriting)
    .sort((a, b) => correctionContextRank(a, chapterNum) - correctionContextRank(b, chapterNum))
  const active = ranked.slice(0, 3)

  if (!active.length) return ''
  const lines = active.map(task => [
    `- [${task.severity || 'minor'} / ${correctionTaskMode(task)} / ${task.targetModule || 'general'}] ${task.title}`,
    isCorrectionTaskBlockingForGeneration(task) ? '处理规则：阻断型硬纠偏，必须先人工确认处理后再继续生成。' : '处理规则：软纠偏，不回改已定稿正文；在后续章节中自然补解释、补动机或回收伏笔。',
    task.suggestedAction ? `建议：${task.suggestedAction}` : '',
    task.chapterRefs?.length ? `涉及章节：${task.chapterRefs.join('、')}` : ''
  ].filter(Boolean).join('；'))

  const omitted = ranked.length - active.length
  if (omitted > 0) {
    lines.push(`- 另有 ${omitted} 条低优先级纠偏未写入本次上下文，避免干扰本章生成；优先处理上方高优先级问题。`)
  }
  return lines.join('\n')
}

function isCorrectionTaskHighPriorityForWriting(task) {
  if (isCorrectionTaskBlockingForGeneration(task)) return true
  return ['critical', 'major'].includes(task?.severity)
}

function correctionTaskMatchesFocus(task, focus) {
  if (!focus?.text && !focus?.keywords?.size && !focus?.threadLabels?.size) return true
  const text = [
    task?.title,
    task?.description,
    task?.suggestedAction,
    task?.targetModule,
    task?.issueType,
    task?.sourceType,
    task?.metadata?.threadLabel,
    task?.metadata?.plotThread
  ].filter(Boolean).join('\n')
  return textMatchesFocus(text, focus)
}

function correctionContextRank(task, chapterNum) {
  const refs = normalizeChapterRefs(task?.chapterRefs)
  const sameChapter = refs.includes(Number(chapterNum)) ? 0 : 20
  const blocking = isCorrectionTaskBlockingForGeneration(task) ? 0 : 10
  const severity = { critical: 0, major: 2, minor: 4, suggestion: 6 }[task?.severity] ?? 4
  return blocking + sameChapter + severity
}

function unwrapMaybeRef(value) {
  return value?.value ?? value
}

function getContextCorrectionTasks(correctionTaskStore) {
  const contextActiveTasks = unwrapMaybeRef(correctionTaskStore?.contextActiveTasks)
  if (Array.isArray(contextActiveTasks)) return contextActiveTasks

  const activeTasks = unwrapMaybeRef(correctionTaskStore?.activeTasks)
  if (Array.isArray(activeTasks)) return activeTasks.filter(isCorrectionTaskActiveForContext)

  const tasks = unwrapMaybeRef(correctionTaskStore?.tasks)
  return Array.isArray(tasks) ? tasks.filter(isCorrectionTaskActiveForContext) : []
}

function normalizeChapterRefs(refs) {
  return (refs || [])
    .map(ref => Number(ref))
    .filter(ref => Number.isFinite(ref) && ref > 0)
}

function pickProfileFacts(type, profile) {
  const keysByType = {
    character: ['family', 'sect', 'faction', 'nation', 'rankTitle', 'realm', 'realmLevel', 'techniques', 'weapons', 'location', 'physicalStatus', 'mentalState', 'currentGoal'],
    faction: ['leader', 'territory', 'hierarchy', 'resources', 'allies', 'enemies', 'goal'],
    location: ['parentLocation', 'geography', 'resources', 'controller', 'dangerLevel', 'restrictions'],
    power_system: ['realms', 'breakthroughRules', 'techniqueGrades', 'itemGrades', 'forbiddenBreaks', 'limits'],
    technique: ['techniqueType', 'grade', 'origin', 'owner', 'requirements', 'effects', 'limitations'],
    item: ['itemType', 'grade', 'owner', 'ability', 'limitation', 'itemStatus']
  }
  const keys = keysByType[type] || []
  return keys
    .filter(key => profile[key])
    .map(key => `${profileLabel(key)}：${profile[key]}`)
    .join('；')
}

function settingTypeLabel(type) {
  const labels = {
    character: '人物',
    faction: '势力',
    location: '地点',
    power_system: '体系',
    technique: '功法',
    item: '物品'
  }
  return labels[type] || '设定'
}

function profileLabel(key) {
  const labels = {
    family: '家族',
    sect: '宗门',
    faction: '阵营',
    nation: '国家',
    rankTitle: '身份',
    realm: '境界',
    realmLevel: '层级',
    techniques: '功法',
    weapons: '武器',
    location: '位置',
    physicalStatus: '身体',
    mentalState: '心理',
    currentGoal: '目标',
    leader: '掌权者',
    territory: '范围',
    hierarchy: '结构',
    resources: '资源',
    allies: '盟友',
    enemies: '敌对',
    goal: '目标',
    parentLocation: '上级地点',
    geography: '地貌',
    controller: '控制者',
    dangerLevel: '危险',
    restrictions: '限制',
    realms: '境界',
    breakthroughRules: '突破规则',
    techniqueGrades: '功法品阶',
    itemGrades: '物品等级',
    forbiddenBreaks: '禁忌',
    limits: '边界',
    techniqueType: '类型',
    grade: '品阶',
    origin: '来源',
    owner: '持有者',
    requirements: '要求',
    effects: '效果',
    limitations: '限制',
    itemType: '类型',
    ability: '能力',
    limitation: '限制',
    itemStatus: '状态'
  }
  return labels[key] || key
}

// === 脑洞发散上下文（不过度约束） ===
export function buildBrainstormContext(seedStore, novelStore) {
  const selectedSeed = seedStore?.selectedSeed?.value || seedStore?.selectedSeed
  const bible = novelStore?.bible?.value || novelStore?.bible
  const styleStandardBrief = formatWritingStyleStandardsForPrompt(bible?.writingProfile)
  return {
    seedInfo: selectedSeed
      ? `题材：${selectedSeed.genre}\n一句话：${selectedSeed.logline}\n主角：${selectedSeed.protagonist}\n欲望：${selectedSeed.desire}`
      : '无',
    bibleInfo: bible
      ? `风格：${bible.styleBible || ''}\n题材/风格标准：${styleStandardBrief || '无'}\n禁忌：${(bible.forbiddenDirections || []).join('、')}`
      : '',
    currentConflict: (novelStore?.outline?.value || novelStore?.outline)?.currentVolume?.mainConflict || '',
    constraints: bible?.forbiddenDirections?.join('\n') || ''
  }
}

// === 审稿上下文 ===
export function buildAuditContext(chapterContent, chapterNum, novelStore) {
  const bible = novelStore?.bible?.value || novelStore?.bible
  const characters = novelStore?.characters?.value || novelStore?.characters || []
  const canonFacts = novelStore?.canonFacts?.value || novelStore?.canonFacts || []
  const plotThreads = novelStore?.plotThreads?.value || novelStore?.plotThreads || []
  return {
    chapterNum,
    chapterContent,
    bible,
    styleStandardBrief: formatWritingStyleStandardsForPrompt(bible?.writingProfile),
    characters,
    canonFacts: canonFacts.filter(f => f.status === 'accepted'),
    plotThreads: plotThreads.filter(t => t.status === 'planted' || t.status === 'developing')
  }
}

// === 提取上下文 ===
export function buildExtractionContext(chapterContent, chapterNum, novelStore) {
  const canonFacts = novelStore?.canonFacts?.value || novelStore?.canonFacts || []
  const characters = novelStore?.characters?.value || novelStore?.characters || []
  const plotThreads = novelStore?.plotThreads?.value || novelStore?.plotThreads || []
  return {
    chapterContent,
    chapterNum,
    existingFacts: canonFacts.filter(f => f.status === 'accepted'),
    characters,
    plotThreads
  }
}

export { BUDGETS }
