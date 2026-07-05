export const REAL_CORPUS_CARD_SCHEMA_VERSION = 'real-corpus-experience-card-v3'
export const REAL_CORPUS_LIBRARY_SCHEMA_VERSION = 'real-corpus-experience-cards-v3'

export const REAL_CORPUS_PROMPT_READY = 'prompt-ready-low-dose'
export const REAL_CORPUS_BACKEND_REFERENCE_ONLY = 'backend-reference-only'
export const REAL_CORPUS_NEEDS_HUMAN_REVIEW = 'needs-human-review'
export const REAL_CORPUS_REJECTED = 'rejected'

export const REAL_CORPUS_SCENE_FUNCTION_TAGS = [
  'dialogue_conflict',
  'emotion_variation',
  'character_humanity',
  'scene_dwell',
  'setting_naturalization',
  'aftermath',
  'longform_rhythm',
  'action_burst'
]

const PROMPT_READINESS_VALUES = new Set([
  REAL_CORPUS_PROMPT_READY,
  REAL_CORPUS_BACKEND_REFERENCE_ONLY,
  REAL_CORPUS_NEEDS_HUMAN_REVIEW,
  REAL_CORPUS_REJECTED
])

const REQUIRED_SAFETY_FLAGS = [
  'no_raw_excerpt',
  'no_source_text',
  'no_source_names',
  'no_direct_imitation',
  'no_long_quote',
  'expression_only'
]

const FORBIDDEN_CARD_KEYS = new Set([
  'rawExcerpt',
  'sourceText',
  'sourceCardIds',
  'sourceWindows',
  'rawWindows',
  'quotedText'
])

const PROMPT_FACING_FIELDS = [
  'applicableScenes',
  'writingMethod',
  'promptInjectionSafeVersion',
  'originalMicroDemo',
  'antiAiReminder',
  'notApplicableScenes',
  'riskNotes'
]

function hasText(value) {
  return value !== undefined && value !== null && String(value).trim() !== ''
}

function asArray(value) {
  if (Array.isArray(value)) return value
  return hasText(value) ? [value] : []
}

function compact(value, limit = 360) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit).replace(/[，。；;,. ]+$/, '')}。` : text
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function promptFacingText(card = {}) {
  return PROMPT_FACING_FIELDS
    .flatMap(field => asArray(card[field]))
    .filter(hasText)
    .join('\n')
}

export function sourceNameTokensForCard(card = {}) {
  return [
    card.sourceTitle,
    card.sourceFileName
  ].flatMap(value => String(value || '')
    .replace(/\.[^.]+$/u, '')
    .split(/[《》【】\[\]（）()：:·,，。_\-\s]+/u)
    .map(token => token.trim())
    .filter(token => token.length >= 2)
    .filter(token => !/^(txt|TXT|com|www)$/i.test(token))
  )
}

function assertCard(condition, cardId, message) {
  if (!condition) throw new Error(`${cardId || 'unknown-card'}: ${message}`)
}

export function validateRealCorpusExperienceCardV3(card = {}) {
  const cardId = card.cardId || ''
  assertCard(card.schemaVersion === REAL_CORPUS_CARD_SCHEMA_VERSION, cardId, 'invalid schemaVersion')
  assertCard(hasText(cardId), cardId, 'missing cardId')
  assertCard(hasText(card.sourceTitle), cardId, 'missing sourceTitle')
  assertCard(/^[a-f0-9]{64}$/.test(card.sourceFileHash || ''), cardId, 'invalid sourceFileHash')
  assertCard(card.sourceAuditOnly === true, cardId, 'sourceAuditOnly must be true')
  assertCard(Array.isArray(card.sourceWindowHashes) && card.sourceWindowHashes.length >= 2, cardId, 'missing sourceWindowHashes')
  for (const hash of card.sourceWindowHashes || []) {
    assertCard(/^[a-f0-9]{64}$/.test(hash), cardId, 'invalid sourceWindowHash')
  }
  assertCard(Array.isArray(card.sceneFunctionTags) && card.sceneFunctionTags.length > 0, cardId, 'missing sceneFunctionTags')
  for (const tag of card.sceneFunctionTags) {
    assertCard(REAL_CORPUS_SCENE_FUNCTION_TAGS.includes(tag), cardId, `unknown sceneFunctionTag ${tag}`)
  }
  for (const field of ['applicableScenes', 'writingMethod', 'promptInjectionSafeVersion', 'originalMicroDemo', 'antiAiReminder', 'notApplicableScenes', 'riskNotes']) {
    assertCard(hasText(asArray(card[field]).join(' ')), cardId, `missing ${field}`)
  }
  assertCard(PROMPT_READINESS_VALUES.has(card.promptReadiness), cardId, 'invalid promptReadiness')
  for (const key of Object.keys(card)) {
    assertCard(!FORBIDDEN_CARD_KEYS.has(key), cardId, `forbidden raw/source key ${key}`)
  }
  for (const flag of REQUIRED_SAFETY_FLAGS) {
    assertCard(card.safetyFlags?.[flag] === true, cardId, `safety flag ${flag} must be true`)
  }
  const promptText = promptFacingText(card)
  if (hasText(card.sourceTitle)) {
    assertCard(!new RegExp(escapeRegExp(card.sourceTitle)).test(promptText), cardId, 'prompt-facing fields contain sourceTitle')
  }
  for (const token of sourceNameTokensForCard(card)) {
    assertCard(!new RegExp(escapeRegExp(token)).test(promptText), cardId, `prompt-facing fields contain source token ${token}`)
  }
  assertCard(!/(sourceTitle|sourceFileHash|sourceWindowHashes|rawExcerpt|sourceText|sourceCardIds)/i.test(promptText), cardId, 'prompt-facing fields contain source/audit tokens')
  return true
}

export function validateRealCorpusExperienceCardsV3(library = {}) {
  if (library.schemaVersion !== REAL_CORPUS_LIBRARY_SCHEMA_VERSION) {
    throw new Error('invalid real corpus library schemaVersion')
  }
  if (!Array.isArray(library.cards)) throw new Error('real corpus library cards must be an array')
  const seen = new Set()
  for (const card of library.cards) {
    validateRealCorpusExperienceCardV3(card)
    if (seen.has(card.cardId)) throw new Error(`duplicate real corpus cardId ${card.cardId}`)
    seen.add(card.cardId)
  }
  return true
}

function sceneText(sceneCard = {}) {
  return [
    sceneCard.sceneObjective,
    sceneCard.conflictPair,
    sceneCard.emotionalTurn,
    sceneCard.dialogueTask,
    sceneCard.physicalPressure,
    sceneCard.facialVoiceCues,
    sceneCard.environmentalPressure,
    sceneCard.stopPoint,
    sceneCard.expressionGap,
    sceneCard.sceneFunction,
    asArray(sceneCard.sceneFunctionTags).join(' ')
  ].filter(hasText).join('\n')
}

export function inferSceneFunctionTags(sceneCard = {}) {
  const text = sceneText(sceneCard)
  const tags = new Set(asArray(sceneCard.sceneFunctionTags).filter(tag => REAL_CORPUS_SCENE_FUNCTION_TAGS.includes(tag)))
  if (/对话|对白|谈判|审讯|质问|争执|否认|逼问|潜台词|conflict|dialogue/i.test(text)) tags.add('dialogue_conflict')
  if (/情绪|转折|误判|亲密|裂隙|迟疑|内心|emotion/i.test(text)) tags.add('emotion_variation')
  if (/人物|血肉|关系|顾虑|私心|humanity|character/i.test(text)) tags.add('character_humanity')
  if (/停留|场景|空间|环境|细节|dwell|scene/i.test(text)) tags.add('scene_dwell')
  if (/设定|规则|世界|证据|自然|信息|setting|rule|fact/i.test(text)) tags.add('setting_naturalization')
  if (/失败|余波|战后|后果|代价|aftermath/i.test(text)) tags.add('aftermath')
  if (/长篇|阶段|伏笔|节奏|handoff|longform/i.test(text)) tags.add('longform_rhythm')
  if (/追逐|动作|爆发|逃|打|冲|身体|action|burst/i.test(text)) tags.add('action_burst')
  return [...tags]
}

function scoreCardForScene(card, desiredTags, text) {
  const cardTags = new Set(card.sceneFunctionTags || [])
  let tagScore = 0
  for (const tag of desiredTags) {
    if (cardTags.has(tag)) tagScore += 8
  }
  let expressionScore = 0
  for (const scene of asArray(card.applicableScenes)) {
    for (const token of scene.split(/[，、,;\s]+/).filter(item => item.length >= 2)) {
      if (text.includes(token)) expressionScore += 1
    }
  }
  const eligibilityScore = tagScore + expressionScore
  let score = eligibilityScore
  if (card.promptReadiness === REAL_CORPUS_PROMPT_READY) score += 2
  if (card.promptReadiness === REAL_CORPUS_REJECTED) score -= 99
  return { score, eligibilityScore, expressionScore }
}

export function retrieveRealCorpusExperienceCards(sceneCard = {}, cards = [], options = {}) {
  const limit = Math.max(0, Math.min(Number(options.limit || 2), 2))
  if (!limit) return []
  const desiredTags = inferSceneFunctionTags(sceneCard)
  const text = sceneText(sceneCard)
  return [...(cards || [])]
    .filter(card => card?.promptReadiness === REAL_CORPUS_PROMPT_READY || card?.promptReadiness === REAL_CORPUS_BACKEND_REFERENCE_ONLY)
    .map(card => ({
      card,
      ...scoreCardForScene(card, desiredTags, text),
      matchedTags: (card.sceneFunctionTags || []).filter(tag => desiredTags.includes(tag))
    }))
    .filter(item => item.eligibilityScore > 0)
    .sort((left, right) => right.score - left.score || String(left.card.cardId).localeCompare(String(right.card.cardId)))
    .slice(0, limit)
    .map(item => ({
      ...item.card,
      retrievalReason: item.matchedTags.length
        ? `sceneFunctionTags:${item.matchedTags.join(',')}`
        : `applicableSceneExpression:${item.expressionScore}`
    }))
}

export function buildExpressionHelperFromRealCorpusCards(cards = [], sceneCard = {}) {
  const selected = (cards || []).slice(0, 2)
  if (!selected.length) return ''
  const desiredTags = inferSceneFunctionTags(sceneCard).join(', ')
  const lines = [
    '## Real Corpus Expression Helper',
    'Use only these expression methods. They do not provide facts, stage boundaries, source worlds, characters, or guard rules.',
    `- Scene function needs: ${desiredTags}`
  ]
  selected.forEach((card, index) => {
    lines.push(`- Helper ${index + 1}: ${compact(card.promptInjectionSafeVersion, 260)}`)
    lines.push(`  Method: ${compact(card.writingMethod, 260)}`)
    lines.push(`  Safe micro-demo: ${compact(card.originalMicroDemo, 260)}`)
    lines.push(`  Anti-AI reminder: ${compact(card.antiAiReminder, 180)}`)
  })
  return lines.join('\n')
}

export function detectRealCorpusPromptLeakage(text = '', cards = []) {
  const source = String(text || '')
  const sourceTitle = (cards || []).find(card => hasText(card.sourceTitle) && source.includes(card.sourceTitle))?.sourceTitle || ''
  const forbiddenToken = ['sourceTitle', 'sourceFileHash', 'sourceWindowHashes', 'rawExcerpt', 'sourceText', 'sourceCardIds', 'stateAuthority', 'guardSnapshot', 'futureRoadmap']
    .find(token => source.includes(token)) || ''
  return {
    detected: Boolean(sourceTitle || forbiddenToken),
    sourceTitle,
    forbiddenToken
  }
}
