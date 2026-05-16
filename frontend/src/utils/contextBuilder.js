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

// === 正文生成上下文 ===
export function buildWritingContext(novelStore, chapterNum, maxTokens) {
  const builder = new ContextBuilder(maxTokens || BUDGETS.writing)
  const bible = novelStore.bible?.value || novelStore.bible
  const outline = novelStore.outline?.value || novelStore.outline
  const characters = novelStore.characters?.value || novelStore.characters || []
  const plotThreads = novelStore.plotThreads?.value || novelStore.plotThreads || []
  const canonFacts = novelStore.canonFacts?.value || novelStore.canonFacts || []

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

  // P2: 当前卷信息（必须）
  if (outline?.currentVolume) {
    builder.add('currentVolume', outline.currentVolume, { priority: 1, required: true, maxTokens: 1000 })
  }

  // P3: 近景大纲
  if (outline?.nearChapters?.length) {
    builder.add('nearOutline', outline.nearChapters.filter(n => n.chapterNum >= chapterNum), { priority: 2, maxTokens: 800 })
  }

  // P4: 世界规则（必须遵守）
  if (bible?.worldRules) {
    builder.add('worldRules', bible.worldRules, { priority: 2, required: true, maxTokens: 1000 })
  }

  // P5: 禁止方向
  if (bible?.forbiddenDirections?.length) {
    builder.add('forbiddenDirections', bible.forbiddenDirections, { priority: 2, maxTokens: 300 })
  }

  // P6: 风格要求
  if (bible?.styleBible) {
    builder.add('styleBible', bible.styleBible, { priority: 3, maxTokens: 600 })
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
    builder.add('characters', simplified, { priority: 4, maxTokens: 1500 })
  }

  // P8: 最近已确认事实
  const recentFacts = canonFacts
    .filter(f => f.status === 'accepted')
    .slice(-20)
  if (recentFacts.length > 0) {
    const summary = recentFacts.map(f => `[${f.factType}] ${f.content}`).join('\n')
    builder.add('recentFacts', summary, { priority: 5, maxTokens: 1500 })
  }

  // P9: 进行中的伏笔
  const activeThreads = plotThreads.filter(t => t.status === 'planted' || t.status === 'developing')
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

// === 脑洞发散上下文（不过度约束） ===
export function buildBrainstormContext(seedStore, novelStore) {
  const selectedSeed = seedStore?.selectedSeed?.value || seedStore?.selectedSeed
  const bible = novelStore?.bible?.value || novelStore?.bible
  return {
    seedInfo: selectedSeed
      ? `题材：${selectedSeed.genre}\n一句话：${selectedSeed.logline}\n主角：${selectedSeed.protagonist}\n欲望：${selectedSeed.desire}`
      : '无',
    bibleInfo: bible
      ? `风格：${bible.styleBible || ''}\n禁忌：${(bible.forbiddenDirections || []).join('、')}`
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
