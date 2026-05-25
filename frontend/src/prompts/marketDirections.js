export function buildMarketDirectionPrompt({ project, keywords, items }) {
  const itemLines = (items || []).slice(0, 40).map((item, index) => {
    const tags = Array.isArray(item.tags) ? item.tags.join('、') : (item.tags || '')
    return `${index + 1}. ${item.title || '未知作品'}｜${item.platform || '未知平台'}｜${item.category || '未分类'}｜${item.rankName || ''}${item.rankPosition ? `#${item.rankPosition}` : ''}
简介：${item.intro || '无'}
标签：${tags}
热度：${item.heatText || ''}`
  }).join('\n\n')

  return `你是一位网文选题策划编辑。请根据当前抓取到的热门小说和平台线索，提炼 4-6 个“值得作者进一步讨论和孵化”的创作方向。

目标：
- 不是复刻热门作品，而是判断读者近期可能期待的题材、情绪价值和可差异化切入点。
- 输出要能直接成为作者和 AI 选题顾问继续讨论的入口。
- 每个方向必须具体，不要只写“玄幻升级流”“都市爽文”这种泛词。

当前项目：
- 项目名：${project?.title || '未命名项目'}
- 题材：${project?.genre || '未设置'}
- 简介：${project?.description || '无'}
- 本次搜索关键词：${keywords || '热门小说'}

抓取数据：
${itemLines || '暂无抓取数据，请基于常见网文市场经验给出保守建议。'}

请严格输出合法 JSON 对象，不要输出 Markdown，不要写解释文字。顶层固定为 "directions"：
{
  "directions": [
    {
      "title": "方向标题，12-24字",
      "genre": "题材类型",
      "readerExpectation": "读者可能期待什么情绪和体验",
      "whyNow": "为什么从当前抓取结果看这个方向值得关注",
      "seedAngle": "可孵化成原创种子的具体切入角度",
      "evidence": "引用2-3个抓取数据中的平台/作品/标签作为依据",
      "risks": "容易写俗、写崩或撞车的风险",
      "discussionPrompt": "用户拿去问AI选题顾问的一句话"
    }
  ]
}`
}

const DIRECTION_FIELD_ALIASES = {
  title: 'title',
  name: 'title',
  '方向标题': 'title',
  '标题': 'title',
  '方向': 'title',
  genre: 'genre',
  category: 'genre',
  type: 'genre',
  '题材': 'genre',
  '类型': 'genre',
  readerExpectation: 'readerExpectation',
  reader_expectation: 'readerExpectation',
  'reader expectation': 'readerExpectation',
  expectation: 'readerExpectation',
  '读者期待': 'readerExpectation',
  '读者可能期待': 'readerExpectation',
  '情绪价值': 'readerExpectation',
  whyNow: 'whyNow',
  why_now: 'whyNow',
  'why now': 'whyNow',
  reason: 'whyNow',
  '为什么值得关注': 'whyNow',
  '为什么值得看': 'whyNow',
  '值得关注': 'whyNow',
  '趋势依据': 'whyNow',
  seedAngle: 'seedAngle',
  seed_angle: 'seedAngle',
  'seed angle': 'seedAngle',
  angle: 'seedAngle',
  '可切入': 'seedAngle',
  '切入角度': 'seedAngle',
  '可孵化角度': 'seedAngle',
  '原创切入': 'seedAngle',
  evidence: 'evidence',
  proof: 'evidence',
  '依据': 'evidence',
  '数据依据': 'evidence',
  '参考依据': 'evidence',
  risks: 'risks',
  risk: 'risks',
  '风险': 'risks',
  '注意风险': 'risks',
  discussionPrompt: 'discussionPrompt',
  discussion_prompt: 'discussionPrompt',
  'discussion prompt': 'discussionPrompt',
  prompt: 'discussionPrompt',
  '讨论提示': 'discussionPrompt',
  '提问话术': 'discussionPrompt'
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

function normalizeDirectionList(parsed) {
  const list = Array.isArray(parsed)
    ? parsed
    : Array.isArray(parsed?.directions)
      ? parsed.directions
      : Array.isArray(parsed?.data)
        ? parsed.data
        : Array.isArray(parsed?.items)
          ? parsed.items
          : looksLikeDirectionPayload(parsed)
            ? [parsed]
            : []

  return list
    .filter(item => item && typeof item === 'object')
    .map(normalizeDirectionPayload)
    .filter(item => item.title || item.seedAngle)
}

function looksLikeDirectionPayload(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  return Object.keys(value).some(key => {
    const cleanKey = String(key).trim()
    return Boolean(DIRECTION_FIELD_ALIASES[cleanKey] || DIRECTION_FIELD_ALIASES[cleanKey.toLowerCase()])
  })
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function normalizeDirectionPayload(raw = {}) {
  const normalized = {
    title: '',
    genre: '',
    readerExpectation: '',
    whyNow: '',
    seedAngle: '',
    evidence: '',
    risks: '',
    discussionPrompt: ''
  }

  for (const [key, value] of Object.entries(raw || {})) {
    const cleanKey = String(key).trim()
    const target = DIRECTION_FIELD_ALIASES[cleanKey] || DIRECTION_FIELD_ALIASES[cleanKey.toLowerCase()] || cleanKey
    if (target in normalized) {
      normalized[target] = Array.isArray(value)
        ? value.filter(Boolean).join('、')
        : value == null
          ? ''
          : String(value).trim()
    }
  }

  return normalized
}

const DIRECTION_LABELS = Object.keys(DIRECTION_FIELD_ALIASES).sort((a, b) => b.length - a.length)

function cleanupLooseValue(value) {
  return (value || '')
    .replace(/^\s*[-*、，。；;]\s*/, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function extractLooseDirectionFromBlock(block) {
  const labelPattern = DIRECTION_LABELS.map(escapeRegExp).join('|')
  const regex = new RegExp(`(?:^|\\n|\\s)(?:[-*+]|\\d+[.)、])?\\s*(?:\\*\\*)?(${labelPattern})(?:\\*\\*)?\\s*[：:]`, 'gi')
  const matches = [...block.matchAll(regex)]
  if (!matches.length) return null

  const raw = {}
  for (let i = 0; i < matches.length; i += 1) {
    const match = matches[i]
    const label = match[1]
    const field = DIRECTION_FIELD_ALIASES[label] || DIRECTION_FIELD_ALIASES[label.toLowerCase()]
    const start = match.index + match[0].length
    const end = i + 1 < matches.length ? matches[i + 1].index : block.length
    const value = cleanupLooseValue(block.slice(start, end))
    if (!field || !value) continue
    raw[field] = raw[field] ? `${raw[field]}\n${value}` : value
  }

  const heading = block.match(/(?:^|\n)\s*(?:#{1,6}\s*)?(?:方向|建议)\s*[一二三四五六七八九十\d]*[：:、.\s-]*([^\n]{2,40})/)
  if (!raw.title && heading?.[1]) raw.title = heading[1].trim()

  return normalizeDirectionPayload(raw)
}

function extractLooseDirections(text) {
  const cleaned = text
    .replace(/```[\s\S]*?```/g, '\n')
    .replace(/<think>[\s\S]*?<\/think>/gi, '\n')

  const headingRegex = /(?:^|\n)\s*(?:#{1,6}\s*)?(?:方向|建议)\s*[一二三四五六七八九十\d]+[：:、.\s-]*/g
  const headingMatches = [...cleaned.matchAll(headingRegex)]
  let blocks = []

  if (headingMatches.length > 1) {
    blocks = headingMatches.map((match, index) => {
      const start = match.index
      const end = index + 1 < headingMatches.length ? headingMatches[index + 1].index : cleaned.length
      return cleaned.slice(start, end)
    })
  } else {
    const titleLabelRegex = /(?:^|\n|\s)(?:[-*+]|\d+[.)、])?\s*(?:\*\*)?(?:方向标题|标题|title|name)(?:\*\*)?\s*[：:]/gi
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
    .map(extractLooseDirectionFromBlock)
    .filter(direction => direction && (direction.title || direction.seedAngle))
}

export function extractMarketDirections(text) {
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
      const directions = normalizeDirectionList(parsed)
      if (directions.length) return directions
    } catch {
      // Try the next candidate.
    }
  }

  return extractLooseDirections(text)
}

export function buildFallbackMarketDirections({ keywords = '', items = [], project } = {}) {
  const groups = groupMarketItems(items)
  const topGroups = groups.length ? groups.slice(0, 4) : [{
    genre: project?.genre || keywords || '综合热门',
    items: [],
    platforms: [],
    tags: []
  }]

  return topGroups.map((group, index) => {
    const sampleTitles = group.items.slice(0, 3).map(item => item.title).filter(Boolean)
    const platformText = group.platforms.slice(0, 3).join('、') || '本地样本'
    const tagText = group.tags.slice(0, 5).join('、') || group.genre
    const title = buildFallbackDirectionTitle(group.genre, keywords, index)

    return normalizeDirectionPayload({
      title,
      genre: group.genre,
      readerExpectation: `读者可能期待${group.genre}题材里的强钩子、清晰爽点和持续升级反馈，同时希望看到区别于同类套路的新设定或新场景。`,
      whyNow: group.items.length
        ? `当前样本中 ${platformText} 出现了 ${sampleTitles.join('、') || group.genre} 等相关作品，说明该方向具备一定热度参考。`
        : `实时 AI 方向解析失败，系统基于“${keywords || project?.genre || '热门小说'}”给出保守选题方向，适合作为后续和 AI 顾问讨论的起点。`,
      seedAngle: `不要复刻样本作品，可从“${tagText}”中选一个核心情绪，再换主角身份、时代背景或能力规则做原创切入。`,
      evidence: group.items.length
        ? `${platformText}；参考作品：${sampleTitles.join('、') || '暂无明确书名'}；标签：${tagText}`
        : '本地保守建议，无实时 AI 结构化结果。',
      risks: '容易只追热点而缺少原创核心；需要尽快落到主角欲望、长期矛盾和前三章钩子，避免停留在题材口号。',
      discussionPrompt: `我想讨论“${title}”这个方向，请结合当前热点样本，帮我拆成一个不撞车、有前三章钩子的原创创作种子。`
    })
  })
}

function groupMarketItems(items = []) {
  const map = new Map()
  for (const item of items || []) {
    const genre = String(item.category || item.genre || item.rankName || '综合热门').trim() || '综合热门'
    if (!map.has(genre)) {
      map.set(genre, {
        genre,
        items: [],
        platformCounts: new Map(),
        tagCounts: new Map()
      })
    }
    const group = map.get(genre)
    group.items.push(item)
    const platform = item.platform || '未知平台'
    group.platformCounts.set(platform, (group.platformCounts.get(platform) || 0) + 1)
    const tags = Array.isArray(item.tags) ? item.tags : String(item.tags || '').split(/[、,\s]+/)
    for (const tag of tags.filter(Boolean)) {
      group.tagCounts.set(tag, (group.tagCounts.get(tag) || 0) + 1)
    }
  }

  return [...map.values()]
    .map(group => ({
      genre: group.genre,
      items: group.items,
      platforms: [...group.platformCounts.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name),
      tags: [...group.tagCounts.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name)
    }))
    .sort((a, b) => b.items.length - a.items.length)
}

function buildFallbackDirectionTitle(genre, keywords, index) {
  const cleanGenre = genre || '热门题材'
  const cleanKeywords = String(keywords || '').replace(/\s+/g, '')
  const suffixes = ['情绪升级方向', '差异化切入方向', '强钩子试写方向', '长线连载方向']
  if (cleanKeywords && !cleanGenre.includes(cleanKeywords)) {
    return `${cleanKeywords}${cleanGenre}${suffixes[index % suffixes.length]}`
  }
  return `${cleanGenre}${suffixes[index % suffixes.length]}`
}

export function buildMarketDirectionRepairPrompt(rawText) {
  return `下面是一段 AI 对热点小说数据生成的方向建议，但格式可能不是合法 JSON，也可能是 Markdown/编号列表/中文标签。请把其中已有方向建议结构化，不要解释。

允许做的事：
- 从原文中提取方向标题、题材、读者期待、趋势依据、可切入角度、风险、讨论提示。
- 原文有明确信息但字段名不同，可以归并到最接近的字段。
- 不要编造原文没有的新市场判断，不要补充本地样本。

请严格输出合法 JSON 对象，顶层只有 "directions" 字段：
{
  "directions": [
    {
      "title": "",
      "genre": "",
      "readerExpectation": "",
      "whyNow": "",
      "seedAngle": "",
      "evidence": "",
      "risks": "",
      "discussionPrompt": ""
    }
  ]
}

原始内容：
${rawText}`
}
