const DEFAULT_FORBIDDEN_IMITATION = [
  '不得复刻人物名、地名、势力名、专有名词、独创设定名',
  '不得复刻原句、连续表达、标志性比喻和独有段落结构',
  '只能提炼写法方法、节奏习惯和叙事组织方式'
]

const FINGERPRINT_FIELDS = [
  ['chapterEntry', '章节进入'],
  ['chapterExit', '章节结尾'],
  ['dialogueMethod', '对话方式'],
  ['characterMethod', '人物方法'],
  ['ensembleMethod', '群像方法'],
  ['challengeMethod', '任务/挑战'],
  ['emotionMethod', '情绪呈现'],
  ['informationMethod', '信息释放'],
  ['proseRhythm', '语言节奏']
]

function cleanText(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function cleanList(value) {
  if (!Array.isArray(value)) return []
  return [...new Set(value
    .map(item => cleanText(item))
    .filter(Boolean))]
}

function cleanObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return Object.fromEntries(
    Object.entries(value)
      .filter(([, item]) => ['string', 'number', 'boolean'].includes(typeof item) || Array.isArray(item))
      .map(([key, item]) => [key, Array.isArray(item) ? cleanList(item) : item])
  )
}

export function createWritingFingerprintCard(input = {}) {
  return {
    id: cleanText(input.id) || `fingerprint-${Date.now()}`,
    sourceTitle: cleanText(input.sourceTitle) || '未命名样本',
    sourceMode: cleanText(input.sourceMode) || 'local_sample',
    sourceNote: cleanText(input.sourceNote),
    genreTags: cleanList(input.genreTags),
    chapterEntry: cleanText(input.chapterEntry),
    chapterExit: cleanText(input.chapterExit),
    dialogueMethod: cleanText(input.dialogueMethod),
    characterMethod: cleanText(input.characterMethod),
    ensembleMethod: cleanText(input.ensembleMethod),
    challengeMethod: cleanText(input.challengeMethod),
    emotionMethod: cleanText(input.emotionMethod),
    informationMethod: cleanText(input.informationMethod),
    proseRhythm: cleanText(input.proseRhythm),
    avoidPatterns: cleanList(input.avoidPatterns),
    metrics: cleanObject(input.metrics),
    analysisNotes: cleanList(input.analysisNotes),
    forbiddenImitation: cleanList([
      ...DEFAULT_FORBIDDEN_IMITATION,
      ...cleanList(input.forbiddenImitation)
    ]),
    noDirectImitation: true
  }
}

export function formatWritingFingerprintCardForPrompt(input = {}) {
  const card = createWritingFingerprintCard(input)
  const lines = [
    `### 写作指纹卡：${card.sourceTitle}`,
    card.genreTags.length ? `题材标签：${card.genreTags.join('、')}` : '',
    card.sourceNote ? `来源说明：${card.sourceNote}` : ''
  ].filter(Boolean)

  for (const [key, label] of FINGERPRINT_FIELDS) {
    if (card[key]) lines.push(`${label}：${card[key]}`)
  }

  if (card.avoidPatterns.length) {
    lines.push(`避免项：${card.avoidPatterns.join('；')}`)
  }

  lines.push(`禁止复刻：${card.forbiddenImitation.join('；')}`)
  return lines.join('\n')
}

export function formatWritingFingerprintCardsForPrompt(cards = [], options = {}) {
  const maxCards = Number.isFinite(options.maxCards) ? Math.max(1, options.maxCards) : 3
  const selected = Array.isArray(cards) ? cards.slice(0, maxCards) : []
  if (!selected.length) return ''
  return selected.map(card => formatWritingFingerprintCardForPrompt(card)).join('\n\n')
}

export function buildWritingFingerprintSections(guidance = {}) {
  return [
    { key: 'chapterEngine', label: '章节组织', text: cleanText(guidance.chapterEngine) },
    { key: 'dialogueMethod', label: '对话方式', text: cleanText(guidance.dialogueMethod) },
    { key: 'characterMethod', label: '人物方法', text: cleanText(guidance.characterMethod) },
    { key: 'ensembleMethod', label: '群像方法', text: cleanText(guidance.ensembleMethod) },
    { key: 'challengeMethod', label: '任务/挑战', text: cleanText(guidance.challengeMethod) },
    { key: 'emotionMethod', label: '情绪呈现', text: cleanText(guidance.emotionMethod) },
    { key: 'informationMethod', label: '信息释放', text: cleanText(guidance.informationMethod) },
    { key: 'proseRhythm', label: '语言节奏', text: cleanText(guidance.proseRhythm) },
    { key: 'endingPreference', label: '结尾倾向', text: cleanText(guidance.endingPreference) },
    { key: 'avoid', label: '避免项', text: cleanText(guidance.avoid) }
  ].filter(section => section.text)
}
