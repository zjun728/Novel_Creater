const definitions = [
  ['whole', '完整创作圣经', null],
  ['premise', '作品承诺', ['premiseAndPromise']],
  ['world_rules', '世界规则', ['worldRules']],
  ['progression', '力量／成长体系', ['powerOrProgressionSystem']],
  ['core_characters', '主角与核心人物', ['protagonist', 'coreCast']],
  ['factions', '势力', ['factions']],
  ['long_term_conflicts', '长期冲突', ['longTermConflicts']],
  ['relationships', '关系动力', ['relationshipDynamics']],
  ['tone_boundaries', '基调与叙事边界', ['toneAndNarrativeBoundaries']],
  ['continuity_guardrails', '连贯性护栏', ['continuityGuardrails']],
  ['open_questions', '开放设计问题', ['openDesignQuestions']],
]

export const BIBLE_PROPOSAL_SCOPES = Object.freeze(definitions.map(([key, label, fields]) => (
  Object.freeze({ key, label, fields: fields === null ? null : Object.freeze(fields) })
)))

const scopesByKey = new Map(BIBLE_PROPOSAL_SCOPES.map(scope => [scope.key, scope]))
const clone = value => value == null ? value : JSON.parse(JSON.stringify(value))

export function bibleProposalScope(key) {
  return scopesByKey.get(String(key || '')) || null
}

export function adoptBibleProposal(current, proposal, scopeKey) {
  const scope = bibleProposalScope(scopeKey)
  if (!scope) throw new TypeError('Unknown Bible proposal scope')
  if (scope.fields === null) return clone(proposal)
  const adopted = clone(current)
  for (const field of scope.fields) adopted[field] = clone(proposal?.[field])
  return adopted
}
