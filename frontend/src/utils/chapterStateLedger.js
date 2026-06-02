const HARD_STATE_KEYWORDS = [
  '剩余',
  '已用',
  '使用',
  '次数',
  '左臂',
  '右臂',
  '受伤',
  '伤口',
  '死亡',
  '失踪',
  '失去',
  '恢复',
  '消失',
  '持有',
  '归属',
  '拥有',
  '位置',
  '地点',
  '离开',
  '进入',
  '境界',
  '等级',
  '修为',
  '功法',
  '武器',
  '法宝',
  '钥匙',
  '契约',
  '封印',
  '代价',
  '冷却',
  '倒计时',
  '交易',
  '寿命',
  '消耗',
  '下次',
  '上次',
  '首次',
  '第一',
  '第二',
  '第三',
  '价值',
  '价格',
  '售价',
  '稀有',
  '药效',
  '时间流速',
  '时间',
  '日期',
  '第几天',
  '次日',
  '同日',
  '隐性',
  '显性',
  '金额',
  '余额',
  '债务',
  '视角',
  '已知',
  '未知',
  '知道',
  '不知',
  '可见',
  '不可见',
  '同场',
  '分线'
]

const PROFILE_KEYS = [
  'physicalStatus',
  'bodyStatus',
  'currentLocation',
  'location',
  'sceneLocation',
  'region',
  'currentTime',
  'timeline',
  'dayIndex',
  'date',
  'season',
  'pov',
  'viewpoint',
  'knownTo',
  'unknownTo',
  'knowledgeBoundary',
  'visibilityBoundary',
  'realm',
  'realmLevel',
  'cultivation',
  'level',
  'powerLevel',
  'technique',
  'techniques',
  'weapon',
  'weapons',
  'itemStatus',
  'inventory',
  'owner',
  'usesLeft',
  'cooldown',
  'cooldownUntil',
  'nextAvailableAt',
  'remainingLifespan',
  'lifespanRemaining',
  'lifespanCost',
  'transactionCount',
  'tradeCount',
  'lastTransaction',
  'costRule',
  'timeFlowRule',
  'valueLevel',
  'rarity',
  'price',
  'behaviorState',
  'emotionalState',
  'currentGoal',
  'status'
]

const TYPE_LABELS = {
  character: '人物',
  faction: '势力',
  location: '地点',
  system: '体系',
  technique: '功法',
  item: '物品'
}

export function hasHardStateSignal(value) {
  const text = typeof value === 'string' ? value : JSON.stringify(value || '')
  if (!text.trim()) return false
  if (/[0-9一二三四五六七八九十百千万两]+(?:\s*)?(次|层|阶|级|年|月|日|天|时|刻|枚|件|章|卷|岁|万|元|两|钱)/.test(text)) return true
  return HARD_STATE_KEYWORDS.some(keyword => text.includes(keyword))
}

function normalizeValue(value) {
  if (value == null || value === '') return ''
  if (Array.isArray(value)) return value.filter(Boolean).join('、')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value).trim()
}

function chapterBefore(item, chapterNum) {
  const itemChapter = Number(item?.chapterNum ?? item?.chapter_num ?? item?.chapter ?? 0)
  const current = Number(chapterNum || 0)
  if (!current) return true
  return itemChapter > 0 && itemChapter < current
}

function isAccepted(item) {
  return (item?.status || 'accepted') === 'accepted'
}

function entityTypeLabel(type) {
  return TYPE_LABELS[type] || type || '设定'
}

function formatEntityLine(entity) {
  const profile = entity?.profile || {}
  const facts = []

  for (const key of PROFILE_KEYS) {
    const value = normalizeValue(profile[key] ?? entity?.[key])
    if (value && hasHardStateSignal(`${key}:${value}`)) facts.push(`${key}=${value}`)
  }

  const summary = normalizeValue(entity?.summary)
  if (summary && hasHardStateSignal(summary)) facts.push(summary)

  if (!facts.length) return ''
  return `- [${entityTypeLabel(entity.entityType)}] ${entity.name || '未命名'}：${facts.slice(0, 6).join('；')}`
}

function formatChangeLine(change) {
  const fieldPath = change?.fieldPath || change?.field_path || change?.field || '状态'
  const value = normalizeValue(change?.newValue ?? change?.new_value ?? change?.summary ?? change?.content)
  if (!hasHardStateSignal(`${fieldPath}:${value}`)) return ''
  const chapter = change?.chapterNum ?? change?.chapter_num ?? '?'
  const name = change?.entityName || change?.entity_name || change?.targetEntityName || '未知实体'
  const type = change?.entityType || change?.entity_type || 'setting'
  return `- [第${chapter}章设定变化/${entityTypeLabel(type)}] ${name}.${fieldPath} -> ${value}`
}

function formatFactLine(fact) {
  const content = normalizeValue(fact?.content || fact?.summary || fact?.fact)
  if (!hasHardStateSignal(content)) return ''
  const chapter = fact?.chapterNum ?? fact?.chapter_num ?? '?'
  const type = fact?.factType || fact?.fact_type || '事实'
  return `- [第${chapter}章已确认事实/${type}] ${content}`
}

export function buildChapterStateLedger({
  chapterNum,
  settingEntities = [],
  settingChangeEvents = [],
  canonFacts = [],
  maxLines = 24
} = {}) {
  const entityLines = (settingEntities || [])
    .filter(entity => (entity?.status || 'active') === 'active')
    .map(formatEntityLine)
    .filter(Boolean)

  const changeLines = (settingChangeEvents || [])
    .filter(change => isAccepted(change) && chapterBefore(change, chapterNum))
    .slice()
    .sort((a, b) => Number(b.chapterNum || b.chapter_num || 0) - Number(a.chapterNum || a.chapter_num || 0))
    .map(formatChangeLine)
    .filter(Boolean)

  const factLines = (canonFacts || [])
    .filter(fact => isAccepted(fact) && chapterBefore(fact, chapterNum))
    .slice()
    .sort((a, b) => Number(b.chapterNum || b.chapter_num || 0) - Number(a.chapterNum || a.chapter_num || 0))
    .map(formatFactLine)
    .filter(Boolean)

  const lines = [...entityLines, ...changeLines, ...factLines]
    .filter((line, index, array) => array.indexOf(line) === index)
    .slice(0, maxLines)

  if (!lines.length) return ''

  return [
    '## 章节状态账本（硬状态，不可漂移）',
    ...lines,
    '',
    '时空硬约束：同一章必须尊重当前时间、地点、视角可知范围和分线信息。角色不能知道自己未在场、未被告知或视角不可见的事实；不同地点/时间线的事件不能无解释串到同一场景。',
    '写作硬约束：以上内容代表已确认的身体状态、位置、归属、数量、次数、境界、物品和规则。不得让角色无解释恢复、重复消耗同一资源、重新获得已失去物品，或让数值/等级/位置回退。若剧情需要改变，必须在正文中给出清楚因果，并在定稿后进入设定变更。'
  ].join('\n')
}
