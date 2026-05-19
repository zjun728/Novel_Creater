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
7. 不确定的信息可以降低 confidence，但不要编造圣经和种子里没有的专有名词。`
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
