const BIBLE_FIELDS = [
  'premise',
  'targetReader',
  'styleBible',
  'themeBible',
  'worldRules',
  'writingProfile',
  'forbiddenDirections'
]

function normalizeText(value) {
  if (value == null) return ''
  if (Array.isArray(value)) return value.filter(Boolean).map(item => normalizeText(item)).filter(Boolean).join('\n')
  if (typeof value === 'object') return JSON.stringify(value)
  const text = String(value).trim()
  return normalizeArrayText(text) || text
}

function normalizeArrayText(text) {
  if (!/^\s*\[/.test(text)) return ''

  const cleaned = text
    .trim()
    .replace(/,\s*\]/g, ']')

  try {
    const parsed = JSON.parse(cleaned)
    if (Array.isArray(parsed)) {
      return parsed
        .map(item => normalizeText(item))
        .filter(Boolean)
        .join('\n')
    }
  } catch {
    // Fall back to a line-based cleanup for JSON-like array strings.
  }

  const inner = cleaned
    .replace(/^\s*\[/, '')
    .replace(/\]\s*$/, '')
    .trim()

  return inner
    .split(/\n+/)
    .map(line => line
      .trim()
      .replace(/^\s*,\s*/, '')
      .replace(/^\s*["'`]/, '')
      .replace(/["'`]\s*,?\s*$/, '')
      .trim()
    )
    .filter(Boolean)
    .join('\n')
}

function normalizeTags(value) {
  if (Array.isArray(value)) {
    return value
      .map(item => normalizeText(item))
      .filter(Boolean)
      .slice(0, 10)
  }

  return normalizeText(value)
    .split(/[\n,，、;；]+/)
    .map(item => item.trim())
    .filter(Boolean)
    .slice(0, 10)
}

function normalizeWritingProfilePayload(value) {
  if (value == null || value === '') return {}

  if (typeof value === 'string') {
    const text = value.trim()
    if (!text) return {}
    try {
      return normalizeWritingProfilePayload(JSON.parse(text))
    } catch {
      return {}
    }
  }

  if (Array.isArray(value)) {
    const ids = value.map(item => normalizeText(item)).filter(Boolean)
    return {
      selectedStandards: ids.slice(0, 3),
      primaryStandard: ids[0] || '',
      secondaryFlavor: ids[1] || '',
      additionalStandards: ids.slice(2, 3),
      customStyleNotes: ''
    }
  }

  if (typeof value !== 'object') return {}

  const selectedStandards = Array.isArray(value.selectedStandards)
    ? value.selectedStandards.map(item => normalizeText(item)).filter(Boolean).slice(0, 3)
    : [
        value.primaryStandard,
        value.secondaryFlavor,
        ...(Array.isArray(value.additionalStandards) ? value.additionalStandards : [])
      ].map(item => normalizeText(item)).filter(Boolean).slice(0, 3)
  const standardSnapshots = value.standardSnapshots && typeof value.standardSnapshots === 'object' && !Array.isArray(value.standardSnapshots)
    ? value.standardSnapshots
    : null
  const normalized = {
    selectedStandards,
    primaryStandard: selectedStandards[0] || String(value.primaryStandard || '').trim(),
    secondaryFlavor: selectedStandards[1] || String(value.secondaryFlavor || '').trim(),
    additionalStandards: selectedStandards.slice(2),
    customStyleNotes: normalizeText(value.customStyleNotes)
  }
  if (standardSnapshots && Object.keys(standardSnapshots).length) normalized.standardSnapshots = standardSnapshots
  return normalized
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function seedLine(label, value) {
  const text = normalizeText(value)
  return text ? `${label}: ${text}` : ''
}

export function buildBibleFromSeedSystemPrompt() {
  return `你是资深长篇小说总编和网文创作策划。你的任务是把一个“创作种子”扩展为可执行的“创作圣经”。

创作圣经不是宣传文案，而是后续 AI 写大纲、设定、章节正文时必须遵守的蓝图。它要保留想象力，但不能空泛。

请严格输出合法 JSON，不要输出 Markdown、解释文字或代码块。`
}

export function buildBibleFromSeedPrompt(seed, options = {}) {
  const selectedStyleBible = normalizeText(options.selectedStyleBible)
  const seedPayload = [
    seedLine('暂定书名', seed.title),
    seedLine('题材类型', seed.genre),
    seedLine('一句话定位', seed.logline),
    seedLine('主角设定', seed.protagonist),
    seedLine('主角欲望', seed.desire),
    seedLine('核心矛盾', seed.coreConflict),
    seedLine('世界压力', seed.worldPressure),
    seedLine('开局钩子', seed.openingHook),
    seedLine('情绪价值', seed.emotionalPromise),
    seedLine('差异化', seed.differentiation),
    seedLine('原始风格目标', seed.styleTarget),
    seedLine('风险提示', seed.riskNotes),
    seedLine('结局锚点', seed.endingAnchor),
    seedLine('已选风格试写/风格基准', selectedStyleBible)
  ].filter(Boolean).join('\n\n')

  return `请根据下面的创作种子，生成一份可直接保存到产品里的“创作圣经”。

创作种子:
${seedPayload || '无'}

必须输出如下 JSON 对象:
{
  "premise": "",
  "targetReader": "",
  "styleBible": ["短句1", "短句2"],
  "themeBible": ["短句1", "短句2"],
  "worldRules": ["短句1", "短句2"],
  "forbiddenDirections": []
}

字段要求:
1. premise: 作品定位，1-2 句话。不是复述书名，要说清“谁在什么压力下，凭什么故事张力吸引读者”。
2. targetReader: 目标读者画像，80-160 字。请从题材、情绪价值、开局钩子、节奏和爽点推导，不要留空。
3. styleBible: 数组，4-6 条短句，写清叙述口吻、节奏、对话、幽默/沉重比例、章节钩子、视角控制。若有“已选风格试写/风格基准”，必须吸收为长期风格规则。
4. themeBible: 数组，4-6 条短句，写清作品真正反复讨论的命题、人物弧光、情感底色、结局锚点要兑现的精神含义。不要留空。
5. worldRules: 数组，4-8 条短句，整理核心矛盾和世界压力里的硬规则。写成后续章节不能违背的设定约束，避免只写氛围。
6. forbiddenDirections: 4-8 条短句数组，来自风险提示和差异化要求。每条是具体禁区，如“不要把群聊写成纯外挂”“不要让反派脸谱化”。

质量要求:
- 不要照搬种子字段，要把它们转化成后续创作约束。
- 允许保留想象空间，但关键规则必须足够清楚，能防止后续长篇写作跑偏。
- 所有字符串值内部不要直接换行；需要分条时必须使用 JSON 数组。
- 每个数组元素控制在 15-45 个中文字符，宁可短，不要长段落。
- 不要生成大纲、章节正文或人物小传。
- 最终回复只能是合法 JSON。`
}

export function buildBibleFromSeedRepairPrompt(rawText) {
  return `下面是一段 AI 生成的创作圣经内容，但格式可能不是合法 JSON。请只提取并整理成一个合法 JSON 对象，不要解释，不要 Markdown。

必须输出:
{
  "premise": "",
  "targetReader": "",
  "styleBible": ["短句1", "短句2"],
  "themeBible": ["短句1", "短句2"],
  "worldRules": ["短句1", "短句2"],
  "forbiddenDirections": []
}

原始内容:
${rawText}`
}

function cleanJsonCandidate(candidate) {
  return candidate
    .trim()
    .replace(/^\uFEFF/, '')
    .replace(/^json\s*/i, '')
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/，\s*([}\]])/g, '$1')
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

function pickBiblePayload(parsed) {
  if (Array.isArray(parsed)) return parsed.find(item => item && typeof item === 'object') || null
  if (!parsed || typeof parsed !== 'object') return null
  if (parsed.bible && typeof parsed.bible === 'object') return parsed.bible
  if (parsed.creativeBible && typeof parsed.creativeBible === 'object') return parsed.creativeBible
  if (parsed.data && typeof parsed.data === 'object' && !Array.isArray(parsed.data)) return parsed.data
  return parsed
}

const BIBLE_FIELD_ALIASES = {
  premise: 'premise',
  logline: 'premise',
  position: 'premise',
  '作品定位': 'premise',
  '一句话定位': 'premise',
  targetReader: 'targetReader',
  target_reader: 'targetReader',
  readers: 'targetReader',
  readerProfile: 'targetReader',
  '目标读者': 'targetReader',
  '读者画像': 'targetReader',
  styleBible: 'styleBible',
  style_bible: 'styleBible',
  style: 'styleBible',
  tone: 'styleBible',
  '风格要求': 'styleBible',
  '风格圣经': 'styleBible',
  themeBible: 'themeBible',
  theme_bible: 'themeBible',
  theme: 'themeBible',
  motifs: 'themeBible',
  '主题与母题': 'themeBible',
  '主题母题': 'themeBible',
  worldRules: 'worldRules',
  world_rules: 'worldRules',
  rules: 'worldRules',
  worldview: 'worldRules',
  '世界规则': 'worldRules',
  '世界观规则': 'worldRules',
  writingProfile: 'writingProfile',
  writing_profile: 'writingProfile',
  writingStrategy: 'writingProfile',
  '写作策略': 'writingProfile',
  '题材风格标准': 'writingProfile',
  '写作标准': 'writingProfile',
  forbiddenDirections: 'forbiddenDirections',
  forbidden_directions: 'forbiddenDirections',
  forbidden: 'forbiddenDirections',
  risks: 'forbiddenDirections',
  doNotWrite: 'forbiddenDirections',
  '禁止方向': 'forbiddenDirections',
  '禁区': 'forbiddenDirections',
  '不要写': 'forbiddenDirections'
}

const BIBLE_LABELS = Object.keys(BIBLE_FIELD_ALIASES).sort((a, b) => b.length - a.length)

export function normalizeBiblePayload(raw = {}) {
  const payload = pickBiblePayload(raw) || {}
  const normalized = Object.fromEntries(BIBLE_FIELDS.map(field => [
    field,
    field === 'forbiddenDirections' ? [] : field === 'writingProfile' ? {} : ''
  ]))

  for (const [key, value] of Object.entries(payload)) {
    const cleanKey = String(key).trim()
    const field = BIBLE_FIELD_ALIASES[cleanKey] || BIBLE_FIELD_ALIASES[cleanKey.toLowerCase()] || cleanKey
    if (!BIBLE_FIELDS.includes(field)) continue

    if (field === 'forbiddenDirections') {
      const tags = normalizeTags(value)
      if (tags.length) normalized.forbiddenDirections = tags
    } else if (field === 'writingProfile') {
      const profile = normalizeWritingProfilePayload(value)
      if (Object.keys(profile).some(key => profile[key])) normalized.writingProfile = profile
    } else {
      const text = normalizeText(value)
      if (text) normalized[field] = text
    }
  }

  return normalized
}

function hasUsableBible(payload) {
  return Boolean(
    payload.premise
    || payload.targetReader
    || payload.styleBible
    || payload.themeBible
    || payload.worldRules
    || Object.keys(payload.writingProfile || {}).length
    || payload.forbiddenDirections.length
  )
}

function cleanupLooseValue(value) {
  return (value || '')
    .replace(/^\s*[-*、，。；;]\s*/, '')
    .replace(/^\s*["'`]/, '')
    .replace(/["'`]\s*,?\s*$/g, '')
    .replace(/\s*,\s*$/g, '')
    .replace(/\s*[}\]]\s*$/g, '')
    .replace(/\\"/g, '"')
    .replace(/\\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function splitLooseTags(value) {
  const text = cleanupLooseValue(value)
  if (!text) return []

  try {
    const parsed = JSON.parse(text)
    if (Array.isArray(parsed)) return normalizeTags(parsed)
  } catch {
    // Fall back to text splitting below.
  }

  return normalizeTags(
    text
      .replace(/^\[/, '')
      .replace(/\]$/, '')
      .replace(/["'`]/g, '')
  )
}

function extractLooseBible(text) {
  const labelPattern = BIBLE_LABELS.map(escapeRegExp).join('|')
  const regex = new RegExp(`(?:^|\\n|\\s|[,{\\[])(?:[-*+]|\\d+[.)、])?\\s*(?:["'\`])?(${labelPattern})(?:["'\`])?\\s*[:：]`, 'gi')
  const matches = [...text.matchAll(regex)]
  if (!matches.length) return null

  const raw = {}
  for (let i = 0; i < matches.length; i += 1) {
    const match = matches[i]
    const label = match[1]
    const field = BIBLE_FIELD_ALIASES[label] || BIBLE_FIELD_ALIASES[label.toLowerCase()]
    const start = match.index + match[0].length
    const end = i + 1 < matches.length ? matches[i + 1].index : text.length
    const value = text.slice(start, end)

    if (!field) continue
    raw[field] = field === 'forbiddenDirections'
      ? splitLooseTags(value)
      : cleanupLooseValue(value)
  }

  const normalized = normalizeBiblePayload(raw)
  return hasUsableBible(normalized) ? normalized : null
}

export function extractBibleFromText(text) {
  if (!text) return null

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
      const normalized = normalizeBiblePayload(parsed)
      if (hasUsableBible(normalized)) return normalized
    } catch {
      // Try the next candidate.
    }
  }

  return extractLooseBible(text)
}
