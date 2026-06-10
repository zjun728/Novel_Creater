import { createWritingStandardCandidate } from './writingSampleAnalyzer.js'

function cleanText(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function uniq(items) {
  return [...new Set(items.filter(Boolean))]
}

function isAuditableCard(card) {
  return Boolean(
    card
    && cleanText(card.id)
    && cleanText(card.sourceTitle)
    && card.noDirectImitation === true
    && !Object.prototype.hasOwnProperty.call(card, 'rawExcerpt')
    && !Object.prototype.hasOwnProperty.call(card, 'sourceText')
  )
}

export function normalizeWritingSampleReport(report = {}) {
  const cards = Array.isArray(report.cards)
    ? report.cards.filter(isAuditableCard)
    : []

  return {
    generatedAt: cleanText(report.generatedAt),
    input: cleanText(report.input),
    fileCount: Number(report.fileCount) || cards.length,
    cards,
    standardCandidate: {
      ...(report.standardCandidate || {}),
      status: 'draft',
      auditRequired: true,
      noDirectImitation: true
    }
  }
}

export function summarizeWritingSampleReport(report = {}) {
  const normalized = normalizeWritingSampleReport(report)
  return {
    fileCount: normalized.fileCount,
    cardCount: normalized.cards.length,
    auditReadyCount: normalized.cards.filter(card => card.noDirectImitation === true).length,
    genreTags: uniq(normalized.cards.flatMap(card => Array.isArray(card.genreTags) ? card.genreTags : []))
  }
}

export function selectWritingSampleCards(report = {}, selectedIds = []) {
  const normalized = normalizeWritingSampleReport(report)
  const idSet = new Set((selectedIds || []).map(id => String(id || '').trim()).filter(Boolean))
  return normalized.cards.filter(card => idSet.has(card.id))
}

export function approveWritingSampleStandard(report = {}, selectedIds = [], options = {}) {
  const selectedCards = selectWritingSampleCards(report, selectedIds)
  if (!selectedCards.length) {
    throw new Error('请至少选择一张已审核样本卡')
  }

  return createWritingStandardCandidate(selectedCards, {
    id: cleanText(options.id) || `reviewed-standard-${Date.now()}`,
    name: cleanText(options.name) || '本地样本审核标准',
    category: cleanText(options.category) || '本地样本 / 人工审核'
  })
}

