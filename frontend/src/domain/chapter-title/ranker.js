import { collectChapterTitleMaterials } from './source-extractor.js'
import {
  evaluateChapterTitlePolicy,
  inferChapterTitleType,
  normalizeChapterTitle,
  normalizeChapterTitleKey
} from './policy.js'

const TYPE_PRIORITY = new Map([
  ['place', 124],
  ['item', 118],
  ['event', 112],
  ['conflict', 108],
  ['result', 106],
  ['organization', 104],
  ['person', 104],
  ['skill', 94],
  ['weapon', 94],
  ['material', 90]
])

function parseChapterTitleCandidates(text) {
  const raw = String(text || '').trim()
  if (!raw) return []
  const jsonText = raw.match(/\{[\s\S]*\}/)?.[0] || raw
  try {
    const parsed = JSON.parse(jsonText)
    const values = Array.isArray(parsed?.candidates)
      ? parsed.candidates
      : [parsed?.title ? parsed : null]
    return values.map((item, index) => {
      if (typeof item === 'string') return { title: item, type: '', reason: '', index, source: 'model' }
      return {
        title: item?.title || '',
        type: item?.type || '',
        reason: item?.reason || '',
        index,
        source: 'model'
      }
    }).filter(item => item.title)
  } catch {
    return raw.split(/\r?\n/)
      .filter(Boolean)
      .map((title, index) => ({ title, type: '', reason: '', index, source: 'model' }))
  }
}

function titleLength(title) {
  return Array.from(String(title || '')).length
}

function firstOccurrenceBonus(title, context = {}) {
  const content = String(context.content || '')
  if (!content || !title || !content.includes(title)) return 0
  return Math.max(1, 14 - Math.floor(content.indexOf(title) / 120))
}

function materialByTitle(materials = []) {
  return new Map(materials.map(item => [normalizeChapterTitleKey(item.title), item]))
}

function uniqueCandidates(candidates = []) {
  const seen = new Set()
  return candidates.filter(candidate => {
    const title = normalizeChapterTitle(candidate.title)
    const key = normalizeChapterTitleKey(title)
    if (!key || seen.has(key)) return false
    seen.add(key)
    candidate.title = title
    return true
  })
}

function scoreCandidate(candidate, material, context, policy) {
  const type = candidate.type || material?.type || inferChapterTitleType(policy.title, { ...context, materials: material ? [material] : [] })
  let score = TYPE_PRIORITY.get(type) || 70
  const length = titleLength(policy.title)
  if (length >= 1 && length <= 6) score += 18
  else if (length <= 8) score += 4
  if (material) score += 140 - Math.min(48, Number(material.sourceIndex || 0) / 20)
  score += firstOccurrenceBonus(policy.title, context)
  const reason = String(candidate.reason || material?.reason || '')
  if (/核心地点|主要场景|关键地点|主场景/.test(reason)) score += 72
  if (/本章核心事件|核心事件|核心冲突|核心转折/.test(reason)) score += 26
  if (/关键物证|关键道具|关键凭证|证据|密约|残页|账本/.test(reason)) score += 20
  if (/不可逆代价|代价|永久|失去|行动后果|后果|换令|换债|换账/.test(reason)) score += 18
  if (/阶段答案|小答案|答案|转折|结算/.test(reason)) score += 16
  if (policy.status === 'warning') score -= 8
  score -= (candidate.index || 0) * 0.01
  return score
}

export function rankChapterTitleCandidates(candidates = [], materials = [], context = {}) {
  const materialMap = materialByTitle(materials)
  return uniqueCandidates([
    ...candidates,
    ...materials.map((item, index) => ({
      title: item.title,
      type: item.type,
      reason: item.reason || 'positive_chapter_material',
      evidence: item.evidence,
      index: candidates.length + index,
      source: 'material'
    }))
  ]).map((candidate, index) => {
    const material = materialMap.get(normalizeChapterTitleKey(candidate.title))
    const policy = evaluateChapterTitlePolicy(candidate.title, { ...context, materials })
    return {
      ...candidate,
      index: candidate.index ?? index,
      title: policy.title || normalizeChapterTitle(candidate.title),
      type: candidate.type || material?.type || inferChapterTitleType(candidate.title, { ...context, materials }),
      evidence: candidate.evidence || material?.evidence || '',
      policy,
      score: policy.status === 'fail' ? -Infinity : scoreCandidate(candidate, material, context, policy)
    }
  }).sort((left, right) => right.score - left.score)
}

export function selectChapterTitle({ modelResponse = '', candidates = [], context = {} } = {}) {
  const materials = collectChapterTitleMaterials(context)
  const modelCandidates = candidates.length ? candidates : parseChapterTitleCandidates(modelResponse)
  const ranked = rankChapterTitleCandidates(modelCandidates, materials, context)
  const selected = ranked.find(item => item.policy.status === 'pass')
  const rejected = ranked
    .filter(item => item.policy.status === 'fail')
    .map(item => ({ title: item.title, reason: item.policy.reason, source: item.source || 'candidate' }))
  return {
    title: selected?.title || '',
    selected,
    selectedEvidence: selected?.evidence || '',
    materials,
    ranked,
    rejected
  }
}

export function deriveFallbackChapterTitle(context = {}) {
  return selectChapterTitle({ candidates: [], context }).title
}

export function cleanGeneratedChapterTitle(text, context = {}) {
  return selectChapterTitle({ modelResponse: text, context }).title
}
