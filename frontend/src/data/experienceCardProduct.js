import { SAMPLE_MICRO_DEMO_LIBRARY } from './sampleMicroDemoCards.js'
import {
  buildSystemWritingStandardsFromExperienceCards,
  sanitizeWritingStyleStandardForPrompt
} from './writingStyleStandards.js'

const USER_CARDS_KEY = 'novel_creator_user_experience_cards_v2'
const DRAFTS_KEY = 'novel_creator_writing_standard_drafts_v2'
const USER_STANDARDS_KEY = 'novel_creator_user_formal_writing_standards_v2'
const INACTIVE_CARD_IDS_KEY = 'novel_creator_inactive_system_experience_cards_v2'
const INACTIVE_STANDARD_IDS_KEY = 'novel_creator_inactive_system_writing_standards_v2'

function storageOf(options = {}) {
  if (options.storage) return options.storage
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null
  } catch {
    return null
  }
}

function readList(key, options = {}) {
  const storage = storageOf(options)
  if (!storage?.getItem) return []
  try {
    const parsed = JSON.parse(storage.getItem(key) || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeList(key, value, options = {}) {
  const storage = storageOf(options)
  if (storage?.setItem) storage.setItem(key, JSON.stringify(value || []))
}

function nowId(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function cleanText(value, fallback = '') {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  return text || fallback
}

function cardFromSample(sample) {
  return {
    id: `system-card-${sample.cardId}`,
    title: sample.cardTitle,
    sourceKind: 'system',
    sourceLabel: '系统内置',
    active: true,
    statusLabel: '激活',
    locked: true,
    cardType: sample.sampleCardType,
    applicableScenes: sample.dialogueType || sample.cardTitle,
    writingMethod: sample.promptInjectionSafeVersion,
    originalMicroDemo: sample.originalMicroDemo,
    antiAiReminder: sample.antiSkeletonEffect,
    promptReadiness: sample.promptReadiness,
    microDemoChars: sample.microDemoChars || sample.originalMicroDemo?.length || 0
  }
}

function normalizeCard(card = {}) {
  const sourceKind = card.sourceKind === 'system' ? 'system' : 'user'
  const active = card.active !== false
  return {
    id: cleanText(card.id, nowId('my-card')),
    title: cleanText(card.title, '未命名经验卡'),
    sourceKind,
    sourceLabel: sourceKind === 'system' ? '系统内置' : '我的经验',
    active,
    statusLabel: active ? '激活' : '未激活',
    locked: sourceKind === 'system',
    cardType: card.cardType || 'experience_method',
    applicableScenes: cleanText(card.applicableScenes),
    writingMethod: cleanText(card.writingMethod || card.promptInjectionSafeVersion),
    originalMicroDemo: cleanText(card.originalMicroDemo),
    antiAiReminder: cleanText(card.antiAiReminder || card.antiSkeletonEffect),
    promptReadiness: card.promptReadiness || '',
    microDemoChars: Number(card.microDemoChars || card.originalMicroDemo?.length || 0)
  }
}

function cardSnapshot(card = {}) {
  return {
    id: card.id,
    title: card.title,
    sourceKind: card.sourceKind,
    applicableScenes: card.applicableScenes,
    writingMethod: card.writingMethod,
    originalMicroDemo: card.originalMicroDemo,
    antiAiReminder: card.antiAiReminder
  }
}

function normalizeDraft(draft = {}) {
  const generatedStandardId = cleanText(draft.generatedStandardId)
  return {
    id: cleanText(draft.id, nowId('standard-draft')),
    name: cleanText(draft.name, '未命名候选标准'),
    description: cleanText(draft.description),
    applicableScenes: cleanText(draft.applicableScenes),
    cardIds: Array.isArray(draft.cardIds) ? draft.cardIds.filter(Boolean) : [],
    generatedStandardId,
    statusLabel: generatedStandardId ? '已生成正式标准' : '草稿'
  }
}

function normalizeStandard(standard = {}) {
  const sourceKind = standard.sourceKind === 'system' ? 'system' : 'user'
  const active = standard.active !== false
  return {
    ...standard,
    id: cleanText(standard.id, nowId('my-standard')),
    name: cleanText(standard.name, '未命名写作标准'),
    sourceKind,
    sourceLabel: sourceKind === 'system' ? '系统内置标准' : '我的写作标准',
    active,
    status: active ? 'active' : 'inactive',
    statusLabel: active ? '激活' : '未激活',
    locked: sourceKind === 'system',
    noDirectImitation: true,
    principles: Array.isArray(standard.principles) ? standard.principles.filter(Boolean) : [cleanText(standard.shortRule)].filter(Boolean),
    originalMicroDemo: cleanText(standard.originalMicroDemo),
    antiAiReminder: cleanText(standard.antiAiReminder),
    notApplicableScenes: cleanText(standard.notApplicableScenes),
    callStrength: cleanText(standard.callStrength, 'low'),
    linkedExperienceCardIds: Array.isArray(standard.linkedExperienceCardIds) ? standard.linkedExperienceCardIds.filter(Boolean) : [],
    experienceCardSnapshots: Array.isArray(standard.experienceCardSnapshots) ? standard.experienceCardSnapshots : []
  }
}

export function getSystemExperienceCards(options = {}) {
  const inactiveIds = new Set(readList(INACTIVE_CARD_IDS_KEY, options))
  return SAMPLE_MICRO_DEMO_LIBRARY.cards.map(cardFromSample).map(card => normalizeCard({
    ...card,
    active: !inactiveIds.has(card.id)
  }))
}

export function getSystemWritingStandards(options = {}) {
  const inactiveIds = new Set(readList(INACTIVE_STANDARD_IDS_KEY, options))
  return buildSystemWritingStandardsFromExperienceCards(SAMPLE_MICRO_DEMO_LIBRARY.cards)
    .map(standard => normalizeStandard({
      ...standard,
      active: !inactiveIds.has(standard.id)
    }))
}

export function createExperienceCardProductState(options = {}) {
  const cards = [
    ...getSystemExperienceCards(options),
    ...readList(USER_CARDS_KEY, options).map(normalizeCard)
  ]
  const drafts = readList(DRAFTS_KEY, options).map(normalizeDraft)
  const standards = [
    ...getSystemWritingStandards(options),
    ...readList(USER_STANDARDS_KEY, options).map(normalizeStandard)
  ]
  return { cards, drafts, standards, options }
}

export function persistExperienceCardProductState(state = {}) {
  const options = state.options || {}
  writeList(USER_CARDS_KEY, (state.cards || []).filter(card => card.sourceKind === 'user'), options)
  writeList(DRAFTS_KEY, state.drafts || [], options)
  writeList(USER_STANDARDS_KEY, (state.standards || []).filter(standard => standard.sourceKind === 'user'), options)
  writeList(INACTIVE_CARD_IDS_KEY, (state.cards || []).filter(card => card.sourceKind === 'system' && card.active === false).map(card => card.id), options)
  writeList(INACTIVE_STANDARD_IDS_KEY, (state.standards || []).filter(standard => standard.sourceKind === 'system' && standard.active === false).map(standard => standard.id), options)
}

function findById(list, id, label) {
  const item = (list || []).find(row => row.id === id)
  if (!item) throw new Error(`${label}不存在`)
  return item
}

export function toggleExperienceCardActive(state, cardId) {
  const card = findById(state.cards, cardId, '经验卡')
  card.active = !card.active
  card.statusLabel = card.active ? '激活' : '未激活'
  persistExperienceCardProductState(state)
  return card
}

export function copyExperienceCardToMine(state, cardId) {
  const source = findById(state.cards, cardId, '经验卡')
  const copied = normalizeCard({
    ...source,
    id: nowId('my-card'),
    title: `${source.title}（我的）`,
    sourceKind: 'user',
    active: true,
    locked: false
  })
  state.cards.unshift(copied)
  persistExperienceCardProductState(state)
  return copied
}

export function createUserExperienceCard(state, payload = {}) {
  const card = normalizeCard({
    ...payload,
    id: nowId('my-card'),
    sourceKind: 'user',
    active: payload.active !== false
  })
  state.cards.unshift(card)
  persistExperienceCardProductState(state)
  return card
}

export function updateUserExperienceCard(state, cardId, payload = {}) {
  const card = findById(state.cards, cardId, '经验卡')
  if (card.sourceKind === 'system') throw new Error('系统内置经验卡不可编辑，可复制为我的经验卡后再编辑。')
  Object.assign(card, normalizeCard({ ...card, ...payload, id: card.id, sourceKind: 'user' }))
  persistExperienceCardProductState(state)
  return card
}

export function canDeleteExperienceCard(state, cardId) {
  const card = (state.cards || []).find(item => item.id === cardId)
  if (!card) return { allowed: false, message: '经验卡不存在' }
  if (card.sourceKind === 'system') return { allowed: false, message: '系统内置经验卡禁止删除，只能取消激活。' }
  const draftCount = (state.drafts || []).filter(draft => draft.cardIds.includes(cardId)).length
  const standardCount = (state.standards || []).filter(standard => (standard.linkedExperienceCardIds || []).includes(cardId)).length
  if (draftCount || standardCount) {
    return {
      allowed: false,
      message: `该经验卡已被 ${draftCount} 个候选标准、${standardCount} 个正式写作标准引用，请先移除引用后再删除。`
    }
  }
  return { allowed: true, message: '' }
}

export function deleteExperienceCard(state, cardId) {
  const check = canDeleteExperienceCard(state, cardId)
  if (!check.allowed) throw new Error(check.message)
  state.cards = (state.cards || []).filter(card => card.id !== cardId)
  persistExperienceCardProductState(state)
  return true
}

export function createWritingStandardDraft(state, payload = {}, cardIds = []) {
  const ids = Array.from(new Set(cardIds.filter(Boolean)))
  if (!ids.length) throw new Error('请至少选择一张经验卡加入候选标准。')
  const draft = normalizeDraft({
    id: nowId('standard-draft'),
    name: payload.name,
    description: payload.description,
    applicableScenes: payload.applicableScenes,
    cardIds: ids
  })
  state.drafts.unshift(draft)
  persistExperienceCardProductState(state)
  return draft
}

export function addExperienceCardsToDraft(state, draftId, cardIds = []) {
  const draft = findById(state.drafts, draftId, '候选标准')
  draft.cardIds = Array.from(new Set([...draft.cardIds, ...cardIds.filter(Boolean)]))
  persistExperienceCardProductState(state)
  return draft
}

export function removeExperienceCardFromDraft(state, draftId, cardId) {
  const draft = findById(state.drafts, draftId, '候选标准')
  const next = draft.cardIds.filter(id => id !== cardId)
  if (!next.length) throw new Error('候选标准移除经验卡时不能产生空候选标准。')
  draft.cardIds = next
  persistExperienceCardProductState(state)
  return draft
}

export function deleteWritingStandardDraft(state, draftId) {
  state.drafts = (state.drafts || []).filter(draft => draft.id !== draftId)
  persistExperienceCardProductState(state)
}

export function generateFormalWritingStandardFromDraft(state, draftId, overrides = {}) {
  const draft = findById(state.drafts, draftId, '候选标准')
  const linkedCards = draft.cardIds.map(id => state.cards.find(card => card.id === id)).filter(Boolean)
  if (!linkedCards.length) throw new Error('候选标准没有可用经验卡，无法生成正式写作标准。')
  const standard = normalizeStandard({
    id: nowId('my-standard'),
    name: overrides.name || draft.name,
    category: '我的写作标准',
    sourceKind: 'user',
    active: true,
    applicableScenes: overrides.applicableScenes || draft.applicableScenes,
    principles: [overrides.principle || linkedCards.find(card => card.writingMethod)?.writingMethod || '从经验卡抽象出当前章节可低量调用的写法原则。'],
    originalMicroDemo: overrides.originalMicroDemo || linkedCards.find(card => card.originalMicroDemo)?.originalMicroDemo || '',
    antiAiReminder: overrides.antiAiReminder || linkedCards.find(card => card.antiAiReminder)?.antiAiReminder || '不要复用经验卡人物、物件、句子，也不要按清单打卡。',
    notApplicableScenes: overrides.notApplicableScenes || '',
    callStrength: overrides.callStrength || 'low',
    linkedExperienceCardIds: linkedCards.map(card => card.id),
    experienceCardSnapshots: linkedCards.map(cardSnapshot),
    guidance: {
      chapterEngine: linkedCards.find(card => card.writingMethod)?.writingMethod || '',
      originalMicroDemo: linkedCards.find(card => card.originalMicroDemo)?.originalMicroDemo || '',
      antiAiReminder: linkedCards.find(card => card.antiAiReminder)?.antiAiReminder || ''
    }
  })
  state.standards.unshift(standard)
  draft.generatedStandardId = standard.id
  draft.statusLabel = '已生成正式标准'
  persistExperienceCardProductState(state)
  return standard
}

export function toggleWritingStandardActive(state, standardId) {
  const standard = findById(state.standards, standardId, '正式写作标准')
  standard.active = !standard.active
  standard.status = standard.active ? 'active' : 'inactive'
  standard.statusLabel = standard.active ? '激活' : '未激活'
  persistExperienceCardProductState(state)
  return standard
}

export function copyWritingStandardToMine(state, standardId) {
  const source = findById(state.standards, standardId, '正式写作标准')
  const copied = normalizeStandard({
    ...source,
    id: nowId('my-standard'),
    name: `${source.name}（我的）`,
    sourceKind: 'user',
    active: true,
    locked: false,
    experienceCardSnapshots: [...(source.experienceCardSnapshots || [])]
  })
  state.standards.unshift(copied)
  persistExperienceCardProductState(state)
  return copied
}

export function updateUserWritingStandard(state, standardId, payload = {}) {
  const standard = findById(state.standards, standardId, '正式写作标准')
  if (standard.sourceKind === 'system') throw new Error('系统内置正式标准不可编辑，可复制为我的写作标准后再编辑。')
  Object.assign(standard, normalizeStandard({ ...standard, ...payload, id: standard.id, sourceKind: 'user' }))
  persistExperienceCardProductState(state)
  return standard
}

export function canDeleteWritingStandard(state, standardId) {
  const standard = (state.standards || []).find(item => item.id === standardId)
  if (!standard) return { allowed: false, message: '正式写作标准不存在' }
  if (standard.sourceKind === 'system') return { allowed: false, message: '系统内置正式标准禁止删除，只能取消激活。' }
  return { allowed: true, message: '' }
}

export function deleteWritingStandard(state, standardId) {
  const check = canDeleteWritingStandard(state, standardId)
  if (!check.allowed) throw new Error(check.message)
  state.standards = (state.standards || []).filter(standard => standard.id !== standardId)
  persistExperienceCardProductState(state)
  return true
}

export function activeFormalStandardsForPrompt(state) {
  return (state.standards || [])
    .filter(standard => standard.active)
    .map(standard => sanitizeWritingStyleStandardForPrompt(standard))
}
