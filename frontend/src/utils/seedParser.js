const FIELD_ALIASES = {
  title: 'title',
  seedTitle: 'title',
  seed_title: 'title',
  'seed title': 'title',
  storyTitle: 'title',
  story_title: 'title',
  'story title': 'title',
  name: 'title',
  '作品名': 'title',
  '作品标题': 'title',
  '作品暂定名': 'title',
  '种子标题': 'title',
  '故事名': 'title',
  '标题': 'title',
  genre: 'genre',
  category: 'genre',
  type: 'genre',
  '题材': 'genre',
  '类型': 'genre',
  logline: 'logline',
  summary: 'logline',
  synopsis: 'logline',
  tagline: 'logline',
  premise: 'logline',
  '一句话故事': 'logline',
  '一句话梗概': 'logline',
  '故事梗概': 'logline',
  '核心卖点': 'logline',
  '一句话': 'logline',
  protagonist: 'protagonist',
  hero: 'protagonist',
  lead: 'protagonist',
  mainCharacter: 'protagonist',
  main_character: 'protagonist',
  'main character': 'protagonist',
  '主角设定': 'protagonist',
  '主角简介': 'protagonist',
  '主角': 'protagonist',
  desire: 'desire',
  goal: 'desire',
  motivation: 'desire',
  protagonistDesire: 'desire',
  protagonist_desire: 'desire',
  'protagonist desire': 'desire',
  '主角欲望': 'desire',
  coreConflict: 'coreConflict',
  core_conflict: 'coreConflict',
  'core conflict': 'coreConflict',
  conflict: 'coreConflict',
  centralConflict: 'coreConflict',
  central_conflict: 'coreConflict',
  'central conflict': 'coreConflict',
  '核心矛盾': 'coreConflict',
  worldPressure: 'worldPressure',
  world_pressure: 'worldPressure',
  'world pressure': 'worldPressure',
  pressure: 'worldPressure',
  externalPressure: 'worldPressure',
  external_pressure: 'worldPressure',
  'external pressure': 'worldPressure',
  '外部压力': 'worldPressure',
  '世界压力': 'worldPressure',
  openingHook: 'openingHook',
  opening_hook: 'openingHook',
  'opening hook': 'openingHook',
  hook: 'openingHook',
  opening: 'openingHook',
  '开篇钩子': 'openingHook',
  '开局': 'openingHook',
  '开篇': 'openingHook',
  '开局钩子': 'openingHook',
  emotionalPromise: 'emotionalPromise',
  emotional_promise: 'emotionalPromise',
  'emotional promise': 'emotionalPromise',
  appeal: 'emotionalPromise',
  readerPromise: 'emotionalPromise',
  reader_promise: 'emotionalPromise',
  'reader promise': 'emotionalPromise',
  '读者期待': 'emotionalPromise',
  '情绪承诺': 'emotionalPromise',
  '情绪价值': 'emotionalPromise',
  differentiation: 'differentiation',
  difference: 'differentiation',
  uniqueAngle: 'differentiation',
  unique_angle: 'differentiation',
  'unique angle': 'differentiation',
  '差异化理由': 'differentiation',
  '独特性': 'differentiation',
  '差异化': 'differentiation',
  styleTarget: 'styleTarget',
  style_target: 'styleTarget',
  'style target': 'styleTarget',
  style: 'styleTarget',
  tone: 'styleTarget',
  '风格': 'styleTarget',
  '风格目标': 'styleTarget',
  riskNotes: 'riskNotes',
  risk_notes: 'riskNotes',
  'risk notes': 'riskNotes',
  risks: 'riskNotes',
  risk: 'riskNotes',
  '风险': 'riskNotes',
  '风险提示': 'riskNotes',
  endingAnchor: 'endingAnchor',
  ending_anchor: 'endingAnchor',
  'ending anchor': 'endingAnchor',
  ending: 'endingAnchor',
  '结局锚点': 'endingAnchor',
  '结尾锚点': 'endingAnchor',
  '结局': 'endingAnchor'
}

const SEED_FIELDS = [
  'title',
  'genre',
  'logline',
  'protagonist',
  'desire',
  'coreConflict',
  'worldPressure',
  'openingHook',
  'emotionalPromise',
  'differentiation',
  'styleTarget',
  'riskNotes',
  'endingAnchor'
]

function normalizeValue(value) {
  if (value == null) return ''
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) return value.filter(Boolean).join('、')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function normalizeSeedPayload(raw = {}) {
  const normalized = Object.fromEntries(SEED_FIELDS.map(field => [field, '']))

  for (const [key, value] of Object.entries(raw || {})) {
    const cleanKey = String(key).trim()
    const target = FIELD_ALIASES[cleanKey] || FIELD_ALIASES[cleanKey.toLowerCase()] || cleanKey
    if (SEED_FIELDS.includes(target)) {
      normalized[target] = normalizeValue(value)
    }
  }

  return normalized
}

function cleanJsonCandidate(candidate) {
  return candidate
    .trim()
    .replace(/^\uFEFF/, '')
    .replace(/^json\s*/i, '')
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/：/g, ':')
    .replace(/,\s*([}\]])/g, '$1')
}

const LOOSE_LABELS = Object.keys(FIELD_ALIASES)
  .sort((a, b) => b.length - a.length)

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
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
        if (escaped) {
          escaped = false
        } else if (ch === '\\') {
          escaped = true
        } else if (ch === '"') {
          inString = false
        }
        continue
      }

      if (ch === '"') {
        inString = true
      } else if (ch === openChar) {
        depth += 1
      } else if (ch === closeChar) {
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

function parseSeedCandidate(candidate) {
  try {
    const parsed = JSON.parse(cleanJsonCandidate(candidate))
    if (Array.isArray(parsed)) return parsed
    if (Array.isArray(parsed?.seeds)) return parsed.seeds
    if (Array.isArray(parsed?.data)) return parsed.data
    if (parsed && typeof parsed === 'object') return [parsed]
  } catch {
    return null
  }
  return null
}

function cleanupLooseValue(value) {
  return (value || '')
    .replace(/^\s*[-*、，。；;]\s*/, '')
    .replace(/^\s*["'`]/, '')
    .replace(/["'`]\s*,?\s*$/g, '')
    .replace(/\s*,\s*$/g, '')
    .replace(/\s*[\]}]\s*$/g, '')
    .replace(/\\"/g, '"')
    .replace(/\\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function extractLooseSeedFromBlock(block) {
  const labelPattern = LOOSE_LABELS.map(escapeRegExp).join('|')
  const regex = new RegExp(`(?:^|\\n|\\s|[,{\\[])(?:[-*+]|\\d+[.)、])?\\s*(?:["'\`])?(?:\\*\\*)?(${labelPattern})(?:\\*\\*)?(?:["'\`])?(?:（[^）]*）|\\([^)]*\\))?\\s*[：:]`, 'gi')
  const matches = [...block.matchAll(regex)]
  if (!matches.length) return null

  const raw = {}
  for (let i = 0; i < matches.length; i += 1) {
    const match = matches[i]
    const label = match[1]
    const field = FIELD_ALIASES[label] || FIELD_ALIASES[label.toLowerCase()]
    const start = match.index + match[0].length
    const end = i + 1 < matches.length ? matches[i + 1].index : block.length
    const value = cleanupLooseValue(block.slice(start, end))
    if (!field || !SEED_FIELDS.includes(field) || !value) continue
    raw[field] = raw[field] ? `${raw[field]}\n${value}` : value
  }

  const heading = block.match(/(?:^|\n)\s*(?:#{1,6}\s*)?(?:种子|方案|方向)\s*[一二三四五六七八九十\d]*[：:、.\s-]*([^\n]{2,40})/)
  if (!raw.title && heading?.[1]) {
    raw.title = heading[1].replace(/[《》]/g, '').trim()
  }

  const bracketTitle = block.match(/《([^》]{2,40})》/)
  if (!raw.title && bracketTitle?.[1]) raw.title = bracketTitle[1].trim()

  return normalizeSeedPayload(raw)
}

function extractLooseSeeds(text) {
  const cleaned = text
    .replace(/```(?:json|JSON)?\s*/g, '\n')
    .replace(/```/g, '\n')
    .replace(/<think>[\s\S]*?<\/think>/gi, '\n')

  const headingRegex = /(?:^|\n)\s*(?:#{1,6}\s*)?(?:种子|方案|方向)\s*[一二三四五六七八九十\d]+[：:、.\s-]*/g
  const headingMatches = [...cleaned.matchAll(headingRegex)]
  let blocks = []

  if (headingMatches.length > 1) {
    blocks = headingMatches.map((match, index) => {
      const start = match.index
      const end = index + 1 < headingMatches.length ? headingMatches[index + 1].index : cleaned.length
      return cleaned.slice(start, end)
    })
  } else {
    const titleLabelRegex = /(?:^|\n|\s|[,{[])(?:[-*+]|\d+[.)、])?\s*(?:["'`])?(?:\*\*)?(?:标题|作品名|作品标题|作品暂定名|种子标题|title|seedTitle|storyTitle)(?:\*\*)?(?:["'`])?\s*[：:]/gi
    const titleMatches = [...cleaned.matchAll(titleLabelRegex)]
    if (titleMatches.length > 1) {
      blocks = titleMatches.map((match, index) => {
        const start = match.index
        const end = index + 1 < titleMatches.length ? titleMatches[index + 1].index : cleaned.length
        return cleaned.slice(start, end)
      })
    } else {
      blocks = [cleaned]
    }
  }

  return blocks
    .map(extractLooseSeedFromBlock)
    .filter(seed => seed && (seed.title || seed.logline || seed.openingHook))
}

export function extractSeedsFromText(text) {
  if (!text) return []

  const candidates = []
  const fenceRegex = /```(?:json)?\s*([\s\S]*?)```/gi
  let match = fenceRegex.exec(text)
  while (match) {
    candidates.push(match[1])
    match = fenceRegex.exec(text)
  }

  candidates.push(...collectBalancedCandidates(text, '[', ']'))
  candidates.push(...collectBalancedCandidates(text, '{', '}'))

  for (const candidate of candidates) {
    const parsed = parseSeedCandidate(candidate)
    if (!parsed) continue

    const seeds = parsed
      .filter(item => item && typeof item === 'object')
      .map(normalizeSeedPayload)
      .filter(seed => seed.title || seed.logline || seed.openingHook)

    if (seeds.length) return seeds
  }

  return extractLooseSeeds(text)
}
