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
export function buildWritingContext(novelStore, chapterNum, maxTokens, settingStore = null, volumeStore = null) {
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

  if (bible?.premise) {
    builder.add('premise', bible.premise, { priority: 1, required: true, maxTokens: 800 })
  }

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
  if (volumeContext) {
    builder.add('volumeStage', volumeContext, { priority: 1, required: true, maxTokens: 2200 })
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

  // P6.5: 结构化设定库，优先注入高重要度、活跃实体和关系
  const settingLibrary = summarizeSettingLibrary(settingEntities, settingRelations)
  if (settingLibrary) {
    builder.add('settingLibrary', settingLibrary, { priority: 3, maxTokens: 2400 })
  }

  const recentSettingChanges = summarizeSettingChanges(settingChangeEvents, chapterNum)
  if (recentSettingChanges) {
    builder.add('recentSettingChanges', recentSettingChanges, { priority: 4, maxTokens: 900 })
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

function summarizeSettingLibrary(entities, relations) {
  const activeEntities = (entities || [])
    .filter(e => (e.status || 'active') === 'active')
    .sort((a, b) => Number(b.importance || 3) - Number(a.importance || 3))
    .slice(0, 36)

  if (!activeEntities.length) return ''

  const entityMap = new Map(activeEntities.map(e => [e.id, e]))
  const lines = activeEntities.map(entity => {
    const profile = entity.profile || {}
    const facts = pickProfileFacts(entity.entityType, profile)
    const tags = entity.tags?.length ? `；标签：${entity.tags.join('、')}` : ''
    const aliases = entity.aliases?.length ? `；别名：${entity.aliases.join('、')}` : ''
    return `- [${settingTypeLabel(entity.entityType)}] ${entity.name}${entity.category ? `（${entity.category}）` : ''}：${entity.summary || '无概要'}${facts ? `；${facts}` : ''}${aliases}${tags}`
  })

  const relationLines = (relations || [])
    .filter(r => r.status !== 'archived' && entityMap.has(r.sourceEntityId) && entityMap.has(r.targetEntityId))
    .slice(0, 24)
    .map(r => {
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

function summarizeSettingChanges(events, chapterNum) {
  const recent = (events || [])
    .filter(e => e.status === 'accepted')
    .filter(e => !chapterNum || !e.chapterNum || e.chapterNum <= chapterNum)
    .sort((a, b) => Number(b.chapterNum || 0) - Number(a.chapterNum || 0))
    .slice(0, 12)

  if (!recent.length) return ''
  return recent.map(e =>
    `- 第${e.chapterNum || '?'}章：${e.entityName || settingTypeLabel(e.entityType)} 的 ${e.fieldPath || e.changeType || '设定'} 变为「${e.newValue || ''}」`
  ).join('\n')
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
    previousVolumeSummaries: previousSummaries
  }
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
