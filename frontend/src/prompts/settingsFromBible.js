const VALID_ENTITY_TYPES = new Set(['character', 'faction', 'location', 'power_system', 'technique', 'item'])

const ENTITY_TYPE_ALIASES = new Map([
  ['character', 'character'],
  ['人物', 'character'],
  ['角色', 'character'],
  ['主角', 'character'],
  ['配角', 'character'],
  ['faction', 'faction'],
  ['势力', 'faction'],
  ['组织', 'faction'],
  ['宗门', 'faction'],
  ['家族', 'faction'],
  ['国家', 'faction'],
  ['派系', 'faction'],
  ['阵营', 'faction'],
  ['location', 'location'],
  ['地点', 'location'],
  ['地理', 'location'],
  ['区域', 'location'],
  ['场所', 'location'],
  ['城市', 'location'],
  ['power_system', 'power_system'],
  ['powersystem', 'power_system'],
  ['world_rule', 'power_system'],
  ['world_rules', 'power_system'],
  ['rule', 'power_system'],
  ['rules', 'power_system'],
  ['system', 'power_system'],
  ['ability_system', 'power_system'],
  ['体系', 'power_system'],
  ['世界规则', 'power_system'],
  ['能力体系', 'power_system'],
  ['修炼体系', 'power_system'],
  ['等级体系', 'power_system'],
  ['规则', 'power_system'],
  ['technique', 'technique'],
  ['功法', 'technique'],
  ['能力', 'technique'],
  ['术法', 'technique'],
  ['技能', 'technique'],
  ['item', 'item'],
  ['物品', 'item'],
  ['道具', 'item'],
  ['武器', 'item'],
  ['法宝', 'item'],
  ['系统', 'item']
])

const CHANGE_TYPE_ALIASES = new Map([
  ['new_entity', 'new_entity'],
  ['newentity', 'new_entity'],
  ['create', 'new_entity'],
  ['新增', 'new_entity'],
  ['新实体', 'new_entity'],
  ['创建实体', 'new_entity'],
  ['relationship', 'relationship'],
  ['relation', 'relationship'],
  ['关系', 'relationship'],
  ['新增关系', 'relationship'],
  ['人物关系', 'relationship']
])

const TOP_LEVEL_LIST_KEYS = [
  'settings',
  'settingCandidates',
  'setting_candidates',
  'candidates',
  'entities',
  'items',
  'changes',
  'events',
  '设定',
  '设定候选',
  '候选设定',
  '实体',
  '实体列表',
  '变更',
  '事件'
]

const CATEGORY_KEYS = new Map([
  ['characters', 'character'],
  ['character', 'character'],
  ['人物', 'character'],
  ['角色', 'character'],
  ['factions', 'faction'],
  ['faction', 'faction'],
  ['势力', 'faction'],
  ['组织', 'faction'],
  ['宗门', 'faction'],
  ['locations', 'location'],
  ['location', 'location'],
  ['地点', 'location'],
  ['地理', 'location'],
  ['powerSystems', 'power_system'],
  ['power_systems', 'power_system'],
  ['powerSystem', 'power_system'],
  ['power_system', 'power_system'],
  ['worldRule', 'power_system'],
  ['worldRules', 'power_system'],
  ['world_rule', 'power_system'],
  ['world_rules', 'power_system'],
  ['rules', 'power_system'],
  ['体系', 'power_system'],
  ['世界规则', 'power_system'],
  ['techniques', 'technique'],
  ['technique', 'technique'],
  ['功法', 'technique'],
  ['能力', 'technique'],
  ['items', 'item'],
  ['item', 'item'],
  ['物品', 'item'],
  ['道具', 'item']
])

export const SETTING_INITIALIZATION_GROUPS = [
  {
    key: 'characters',
    label: '人物',
    entityTypes: ['character'],
    maxItems: 8,
    focus: '主角、关键配角、长期对手、隐藏守护者、会反复影响主线的人物。优先提取身份、归属、长期欲望、能力限制、秘密和需要追踪的状态。'
  },
  {
    key: 'factions',
    label: '势力/组织',
    entityTypes: ['faction'],
    maxItems: 8,
    focus: '家族、宗门、国家、机构、秘密组织、群聊组织、理念派系。优先提取立场、目标、控制范围、组织规则和与主线矛盾的关系。'
  },
  {
    key: 'worldRules',
    label: '世界规则/能力体系',
    entityTypes: ['power_system', 'technique'],
    maxItems: 8,
    focus: '世界底层规则、修炼/能力体系、等级秩序、封印规则、资源分布、功法或特殊能力。优先提取后续章节不能写错的硬规则。'
  },
  {
    key: 'locationsItems',
    label: '地点/物品',
    entityTypes: ['location', 'item'],
    maxItems: 8,
    focus: '国家区域、城市、宗门驻地、秘境、关键道具、武器、系统、账号、信物。优先提取会反复出现或承载剧情功能的地点和物品。'
  },
  {
    key: 'relationships',
    label: '长期关系',
    entityTypes: ['character', 'faction', 'location', 'power_system', 'technique', 'item'],
    maxItems: 10,
    relationshipOnly: true,
    focus: '亲属、血脉、师承、隶属、敌对、守护、控制、持有、隐藏观察、理念对立等长期关系。只提取明确存在且后续会影响剧情的关系。'
  }
]

function asText(value) {
  if (value == null) return ''
  if (Array.isArray(value)) return value.filter(Boolean).map(asText).join('\n')
  if (typeof value === 'object') return JSON.stringify(value, null, 0)
  return String(value).trim()
}

function normalizedKey(key) {
  return String(key || '').trim().toLowerCase().replace(/[\s_-]/g, '')
}

function pick(raw, keys) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  for (const key of keys) {
    if (raw[key] != null && raw[key] !== '') return raw[key]
  }

  const wanted = new Set(keys.map(normalizedKey))
  for (const [key, value] of Object.entries(raw)) {
    if (wanted.has(normalizedKey(key)) && value != null && value !== '') return value
  }
  return undefined
}

function normalizeAlias(value, aliases) {
  const direct = asText(value)
  if (!direct) return ''
  if (aliases.has(direct)) return aliases.get(direct)
  const compact = normalizedKey(direct)
  for (const [alias, normalized] of aliases.entries()) {
    if (normalizedKey(alias) === compact) return normalized
  }
  return ''
}

function normalizeEntityType(value) {
  const normalized = normalizeAlias(value, ENTITY_TYPE_ALIASES)
  return VALID_ENTITY_TYPES.has(normalized) ? normalized : ''
}

function normalizeChangeType(value) {
  return normalizeAlias(value, CHANGE_TYPE_ALIASES)
}

function formatBible(bible = {}) {
  return [
    ['作品定位', bible.premise],
    ['目标读者', bible.targetReader],
    ['风格要求', bible.styleBible],
    ['主题与母题', bible.themeBible],
    ['世界规则', bible.worldRules],
    ['禁止方向', Array.isArray(bible.forbiddenDirections) ? bible.forbiddenDirections.join('\n') : bible.forbiddenDirections]
  ]
    .filter(([, value]) => asText(value))
    .map(([label, value]) => `## ${label}\n${asText(value)}`)
    .join('\n\n')
}

function formatSeed(seed = {}) {
  return [
    ['标题', seed.title],
    ['题材', seed.genre],
    ['一句话', seed.logline],
    ['主角', seed.protagonist],
    ['主角欲望', seed.desire],
    ['核心矛盾', seed.coreConflict],
    ['世界压力', seed.worldPressure],
    ['开局钩子', seed.openingHook],
    ['情绪价值', seed.emotionalPromise],
    ['差异化', seed.differentiation],
    ['风险提示', seed.riskNotes],
    ['结局锚点', seed.endingAnchor]
  ]
    .filter(([, value]) => asText(value))
    .map(([label, value]) => `${label}: ${asText(value)}`)
    .join('\n')
}

function formatExistingSettings(settings = []) {
  return (settings || [])
    .slice(0, 80)
    .map(entity => `- [${entity.entityType || 'unknown'}] ${entity.name || '未命名'}：${entity.summary || ''}`)
    .join('\n')
}

function formatExistingEvents(events = []) {
  return (events || [])
    .slice(0, 80)
    .map(event => `- [${event.entityType || 'unknown'}] ${event.entityName || '未命名'} / ${event.changeType || 'new_entity'} / ${event.fieldPath || 'summary'}：${event.evidence || ''}`)
    .join('\n')
}

function compactText(value, limit = 900) {
  const text = dedupeRepeatedSentences(asText(value).replace(/\s+/g, ' ').trim())
  if (text.length <= limit) return text
  return `${text.slice(0, limit)}...`
}

function dedupeRepeatedSentences(text = '') {
  const parts = String(text || '').split(/(?<=[。！？!?；;])/)
  if (parts.length < 3) return text
  const seen = new Set()
  const result = []
  for (const part of parts) {
    const normalized = part.trim()
    if (!normalized) continue
    if (seen.has(normalized)) continue
    seen.add(normalized)
    result.push(normalized)
  }
  return result.join('')
}

export function buildCompactBibleContext({ bible = {}, seed = {}, group } = {}) {
  const safeGroup = group || SETTING_INITIALIZATION_GROUPS[0]
  const common = [
    ['作品定位', bible.premise, 700],
    ['目标读者', bible.targetReader, 220],
    ['创作种子', formatSeed(seed), 700]
  ]
  const groupFields = []

  if (safeGroup.key === 'characters' || safeGroup.key === 'relationships') {
    groupFields.push(['人物相关线索', [seed.protagonist, seed.desire, seed.coreConflict, bible.themeBible].filter(Boolean).join('\n'), 1100])
  }
  if (safeGroup.key === 'factions' || safeGroup.key === 'relationships') {
    groupFields.push(['势力/组织线索', [seed.worldPressure, seed.coreConflict, bible.worldRules, bible.themeBible].filter(Boolean).join('\n'), 1100])
  }
  if (safeGroup.key === 'worldRules') {
    groupFields.push(['世界规则/能力体系线索', [bible.worldRules, seed.worldPressure, seed.coreConflict, bible.themeBible].filter(Boolean).join('\n'), 1300])
  }
  if (safeGroup.key === 'locationsItems') {
    groupFields.push(['地点/物品线索', [seed.openingHook, seed.worldPressure, bible.worldRules, seed.differentiation].filter(Boolean).join('\n'), 1100])
  }
  if (safeGroup.key === 'relationships') {
    groupFields.push(['长期关系线索', [seed.protagonist, seed.coreConflict, seed.emotionalPromise, bible.themeBible].filter(Boolean).join('\n'), 1200])
  }

  return [...common, ['本组目标', safeGroup.label, 120], ['本组关注', safeGroup.focus, 500], ...groupFields]
    .filter(([, value]) => asText(value))
    .map(([label, value, limit]) => `## ${label}\n${compactText(value, limit)}`)
    .join('\n\n')
}

export function buildSettingsFromBibleSystemPrompt() {
  return `你是长篇小说设定库编辑，负责从“创作圣经”和“创作种子”中提取初始设定候选。
你的任务不是扩写剧情，也不是写百科大全，而是找出后续长篇写作必须长期追踪的设定：人物、势力、地点、世界规则、能力体系、功法、物品、关系。
只能输出合法 JSON，不要输出 Markdown、解释或额外文字。`
}

export function buildSettingsFromBiblePrompt({ bible, seed, existingSettings }) {
  return `请从下面的创作圣经和创作种子中，提取“初始设定候选”。这些候选会进入待确认设定变更，由作者确认后才写入正式设定库。

## 创作圣经
${formatBible(bible) || '无'}

## 创作种子
${formatSeed(seed) || '无'}

${existingSettings?.length ? `## 已有设定库（避免重复创建）\n${formatExistingSettings(existingSettings)}` : ''}

请严格输出 JSON 对象，顶层固定为 settings 数组：
{
  "settings": [
    {
      "entityType": "character|faction|location|power_system|technique|item",
      "entityName": "实体名称",
      "changeType": "new_entity|relationship",
      "fieldPath": "summary|关系",
      "summary": "一句话说明该实体或关系为何需要长期追踪",
      "category": "可选分类，如 主角/天庭部门/世界规则/封印体系",
      "importance": 1,
      "profilePatch": {
        "身份/归属/等级/位置/能力/限制等": "只写已能从圣经或种子推导的设定"
      },
      "newValue": "如果 changeType 是 relationship，则必须是关系对象；否则可留空",
      "evidence": "来自圣经或种子的依据，短句即可",
      "confidence": 0.8
    }
  ]
}

relationship 的 newValue 必须是对象：
{
  "targetEntityName": "关系另一端名称",
  "targetEntityType": "character|faction|location|power_system|technique|item",
  "relationType": "亲属|师承|隶属|敌对|持有|控制|隐藏关系|理念对立|守护",
  "stance": "亲近|中立|敌对|利用|未知",
  "summary": "关系说明"
}

提取要求：
1. 优先提取会反复影响后续章节的设定，最多 12 条。
2. 不要把风格要求、目标读者、禁止方向直接填进设定库。
3. 主题与母题只在它们形成“世界规则/组织理念/人物长期动机”时提取。
4. 关系候选只提取明确长期存在的关系，不要臆造人物关系。
5. 如果一个实体有多个属性，用一个 new_entity 加 profilePatch，不要拆成多条。
6. 如果已有设定库里已有同名同类型实体，不要重复 new_entity，可输出关系或跳过。
7. 不确定的信息可以降低 confidence，但不要编造圣经和种子里没有的专有名词。
8. profilePatch 每个字段值必须短，不要整段复制原文；长说明放入 summary 或 evidence。`
}

export function buildSettingsFromBibleSegmentPrompt({ bible, bibleContext, seed, existingSettings = [], existingEvents = [], group }) {
  const safeGroup = group || SETTING_INITIALIZATION_GROUPS[0]
  const allowedTypes = (safeGroup.entityTypes || Array.from(VALID_ENTITY_TYPES)).join('|')
  const typeRule = safeGroup.relationshipOnly
    ? '本轮只允许输出 relationship；不要输出 new_entity。关系两端如果尚未在已提取候选中出现，也可以按名称写入 targetEntityName，但不要补写实体档案。'
    : `本轮主要输出 new_entity；entityType 只能是 ${allowedTypes}。除非关系是理解该实体不可缺少的信息，否则不要在本轮输出 relationship。`
  const compactContext = bibleContext || buildCompactBibleContext({ bible, seed, group: safeGroup })

  return `请从下面的创作圣经和创作种子中，分批提取“${safeGroup.label}”设定候选。
这一轮只处理：${safeGroup.focus}

## 紧凑圣经上下文
${compactContext || '无'}

${existingSettings?.length ? `## 已有正式设定库（避免重复创建）\n${formatExistingSettings(existingSettings)}` : ''}

${existingEvents?.length ? `## 本次初始化已提取候选（避免重复）\n${formatExistingEvents(existingEvents)}` : ''}

请严格输出 JSON 对象，顶层固定为 settings 数组：
{
  "settings": [
    {
      "entityType": "${allowedTypes}",
      "entityName": "实体名称",
      "changeType": "new_entity|relationship",
      "fieldPath": "summary|关系",
      "summary": "一句话说明该实体或关系为何需要长期追踪",
      "category": "可选分类",
      "importance": 1,
      "profilePatch": {
        "身份/归属/等级/位置/能力/限制等": "只写短字段，不要整段复制原文"
      },
      "newValue": "",
      "evidence": "来自圣经或种子的依据，短句即可",
      "confidence": 0.8
    }
  ]
}

relationship 的 newValue 必须是对象：
{
  "targetEntityName": "关系另一端名称",
  "targetEntityType": "character|faction|location|power_system|technique|item",
  "relationType": "亲属|血脉|师承|隶属|敌对|持有|控制|隐藏关系|理念对立|守护",
  "stance": "亲近|中立|敌对|利用|未知",
  "summary": "关系说明"
}

提取要求：
1. ${typeRule}
2. 本轮最多 ${safeGroup.maxItems || 8} 条，只提取会影响后续长篇写作的核心设定。
3. 不要把风格要求、目标读者、禁止方向直接填进设定库。
4. 同名同类型实体如果已在正式设定库或本次已提取候选中出现，不要重复 new_entity。
5. profilePatch 每个字段值必须短；长说明放入 summary 或 evidence。
6. 不确定的信息可以降低 confidence，但不要编造圣经和种子里没有的专有名词。
7. 只输出合法 JSON，不要输出 Markdown、解释或额外文字。`
}

export function buildSettingsFromBibleRepairPrompt(rawText) {
  return `下面是一段“不稳定格式”的设定候选输出。请只做格式修复和字段归一，不要新增内容。
必须输出合法 JSON 对象，顶层为 settings 数组；字段使用 entityType/entityName/changeType/fieldPath/summary/category/importance/profilePatch/newValue/evidence/confidence。
entityType 只能是 character、faction、location、power_system、technique、item。
changeType 只能是 new_entity 或 relationship。

原始输出：
${String(rawText || '').slice(0, 12000)}`
}

function cleanJsonCandidate(candidate) {
  return candidate
    .trim()
    .replace(/^\uFEFF/, '')
    .replace(/^json\s*/i, '')
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/,\s*([}\]])/g, '$1')
}

function collectBalancedCandidates(text, openChar, closeChar) {
  const candidates = []
  let cursor = 0

  while (cursor < text.length) {
    const start = text.indexOf(openChar, cursor)
    if (start === -1) break

    let depth = 0
    let inString = false
    let escaped = false
    let found = false

    for (let i = start; i < text.length; i += 1) {
      const ch = text[i]
      if (inString) {
        if (escaped) escaped = false
        else if (ch === '\\') escaped = true
        else if (ch === '"') inString = false
        continue
      }

      if (ch === '"') inString = true
      else if (ch === openChar) depth += 1
      else if (ch === closeChar) {
        depth -= 1
        if (depth === 0) {
          candidates.push(text.slice(start, i + 1))
          cursor = i + 1
          found = true
          break
        }
      }
    }

    if (!found) cursor = start + 1
  }

  return candidates
}

function inferEntityType(raw) {
  const category = normalizeEntityType(pick(raw, ['category', '分类', '类别']))
  if (category) return category

  const name = asText(pick(raw, ['entityName', 'entity_name', 'name', 'title', '实体名称', '名称', '设定名称']))
  if (/群|组织|宗门|家族|派|国|天庭|地府|龙宫|灵山/.test(name)) return 'faction'
  if (/城|山|海|宫|府|界|域|地|小城|学院/.test(name)) return 'location'
  if (/体系|规则|等级|封印|末法|灵气/.test(name)) return 'power_system'
  if (/功法|术|法|诀|能力/.test(name)) return 'technique'
  if (/剑|刀|灯|书|群|系统|账号|法宝|武器/.test(name)) return 'item'
  return 'character'
}

function normalizeProfilePatch(raw = {}) {
  const profile = pick(raw, ['profilePatch', 'profile_patch', 'profile', '档案', '属性', '设定', '设定资料', '人物设定', '资料'])
  if (profile && typeof profile === 'object' && !Array.isArray(profile)) return profile
  if (asText(profile)) return { 说明: asText(profile) }
  return {}
}

function normalizeTags(raw = {}) {
  const tags = pick(raw, ['tags', '标签'])
  if (Array.isArray(tags)) return tags.filter(Boolean).map(asText)
  if (asText(tags)) return asText(tags).split(/[,\n，、]/).map(item => item.trim()).filter(Boolean)
  return ['创作圣经初始化']
}

function normalizeConfidence(value) {
  const parsed = Number(value ?? 0.8)
  if (!Number.isFinite(parsed)) return 0.8
  return Math.min(1, Math.max(0, parsed))
}

function normalizeImportance(value) {
  const parsed = Number(value ?? 3)
  if (!Number.isFinite(parsed)) return 3
  return Math.min(5, Math.max(1, parsed))
}

function normalizeEvent(raw = {}) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null

  const ambiguousType = pick(raw, ['type', '类型'])
  const explicitEntityType = pick(raw, ['entityType', 'entity_type', 'entity', '实体类型', '设定类型'])
  const entityType = normalizeEntityType(explicitEntityType)
    || normalizeEntityType(ambiguousType)
    || inferEntityType(raw)

  const explicitChangeType = pick(raw, ['changeType', 'change_type', 'action', 'operation', '变更类型', '操作'])
  const changeType = normalizeChangeType(explicitChangeType)
    || (!normalizeEntityType(ambiguousType) ? normalizeChangeType(ambiguousType) : '')
    || 'new_entity'

  const entityName = asText(pick(raw, [
    'entityName',
    'entity_name',
    'name',
    'title',
    '实体名称',
    '设定名称',
    '名称',
    '人物名称',
    '角色名称',
    '势力名称',
    '组织名称',
    '地点名称',
    '体系名称',
    '规则名称',
    '能力体系名称',
    'ruleName',
    'rule_name',
    'systemName',
    'system_name',
    '功法名称',
    '物品名称',
    '人物',
    '角色',
    '势力',
    '地点'
  ]))

  if (!entityName) return null

  return {
    entityType,
    entityName,
    changeType,
    fieldPath: asText(pick(raw, ['fieldPath', 'field_path', 'field', '字段', '设定字段'])) || (changeType === 'relationship' ? '关系' : 'summary'),
    oldValue: '',
    newValue: normalizeNewValue(raw, changeType),
    evidence: asText(pick(raw, ['evidence', '依据', '来源', '证据'])) || asText(pick(raw, ['summary', 'description', 'desc', '简介', '摘要', '说明'])),
    confidence: normalizeConfidence(pick(raw, ['confidence', '置信度'])),
    status: 'pending_review'
  }
}

function normalizeNewValue(raw = {}, changeType = 'new_entity') {
  const rawNewValue = pick(raw, ['newValue', 'new_value', 'value', '内容', '设定值', '关系对象'])
  if (changeType === 'relationship') {
    const relationValue = rawNewValue && typeof rawNewValue === 'object' && !Array.isArray(rawNewValue)
      ? rawNewValue
      : raw
    return JSON.stringify({
      targetEntityName: asText(pick(relationValue, ['targetEntityName', 'target_entity_name', 'targetName', 'target', '目标实体', '目标名称', '关系对象', '对象', '目标'])) || asText(rawNewValue),
      targetEntityType: normalizeEntityType(pick(relationValue, ['targetEntityType', 'target_entity_type', 'targetType', '目标类型'])) || 'character',
      relationType: asText(pick(relationValue, ['relationType', 'relation_type', '关系类型', '关系'])) || '关系',
      stance: asText(pick(relationValue, ['stance', '立场', '态度'])) || '未知',
      summary: asText(pick(relationValue, ['summary', 'description', 'desc', '简介', '摘要', '说明'])) || asText(rawNewValue)
    }, null, 0)
  }

  return JSON.stringify({
    summary: asText(pick(raw, ['summary', 'description', 'desc', '简介', '摘要', '说明'])) || asText(rawNewValue),
    category: asText(pick(raw, ['category', '分类', '类别'])),
    importance: normalizeImportance(pick(raw, ['importance', '重要性'])),
    profile: normalizeProfilePatch(raw),
    tags: normalizeTags(raw)
  }, null, 0)
}

function flattenSettingList(value, hintedType = '') {
  if (Array.isArray(value)) {
    return value.map(item =>
      item && typeof item === 'object' && hintedType && !pick(item, ['entityType', 'entity_type', '实体类型', '设定类型', 'type', '类型'])
        ? { ...item, entityType: hintedType }
        : item
    )
  }

  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, item]) => {
      const entityType = normalizeEntityType(key) || hintedType
      if (Array.isArray(item)) return flattenSettingList(item, entityType)
      if (item && typeof item === 'object') {
        return [{ entityName: key, entityType, ...item }]
      }
      return [{ entityName: key, entityType, summary: asText(item) }]
    })
  }

  return []
}

function normalizeEventList(parsed) {
  let list = []

  if (Array.isArray(parsed)) {
    list = parsed
  } else if (parsed && typeof parsed === 'object') {
    const direct = pick(parsed, TOP_LEVEL_LIST_KEYS)
    if (direct) list = flattenSettingList(direct)

    if (!list.length) {
      for (const [key, value] of Object.entries(parsed)) {
        const hintedType = CATEGORY_KEYS.get(key) || CATEGORY_KEYS.get(normalizedKey(key))
        if (hintedType) list.push(...flattenSettingList(value, hintedType))
      }
    }

    if (!list.length && pick(parsed, ['entityName', 'entity_name', 'name', 'title', '实体名称', '名称', '设定名称'])) {
      list = [parsed]
    }
  }

  return list
    .map(normalizeEvent)
    .filter(Boolean)
    .slice(0, 20)
}

export function extractSettingsFromBibleText(text) {
  if (!text) return []

  const candidates = []
  const fenceRegex = /```(?:json)?\s*([\s\S]*?)```/gi
  let match = fenceRegex.exec(text)
  while (match) {
    candidates.push(match[1])
    match = fenceRegex.exec(text)
  }

  candidates.push(...collectBalancedCandidates(text, '{', '}'))
  candidates.push(...collectBalancedCandidates(text, '[', ']'))

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(cleanJsonCandidate(candidate))
      const events = normalizeEventList(parsed)
      if (events.length) return events
    } catch {
      // Try the next candidate.
    }
  }

  return []
}

export function filterEventsForInitializationGroup(events = [], group) {
  if (!group) return events
  const allowedTypes = new Set(group.entityTypes || [])
  return (events || []).filter(event => {
    if (!event?.entityName) return false
    if (group.relationshipOnly) return event.changeType === 'relationship'
    if (event.changeType === 'relationship') return false
    return !allowedTypes.size || allowedTypes.has(event.entityType)
  })
}

export function dedupeSettingInitializationEvents(events = [], existingSettings = []) {
  const existingEntityKeys = new Set((existingSettings || [])
    .map(entity => entityKey(entity.entityType || 'character', entity.name || entity.entityName || '')))
  const seenEntityKeys = new Set()
  const seenEventKeys = new Set()
  const seenRelationKeys = new Set()
  const deduped = []

  for (const event of events || []) {
    if (!event?.entityName) continue

    if (event.changeType === 'relationship') {
      const relation = parseRelationValue(event.newValue)
      const key = relationKey(
        event.entityType,
        event.entityName,
        relation.targetEntityType,
        relation.targetEntityName,
        relation.relationType
      )
      if (!relation.targetEntityName || seenRelationKeys.has(key)) continue
      seenRelationKeys.add(key)
      deduped.push(event)
      continue
    }

    const key = entityKey(event.entityType, event.entityName)
    if (existingEntityKeys.has(key) || seenEntityKeys.has(key)) continue
    seenEntityKeys.add(key)

    const eventKey = [
      key,
      event.changeType || 'new_entity',
      event.fieldPath || 'summary',
      String(event.newValue || '')
    ].join('::')
    if (seenEventKeys.has(eventKey)) continue
    seenEventKeys.add(eventKey)
    deduped.push(event)
  }

  return deduped
}

export function buildSettingInitializationDedupKey(event = {}) {
  if (event.changeType === 'relationship') {
    const relation = parseRelationValue(event.newValue)
    return relationKey(
      event.entityType,
      event.entityName,
      relation.targetEntityType,
      relation.targetEntityName,
      relation.relationType
    )
  }

  return [
    entityKey(event.entityType, event.entityName),
    event.changeType || 'new_entity',
    event.fieldPath || 'summary',
    String(event.newValue || '').trim()
  ].join('::')
}

function entityKey(entityType, entityName) {
  return `${String(entityType || 'character').trim()}::${String(entityName || '').trim()}`
}

function relationKey(sourceType, sourceName, targetType, targetName, relationType) {
  const source = entityKey(sourceType, sourceName)
  const target = entityKey(targetType || 'character', targetName)
  const relation = String(relationType || '关系').trim()
  return `${source}::${target}::${relation}`
}

function parseRelationValue(value) {
  if (!value) return {}
  if (typeof value === 'object') return value
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function buildFallbackSettingsFromBibleEvents({ bible = {}, seed = {}, existingSettings = [] } = {}) {
  const existingKeys = new Set((existingSettings || [])
    .map(entity => `${entity.entityType || 'character'}::${entity.name || ''}`))
  const rawEvents = buildFallbackRawEvents(bible, seed)
  const seen = new Set()

  return rawEvents
    .filter(item => !existingKeys.has(`${item.entityType || 'character'}::${item.entityName || ''}`))
    .map(normalizeEvent)
    .filter(Boolean)
    .filter(event => {
      const key = `${event.entityType}::${event.entityName}::${event.changeType}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .slice(0, 12)
}

function buildFallbackRawEvents(bible, seed) {
  const text = [
    formatBible(bible),
    formatSeed(seed)
  ].filter(Boolean).join('\n')

  const events = []
  const protagonistName = extractLeadingChineseName(seed.protagonist) || extractLeadingChineseName(seed.logline)
  if (protagonistName) {
    events.push({
      entityType: 'character',
      entityName: protagonistName,
      changeType: 'new_entity',
      fieldPath: 'summary',
      summary: summarizeText(seed.protagonist || seed.logline || bible.premise, 160) || '作品主角，需要长期追踪成长、身份和选择。',
      category: '主角',
      importance: 5,
      profilePatch: {
        身份: extractAfter(seed.protagonist, ['身份：', '隐藏身份：']) || '',
        初始处境: summarizeText(seed.protagonist, 80),
        长期欲望: summarizeText(seed.desire, 120)
      },
      evidence: seed.protagonist || seed.logline || bible.premise,
      confidence: 0.85
    })
  }

  for (const candidate of extractCandidateEntityNames(text, protagonistName)) {
    const { name, evidence, category, importance } = candidate
    if (name === protagonistName) continue
    events.push({
      entityType: 'character',
      entityName: name,
      changeType: 'new_entity',
      fieldPath: 'summary',
      summary: inferCharacterSummary(name, text, evidence),
      category,
      importance,
      profilePatch: {},
      evidence,
      confidence: 0.72
    })
  }

  for (const faction of extractFactionCandidates(text)) {
    events.push({
      entityType: 'faction',
      entityName: faction.name,
      changeType: 'new_entity',
      fieldPath: 'summary',
      summary: summarizeText(faction.evidence, 150) || `${faction.name} 是作品中需要追踪的组织、势力或群体。`,
      category: faction.category,
      importance: faction.importance,
      profilePatch: {},
      evidence: faction.evidence,
      confidence: 0.74
    })
  }

  const systemText = seed.coreConflict || seed.worldPressure || bible.worldRules || ''
  if (systemText) {
    events.push({
      entityType: 'power_system',
      entityName: inferSystemName(systemText),
      changeType: 'new_entity',
      fieldPath: 'summary',
      summary: summarizeText(systemText, 180),
      category: '世界规则/力量体系',
      importance: 5,
      profilePatch: {
        核心规则: summarizeText(systemText, 160)
      },
      evidence: systemText,
      confidence: 0.82
    })
  }

  for (const candidate of extractLocationItemCandidates({ bible, seed, text })) {
    events.push({
      entityType: candidate.entityType,
      entityName: candidate.name,
      changeType: 'new_entity',
      fieldPath: 'summary',
      summary: candidate.summary,
      category: candidate.category,
      importance: candidate.importance,
      profilePatch: candidate.profilePatch,
      evidence: candidate.evidence,
      confidence: candidate.confidence
    })
  }

  return events
}

function extractCandidateEntityNames(text = '', protagonistName = '') {
  const value = String(text || '')
  const candidates = new Map()
  const add = (name, score, evidence = '') => {
    const normalized = normalizeCandidateName(name)
    if (!normalized || normalized === protagonistName || isCommonNonName(normalized)) return
    const prev = candidates.get(normalized)
    if (!prev || prev.score < score) {
      candidates.set(normalized, {
        name: normalized,
        score,
        evidence: evidence || findSentenceContaining(value, normalized),
        category: inferCharacterCategory(normalized, evidence || findSentenceContaining(value, normalized)),
        importance: score >= 7 ? 5 : 4
      })
    }
  }

  const patterns = [
    /(?:男主|女主|主角|配角|反派|关键人物|导师|师父|父亲|母亲|兄长|妹妹|同伴|盟友|敌人|宿敌|家主|宗主|掌门|长老|人物)[：:]\s*([\u4e00-\u9fa5]{2,5})/g,
    /([\u4e00-\u9fa5]{2,5})[，,]\s*(?:\d{1,3}岁|男主|女主|主角|配角|反派|导师|师父|父亲|母亲|兄长|妹妹|同伴|盟友|敌人|宿敌|家主|宗主|掌门|长老)/g,
    /(?:名叫|叫做|名为|化名|自称|代号|真名是|本名是)[“"']?([\u4e00-\u9fa5]{2,5})/g,
    /([\u4e00-\u9fa5]{2,5})(?:的父亲|的母亲|的师父|的导师|的宿敌|的同伴|的盟友|的家主|的宗主|的掌门)/g
  ]

  for (const pattern of patterns) {
    for (const match of value.matchAll(pattern)) {
      add(match[1], 8, findSentenceContaining(value, match[1]))
    }
  }

  return [...candidates.values()]
    .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name, 'zh-CN'))
    .slice(0, 8)
}

function extractFactionCandidates(text = '') {
  const value = String(text || '')
  const candidates = new Map()
  const pattern = /([\u4e00-\u9fa5]{2,10}(?:家|族|宗|门|派|宫|阁|司|局|会|院|城|国|军|盟|组织|集团|教团|书院|商会|帮|堂))(?:[，,。；;：:\s]|$)/g
  for (const match of value.matchAll(pattern)) {
    const name = normalizeCandidateName(match[1])
    if (!name || isCommonNonName(name) || candidates.has(name)) continue
    const evidence = findSentenceContaining(value, name)
    candidates.set(name, {
      name,
      evidence,
      category: inferFactionCategory(name, evidence),
      importance: /主线|核心|敌|控制|追杀|统治|掌控|隐秘/.test(evidence) ? 5 : 4
    })
  }
  return [...candidates.values()].slice(0, 4)
}

function extractLocationItemCandidates({ bible = {}, seed = {}, text = '' } = {}) {
  const value = String(text || '')
  const candidates = new Map()
  const add = (entityType, name, evidence, options = {}) => {
    const normalized = normalizeCandidateName(name)
    if (!normalized || isCommonNonName(normalized)) return
    const key = `${entityType}::${normalized}`
    if (candidates.has(key)) return
    candidates.set(key, {
      entityType,
      name: normalized,
      evidence: summarizeText(evidence, 180) || summarizeText(value, 180),
      summary: options.summary || summarizeText(evidence, 150) || `${normalized} 是创作圣经初始化识别出的${entityType === 'location' ? '地点' : '物品'}候选，需要人工确认。`,
      category: options.category || (entityType === 'location' ? '地点' : '关键物品'),
      importance: options.importance || 4,
      profilePatch: options.profilePatch || {},
      confidence: options.confidence || 0.66
    })
  }

  const openingHook = asText(seed.openingHook)
  const worldRules = asText(bible.worldRules)
  const differentiation = asText(seed.differentiation)
  const coreConflict = asText(seed.coreConflict)

  for (const match of openingHook.matchAll(/([\u4e00-\u9fa5]{2,10}(?:当铺|城|镇|村|街|巷|楼|阁|司|府|院|港|渡|山|谷|河|湖|域|界|坊|铺))/g)) {
    add('location', match[1], findSentenceContaining(openingHook, match[1]) || openingHook, {
      category: '开局地点',
      importance: 4,
      profilePatch: { 来源: '开局钩子' },
      confidence: 0.68
    })
  }

  if (/当铺/.test(openingHook) && ![...candidates.keys()].some(key => key.includes('当铺'))) {
    add('location', '雨夜当铺', openingHook, {
      summary: '开局清账场景，承接父亲新账线索，需要人工确认正式名称。',
      category: '开局地点',
      importance: 4,
      profilePatch: { 来源: '开局钩子', 状态: '名称待确认' },
      confidence: 0.58
    })
  }

  for (const itemName of ['星账', '账本']) {
    const evidence = [openingHook, worldRules, differentiation, coreConflict]
      .find(textPart => asText(textPart).includes(itemName))
    if (evidence) {
      add('item', itemName === '账本' && /星账/.test(value) ? '星账' : itemName, evidence, {
        summary: `${itemName === '账本' && /星账/.test(value) ? '星账' : itemName}承载主线线索和代价机制，需要长期追踪持有、使用和限制。`,
        category: '关键物品',
        importance: 5,
        profilePatch: {
          功能: summarizeText(worldRules || differentiation || coreConflict, 120),
          初次线索: summarizeText(openingHook, 100)
        },
        confidence: 0.72
      })
    }
  }

  return [...candidates.values()].slice(0, 4)
}

function normalizeCandidateName(name = '') {
  return String(name || '')
    .replace(/[“”"'《》、，。；：:（）()\[\]\s]/g, '')
    .trim()
}

function isCommonNonName(name = '') {
  if (!name || name.length < 2 || name.length > 10) return true
  const common = new Set([
    '主角', '男主', '女主', '配角', '反派', '人物', '角色', '读者', '作者',
    '世界', '故事', '系统', '设定', '真相', '规则', '核心', '关键', '开局',
    '前期', '中期', '后期', '终极', '能力', '功法', '势力', '家族', '宗门',
    '父亲', '母亲', '师父', '导师', '敌人', '同伴', '盟友', '少年', '少女',
    '老人', '男人', '女人', '凡人', '神仙', '皇帝', '读者们'
  ])
  if (common.has(name)) return true
  if (/^(一个|一种|这个|那个|所有|当前|真正|隐藏|普通|关键|核心)/.test(name)) return true
  return false
}

function extractLeadingChineseName(text = '') {
  const value = String(text || '').trim()
  const match = value.match(/^([\u4e00-\u9fa5]{2,4})[，,、\s]/)
  return match?.[1] || ''
}

function extractAfter(text = '', markers = []) {
  const value = String(text || '')
  for (const marker of markers) {
    const index = value.indexOf(marker)
    if (index !== -1) return summarizeText(value.slice(index + marker.length), 80)
  }
  return ''
}

function findSentenceContaining(text = '', keyword = '') {
  if (!keyword) return ''
  const normalized = String(text || '').replace(/\s+/g, ' ')
  const index = normalized.indexOf(keyword)
  if (index === -1) return ''
  const start = Math.max(0, index - 70)
  const end = Math.min(normalized.length, index + keyword.length + 110)
  return normalized.slice(start, end).trim()
}

function summarizeText(text = '', limit = 120) {
  const value = String(text || '').replace(/\s+/g, ' ').trim()
  if (value.length <= limit) return value
  return `${value.slice(0, limit)}...`
}

function inferCharacterSummary(name, text, evidence = '') {
  const sentence = evidence || findSentenceContaining(text, name)
  return summarizeText(sentence, 120) || `${name} 是种子中出现的长期角色候选。`
}

function inferCharacterCategory(name, evidence = '') {
  const text = `${name} ${evidence || ''}`
  if (/主角|男主|女主/.test(text)) return '主角'
  if (/反派|敌|宿敌|对立|追杀/.test(text)) return '对立人物'
  if (/父|母|兄|妹|家主|亲属|血脉|家族/.test(text)) return '亲缘/家族人物'
  if (/师|导师|长老|宗主|掌门|宗门/.test(text)) return '师承/宗门人物'
  if (/同伴|盟友|朋友|队友|搭档/.test(text)) return '关键同伴'
  return '长期角色候选'
}

function inferFactionCategory(name, evidence = '') {
  const text = `${name} ${evidence || ''}`
  if (/家|族/.test(name)) return '家族/血脉势力'
  if (/宗|门|派|宫|阁|教/.test(name)) return '宗门/修行势力'
  if (/司|局|院|军|国|城/.test(name)) return '官方/地域势力'
  if (/组织|集团|商会|帮|堂|盟/.test(name)) return '组织/利益势力'
  if (/敌|追杀|控制|隐秘|黑暗/.test(text)) return '对立势力'
  return '势力/组织候选'
}

function inferSystemName(text = '') {
  const value = String(text || '')
  const explicit = value.match(/(?:力量体系|修炼体系|世界规则|核心规则|底层规则|核心矛盾|世界压力)[：:]\s*([\u4e00-\u9fa5A-Za-z0-9·\-]{2,16})/)
  if (explicit?.[1]) return normalizeCandidateName(explicit[1]).slice(0, 16)
  const named = value.match(/([\u4e00-\u9fa5]{2,12}(?:体系|规则|契约|循环|污染|封锁|诅咒|剧场|系统|灵脉|法则))/)
  if (named?.[1] && !isCommonNonName(named[1])) return normalizeCandidateName(named[1]).slice(0, 16)
  return '核心力量与世界规则'
}
