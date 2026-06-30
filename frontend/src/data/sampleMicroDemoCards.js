import v21PromptCardsRaw from './sampleMicroDemoCards.v2_1.json' with { type: 'json' }
import v22DialogueCardsRaw from './sampleMicroDemoCards.v2_2.json' with { type: 'json' }

export const SAMPLE_PROMPT_READY = 'prompt-ready-low-dose'
export const SAMPLE_BACKEND_REFERENCE_ONLY = 'backend-reference-only-until-reviewed'

const FORBIDDEN_PROMPT_FIELD_NAMES = [
  'sourceWork',
  'sourceInfluence',
  'sourceCardId',
  'characterEmotionVariants',
  'emotionDialogueOptions',
  'rawExcerpt',
  'sourceText'
]

const FORBIDDEN_SOURCE_TOKENS = [
  '凡人修仙传',
  '四世同堂',
  '老舍：四世同堂',
  '一句顶一万句',
  '大奉打更人',
  '修真聊天群',
  '斗破苍穹',
  '全球高武',
  '韩立',
  '黄枫谷',
  '祁家'
]

const DIALOGUE_MATCHERS = [
  {
    type: '嘴硬关心',
    cardId: 'dialogue-v2_2-01-tough-care',
    patterns: [/嘴硬/, /关心|照顾|心疼/, /嫌弃|别扭/, /伤口|药|披|冻|冷/]
  },
  {
    type: '旧识旧账',
    cardId: 'dialogue-v2_2-02-old-debt',
    patterns: [/旧识|旧账|旧事|旧伤/, /寒暄|多年|当年/, /亏欠|欠|翻账/]
  },
  {
    type: '讨价还价',
    cardId: 'dialogue-v2_2-04-bargain',
    patterns: [/讨价|还价|价格|价钱|加钱/, /交易|买卖|交换|筹码/, /谁更急|急着|开价|压价/]
  },
  {
    type: '市井闲话',
    cardId: 'dialogue-v2_2-06-market-gossip',
    patterns: [/市井|闲话|热闹|街坊|摊贩|伙计|掌柜|船工/, /传闻|打听|漏出线索/, /没用的|废话/]
  },
  {
    type: '沉默岔开',
    cardId: 'dialogue-v2_2-07-silence-deflection',
    patterns: [/沉默|不回答|没接话/, /岔开|转开|避开|绕开/, /半截话|说半句/]
  },
  {
    type: '失败后互相埋怨',
    cardId: 'dialogue-v2_2-09-failure-blame',
    patterns: [/失败|失手|搞砸|坏事/, /埋怨|甩锅|怪你|怨/, /收拾|补救/]
  },
  {
    type: '亲近关系无效废话',
    cardId: 'dialogue-v2_2-10-intimate-useless-talk',
    patterns: [/亲近|熟人|同伴|搭档/, /无效废话|废话|重复问题|没话找话/, /多留一会儿|不想走/]
  },
  {
    type: '恐惧里的胡扯',
    cardId: 'dialogue-v2_2-11-fear-nonsense',
    patterns: [/恐惧|害怕|怕|惊慌/, /胡扯|跑题|乱说|废话/, /不断气|撑住|缓一口气/]
  }
]

const SCENE_MATCHERS = [
  {
    title: '配角先有自己的今天',
    patterns: [/配角|旁人|小人物|街坊|掌柜|摊贩|伙计|老太太/, /自己的|今天|小目标|难处|顾虑/]
  },
  {
    title: '场景三拍',
    patterns: [/场景|市井|街|码头|茶馆|饭铺|衙门|巷口/, /秩序|规矩/, /摩擦|微变|变化/]
  },
  {
    title: '给一个小答案，再让后果开门',
    patterns: [/答案|阶段答案|确认|证实|原来|不是/, /后果|代价|余波|开门|新问题/]
  },
  {
    title: '先看一眼再伸手',
    patterns: [/陌生|高风险|危险|接触|物件|木匣|门|钥匙/, /看一眼|观察|试探|摸底|无害问题|伸手/]
  }
]

function hasText(value) {
  return value !== undefined && value !== null && String(value).trim() !== ''
}

function cleanText(value, limit = 900) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  if (!text) return ''
  return text.length > limit ? `${text.slice(0, limit).replace(/[，。；;,. ]+$/, '')}。` : text
}

function stripForbiddenPromptText(value, limit = 900) {
  let text = cleanText(value, limit)
  if (!text) return ''
  for (const field of FORBIDDEN_PROMPT_FIELD_NAMES) {
    text = text.replaceAll(field, '')
  }
  for (const token of [...FORBIDDEN_SOURCE_TOKENS].sort((left, right) => right.length - left.length)) {
    text = text.replaceAll(token, '样本原作')
  }
  return cleanText(text, limit)
}

function normalizePromptReadiness(card = {}, source = {}, version = '') {
  const explicit = cleanText(card.promptReadiness)
  if (explicit) return explicit
  if (Array.isArray(source.promptReadyCardIds) && source.promptReadyCardIds.includes(card.cardId)) return SAMPLE_PROMPT_READY
  if (Array.isArray(source.backendReferenceOnlyCardIds) && source.backendReferenceOnlyCardIds.includes(card.cardId)) return SAMPLE_BACKEND_REFERENCE_ONLY
  const safety = card.safetyCheck || {}
  const lowRisk = safety.directImitationRisk === 'low' &&
    safety.containsSourceNameInPromptText !== true &&
    safety.containsSourceCharacters !== true &&
    safety.containsLongQuote !== true
  return version === 'v2.1' && lowRisk ? SAMPLE_PROMPT_READY : SAMPLE_BACKEND_REFERENCE_ONLY
}

function normalizeRawCard(card = {}, source = {}, options = {}) {
  const cardId = cleanText(card.cardId)
  const cardTitle = stripForbiddenPromptText(card.cardTitle, 120)
  const promptInjectionSafeVersion = stripForbiddenPromptText(card.promptInjectionSafeVersion, 360)
  const originalMicroDemo = stripForbiddenPromptText(card.originalMicroDemo, 520)
  const antiSkeletonEffect = stripForbiddenPromptText(card.antiSkeletonEffect, 220)
  if (!cardId || !cardTitle || !promptInjectionSafeVersion || !originalMicroDemo || !antiSkeletonEffect) return null

  const promptReadiness = normalizePromptReadiness(card, source, options.version)
  const sampleCardType = options.sampleCardType || 'prompt_injectable_scene'
  return {
    cardId,
    cardTitle,
    sampleCardType,
    promptReadiness,
    version: options.version || '',
    dialogueType: stripForbiddenPromptText(card.dialogueType, 80),
    promptInjectionSafeVersion,
    originalMicroDemo,
    antiSkeletonEffect,
    microDemoChars: Number(card.originalMicroDemoCharCount || originalMicroDemo.length || 0) || originalMicroDemo.length,
    sourceFieldsStripped: true
  }
}

export function normalizeSampleMicroDemoLibrary(raw = {}) {
  const v21 = raw.v21 || {}
  const v22 = raw.v22 || {}
  const v21Cards = [
    ...(Array.isArray(v21.promptInjectableCards) ? v21.promptInjectableCards : []),
    ...(Array.isArray(v21.dialoguePromptInjectableCards) ? v21.dialoguePromptInjectableCards : [])
  ].map(card => normalizeRawCard(card, v21, {
    version: 'v2.1',
    sampleCardType: 'prompt_injectable_scene'
  })).filter(Boolean)

  const v22Cards = (Array.isArray(v22.dialoguePromptInjectableCards) ? v22.dialoguePromptInjectableCards : [])
    .map(card => normalizeRawCard(card, v22, {
      version: 'v2.2',
      sampleCardType: 'prompt_injectable_dialogue'
    })).filter(Boolean)

  const cards = [...v21Cards, ...v22Cards]
  return {
    cards,
    promptCandidates: cards.filter(card => card.promptReadiness === SAMPLE_PROMPT_READY),
    backendReferenceOnly: cards.filter(card => card.promptReadiness === SAMPLE_BACKEND_REFERENCE_ONLY)
  }
}

export const SAMPLE_MICRO_DEMO_LIBRARY = normalizeSampleMicroDemoLibrary({
  v21: v21PromptCardsRaw,
  v22: v22DialogueCardsRaw
})

function textFromValue(value) {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(textFromValue).filter(Boolean).join('\n')
  if (typeof value === 'object') {
    return Object.values(value).map(textFromValue).filter(Boolean).join('\n')
  }
  return String(value)
}

function contextMatchText(context = {}) {
  return [
    context.chapterGoal,
    context.beatPlan,
    context.storyBlock,
    context.blockStageSnapshot,
    context.relationships,
    context.directionReference,
    context.volumeStage
  ].map(textFromValue).filter(Boolean).join('\n')
}

function isDialogueScene(text = '') {
  return /对话|说|问|答|开口|沉默|争执|埋怨|讨价|闲话|嘴硬|关心|旧账|交易|寒暄|岔开|胡扯|关系|误会|隐瞒|同伴|搭档/.test(text)
}

function scoreByMatchers(text, patterns = []) {
  return patterns.reduce((score, pattern) => score + (pattern.test(text) ? 1 : 0), 0)
}

function pickBest(scored = [], threshold = 2) {
  const [best] = scored
    .filter(item => item.score >= threshold)
    .sort((left, right) => right.score - left.score)
  return best || null
}

function attachReason(card, reason) {
  return {
    ...card,
    sampleInjectionReason: reason
  }
}

export function selectSampleMicroDemoCard(context = {}, library = SAMPLE_MICRO_DEMO_LIBRARY) {
  // Product boundary: experience cards are source material for formal writing standards only.
  // They must not be selected directly for chapter draft prompts.
  return null
  /*
  if (context.disableSampleMicroDemo === true) return null
  const text = contextMatchText(context)
  if (!text.trim()) return null
  const candidates = Array.isArray(library?.promptCandidates) ? library.promptCandidates : []
  const dialogueCandidates = candidates.filter(card => card.sampleCardType === 'prompt_injectable_dialogue')
  const sceneCandidates = candidates.filter(card => card.version === 'v2.1')

  if (isDialogueScene(text)) {
    const dialogueMatch = pickBest(DIALOGUE_MATCHERS.map(matcher => {
      const card = dialogueCandidates.find(item => item.cardId === matcher.cardId)
      if (!card) return null
      const titleBonus = text.includes(matcher.type) || text.includes(card.dialogueType) ? 2 : 0
      return { card, score: titleBonus + scoreByMatchers(text, matcher.patterns), type: matcher.type }
    }).filter(Boolean), 2)
    if (dialogueMatch) {
      return attachReason(dialogueMatch.card, `对话场景匹配：${dialogueMatch.type}`)
    }
  }

  const sceneMatch = pickBest(SCENE_MATCHERS.map(matcher => {
    const card = sceneCandidates.find(item => item.cardTitle.includes(matcher.title))
    if (!card) return null
    const titleBonus = text.includes(matcher.title) ? 2 : 0
    return { card, score: titleBonus + scoreByMatchers(text, matcher.patterns), title: matcher.title }
  }).filter(Boolean), 2)
  if (sceneMatch) {
    return attachReason(sceneMatch.card, `场景功能匹配：${sceneMatch.title}`)
  }

  return null
  */
}

export function formatSampleMicroDemoPromptSection(card = null) {
  // Disabled by product rule: only active formal writing standards may enter draft prompts.
  return ''
  /*
  if (!card || card.promptReadiness !== SAMPLE_PROMPT_READY) return ''
  const safe = normalizeRawCard(card, {}, {
    version: card.version,
    sampleCardType: card.sampleCardType
  }) || card
  return [
    '## 原创微示范低量参考',
    '本章可参考一张原创微示范的手感，不要复用人物、物件、句子，也不要按清单打卡。',
    `- cardTitle：${stripForbiddenPromptText(safe.cardTitle, 120)}`,
    `- promptInjectionSafeVersion：${stripForbiddenPromptText(safe.promptInjectionSafeVersion, 360)}`,
    `- originalMicroDemo：${stripForbiddenPromptText(safe.originalMicroDemo, 520)}`,
    `- antiSkeletonEffect：${stripForbiddenPromptText(safe.antiSkeletonEffect, 220)}`
  ].join('\n')
  */
}

export function detectSamplePromptLeakage(text = '') {
  const source = String(text || '')
  const forbiddenField = FORBIDDEN_PROMPT_FIELD_NAMES.find(field => source.includes(field))
  const forbiddenToken = FORBIDDEN_SOURCE_TOKENS.find(token => source.includes(token))
  return {
    detected: Boolean(forbiddenField || forbiddenToken),
    forbiddenField: forbiddenField || '',
    forbiddenToken: forbiddenToken || ''
  }
}

export function sampleMicroDemoReportFields(card = null) {
  const section = formatSampleMicroDemoPromptSection(card)
  const leakage = detectSamplePromptLeakage(section)
  return {
    sampleCardInjected: Boolean(card && section),
    sampleCardId: card?.cardId || '',
    sampleCardTitle: card?.cardTitle || '',
    sampleCardType: card?.sampleCardType || '',
    sampleInjectionReason: card?.sampleInjectionReason || '',
    microDemoChars: card?.microDemoChars || 0,
    sourceFieldsStripped: true,
    sampleLeakageDetected: leakage.detected
  }
}
